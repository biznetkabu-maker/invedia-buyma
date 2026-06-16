"""共通セレクタベース Strategy 基底クラス。

19 サイト中大半が共通パターン（CSS セレクタ→価格・在庫判定→JSON-LD フォールバック）。
各サイト固有のセレクタを定義するだけで Strategy を作成できるようにする。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy
from ..json_ld_style_id import extract_primary_style_id_from_json_ld

logger = logging.getLogger(__name__)

_JSON_LD_PRICE_JS = """() => {
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
}"""

_OGP_PRICE_JS = """() => {
    const a = document.querySelector('meta[property="product:price:amount"]');
    const c = document.querySelector('meta[property="product:price:currency"]');
    return a ? (c ? c.content : '') + a.content : null;
}"""


class SelectorBasedStrategy(ScraperStrategy):
    """セレクタ定義だけで構築可能な共通 Strategy。

    サブクラスで以下のクラス変数を定義するだけでよい::

        class MYSITEStrategy(SelectorBasedStrategy):
            _domain = "mysite.com"
            _price_selectors = ["[data-testid='price']", ".price"]
            _out_of_stock_selectors = ["[class*='sold-out']"]
            _out_of_stock_texts = {"sold out", "out of stock"}
            _in_stock_texts = {"add to bag", "add to cart"}
    """

    _domain: str = ""
    _price_selectors: Sequence[str] = ()
    _price_wait_selector: str = ""
    _price_wait_timeout_ms: int = 10_000
    _out_of_stock_selectors: Sequence[str] = ()
    _add_to_bag_selectors: Sequence[str] = ()
    _out_of_stock_texts: frozenset[str] = frozenset()
    _in_stock_texts: frozenset[str] = frozenset()
    _use_json_ld_price: bool = True
    _use_ogp_price: bool = False
    _use_json_ld_style_id: bool = False

    @property
    def domain(self) -> str:
        return self._domain

    async def extract(self, page: Page) -> ExtractionResult:
        price = await self._extract_price(page)
        stock = await self._extract_stock(page)
        result: ExtractionResult = {"stock_status": stock}
        if price:
            result["price"] = price
        if self._use_json_ld_style_id:
            sid = await extract_primary_style_id_from_json_ld(page)
            if sid:
                result["style_id"] = sid
        logger.debug(
            "%s extract: price=%s status=%s url=%s",
            self._domain, price, stock, page.url,
        )
        return result

    async def _extract_price(self, page: Page) -> str | None:
        if self._price_wait_selector:
            try:
                await page.wait_for_selector(
                    self._price_wait_selector,
                    timeout=self._price_wait_timeout_ms,
                )
            except Exception as exc:
                logger.debug("%s price wait: %s", self._domain, exc)

        price = await self._text_or_none(page, *self._price_selectors)
        if price:
            return price

        if self._use_json_ld_price:
            try:
                ld = await page.evaluate(_JSON_LD_PRICE_JS)
                if ld:
                    return str(ld)
            except Exception as exc:
                logger.debug("%s JSON-LD: %s", self._domain, exc)

        if self._use_ogp_price:
            try:
                ogp = await page.evaluate(_OGP_PRICE_JS)
                if ogp:
                    return str(ogp)
            except Exception as exc:
                logger.debug("%s OGP: %s", self._domain, exc)

        return None

    async def _extract_stock(self, page: Page) -> str:
        for sel in self._out_of_stock_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return "out_of_stock"
            except Exception:
                continue

        for sel in self._add_to_bag_selectors:
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

        for t in self._out_of_stock_texts:
            if t in body:
                return "out_of_stock"
        for t in self._in_stock_texts:
            if t in body:
                return "in_stock"
        return "unknown"
