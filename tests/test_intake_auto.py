"""intake.py 自動モードのヘルパーテスト。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lib.buyma_demand import BUYMADemandSignal
from lib.intake import (
    _guess_currency_from_url,
    _is_buyma_reference_url,
    _product_name_without_brand,
    _resolve_buyma_price_auto,
    _select_fallback_candidate,
)
from lib.intake_auto import (
    _auto_check_prada_official,
    _auto_extract_product_identity,
    _auto_search_supply_urls,
    _get_exchange_rate_auto,
    _run_auto_intake,
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


class TestGetExchangeRateAuto(unittest.TestCase):

    def test_jpy_returns_one(self) -> None:
        self.assertEqual(_get_exchange_rate_auto("JPY"), 1.0)

    @patch("lib.intake_auto.get_rate", return_value=158.345)
    def test_success_rounds(self, _rate) -> None:
        self.assertEqual(_get_exchange_rate_auto("EUR"), 158.34)

    @patch("lib.intake_auto.get_rate", side_effect=RuntimeError("api down"))
    def test_failure_falls_back(self, _rate) -> None:
        self.assertEqual(_get_exchange_rate_auto("USD"), 155.0)

    @patch("lib.intake_auto.get_rate", return_value=None)
    def test_none_rate_falls_back(self, _rate) -> None:
        self.assertEqual(_get_exchange_rate_auto("GBP"), 155.0)


class TestAutoCheckPradaOfficial(unittest.TestCase):

    def test_non_prada_returns_none(self) -> None:
        self.assertIsNone(
            _auto_check_prada_official("GUCCI", "SKU1", "raw", "name")
        )

    def test_no_style_id_returns_none(self) -> None:
        self.assertIsNone(
            _auto_check_prada_official("PRADA", "", "raw", "name")
        )

    @patch("lib.funnel_policy.official_prada_enabled", return_value=False)
    def test_disabled_returns_none(self, _enabled) -> None:
        self.assertIsNone(
            _auto_check_prada_official("PRADA", "SKU1", "raw", "name")
        )

    @patch("lib.official_catalog.prada.lookup_prada_official_sync")
    @patch("lib.funnel_policy.official_prada_enabled", return_value=True)
    def test_enabled_returns_match(self, _enabled, mock_lookup) -> None:
        match = SimpleNamespace(
            sku="SKU1", english_name="Bag", product_url="https://prada.com/x",
            identity_note="exact",
        )
        mock_lookup.return_value = match
        result = _auto_check_prada_official("PRADA", "SKU1", "raw", "Bag")
        self.assertIs(result, match)


class TestAutoExtractProductIdentity(unittest.TestCase):

    def _info(self, **kw):
        base = dict(
            product_name="Galleria Bag", raw_title="PRADA Galleria Bag",
            brand="PRADA", style_id="1BA863", price_jpy=250000,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_extracts_identity(self) -> None:
        result = _auto_extract_product_identity(
            self._info(), "Galleria Bag", "PRADA", "1BA863", "バッグ",
        )
        self.assertIsNotNone(result)
        brand, product_name = result[0], result[1]
        self.assertTrue(brand)
        self.assertTrue(product_name)
        self.assertEqual(result[6], "1BA863")  # buyma_style_id

    def test_missing_brand_returns_none(self) -> None:
        info = self._info(product_name="", raw_title="", brand="")
        result = _auto_extract_product_identity(info, "", "", "", "バッグ")
        self.assertIsNone(result)


class TestAutoSearchSupplyUrls(unittest.TestCase):

    @patch("lib.supply_search_utils.url_is_valid_supply_candidate", return_value=True)
    @patch("lib.supply_url_finder.discover_supply_urls_sync")
    def test_non_funnel_collects_urls(self, mock_disc, _valid) -> None:
        mock_disc.return_value = [
            SimpleNamespace(product_url="https://ssense.com/p1", site_name="SSENSE"),
        ]
        urls = _auto_search_supply_urls(
            "PRADA", "Bag", "SKU1", "raw", None, None, use_funnel=False,
        )
        self.assertEqual(urls, ["https://ssense.com/p1"])

    @patch("lib.supply_search_utils.url_is_valid_supply_candidate", return_value=True)
    @patch("lib.supply_url_finder.discover_supply_urls_funnel")
    def test_funnel_collects_urls(self, mock_disc, _valid) -> None:
        mock_disc.return_value = [
            SimpleNamespace(product_url="https://farfetch.com/p2", site_name="FARFETCH"),
        ]
        urls = _auto_search_supply_urls(
            "PRADA", "Bag", "SKU1", "raw",
            MagicMock(english_name="Galleria"), ["https://preset.com/x"],
            use_funnel=True,
        )
        self.assertEqual(urls, ["https://farfetch.com/p2"])


class TestRunAutoIntake(unittest.TestCase):

    def test_invalid_url_returns_skip(self) -> None:
        outcome = _run_auto_intake(buyma_url="https://ssense.com/notbuyma")
        self.assertFalse(outcome.success)

    @patch("lib.intake_auto._auto_fetch_buyma_info", return_value=None)
    def test_fetch_failure_returns_skip(self, _fetch) -> None:
        outcome = _run_auto_intake(buyma_url="https://www.buyma.com/item/12345/")
        self.assertFalse(outcome.success)


if __name__ == "__main__":
    unittest.main()
