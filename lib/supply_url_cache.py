"""
(brand, MPN) → 仕入先 URL キャッシュ（P2）。

Step4 で S/A 判定された URL を永続化し、同一 (brand, MPN) の再探索を省略する。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lib.style_id_utils import normalize_style_id
from lib.supply_search_utils import normalize_brand_name, url_is_valid_supply_candidate

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_FILE = Path(".supply_url_cache.json")
_DEFAULT_TTL_DAYS = 90
_GRADES_OK: frozenset[str] = frozenset({"S", "A"})


def _cache_enabled() -> bool:
    return os.environ.get("SUPPLY_URL_CACHE", "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    )


def _cache_file() -> Path:
    override = os.environ.get("SUPPLY_URL_CACHE_FILE", "").strip()
    return Path(override) if override else _DEFAULT_CACHE_FILE


def _ttl_seconds() -> float:
    try:
        days = float(os.environ.get("SUPPLY_URL_CACHE_TTL_DAYS", str(_DEFAULT_TTL_DAYS)))
    except ValueError:
        days = _DEFAULT_TTL_DAYS
    return max(days, 0) * 86400


def _min_grade() -> str:
    return os.environ.get("SUPPLY_URL_CACHE_MIN_GRADE", "A").strip().upper() or "A"


def _grade_allowed(grade: str) -> bool:
    g = (grade or "").strip().upper()
    if not g:
        return False
    if _min_grade() == "S":
        return g == "S"
    return g in _GRADES_OK


def cache_key(brand: str, mpn: str) -> str:
    b = normalize_brand_name(brand).upper()
    m = normalize_style_id(mpn)
    if not b or not m:
        return ""
    return f"{b}|{m}"


def _load() -> dict[str, Any]:
    from lib.file_lock import atomic_json_read
    data: dict[str, Any] = atomic_json_read(_cache_file(), default={})
    return data


def _save(data: dict) -> None:
    from lib.file_lock import atomic_json_write
    atomic_json_write(_cache_file(), data)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def lookup_supply_urls(
    brand: str,
    mpn: str,
    *,
    log_lines: list[str] | None = None,
) -> list[str]:
    """キャッシュから検証済み URL を返す。無効・期限切れは []。"""
    if not _cache_enabled():
        return []
    key = cache_key(brand, mpn)
    if not key:
        return []

    entry = _load().get(key)
    if not entry:
        return []

    ttl = _ttl_seconds()
    updated_at = float(entry.get("updated_at") or 0)
    if ttl > 0 and updated_at and (time.time() - updated_at) > ttl:
        return []

    norm_brand = normalize_brand_name(brand)
    style_hint = normalize_style_id(mpn)
    out: list[str] = []
    seen: set[str] = set()
    for raw in entry.get("urls") or []:
        url = (raw.get("url") if isinstance(raw, dict) else raw) or ""
        url = str(url).strip()
        if not url or url in seen:
            continue
        if not url_is_valid_supply_candidate(norm_brand, url, style_id=style_hint):
            continue
        seen.add(url)
        out.append(url)

    if out and log_lines is not None:
        log_lines.append(
            f"  URLキャッシュヒット ({key}): {len(out)} 件"
            "（site:検索・Playwright スキップ）"
        )
    return out[:5]


def store_supply_urls(
    brand: str,
    mpn: str,
    urls: list[str],
    *,
    match_grade: str = "",
    source: str = "auto_intake",
) -> None:
    """Step4 成功後に URL をキャッシュへ書き込む（S/A のみ）。"""
    if not _cache_enabled():
        return
    if not _grade_allowed(match_grade):
        return

    key = cache_key(brand, mpn)
    if not key:
        return

    norm_brand = normalize_brand_name(brand)
    style_hint = normalize_style_id(mpn)
    grade = (match_grade or "").strip().upper()
    now = time.time()

    items: list[dict] = []
    seen_domains: set[str] = set()
    for url in urls:
        url = (url or "").strip()
        if not url:
            continue
        if not url_is_valid_supply_candidate(norm_brand, url, style_id=style_hint):
            continue
        dom = _domain(url)
        if dom in seen_domains:
            continue
        seen_domains.add(dom)
        items.append(
            {
                "url": url,
                "domain": dom,
                "match_grade": grade,
                "source": source,
                "cached_at": now,
            }
        )

    if not items:
        return

    data = _load()
    data[key] = {
        "brand": norm_brand.upper(),
        "mpn": style_hint,
        "urls": items[:10],
        "updated_at": now,
    }
    _save(data)
