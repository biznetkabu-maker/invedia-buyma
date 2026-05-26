"""ScraperStrategy 抽象基底クラス。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict

from playwright.async_api import Page


class ExtractionResult(TypedDict, total=False):
    """Strategy.extract() が返す辞書の型定義。"""

    price: str        # 生価格文字列（例: "$1,550"）
    currency: str     # 通貨コード。parse_price_string で解決できない場合に補完。
    stock_status: str  # "in_stock" | "out_of_stock" | "unknown"
    style_id: str  # sku/mpn 等（任意）


class ScraperStrategy(ABC):
    """各ショップのスクレイピングロジックを定義するStrategyインターフェース。

    新しいショップを追加する場合は、このクラスを継承して
    `domain` と `extract` を実装し、PriceScraper.register() で登録する。
    """

    @property
    @abstractmethod
    def domain(self) -> str:
        """照合に使用するドメイン名（例: "ssense.com"）。"""
        ...

    @abstractmethod
    async def extract(self, page: Page) -> ExtractionResult:
        """ページから価格・在庫情報を抽出して辞書で返す。

        このメソッド内で発生した例外は PriceScraper が捕捉するため、
        実装側は ValueError / AttributeError などをそのまま raise して構わない。

        Args:
            page: Playwright の Page オブジェクト（ナビゲーション済み）。

        Returns:
            ExtractionResult 型の辞書。
        """
        ...

    async def _text_or_none(self, page: Page, *selectors: str) -> str | None:
        """複数セレクターを順番に試し、最初に取得できたテキストを返すユーティリティ。"""
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return None
