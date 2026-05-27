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
    _select_fallback_candidate,
)
from lib.multi_source import BestSourceResult, SourceCandidate
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


class TestSelectFallbackCandidate(unittest.TestCase):

    def _make_candidate(
        self, url: str = "https://example.com/p1", price: float | None = 500.0,
        currency: str = "EUR", stock_status: str = "out_of_stock",
        profit: float | None = 30000.0, style_id: str = "ABC123",
    ) -> SourceCandidate:
        return SourceCandidate(
            url=url, price=price, currency=currency,
            stock_status=stock_status, jpy_cost=None,
            profit=profit, profit_rate=None, breakdown=None,
            style_id=style_id,
        )

    def _make_result(
        self, candidates: list[SourceCandidate], reason: str = "",
    ) -> BestSourceResult:
        return BestSourceResult(
            best=None, all_candidates=candidates, reason=reason,
        )

    @patch("lib.scraper.price_sanity.is_plausible_supply_price", return_value=True)
    def test_returns_first_valid_candidate(self, _mock) -> None:
        c = self._make_candidate()
        result = self._make_result([c])
        url, price, _, sid, stock = _select_fallback_candidate(
            result, "ABC123", 200000.0, 155.0,
        )
        self.assertEqual(url, "https://example.com/p1")
        self.assertEqual(price, 500.0)
        self.assertEqual(sid, "ABC123")

    def test_skips_no_price(self) -> None:
        c = self._make_candidate(price=None)
        result = self._make_result([c])
        url, price, _, _, _ = _select_fallback_candidate(
            result, "", 200000.0, 155.0,
        )
        self.assertEqual(url, "")
        self.assertEqual(price, 0.0)

    @patch("lib.scraper.price_sanity.is_plausible_supply_price", return_value=True)
    def test_skips_style_mismatch(self, _mock) -> None:
        c = self._make_candidate(style_id="XYZ999")
        result = self._make_result([c])
        url, price, _, _, _ = _select_fallback_candidate(
            result, "ABC123", 200000.0, 155.0,
        )
        self.assertEqual(url, "")

    @patch("lib.scraper.price_sanity.is_plausible_supply_price", return_value=True)
    def test_skips_negative_profit(self, _mock) -> None:
        c = self._make_candidate(profit=-5000.0)
        result = self._make_result([c])
        url, price, _, _, _ = _select_fallback_candidate(
            result, "", 200000.0, 155.0,
        )
        self.assertEqual(url, "")

    def test_style_id_mismatch_reason_returns_empty(self) -> None:
        c = self._make_candidate()
        result = self._make_result([c], reason='型番「ABC」が一致しません')
        url, price, _, _, _ = _select_fallback_candidate(
            result, "ABC", 200000.0, 155.0,
        )
        self.assertEqual(url, "")


if __name__ == "__main__":
    unittest.main()
