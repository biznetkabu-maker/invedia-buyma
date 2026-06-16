"""スプレッドシート行の集計・分析（副作用なし）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from lib.profit_calculator import ProfitBreakdown, try_calculate_profit
from lib.sheet_manager import ProductRecord


@dataclass
class ProductInsight:
    """分析対象の1商品サマリー。"""

    商品名: str
    ブランド: str
    在庫ステータス: str
    利益額: float | None
    利益率: float | None
    仕入れURL: str
    備考: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "商品名": self.商品名,
            "ブランド": self.ブランド,
            "在庫ステータス": self.在庫ステータス,
            "利益額": self.利益額,
            "利益率": self.利益率,
            "仕入れURL": self.仕入れURL,
            "備考": self.備考,
        }


@dataclass
class SheetAnalysisReport:
    """全行を走査した分析結果。"""

    total_rows: int
    status_counts: dict[str, int]
    calculable_rows: int
    profitable_rows: int
    below_target_profit_rows: int
    missing_price_rows: int
    avg_profit_jpy: float | None
    top_profit: list[ProductInsight] = field(default_factory=list)
    lowest_profit: list[ProductInsight] = field(default_factory=list)
    needs_attention: list[ProductInsight] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "status_counts": self.status_counts,
            "calculable_rows": self.calculable_rows,
            "profitable_rows": self.profitable_rows,
            "below_target_profit_rows": self.below_target_profit_rows,
            "missing_price_rows": self.missing_price_rows,
            "avg_profit_jpy": self.avg_profit_jpy,
            "top_profit": [p.to_dict() for p in self.top_profit],
            "lowest_profit": [p.to_dict() for p in self.lowest_profit],
            "needs_attention": [p.to_dict() for p in self.needs_attention],
        }


def _insight_from_record(
    record: ProductRecord,
    breakdown: ProfitBreakdown | None,
    *,
    note: str = "",
) -> ProductInsight:
    profit_val: float | None = None
    rate_val: float | None = None
    if breakdown is not None:
        profit_val = breakdown.profit
        rate_val = breakdown.profit_rate
    elif record.利益額.strip():
        try:
            profit_val = float(record.利益額)
        except ValueError:
            logger.debug("利益額パース失敗: %s", record.利益額)
    return ProductInsight(
        商品名=record.商品名,
        ブランド=record.ブランド,
        在庫ステータス=record.在庫ステータス,
        利益額=profit_val,
        利益率=rate_val,
        仕入れURL=record.仕入れURL,
        備考=note,
    )


def analyze_records(
    records: list[ProductRecord],
    *,
    buyma_fee_rate: float = 0.077,
    customs_rate: float = 0.10,
    shipping_cost_jpy: float = 2000.0,
    target_profit_rate: float = 0.10,
    top_n: int = 10,
) -> SheetAnalysisReport:
    """ProductRecord リストから分析レポートを生成する。"""
    status_counts: dict[str, int] = {}
    profits: list[float] = []
    scored: list[tuple[float, ProductInsight]] = []
    needs_attention: list[ProductInsight] = []
    calculable = 0
    profitable = 0
    below_target = 0
    missing_price = 0

    attention_seen: set[str] = set()

    for record in records:
        status_key = record.在庫ステータス or "(空)"
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

        breakdown = try_calculate_profit(
            record.現地価格,
            record.為替,
            record.BUYMA販売価格,
            customs_rate=customs_rate,
            shipping_cost=shipping_cost_jpy,
            buyma_fee_rate=buyma_fee_rate,
        )
        insight = _insight_from_record(record, breakdown)

        if breakdown is None:
            missing_price += 1
        else:
            calculable += 1
            profits.append(breakdown.profit)
            scored.append((breakdown.profit, insight))
            if breakdown.profit > 0:
                profitable += 1
            if breakdown.profit_rate < target_profit_rate:
                below_target += 1

        def _add_attention(note: str, record=record, breakdown=breakdown) -> None:
            key = record.商品名 or f"__row_{len(needs_attention)}"
            if key in attention_seen:
                return
            attention_seen.add(key)
            needs_attention.append(_insight_from_record(record, breakdown, note=note))

        status = record.在庫ステータス
        if status.startswith("要確認") or status == "停止中" or status == "BUYMA候補":
            _add_attention(status)
        elif breakdown is not None and breakdown.profit_rate < target_profit_rate:
            _add_attention(
                f"利益率 {breakdown.profit_rate:.1%} < 目標 {target_profit_rate:.1%}"
            )

    scored.sort(key=lambda x: x[0], reverse=True)
    top_profit = [item for _, item in scored[:top_n]]
    lowest_profit = [item for _, item in sorted(scored, key=lambda x: x[0])[:top_n]]

    avg_profit: float | None = None
    if profits:
        avg_profit = round(sum(profits) / len(profits), 2)

    return SheetAnalysisReport(
        total_rows=len(records),
        status_counts=status_counts,
        calculable_rows=calculable,
        profitable_rows=profitable,
        below_target_profit_rows=below_target,
        missing_price_rows=missing_price,
        avg_profit_jpy=avg_profit,
        top_profit=top_profit,
        lowest_profit=lowest_profit,
        needs_attention=needs_attention[: top_n * 2],
    )
