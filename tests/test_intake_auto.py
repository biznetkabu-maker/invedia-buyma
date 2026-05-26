"""intake.py 自動モードのヘルパーテスト。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.buyma_demand import BUYMADemandSignal
from lib.intake import (
    _guess_currency_from_url,
    _is_buyma_reference_url,
    _product_name_without_brand,
    _resolve_buyma_price_auto,
)
from lib.sheet_manager import ProductRecord


class TestIntakeAutoHelpers(unittest.TestCase):

    def test_is_buyma_reference_url(self) -> None:
        self.assertTrue(
            _is_buyma_reference_url("https://www.buyma.com/items/12345/")
        )
        self.assertFalse(
            _is_buyma_reference_url("https://www.ssense.com/product/1")
        )

    def test_product_name_without_brand(self) -> None:
        rec = ProductRecord(
            商品名="CELINE トリオバッグ",
            ブランド="CELINE",
        )
        self.assertEqual(_product_name_without_brand(rec), "トリオバッグ")

    def test_guess_currency(self) -> None:
        self.assertEqual(
            _guess_currency_from_url("https://www.ssense.com/en-us/product/x"),
            "USD",
        )
        self.assertEqual(
            _guess_currency_from_url("https://www.mytheresa.com/en/product.html"),
            "EUR",
        )

    @patch("lib.intake._price_factor", return_value=0.97)
    def test_resolve_buyma_price_auto(self, _factor) -> None:
        demand = BUYMADemandSignal(
            brand="X", product_name="Y",
            favorites_count=0, listing_count=0,
            min_price=200000, max_price=250000,
            order_count=0, has_cart=False, search_url="",
        )
        self.assertEqual(_resolve_buyma_price_auto(demand, None), 194000.0)
        self.assertEqual(_resolve_buyma_price_auto(demand, 180000), 194000.0)

        empty = BUYMADemandSignal(
            brand="X", product_name="Y",
            favorites_count=0, listing_count=0,
            min_price=None, max_price=None,
            order_count=0, has_cart=False, search_url="",
        )
        self.assertEqual(_resolve_buyma_price_auto(empty, 150000), 150000.0)


if __name__ == "__main__":
    unittest.main()
