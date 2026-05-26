"""TESSABIT (tessabit.com) 向けスクレイピングStrategy。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy

logger = logging.getLogger(__name__)

_PRICE_SELECTORS = [
    # Magento/カスタム価格ブロック（優先順）
    "[data-price-type='finalPrice'] .price",
    "[data-price-type='finalPrice']",
    ".product-info-price .price",
    ".price-box .price",
    ".special-price .price",
    ".regular-price .price",
    "[class*='product-price'] .price",
    "[itemprop='price']",
    ".price",
]

_ADD_TO_CART_SELECTORS = [
    "#product-addtocart-button",
    "[class*='add-to-cart']",
    "button[title*='Add to Cart']",
    "button[title*='カートに追加']",
    ".btn-cart",
    "button[type='submit'][class*='cart']",
]

_OUT_OF_STOCK_SELECTORS = [
    ".unavailable",
    ".out-of-stock",
    "[class*='out-of-stock']",
    "[class*='outOfStock']",
    ".stock.unavailable",
]

_OUT_OF_STOCK_TEXTS = {
    "out of stock",
    "sold out",
    "unavailable",
    "non disponibile",
    "esaurito",
    "ausverkauft",
    "épuisé",
}


class TESSABITStrategy(ScraperStrategy):
    """TESSABIT の商品ページから価格・在庫を取得するStrategy。"""

    @property
    def domain(self) -> str:
        return "tessabit.com"

    async def extract(self, page: Page) -> ExtractionResult:
        price_text = await self._extract_price(page)
        stock_status = await self._extract_stock(page)

        result: ExtractionResult = {"stock_status": stock_status}
        if price_text:
            result["price"] = price_text

        logger.debug("TESSABIT extract: price=%s status=%s url=%s", price_text, stock_status, page.url)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        price_text = await self._text_or_none(page, *_PRICE_SELECTORS)
        if price_text:
            return price_text

        # meta タグから価格を取得（OGP / schema.org）
        try:
            meta_price = await page.evaluate("""() => {
                const meta = document.querySelector(
                    'meta[property="product:price:amount"], meta[name="price"]'
                );
                if (meta) {
                    const currency = document.querySelector(
                        'meta[property="product:price:currency"]'
                    );
                    const c = currency ? currency.getAttribute('content') : '';
                    return c + meta.getAttribute('content');
                }
                return null;
            }""")
            if meta_price:
                return meta_price
        except Exception as e:
            logger.debug("meta price parse failed: %s", e)

        return None

    async def _extract_stock(self, page: Page) -> str:
        # 1. 在庫なし専用要素を確認
        for sel in _OUT_OF_STOCK_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return "out_of_stock"
            except Exception:
                continue

        # 2. "Add to Cart" ボタンの有無を確認（有効状態のみ）
        for sel in _ADD_TO_CART_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    return "in_stock"
            except Exception:
                continue

        # 3. テキストスキャン
        try:
            page_text = (await page.inner_text("body")).lower()
        except Exception:
            return "unknown"

        for phrase in _OUT_OF_STOCK_TEXTS:
            if phrase in page_text:
                return "out_of_stock"

        if "add to cart" in page_text or "aggiungi al carrello" in page_text:
            return "in_stock"

        return "unknown"
