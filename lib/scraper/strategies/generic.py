"""汎用フォールバックStrategy。専用Strategyが存在しないドメイン向け。"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy
from ..json_ld_style_id import extract_primary_style_id_from_json_ld

logger = logging.getLogger(__name__)

# 価格要素の汎用セレクター候補
_GENERIC_PRICE_SELECTORS = [
    "[itemprop='price']",
    "[data-price]",
    "[class*='product-price']",
    "[class*='ProductPrice']",
    "[class*='price-item--regular']",
    "[class*='price__regular']",
    ".price-box .price",
    ".price",
    "[class*='price']",
]

_OUT_OF_STOCK_PHRASES = [
    "sold out",
    "out of stock",
    "unavailable",
    "non disponibile",
    "esaurito",
    "ausverkauft",
    "épuisé",
    "agotado",
    "在庫なし",
    "売り切れ",
]

_IN_STOCK_PHRASES = [
    "add to cart",
    "add to bag",
    "buy now",
    "in stock",
    "available",
    "カートに追加",
    "今すぐ購入",
]


class GenericStrategy(ScraperStrategy):
    """サイト固有のStrategyがない場合に使用する汎用実装。

    schema.org JSON-LD / OGP メタタグ / 共通CSSセレクターを優先順で試みる。
    """

    @property
    def domain(self) -> str:
        return "__generic__"

    async def extract(self, page: Page) -> ExtractionResult:
        price_text = await self._extract_price(page)
        stock_status = await self._extract_stock(page)

        result: ExtractionResult = {"stock_status": stock_status}
        if price_text:
            result["price"] = price_text

        sid = await extract_primary_style_id_from_json_ld(page)
        if sid:
            result["style_id"] = sid

        logger.debug("Generic extract: price=%s status=%s url=%s", price_text, stock_status, page.url)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        # 1. schema.org JSON-LD
        try:
            ld_price = await page.evaluate("""() => {
                for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const nodes = [data, ...(data['@graph'] || [])];
                        for (const node of nodes) {
                            const offers = [].concat(node.offers || []);
                            for (const o of offers) {
                                if (o && o.price != null) {
                                    const c = o.priceCurrency || '';
                                    return (c ? c + ' ' : '') + String(o.price);
                                }
                            }
                        }
                    } catch {}
                }
                return null;
            }""")
            if ld_price:
                return ld_price
        except Exception as e:
            logger.debug("JSON-LD failed: %s", e)

        # 2. OGP / meta タグ
        try:
            meta_price = await page.evaluate("""() => {
                const amount = document.querySelector(
                    'meta[property="product:price:amount"], meta[name="price"]'
                );
                if (!amount) return null;
                const currency = document.querySelector(
                    'meta[property="product:price:currency"]'
                );
                const c = currency ? currency.getAttribute('content') : '';
                return (c ? c + ' ' : '') + amount.getAttribute('content');
            }""")
            if meta_price:
                return meta_price
        except Exception as e:
            logger.debug("meta price failed: %s", e)

        # 3. CSS セレクター
        price_text = await self._text_or_none(page, *_GENERIC_PRICE_SELECTORS)
        if price_text:
            return price_text

        # 4. 正規表現によるページ全文スキャン（最終手段）
        try:
            body_text = await page.inner_text("body")
            match = re.search(
                r"((?:USD|EUR|GBP|CA\$|AU\$|¥|€|£|\$)\s?\d[\d,\.]{1,10})",
                body_text,
            )
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug("body text scan failed: %s", e)

        return None

    async def _extract_stock(self, page: Page) -> str:
        try:
            page_text = (await page.inner_text("body")).lower()
        except Exception:
            return "unknown"

        for phrase in _OUT_OF_STOCK_PHRASES:
            if phrase in page_text:
                return "out_of_stock"

        for phrase in _IN_STOCK_PHRASES:
            if phrase in page_text:
                return "in_stock"

        return "unknown"
