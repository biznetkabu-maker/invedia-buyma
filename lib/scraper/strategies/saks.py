"""Saks Fifth Avenue (saksfifthavenue.com) 向けスクレイピングStrategy。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy

logger = logging.getLogger(__name__)

_PRICE_SELECTORS = [
    "[data-testid='product-price']",
    "[class*='price-main']",
    "[class*='Price_main']",
    "[class*='saks-price']",
    "[class*='ProductPrice']",
    "[class*='product-card__price']",
    "[itemprop='price']",
    ".price",
]

_ADD_TO_BAG_SELECTORS = [
    "[data-testid='add-to-bag']",
    "button[class*='AddToBag']",
    "button[aria-label*='Add to Bag']",
    "#add-to-cart-btn",
]

_OUT_OF_STOCK_SELECTORS = [
    "[class*='soldOut']",
    "[class*='sold-out']",
    "[class*='outOfStock']",
    "[data-testid='out-of-stock']",
]

_OUT_OF_STOCK_TEXTS = {"sold out", "out of stock", "temporarily unavailable", "notify me"}
_IN_STOCK_TEXTS = {"add to bag", "add to cart"}


class SAKSStrategy(ScraperStrategy):
    @property
    def domain(self) -> str:
        return "saksfifthavenue.com"

    async def extract(self, page: Page) -> ExtractionResult:
        price = await self._extract_price(page)
        stock = await self._extract_stock(page)
        result: ExtractionResult = {"stock_status": stock}
        if price:
            result["price"] = price
        logger.debug("SAKS extract: price=%s status=%s", price, stock)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        try:
            await page.wait_for_selector(
                "[data-testid='product-price'], [class*='price-main'], [itemprop='price']",
                timeout=30_000,
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
                        for (const o of [].concat(d.offers || [])) {
                            if (o && o.price != null)
                                return '$' + String(o.price);
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
