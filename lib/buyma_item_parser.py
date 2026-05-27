"""
BUYMA 商品詳細ページからブランド・商品名・型番などを抽出する。

intake.py --auto-buyma / --auto-sheet で使用。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from lib.buyma_style_id import (
    extract_primary_style_id_from_buyma_html,
    is_buyma_item_url,
)

logger = logging.getLogger(__name__)

_OG_TITLE = re.compile(
    r'<meta\s+property="og:title"\s+content="([^"]+)"',
    re.I,
)
_TITLE_TAG = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)
_BRAND_JSON = re.compile(
    r'"brand"\s*:\s*(?:\{\s*"name"\s*:\s*"([^"]+)"\s*\}|"([^"]+)")',
    re.I,
)
_NAME_JSON = re.compile(r'"name"\s*:\s*"([^"]{3,120})"', re.I)


def _extract_json_product_name(html: str) -> str:
    """JSON-LD の name 候補から商品名らしいものを選ぶ（brand.name=BUYMA を除外）。"""
    from lib.supply_search_utils import is_marketplace_brand_noise

    best = ""
    best_score = -1
    for m in _NAME_JSON.finditer(html or ""):
        name = m.group(1).strip()
        if not name or is_marketplace_brand_noise(name):
            continue
        score = len(name)
        # 単独の CELINE 等ブランドトークンより長い商品名を優先
        if re.fullmatch(r"[A-Za-z]{2,20}", name):
            score -= 50
        if score > best_score:
            best_score = score
            best = name
    return best
_JPY_PRICE = re.compile(
    r"(?:¥|￥|JPY\s?)([\d,]+)|([\d,]+)\s*円",
)


@dataclass
class BuymaItemInfo:
    buyma_url: str
    brand: str
    product_name: str
    style_id: Optional[str] = None
    price_jpy: Optional[int] = None
    raw_title: str = ""


def parse_buyma_item_from_html(html: str, buyma_url: str = "") -> BuymaItemInfo:
    """HTML から BuymaItemInfo を構築する（Playwright 不要・テスト用）。"""
    style_id = extract_primary_style_id_from_buyma_html(html)

    title = _extract_title(html)
    brand, product_name = _split_brand_product(title, html)

    price_jpy = _extract_jpy_price(html)

    from lib.supply_search_utils import (
        clean_product_name_for_search,
        dedupe_product_phrase,
        is_marketplace_brand_noise,
        is_plausible_model_code,
        resolve_merchandise_brand,
        sheet_style_id_value,
    )

    json_merch_brand = ""
    m = _BRAND_JSON.search(html)
    if m:
        jb = (m.group(1) or m.group(2) or "").strip()
        if jb and not is_marketplace_brand_noise(jb) and not is_plausible_model_code(jb):
            json_merch_brand = jb

    json_name = _extract_json_product_name(html)

    brand = resolve_merchandise_brand(json_merch_brand, json_name, brand, title, product_name)
    product_name = dedupe_product_phrase(
        clean_product_name_for_search(product_name, brand) or product_name or json_name
    )
    style_id = sheet_style_id_value(f"{title} {product_name}", style_id) or None

    return BuymaItemInfo(
        buyma_url=buyma_url,
        brand=brand,
        product_name=product_name,
        style_id=style_id,
        price_jpy=price_jpy,
        raw_title=title,
    )


def _extract_title(html: str) -> str:
    m = _OG_TITLE.search(html)
    if m:
        return _clean_title(m.group(1))
    m = _TITLE_TAG.search(html)
    if m:
        return _clean_title(m.group(1))
    return ""


def _clean_title(s: str) -> str:
    s = s.strip()
    for suffix in (" | BUYMA", " - BUYMA", "｜BUYMA", "－BUYMA"):
        if suffix.upper() in s.upper():
            s = re.split(re.escape(suffix.split()[0]), s, flags=re.I)[0]
    return s.strip()


_BRACKET_TAG = re.compile(r"【[^】]*】|\[[^\]]*\]")


def _split_brand_product(title: str, html: str) -> tuple[str, str]:
    from lib.supply_search_utils import (
        _brand_from_bracket_tags,
        is_marketplace_brand_noise,
        is_plausible_model_code,
        normalize_brand_name,
    )

    raw_title = (title or "").strip()
    brand = _brand_from_bracket_tags(raw_title)

    title = _BRACKET_TAG.sub(" ", raw_title).strip()
    title = re.sub(r"\s+", " ", title)

    json_brand = ""
    m = _BRAND_JSON.search(html)
    if m:
        json_brand = (m.group(1) or m.group(2) or "").strip()
    if not brand and json_brand and not is_plausible_model_code(json_brand):
        if not is_marketplace_brand_noise(json_brand):
            brand = normalize_brand_name(json_brand)

    product_name = title
    if brand and title.lower().startswith(brand.lower()):
        product_name = title[len(brand):].strip(" -|/：:")

    if not brand and " " in title:
        parts = title.split(None, 1)
        if len(parts[0]) <= 24 and not is_plausible_model_code(parts[0]):
            brand, product_name = parts[0], parts[1]

    if brand and re.search(r"[☆★◆]", brand):
        brand = re.split(r"[☆★◆]", brand)[0].strip()

    if brand and is_plausible_model_code(brand):
        product_name = f"{brand} {product_name}".strip()
        brand = _brand_from_bracket_tags(raw_title) or ""
        if not brand and json_brand and not is_plausible_model_code(json_brand):
            if not is_marketplace_brand_noise(json_brand):
                brand = normalize_brand_name(json_brand)

    if not product_name:
        json_name = _extract_json_product_name(html)
        if json_name:
            product_name = json_name

    return brand.strip(), product_name.strip() or title.strip() or "（商品名未取得）"


def _extract_jpy_price(html: str) -> Optional[int]:
    for m in _JPY_PRICE.finditer(html):
        raw = m.group(1) or m.group(2)
        if raw:
            try:
                return int(raw.replace(",", ""))
            except ValueError:
                continue
    return None


async def fetch_buyma_item_info(
    url: str,
    *,
    headless: bool = True,
    page_wait_ms: int = 2500,
    timeout_ms: int = 25_000,
) -> Optional[BuymaItemInfo]:
    """BUYMA 商品 URL を開き、商品情報を返す。"""
    if not is_buyma_item_url(url):
        logger.warning("not a BUYMA item URL: %s", url)
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
                info = parse_buyma_item_from_html(html, buyma_url=url)
                if not info.brand and not info.product_name:
                    logger.warning("BUYMA parse: title/brand empty [%s]", url)
                return info
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("fetch_buyma_item_info failed [%s]: %s", url, e)
        return None


def fetch_buyma_item_info_sync(
    url: str,
    *,
    headless: bool = True,
    page_wait_ms: int = 2500,
    timeout_ms: int = 25_000,
) -> Optional[BuymaItemInfo]:
    return asyncio.run(
        fetch_buyma_item_info(
            url,
            headless=headless,
            page_wait_ms=page_wait_ms,
            timeout_ms=timeout_ms,
        )
    )
