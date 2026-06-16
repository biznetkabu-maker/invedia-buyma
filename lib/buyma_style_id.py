"""
BUYMA 商品詳細ページの HTML から型番・Style ID 候補を抽出する。

ショッパー記載の自由文言が多いため、ラベル付き近傍と URL / data 属性を複数パターンで走査する。
取得した文字列の突合は style_id_utils を利用する。
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from lib.async_compat import run_sync
from lib.style_id_utils import normalize_style_id

logger = logging.getLogger(__name__)

_ITEM_ID_IN_PATH = re.compile(r"/(?:items?|item)/(\d+)", re.I)

# ラベル直後のコードっぽい文字列（ハイフン・スラッシュ・英数字）
_AFTER_LABEL = re.compile(
    r"(?:"
    r"型番|品番|モデル(?:番号|No\.?)?|スタイル|"
    r"Style(?:\s*(?:ID|No\.?|#|Code))?|"
    r"SKU|Model(?:\s*(?:No\.?|Number))?|"
    r"REF\.?(?:ERENCE)?|Product\s*Code|Article\s*(?:No\.?|Code)|"
    r"アイテム(?:番号|コード)"
    r")[\s:：'\"]*"
    r"([A-Za-z0-9][A-Za-z0-9\-/.]{3,47})",
    re.I,
)

# data- 属性と JSON 断片（ページ内埋め込み）から拾う
_DATA_ATTR = re.compile(
    r'''data-(?:model|sku|style|article)\s*=\s*["']([A-Za-z0-9][A-Za-z0-9\-/.]{3,47})["']''',
    re.I,
)
_JSON_CODE_KEYS = re.compile(
    r'"(?:sku|mpn|productID)"\s*:\s*"([^"]+)"',
    re.I,
)

_EXCLUDE_NORMALIZED = frozenset({
    "SIZE", "COLOR", "NEW", "SALE", "FREE", "BUYMA", "ITEM",
    "HTML", "HTTP", "HTTPS", "WWW",
})


def is_buyma_item_url(url: str) -> bool:
    """BUYMA の個別商品ページ URL かどうかの簡易判定。"""
    if not url or "buyma.com" not in url.lower():
        return False
    path = urlparse(url).path.lower()
    qs = urlparse(url).query.lower()
    # 検索・一覧は除外（詳細フェッチ対象外）
    if "/buy/search" in path or "keyword=" in qs:
        return False
    if "/items/" in path or "/item/" in path:
        return True
    return bool(_ITEM_ID_IN_PATH.search(url))


def extract_style_id_candidates_from_html(html: str) -> list[str]:
    """HTML 文字列から型番候補を列挙（重複除去・軽いノイズ除去）。"""
    if not html:
        return []

    found: list[str] = []

    for m in _AFTER_LABEL.finditer(html):
        code = m.group(1).strip().strip(" '\".,;:")
        if _is_plausible_code(code):
            found.append(code)

    for m in _DATA_ATTR.finditer(html):
        g = m.group(1)
        if g and _is_plausible_code(g):
            found.append(g.strip())
    for m in _JSON_CODE_KEYS.finditer(html):
        g = m.group(1)
        if g and _is_plausible_code(g):
            found.append(g.strip())

    # ユニーク順序維持
    seen: set[str] = set()
    unique: list[str] = []
    for c in found:
        key = normalize_style_id(c)
        if not key or key in _EXCLUDE_NORMALIZED:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def extract_primary_style_id_from_buyma_html(html: str) -> Optional[str]:
    """HTML から最も信頼できそうな1件の Style ID を返す。"""
    cands = extract_style_id_candidates_from_html(html)
    if not cands:
        return None
    # ラベルマッチを優先（最初の要素がラベル近傍のため）
    return cands[0]


def _is_plausible_code(code: str) -> bool:
    if not code or len(code) < 4 or len(code) > 48:
        return False
    if code.isdigit() and len(code) > 14:
        return False
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9\-/.]+$", code):
        return False
    low = code.lower()
    if low.startswith("http") or "://" in code:
        return False
    return True


async def fetch_buyma_style_id_from_url(
    url: str,
    *,
    headless: bool = True,
    page_wait_ms: int = 2500,
    timeout_ms: int = 25_000,
) -> Optional[str]:
    """BUYMA 商品URLを開き、型番を抽出する（Playwright）。"""
    if not is_buyma_item_url(url):
        logger.debug("skip style_id fetch: not a BUYMA item URL: %s", url)
        return None

    from playwright.async_api import async_playwright

    from lib.scraper.stealth import (
        LAUNCH_ARGS,
        apply_stealth_scripts,
        stealth_context_options,
    )

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless, args=LAUNCH_ARGS)
            try:
                ctx = await browser.new_context(**stealth_context_options())
                page = await ctx.new_page()
                await apply_stealth_scripts(page)
                page.set_default_timeout(timeout_ms)
                await page.goto(url, wait_until="domcontentloaded")
                if page_wait_ms > 0:
                    await page.wait_for_timeout(page_wait_ms)
                html = await page.content()
                return extract_primary_style_id_from_buyma_html(html)
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("BUYMA style_id fetch failed [%s]: %s", url, e)
        return None


def fetch_buyma_style_id_from_url_sync(
    url: str,
    *,
    headless: bool = True,
    page_wait_ms: int = 2500,
    timeout_ms: int = 25_000,
) -> Optional[str]:
    """同期ラッパー。"""
    result: Optional[str] = run_sync(
        fetch_buyma_style_id_from_url(
            url,
            headless=headless,
            page_wait_ms=page_wait_ms,
            timeout_ms=timeout_ms,
        )
    )
    return result
