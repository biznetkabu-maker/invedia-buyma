"""intake.py の売価自動算出ロジックのテスト。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.buyma_demand import BUYMADemandSignal
from lib.intake import _resolve_buyma_price_from_demand


def _demand(min_price: int | None = 200000) -> BUYMADemandSignal:
    return BUYMADemandSignal(
        brand="PRADA",
        product_name="wallet",
        favorites_count=10,
        listing_count=5,
        min_price=min_price,
        max_price=250000,
        order_count=0,
        has_cart=False,
        search_url="https://www.buyma.com/buy/search/",
    )


class TestResolveBuymaPrice(unittest.TestCase):
    @patch("lib.intake._price_factor", return_value=0.97)
    def test_auto_uses_min_times_factor(self, _factor) -> None:
        price = _resolve_buyma_price_from_demand(
            _demand(200000), manual_jpy=0.0, use_auto=True
        )
        self.assertEqual(price, 194000.0)

    @patch("lib.intake._price_factor", return_value=0.97)
    def test_manual_overrides_auto_flag_false(self, _factor) -> None:
        price = _resolve_buyma_price_from_demand(
            _demand(200000), manual_jpy=180000.0, use_auto=False
        )
        self.assertEqual(price, 180000.0)


if __name__ == "__main__":
    unittest.main()
