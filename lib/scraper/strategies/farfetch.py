"""FARFETCH (farfetch.com) 向けスクレイピングStrategy。"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy
from ..json_ld_style_id import extract_primary_style_id_from_json_ld

logger = logging.getLogger(__name__)

_PRICE_SELECTORS = [
    "[data-tstid='pd-price']",
    "[data-component='PriceFinalLarge']",
    "[data-component='PriceLarge']",
    "[data-component='PriceBlock']",
    "[class*='PriceFinal']",
    "[class*='Price_price']",
    "[class*='prices_price']",
    "[data-testid='product-price']",
    "[p[data-testid='price']",
    "[class*='ProductPrice']",
    "[itemprop='price']",
]

_ADD_TO_BAG_SELECTORS = [
    "[data-tstid='buy-item-btn']",
    "[data-testid='add-to-bag-button']",
    "button[class*='AddToBag']",
    "button[aria-label*='Add to bag']",
    "button[aria-label*='Add to Bag']",
    "button[aria-label*='カート']",
    "button[aria-label*='ショッピングバッグ']",
]

_OUT_OF_STOCK_TEXTS = {
    "sold out", "out of stock", "currently unavailable", "notify me",
    "在庫なし", "売り切れ",
}
_IN_STOCK_TEXTS = {
    "add to bag", "add to cart", "カートに入れる", "ショッピングバッグに入れる",
}


class FARFETCHStrategy(ScraperStrategy):
    @property
    def domain(self) -> str:
        return "farfetch.com"

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        for sel in (
            "button[id*='accept']",
            "button[data-testid='accept-button']",
            "button:has-text('Accept')",
            "button:has-text('同意')",
            "button:has-text('すべて同意')",
        ):
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    async def extract(self, page: Page) -> ExtractionResult:
        await self._dismiss_cookie_banner(page)
        await page.wait_for_timeout(2500)
        item_id = self._item_id_from_url(page.url)
        price = await self._extract_price(page, item_id=item_id)
        stock = await self._extract_stock(page)
        result: ExtractionResult = {"stock_status": stock}
        if price:
            result["price"] = price
            if "/jp/" in page.url.lower():
                result["currency"] = "JPY"
        sid = await extract_primary_style_id_from_json_ld(page)
        if sid:
            result["style_id"] = sid
        logger.debug("FARFETCH extract: price=%s status=%s url=%s", price, stock, page.url)
        return result

    @staticmethod
    def _item_id_from_url(url: str) -> int | None:
        m = re.search(r"item-(\d+)\.aspx", url, re.I)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    async def _extract_price(self, page: Page, *, item_id: int | None = None) -> str | None:
        try:
            await page.wait_for_selector(
                "[data-tstid='pd-price'], [data-component='PriceFinalLarge'], "
                "[class*='Price_price'], [itemprop='price'], #__NEXT_DATA__",
                timeout=20_000,
            )
        except Exception as exc:
            logger.debug("farfetch: %s", exc)

        price = await self._text_or_none(page, *_PRICE_SELECTORS)
        if price:
            return price

        for sel in ("meta[property='og:price:amount']", "meta[itemprop='price']"):
            try:
                el = await page.query_selector(sel)
                if el:
                    content = await el.get_attribute("content")
                    if content and re.search(r"\d", content):
                        return content
            except Exception:
                continue

        price = await self._price_from_next_data(page, item_id=item_id)
        if price:
            return price

        try:
            ld = await page.evaluate("""() => {
                for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const d = JSON.parse(s.textContent);
                        const items = Array.isArray(d) ? d : [d];
                        for (const item of items) {
                            const offers = [].concat(item.offers || []);
                            for (const o of offers) {
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
            logger.debug("farfetch: %s", exc)

        yen = await self._extract_yen_from_page(page)
        if yen:
            return yen
        return None

    async def _extract_yen_from_page(self, page: Page) -> str | None:
        try:
            found = await page.evaluate("""() => {
                const sels = [
                    '[data-tstid="pd-price"]',
                    '[data-component="PriceFinalLarge"]',
                    '[data-component="PriceLarge"]',
                    '[class*="Price_price"]',
                ];
                for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el) {
                        const t = (el.textContent || '').trim();
                        if (/[¥￥]\\s*[\\d,]+/.test(t)) return t;
                    }
                }
                const m = document.body.innerText.match(/[¥￥]\\s*[\\d,]+/);
                return m ? m[0] : null;
            }""")
            if found:
                return found.strip()
        except Exception as e:
            logger.debug("FARFETCH yen extract failed: %s", e)
        return None

    async def _price_from_next_data(
        self, page: Page, *, item_id: int | None = None
    ) -> str | None:
        try:
            raw = await page.evaluate(
                "() => document.querySelector('#__NEXT_DATA__')?.textContent || ''"
            )
            if not raw:
                return None
            data = json.loads(raw)
            found = self._find_price_in_obj(data, item_id=item_id)
            if found:
                return found
        except Exception as e:
            logger.debug("FARFETCH __NEXT_DATA__ parse failed: %s", e)
        return None

    def _find_price_in_obj(
        self, obj: object, depth: int = 0, *, item_id: int | None = None
    ) -> str | None:
        candidates: list[tuple[float, str]] = []

        def _skip_as_item_id(val: float) -> bool:
            if item_id is None:
                return False
            iv = int(val)
            if iv == item_id:
                return True
            if len(str(item_id)) >= 6 and str(item_id) in str(iv):
                return True
            return False

        def collect(o: object, d: int) -> None:
            if d > 14:
                return
            if isinstance(o, dict):
                if "price" in o and o["price"] is not None:
                    cur = o.get("priceCurrency") or o.get("currency") or ""
                    if cur is None or str(cur).lower() in ("none", "null"):
                        cur = ""
                    try:
                        p = o["price"]
                        val: Optional[float] = None
                        if isinstance(p, (int, float)):
                            val = float(p)
                        elif isinstance(p, str) and re.search(r"\d", p):
                            from lib.scraper.utils import parse_price_string
                            val, _ = parse_price_string(p)
                        if val and 1_000 <= val <= 2_500_000 and not _skip_as_item_id(val):
                            raw = f"{cur}{val}" if cur else str(val)
                            candidates.append((val, raw))
                    except (TypeError, ValueError):
                        pass
                for v in o.values():
                    collect(v, d + 1)
            elif isinstance(o, list):
                for item in o[:50]:
                    collect(item, d + 1)

        collect(obj, depth)
        if not candidates:
            return None
        # 外れ値（商品ID・誤った高額）を避け、中間的な妥当な価格を優先
        candidates.sort(key=lambda x: x[0])
        mid = candidates[len(candidates) // 2]
        return mid[1]

    async def _extract_stock(self, page: Page) -> str:
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
