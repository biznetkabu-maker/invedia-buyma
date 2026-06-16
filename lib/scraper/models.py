"""スクレイピング結果を保持するデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScrapedResult:
    """1件のスクレイピング結果を表すデータクラス。

    Attributes:
        url: スクレイピング対象URL。
        price: 数値に変換した価格。取得失敗時は None。
        currency: ISO 4217通貨コード（例: "USD", "EUR"）。
        stock_status: "in_stock" | "out_of_stock" | "unknown"。
        raw_price: サイトから取得した価格の生文字列（例: "$1,550"）。
        style_id: JSON-LD の sku/mpn 等から得た商品識別子（任意）。
        scraped_at: スクレイピング実行日時（UTC）。
        success: 正常に取得できた場合 True。
        error: 失敗時の例外メッセージ。
    """

    url: str
    price: float | None
    currency: str | None
    stock_status: str
    raw_price: str | None
    style_id: str | None = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True
    error: str | None = None

    @property
    def is_available(self) -> bool:
        """在庫ありの場合 True を返す。"""
        return self.stock_status == "in_stock"

    def __str__(self) -> str:
        if not self.success:
            return f"[FAILED] {self.url} — {self.error}"
        price_str = f"{self.currency} {self.price:,.2f}" if self.price is not None else "N/A"
        return f"[OK] {self.url} | {price_str} | {self.stock_status}"
