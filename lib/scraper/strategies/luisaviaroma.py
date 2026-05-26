"""LUISAVIAROMA (luisaviaroma.com) 向けスクレイピングStrategy。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy

logger = logging.getLogger(__name__)

_PRICE_SELECTORS = [
    "[class*='ProductPrice__listPrice']",
    "[class*='ProductPrice']",
    "[class*='product-price']",
    "[class*='pdp-price']",
    "[data-testid='price']",
    "[itemprop='price']",
    ".price",
]

_ADD_TO_CART_SELECTORS = [
    "#btnAddToCart",
    "[class*='AddToCart']",
    "[class*='add-to-cart']",
    "button[aria-label*='Add to cart']",
]

_OUT_OF_STOCK_SELECTORS = [
    "[class*='soldOut']",
    "[class*='sold-out']",
    "[class*='notifyMe']",
]

_OUT_OF_STOCK_TEXTS = {"sold out", "notify me", "out of stock", "not available"}
_IN_STOCK_TEXTS = {"add to cart", "add to bag"}


class LUISAVIAROMAStrategy(ScraperStrategy):
    @property
    def domain(self) -> str:
        return "luisaviaroma.com"

    async def extract(self, page: Page) -> ExtractionResult:
        price = await self._extract_price(page)
        stock = await self._extract_stock(page)
        result: ExtractionResult = {"stock_status": stock}
        if price:
            result["price"] = price
        logger.debug("LUISAVIAROMA extract: price=%s status=%s", price, stock)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        try:
            await page.wait_for_selector(
                "[class*='ProductPrice'], [itemprop='price']",
                timeout=30_000,
            )
        except Exception as exc:
            logger.debug("luisaviaroma: %s", exc)

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
                                    return (o.priceCurrency || '') + String(o.price);
                            }
                        }
                    } catch {}
                }
                return null;
            }""")
            if ld:
                return ld
        except Exception as exc:
            logger.debug("luisaviaroma: %s", exc)
        return None

    async def _extract_stock(self, page: Page) -> str:
        for sel in _OUT_OF_STOCK_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return "out_of_stock"
            except Exception:
                continue

        for sel in _ADD_TO_CART_SELECTORS:
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
