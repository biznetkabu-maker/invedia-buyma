"""利益計算モジュール。

利益計算式:
    JPY仕入原価  = 現地価格 × 為替レート
    関税         = JPY仕入原価 × 関税率
    BUYMA手数料  = BUYMA販売価格 × 手数料率
    総コスト     = JPY仕入原価 + 関税 + 国際送料 + BUYMA手数料
    利益         = BUYMA販売価格 - 総コスト
    利益率       = 利益 / BUYMA販売価格
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProfitBreakdown:
    """利益計算の内訳を保持するデータクラス。"""

    local_price: float       # 現地価格（外貨）
    exchange_rate: float     # 為替レート
    buyma_price: float       # BUYMA販売価格（JPY）
    jpy_cost: float          # JPY仕入原価（local_price × exchange_rate）
    customs_cost: float      # 関税（JPY）
    shipping_cost: float     # 国際送料（JPY）
    buyma_fee: float         # BUYMA手数料（JPY）
    total_cost: float        # 総コスト（JPY）
    profit: float            # 利益（JPY）
    profit_rate: float       # 利益率（0.0〜1.0）

    @property
    def is_profitable(self) -> bool:
        return self.profit > 0

    def summary(self) -> str:
        return (
            f"BUYMA価格: ¥{self.buyma_price:,.0f} | "
            f"総コスト: ¥{self.total_cost:,.0f} "
            f"(仕入: ¥{self.jpy_cost:,.0f} + 関税: ¥{self.customs_cost:,.0f} + "
            f"送料: ¥{self.shipping_cost:,.0f} + 手数料: ¥{self.buyma_fee:,.0f}) | "
            f"利益: ¥{self.profit:,.0f} ({self.profit_rate:.1%})"
        )


def calculate_profit(
    local_price: float,
    exchange_rate: float,
    buyma_price: float,
    customs_rate: float = 0.10,
    shipping_cost: float = 2000.0,
    buyma_fee_rate: float = 0.077,
) -> ProfitBreakdown:
    """利益を計算して ProfitBreakdown を返す。

    Args:
        local_price: 現地価格（外貨単位）。
        exchange_rate: 為替レート（1外貨単位あたりのJPY）。
        buyma_price: BUYMA上の販売価格（JPY）。
        customs_rate: 関税率（例: 0.10 = 10%）。
        shipping_cost: 国際送料固定額（JPY）。
        buyma_fee_rate: BUYMA手数料率（例: 0.077 = 7.7%）。小口取引の上限値を使用。

    Returns:
        ProfitBreakdown。

    Raises:
        ValueError: 入力値が負の場合。
    """
    if local_price < 0 or exchange_rate <= 0 or buyma_price < 0:
        raise ValueError(
            f"価格・為替に不正な値が含まれています: "
            f"local_price={local_price}, exchange_rate={exchange_rate}, "
            f"buyma_price={buyma_price}"
        )

    jpy_cost = local_price * exchange_rate
    customs_cost = jpy_cost * customs_rate
    buyma_fee = buyma_price * buyma_fee_rate
    total_cost = jpy_cost + customs_cost + shipping_cost + buyma_fee
    profit = buyma_price - total_cost
    profit_rate = profit / buyma_price if buyma_price > 0 else 0.0

    return ProfitBreakdown(
        local_price=local_price,
        exchange_rate=exchange_rate,
        buyma_price=buyma_price,
        jpy_cost=round(jpy_cost, 2),
        customs_cost=round(customs_cost, 2),
        shipping_cost=round(shipping_cost, 2),
        buyma_fee=round(buyma_fee, 2),
        total_cost=round(total_cost, 2),
        profit=round(profit, 2),
        profit_rate=round(profit_rate, 6),
    )


def try_calculate_profit(
    local_price_str: str,
    exchange_rate_str: str,
    buyma_price_str: str,
    customs_rate: float = 0.10,
    shipping_cost: float = 2000.0,
    buyma_fee_rate: float = 0.077,
) -> ProfitBreakdown | None:
    """文字列入力から利益計算を試みる。変換失敗時は None を返す。"""
    try:
        local_price = float(local_price_str or 0)
        exchange_rate = float(exchange_rate_str or 0)
        buyma_price = float(buyma_price_str or 0)

        if local_price <= 0 or exchange_rate <= 0 or buyma_price <= 0:
            return None

        return calculate_profit(
            local_price=local_price,
            exchange_rate=exchange_rate,
            buyma_price=buyma_price,
            customs_rate=customs_rate,
            shipping_cost=shipping_cost,
            buyma_fee_rate=buyma_fee_rate,
        )
    except (ValueError, ZeroDivisionError):
        return None
