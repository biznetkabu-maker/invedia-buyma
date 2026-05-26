"""SSENSE (ssense.com) 向けスクレイピングStrategy。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..base import ExtractionResult, ScraperStrategy
from ..json_ld_style_id import extract_primary_style_id_from_json_ld

logger = logging.getLogger(__name__)

# 価格要素のセレクター候補（優先順）
_PRICE_SELECTORS = [
    # data-testid 属性（最も安定）
    "[data-testid='price']",
    "[data-testid='product-price']",
    # class名ベース（ハッシュ付きでも部分一致で拾う）
    "[class*='Price__priceItem']",
    "[class*='Price__price']",
    "[class*='ProductPrice']",
    # schema.org マイクロデータ
    "[itemprop='price']",
    # JSON-LD は engine 側で処理するため ここではスキップ
    # 最後の手段
    ".price",
    "[class*='price']",
]

# 在庫ステータス判定用テキストマッピング
_OUT_OF_STOCK_TEXTS = {
    "sold out",
    "épuisé",
    "ausverkauft",
    "agotado",
    "なし",
    "sold-out",
}

_IN_STOCK_TEXTS = {
    "add to bag",
    "add to cart",
    "ajouter au panier",
    "in den warenkorb",
    "añadir al carrito",
    "カートに追加",
}


class SSENSEStrategy(ScraperStrategy):
    """SSENSE の商品ページから価格・在庫を取得するStrategy。"""

    @property
    def domain(self) -> str:
        return "ssense.com"

    async def extract(self, page: Page) -> ExtractionResult:
        price_text = await self._extract_price(page)
        stock_status = await self._extract_stock(page)

        result: ExtractionResult = {"stock_status": stock_status}
        if price_text:
            result["price"] = price_text

        sid = await extract_primary_style_id_from_json_ld(page)
        if sid:
            result["style_id"] = sid

        logger.debug("SSENSE extract: price=%s status=%s url=%s", price_text, stock_status, page.url)
        return result

    async def _extract_price(self, page: Page) -> str | None:
        # セレクター候補を順番に試す
        price_text = await self._text_or_none(page, *_PRICE_SELECTORS)
        if price_text:
            return price_text

        # fallback: JSON-LD schema.org から価格を読む
        try:
            price_ld = await page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const offers = data.offers || (data['@graph'] || []).flatMap(n => n.offers || []);
                        for (const o of [].concat(offers)) {
                            if (o && o.price != null) return String(o.priceCurrency || '') + String(o.price);
                        }
                    } catch {}
                }
                return null;
            }""")
            if price_ld:
                return price_ld
        except Exception as e:
            logger.debug("JSON-LD parse failed: %s", e)

        return None

    async def _extract_stock(self, page: Page) -> str:
        # 1. Sold Out オーバーレイ・テキストを確認
        sold_out_selectors = [
            "[class*='SoldOut']",
            "[class*='sold-out']",
            "[class*='soldOut']",
            "[data-testid='sold-out']",
            ".sold-out",
        ]
        for sel in sold_out_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return "out_of_stock"
            except Exception:
                continue

        # 2. ページ内の全ボタン・テキストを走査
        try:
            page_text = (await page.inner_text("body")).lower()
        except Exception:
            return "unknown"

        for phrase in _OUT_OF_STOCK_TEXTS:
            if phrase in page_text:
                return "out_of_stock"

        for phrase in _IN_STOCK_TEXTS:
            if phrase in page_text:
                return "in_stock"

        return "unknown"
