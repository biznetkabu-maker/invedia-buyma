"""Neiman Marcus (neimanmarcus.com) 向けスクレイピングStrategy。

米国のラグジュアリーデパート。Balenciaga、Saint Laurent 等のハイブランドを幅広く取り扱う。
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy

logger = logging.getLogger(__name__)

_PRICE_SELECTORS = [
    "[data-testid='product-price']",
    "[class*='product-price']",
    "[class*='ProductPrice']",
    "[class*='ItemPrice']",
    "[class*='price-now']",
    "[class*='price__sale']",
    "[itemprop='price']",
    ".price",
]

_ADD_TO_BAG_SELECTORS = [
    "[class*='add-to-bag']",
    "[class*='AddToBag']",
    "button[id*='addToCart']",
    "button[data-id='addToBag']",
    "button[aria-label*='Add to Bag']",
]

_OUT_OF_STOCK_SELECTORS = [
    "[class*='sold-out']",
    "[class*='SoldOut']",
    "[class*='out-of-stock']",
    "[class*='notifyMe']",
    "[class*='notify-me']",
]

_OUT_OF_STOCK_TEXTS = {
    "sold out", "out of stock", "notify me when available",
    "this item is not available", "temporarily out of stock",
}
_IN_STOCK_TEXTS = {"add to bag", "add to cart"}


class NEIMANMARCUSStrategy(ScraperStrategy):
    @property
    def domain(self) -> str:
        return "neimanmarcus.com"

    async def extract(self, page: Page) -> ExtractionResult:
        price = await self._extract_price(page)
        stock = await self._extract_stock(page)
        result: ExtractionResult = {"stock_status": stock}
        if price:
            result["price"] = price
        logger.debug("NEIMAN MARCUS extract: price=%s status=%s", price, stock)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        try:
            await page.wait_for_selector(
                "[class*='product-price'], [class*='ItemPrice'], [itemprop='price']",
                timeout=10_000,
            )
        except Exception:
            pass

        price = await self._text_or_none(page, *_PRICE_SELECTORS)
        if price:
            return price

        try:
            ld = await page.evaluate("""() => {
                for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const d = JSON.parse(s.textContent);
                        const nodes = [d, ...(d['@graph'] || [])];
                        for (const n of nodes) {
                            for (const o of [].concat(n.offers || [])) {
                                if (o && o.price != null)
                                    return '$' + String(o.price);
                            }
                        }
                    } catch {}
                }
                return null;
            }""")
            if ld:
                return ld
        except Exception:
            pass
        return None

    async def _extract_stock(self, page: Page) -> str:
        for sel in _OUT_OF_STOCK_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return "out_of_stock"
            except Exception:
                continue

        for sel in _ADD_TO_BAG_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    return "in_stock"
            except Exception:
                continue

        try:
            body = (await page.inner_text("body")).lower()
        except Exception:
            return "unknown"

        for t in _OUT_OF_STOCK_TEXTS:
            if t in body:
                return "out_of_stock"
        for t in _IN_STOCK_TEXTS:
            if t in body:
                return "in_stock"
        return "unknown"
