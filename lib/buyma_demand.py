"""
BUYMA 需要調査モジュール。

BUYMA の公開検索ページをスクレイプして、指定商品の需要シグナルを取得する。
工程② 「お気に入り数・競合出品数の確認」を自動化する。

取得できる情報:
  - favorites_count   : お気に入り登録数（需要の直接指標）
  - listing_count     : 競合出品数
  - min_price         : 競合の最安値（JPY）
  - max_price         : 競合の最高値（JPY）
  - order_count       : 注文実績数（表示されている場合）
  - has_cart          : カート投入された商品があるか

⚠️ BUYMA 利用規約を確認の上ご使用ください。
   公開検索ページのみを対象とし、ログインは不要です。
   リクエスト間隔を設けています。

使い方:
    from lib.buyma_demand import BUYMADemandScraper

    scraper = BUYMADemandScraper()
    signal = scraper.get_demand("CELINE", "トリオバッグ スモール")
    print(signal)
    # → BUYMADemandSignal(
    #       favorites_count=23, listing_count=8,
    #       min_price=198000, max_price=245000, order_count=5
    #   )
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# BUYMA 公開検索URL（ログイン不要）
_BUYMA_SEARCH_URL = "https://www.buyma.com/buy/search/"


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class BUYMADemandSignal:
    """BUYMA 検索結果から抽出した需要シグナル。"""

    brand: str
    product_name: str
    favorites_count: int        # 最上位商品のお気に入り数（0 = 未取得）
    listing_count: int          # 検索結果の出品数
    min_price: Optional[int]    # 競合の最安値 JPY
    max_price: Optional[int]    # 競合の最高値 JPY
    order_count: int            # 注文実績数合計（表示されている場合）
    has_cart: bool              # カート投入された商品が1件以上あるか
    search_url: str             # 調査に使用した検索URL
    raw_count_text: str = ""    # デバッグ用の生テキスト

    @property
    def demand_level(self) -> str:
        """需要レベルを文字列で返す。"""
        if self.favorites_count >= 20 or self.order_count >= 5:
            return "高"
        if self.favorites_count >= 10 or self.order_count >= 2:
            return "中"
        if self.listing_count == 0:
            return "データなし"
        return "低"

    @property
    def competition_level(self) -> str:
        """競合レベルを文字列で返す。"""
        if self.listing_count == 0:
            return "データなし"
        if self.listing_count <= 3:
            return "少（参入しやすい）"
        if self.listing_count <= 10:
            return "中（標準的）"
        return "多（価格競争になりやすい）"

    def summary(self) -> str:
        price_range = ""
        if self.min_price and self.max_price:
            price_range = f" | 競合価格帯: ¥{self.min_price:,}〜¥{self.max_price:,}"
        return (
            f"[BUYMA需要] {self.brand} {self.product_name}\n"
            f"  お気に入り: {self.favorites_count}件 / "
            f"競合出品: {self.listing_count}件 / "
            f"注文実績: {self.order_count}件"
            f"{price_range}\n"
            f"  需要レベル: {self.demand_level} | 競合レベル: {self.competition_level}"
        )

    def to_evaluation_kwargs(self) -> dict:
        """PurchaseEvaluator の EvaluationInput に渡せる辞書を返す。"""
        return {
            "favorites_count": self.favorites_count,
            "has_cart_addition": self.has_cart,
        }


# ============================================================================
# BUYMADemandScraper
# ============================================================================

class BUYMADemandScraper:
    """BUYMA 公開検索ページから需要シグナルを取得するクラス。

    Args:
        headless: ヘッドレスモードで実行するか（default: True）
        page_wait_ms: ページ読み込み後の追加待機時間 ms（default: 3000）
    """

    def __init__(self, headless: bool = True, page_wait_ms: int = 3000) -> None:
        self._headless = headless
        self._page_wait_ms = page_wait_ms

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------

    def get_demand(
        self,
        brand: str,
        product_name: str,
        timeout_ms: int = 20_000,
    ) -> BUYMADemandSignal:
        """ブランド名・商品名で BUYMA を検索して需要シグナルを取得する（同期版）。"""
        return asyncio.run(self.get_demand_async(brand, product_name, timeout_ms))

    async def get_demand_async(
        self,
        brand: str,
        product_name: str,
        timeout_ms: int = 20_000,
    ) -> BUYMADemandSignal:
        """ブランド名・商品名で BUYMA を検索して需要シグナルを取得する（非同期版）。"""
        from urllib.parse import quote
        from playwright.async_api import async_playwright
        from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

        keyword = f"{brand} {product_name}"
        search_url = f"{_BUYMA_SEARCH_URL}?keyword={quote(keyword)}"

        logger.info("BUYMA需要調査: %s", search_url)

        empty = BUYMADemandSignal(
            brand=brand, product_name=product_name,
            favorites_count=0, listing_count=0,
            min_price=None, max_price=None,
            order_count=0, has_cart=False,
            search_url=search_url,
        )

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self._headless, args=LAUNCH_ARGS
                )
                ctx = await browser.new_context(**stealth_context_options())
                page = await ctx.new_page()
                await apply_stealth_scripts(page)
                page.set_default_timeout(timeout_ms)

                try:
                    await page.goto(search_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(self._page_wait_ms)
                    signal = await self._extract_demand(page, brand, product_name, search_url)
                    return signal
                except Exception as e:
                    logger.warning("BUYMA需要調査失敗 [%s]: %s", keyword, e)
                    return empty
                finally:
                    await browser.close()
        except Exception as e:
            logger.warning("Playwright起動失敗: %s", e)
            return empty

    # ------------------------------------------------------------------
    # ページ解析
    # ------------------------------------------------------------------

    async def _extract_demand(
        self, page, brand: str, product_name: str, search_url: str
    ) -> BUYMADemandSignal:
        """検索結果ページから需要シグナルを抽出する。
        複数のアプローチを試みてフォールバックする。
        """
        # ── アプローチ1: 商品カードを解析 ─────────────────────────────────
        listing_count = await self._extract_listing_count(page)
        favorites_list, prices, orders = await self._extract_item_cards(page)

        # ── アプローチ2: 数値が取れなければ body テキスト全体からフォールバック ─
        if not favorites_list and not prices:
            try:
                body = (await page.inner_text("body")).strip()
                # ページに商品があるか最低限チェック
                if brand.lower() not in body.lower() and listing_count == 0:
                    logger.debug("BUYMAページに対象商品が見つかりません")
                # body全体からお気に入り数・価格を抽出
                fav_from_body = _extract_number_with_keyword(
                    body, ["お気に入り", "いいね"]
                )
                if fav_from_body:
                    favorites_list = [fav_from_body]
                prices_from_body = _extract_all_jpy_prices(body)
                if prices_from_body:
                    prices = prices_from_body[:10]  # 上位10件
            except Exception as e:
                logger.debug("body解析フォールバック失敗: %s", e)

        favorites_count = max(favorites_list, default=0)
        order_count = sum(orders)
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        has_cart = order_count > 0 or favorites_count >= 10

        # ── 結果テキスト（デバッグ用） ─────────────────────────────────────
        raw_count_text = f"listing={listing_count} favs={favorites_list[:3]} prices={prices[:3]}"

        signal = BUYMADemandSignal(
            brand=brand,
            product_name=product_name,
            favorites_count=favorites_count,
            listing_count=listing_count,
            min_price=min_price,
            max_price=max_price,
            order_count=order_count,
            has_cart=has_cart,
            search_url=search_url,
            raw_count_text=raw_count_text,
        )
        logger.info("BUYMA需要: %s", signal.summary())
        return signal

    async def _extract_listing_count(self, page) -> int:
        """検索結果の総出品数を取得する。複数セレクタを試みる。"""
        # BUYMA 固有のセレクタ（安定度が高い順）
        count_selectors = [
            "[class*='SearchResult'] [class*='count']",
            "[class*='search-result'] [class*='count']",
            "[class*='itemCount']",
            "[class*='item-count']",
            "[class*='result-count']",
            "[class*='search-count']",
            "[class*='total']",
        ]
        for sel in count_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    n = _extract_number(text)
                    if n and n < 100_000:
                        return n
            except Exception:
                continue

        # フォールバック: 商品カードを数える
        card_selectors = [
            "[class*='item-card']",
            "[class*='ItemCard']",
            "[class*='product-card']",
            "[class*='item-list'] li",
            "[class*='itemList'] li",
        ]
        for sel in card_selectors:
            try:
                cards = await page.query_selector_all(sel)
                if cards:
                    return len(cards)
            except Exception:
                continue
        return 0

    async def _extract_item_cards(
        self, page
    ) -> tuple[list[int], list[int], list[int]]:
        """商品カードからお気に入り数・価格・注文数を抽出する。"""
        favorites_list: list[int] = []
        prices: list[int] = []
        orders: list[int] = []

        card_selectors = [
            "[class*='item-card']",
            "[class*='ItemCard']",
            "[class*='product-card']",
            "[class*='item-list'] li",
            "[class*='itemList'] li",
            "article",
        ]

        for sel in card_selectors:
            try:
                cards = await page.query_selector_all(sel)
                if not cards:
                    continue

                for card in cards[:20]:
                    try:
                        text = (await card.inner_text()).strip()
                        if not text or len(text) < 5:
                            continue

                        fav = _extract_number_with_keyword(
                            text, ["お気に入り", "いいね", "ハート", "♡", "❤", "likes"]
                        )
                        if fav and fav < 10_000:
                            favorites_list.append(fav)

                        price = _extract_jpy_price(text)
                        if price:
                            prices.append(price)

                        order = _extract_number_with_keyword(
                            text, ["注文", "販売実績", "購入", "sold", "orders"]
                        )
                        if order and order < 10_000:
                            orders.append(order)

                    except Exception:
                        continue

                if favorites_list or prices:
                    break

            except Exception:
                continue

        return favorites_list, prices, orders


# ============================================================================
# ユーティリティ
# ============================================================================

def _extract_number(text: str) -> Optional[int]:
    """テキストから最初の数値を抽出する。"""
    m = re.search(r"[\d,]+", text.replace("，", ","))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _extract_number_with_keyword(text: str, keywords: list[str]) -> Optional[int]:
    """キーワードの近くにある数値を抽出する。"""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            idx = text_lower.index(kw.lower())
            # キーワードの前後30文字から数値を探す
            window = text[max(0, idx - 10): idx + 30]
            n = _extract_number(window)
            if n and n < 10000:
                return n
    return None


def _extract_jpy_price(text: str) -> Optional[int]:
    """テキストから最初の JPY 価格を抽出する（¥ または 円 付き）。"""
    prices = _extract_all_jpy_prices(text)
    return prices[0] if prices else None


def _extract_all_jpy_prices(text: str) -> list[int]:
    """テキストから全ての JPY 価格を抽出する。"""
    patterns = [
        r"¥\s*([\d,]+)",
        r"￥\s*([\d,]+)",
        r"([\d,]+)\s*円",
    ]
    results: list[int] = []
    text_norm = text.replace("，", ",")
    for pat in patterns:
        for m in re.finditer(pat, text_norm):
            try:
                val = int(m.group(1).replace(",", ""))
                if 1_000 <= val <= 10_000_000:  # 現実的な価格範囲
                    results.append(val)
            except ValueError:
                continue
    return sorted(set(results))
