"""
SSENSE 検索ページの F12 相当解析（Step3 URL 探索）。

SSENSE 検索 URL（2026-05）:
  https://www.ssense.com/en-us/women?q={query}
  ※ 旧 /en-us/search?q= は 404。product_finder も women パスに更新済み。

主ソース: HTML 内 JSON-LD Product（name / brand / offers.url / sku）
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote_plus

from lib.async_compat import run_sync
from lib.supply_search.json_walk import (
    SearchHit,
    collect_hits_from_json_text,
    normalize_style_token,
)
from lib.supply_search_utils import infer_supply_category_hints, normalize_brand_name

logger = logging.getLogger(__name__)

_BASE = "https://www.ssense.com"
_SEARCH_PATH = "/en-us/women"
_LOCALE = "en-us"

_XHR_URL_HINTS = (
    "/api/",
    "search",
    "catalog",
    "product",
    "listing",
    "graphql",
)

_JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)
_PRODUCT_HREF_RE = re.compile(
    r'https?://(?:www\.)?ssense\.com/(?:en-[a-z]{2}/)?(?:women|men)/product/[^"\s?#]+/\d+',
    re.I,
)
_PRODUCT_PATH_RE = re.compile(
    r'"(/(?:en-[a-z]{2}/)?(?:women|men)/product/[^"\s?#]+/\d+)"',
    re.I,
)
_NO_MATCH_RE = re.compile(
    r"there are no (?:\w+ )*products that match",
    re.I,
)
_SSENSE_PRODUCT = re.compile(
    r"/(?:en-[a-z]{2}/)?(?:women|men)/product/[^/?#]+/[^/?#]+/\d+$",
    re.I,
)


@dataclass
class SsenseCatalogItem:
    name: str
    brand: str
    path: str
    sku: str
    source: str

    @property
    def url(self) -> str:
        if self.path.startswith("http"):
            return self.path.split("?")[0]
        path = self.path if self.path.startswith("/") else f"/{self.path.lstrip('/')}"
        return f"{_BASE}{path.split('?')[0]}"


def is_valid_ssense_product_url(url: str) -> bool:
    from urllib.parse import urlparse

    if not url or "ssense.com" not in url.lower():
        return False
    path = urlparse(url).path.rstrip("/")
    if not _SSENSE_PRODUCT.match(path):
        return False
    if re.search(r"/(?:search|cart|login|account)(?:/|$)", path, re.I):
        return False
    return True


def build_ssense_search_url(query: str, *, department: str = "women") -> str:
    q = quote_plus((query or "").strip())
    dept = "men" if department.lower().startswith("men") else "women"
    return f"{_BASE}/{_LOCALE}/{dept}?q={q}"


def is_no_results_html(html: str) -> bool:
    return bool(_NO_MATCH_RE.search(html or ""))


def _brand_matches(brand: str, item_brand: str, item_name: str, path: str) -> bool:
    b = normalize_brand_name(brand).lower()
    if not b:
        return True
    blob = f"{item_brand} {item_name} {path}".lower()
    token = b.split()[0] if b else ""
    if token and token in blob:
        return True
    if "prada" in b and "prada" in blob:
        return True
    return False


def _parse_json_ld_products(html: str) -> list[SsenseCatalogItem]:
    out: list[SsenseCatalogItem] = []
    seen: set[str] = set()
    for m in _JSON_LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            if root.get("@type") != "Product":
                continue
            name = str(root.get("name") or "").strip()
            brand_raw = root.get("brand") or {}
            if isinstance(brand_raw, dict):
                brand = str(brand_raw.get("name") or "").strip()
            else:
                brand = str(brand_raw or "").strip()
            sku = str(root.get("sku") or root.get("mpn") or "").strip()
            offers = root.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            url = str((offers or {}).get("url") or root.get("url") or "").strip()
            if not url:
                continue
            from urllib.parse import urlparse
            path = urlparse(url).path if url.startswith("http") else url
            key = path.rstrip("/")
            if key in seen:
                continue
            if not is_valid_ssense_product_url(
                url if url.startswith("http") else f"{_BASE}{path}"
            ):
                continue
            seen.add(key)
            out.append(
                SsenseCatalogItem(
                    name=name,
                    brand=brand,
                    path=path,
                    sku=sku,
                    source="json_ld_product",
                )
            )
    return out


def _parse_embedded_links(html: str) -> list[SsenseCatalogItem]:
    out: list[SsenseCatalogItem] = []
    seen: set[str] = set()
    for m in _PRODUCT_HREF_RE.finditer(html or ""):
        url = m.group(0).split("?")[0]
        if not is_valid_ssense_product_url(url):
            continue
        from urllib.parse import urlparse
        path = urlparse(url).path
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 2)[-2] if "/" in path else path
        out.append(
            SsenseCatalogItem(
                name=slug.replace("-", " ")[:120],
                brand="",
                path=path,
                sku="",
                source="html_link",
            )
        )
    return out


def parse_ssense_search_html(
    html: str,
    *,
    brand: str = "",
    require_brand_match: bool = True,
) -> list[SsenseCatalogItem]:
    """検索 HTML から商品候補を抽出。"""
    if is_no_results_html(html):
        return []
    items = _parse_json_ld_products(html)
    if not items:
        items = _parse_embedded_links(html)
    if brand and require_brand_match:
        items = [
            it for it in items
            if _brand_matches(brand, it.brand, it.name, it.path)
        ]
    return items


def _has_category_intent(product_name: str) -> bool:
    name_l = (product_name or "").lower()
    tokens = (
        "wallet", "bag", "shoulder", "sunglass", "eyewear", "glasses",
        "boot", "sandal", "t-shirt", "shirt", "pouch",
        "財布", "バッグ", "サングラス", "メガネ", "ショルダー", "ポーチ",
    )
    return any(t in name_l for t in tokens)


def _category_intent_delta(
    blob: str, path: str, product_name: str, pos: list[str], neg: list[str]
) -> int:
    """カテゴリ意図がある場合のヒント加減点。"""
    delta = 0
    for hint in pos:
        h = hint.lower().replace("-", " ")
        if h in blob or h.replace(" ", "-") in path.lower():
            delta += 25
        if hint == "bag" and any(k in blob for k in ("バッグ", "handbag", "hand bag")):
            delta += 25
        if hint == "wallet" and "wallet" in blob:
            delta += 25
        if hint == "shoulder" and any(k in blob for k in ("ショルダー", "shoulder")):
            delta += 20
        if hint in ("sunglasses", "eyewear") and any(
            k in blob for k in ("sunglass", "eyewear", "サングラス", "glasses")
        ):
            delta += 25
    for hint in neg:
        if hint.lower() in blob:
            delta -= 40
    if "eyewear" in blob and not any(
        x in (product_name or "").lower()
        for x in ("sunglass", "eyewear", "サングラス", "メガネ", "glasses")
    ):
        delta -= 25
    return delta


def _score_item(
    item: SsenseCatalogItem,
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> int:
    score = 30
    blob = f"{item.name} {item.brand} {item.path} {item.sku}".lower()
    sid = (style_id or "").strip()
    if sid:
        compact = normalize_style_token(sid)
        if compact and compact in normalize_style_token(blob):
            score += 100
        if item.sku and style_id_matches_loose(sid, item.sku):
            score += 90
    pos, neg = infer_supply_category_hints(product_name)
    if _has_category_intent(product_name):
        score += _category_intent_delta(blob, item.path, product_name, pos, neg)
    if brand and not _brand_matches(brand, item.brand, item.name, item.path):
        score -= 50
    if not is_valid_ssense_product_url(item.url):
        score -= 100
    if item.source == "json_ld_product":
        score += 5
    return score


def style_id_matches_loose(query: str, candidate: str) -> bool:
    q = normalize_style_token(query)
    c = normalize_style_token(candidate)
    if not q or not c:
        return False
    return q in c or c.startswith(q)


def rank_ssense_catalog_items(
    items: list[SsenseCatalogItem],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
) -> list[tuple[SsenseCatalogItem, int]]:
    from lib.supply_search.base_search import rank_catalog_items

    return rank_catalog_items(
        items, style_id=style_id, product_name=product_name,
        brand=brand, limit=limit, scorer=_score_item,
    )


def merge_search_hits(
    catalog: list[SsenseCatalogItem],
    xhr_hits: list[SearchHit],
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> list[str]:
    from lib.supply_search.base_search import rank_merge_and_debug

    urls, _ = rank_merge_and_debug(
        catalog, xhr_hits, style_id=style_id, product_name=product_name,
        brand=brand, base_url=_BASE, url_validator=is_valid_ssense_product_url,
        scorer=_score_item,
    )
    return urls


async def search_ssense_product_urls(
    page,
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    wait_ms: int = 5000,
    xhr_blobs: Optional[list[str]] = None,
    department: str = "women",
) -> tuple[list[str], dict[str, Any]]:
    search_url = build_ssense_search_url(query, department=department)
    debug: dict[str, Any] = {
        "search_url": search_url,
        "no_results": False,
        "json_ld_items": 0,
        "html_link_items": 0,
        "xhr_blobs": 0,
        "top_scores": [],
    }
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(wait_ms)
    html = await page.content()
    debug["no_results"] = is_no_results_html(html)

    catalog = parse_ssense_search_html(html, brand=brand)
    json_ld = _parse_json_ld_products(html)
    embedded = _parse_embedded_links(html)
    debug["json_ld_items"] = len(json_ld)
    debug["html_link_items"] = len(embedded)

    xhr_hits: list[SearchHit] = []
    for blob in xhr_blobs or []:
        xhr_hits.extend(
            collect_hits_from_json_text(
                blob, style_id, source="xhr", base_url=_BASE,
            )
        )

    pname = product_name or query
    ranked = rank_ssense_catalog_items(
        catalog, style_id=style_id, product_name=pname, brand=brand, limit=5,
    )
    debug["top_scores"] = [
        {
            "score": s,
            "name": it.name[:60],
            "brand": it.brand[:30],
            "sku": it.sku,
            "url": it.url,
            "source": it.source,
        }
        for it, s in ranked
    ]

    urls = merge_search_hits(
        catalog, xhr_hits, style_id=style_id, product_name=pname, brand=brand,
    )
    return urls, debug


from lib.supply_search.base_search import (
    SearchDiagnostics as SsenseSearchDiagnostics,
)
from lib.supply_search.base_search import (
    run_playwright_search,
)


async def _lookup_playwright(
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    department: str = "women",
) -> tuple[list[str], SsenseSearchDiagnostics]:
    async def _search(page: Any, *, xhr_blobs: list[str], **_kw: Any) -> tuple[list[str], dict[str, Any]]:
        return await search_ssense_product_urls(
            page, query, brand=brand, style_id=style_id,
            product_name=product_name or query, xhr_blobs=xhr_blobs,
            department=department,
        )

    diag = SsenseSearchDiagnostics(
        query=query, style_id=style_id, playwright_ok=False,
        search_url=build_ssense_search_url(query, department=department),
    )
    return await run_playwright_search(
        "ssense.com", _XHR_URL_HINTS, _search,
        diag.search_url, diag,
    )


def lookup_ssense_search_diagnose(
    query: str,
    *,
    brand: str = "PRADA",
    style_id: str = "",
    product_name: str = "",
    department: str = "women",
) -> tuple[list[str], SsenseSearchDiagnostics]:
    return run_sync(
        _lookup_playwright(
            query, brand=brand, style_id=style_id,
            product_name=product_name, department=department,
        )
    )
