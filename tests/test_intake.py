"""intake.py のヘルパー関数テスト（価格係数・URL収集・為替・候補選択・レコード構築）。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.intake import (
    _build_record,
    _collect_source_urls,
    _evaluate,
    _get_exchange_rate,
    _price_factor,
    _run_demand_check,
    _select_fallback_candidate,
)
from lib.multi_source import BestSourceResult, SourceCandidate


def _candidate(
    url: str = "https://shop.example.com/item",
    price: float = 100.0,
    currency: str = "EUR",
    stock_status: str = "out_of_stock",
    profit: float | None = 5000.0,
    style_id: str | None = None,
) -> SourceCandidate:
    return SourceCandidate(
        url=url,
        price=price,
        currency=currency,
        stock_status=stock_status,
        jpy_cost=None,
        profit=profit,
        profit_rate=None,
        breakdown=None,
        style_id=style_id,
    )


class TestPriceFactor(unittest.TestCase):
    def test_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("BUYMA_PRICE_FACTOR", None)
            self.assertEqual(_price_factor(), 0.97)

    def test_custom(self) -> None:
        with patch.dict("os.environ", {"BUYMA_PRICE_FACTOR": "0.9"}):
            self.assertEqual(_price_factor(), 0.9)

    def test_invalid_falls_back(self) -> None:
        with patch.dict("os.environ", {"BUYMA_PRICE_FACTOR": "abc"}):
            self.assertEqual(_price_factor(), 0.97)


class TestCollectSourceUrls(unittest.TestCase):
    @patch("lib.intake.build_search_urls")
    @patch("builtins.input", return_value="")
    def test_empty_returns_empty(self, _inp, mock_urls) -> None:
        mock_urls.return_value.display.return_value = ""
        self.assertEqual(_collect_source_urls("PRADA", "wallet"), [])

    @patch("lib.intake.build_search_urls")
    @patch("builtins.input", return_value="https://a.com/1, https://b.com/2")
    def test_parses_valid_urls(self, _inp, mock_urls) -> None:
        mock_urls.return_value.display.return_value = ""
        self.assertEqual(
            _collect_source_urls("PRADA", "wallet"),
            ["https://a.com/1", "https://b.com/2"],
        )

    @patch("lib.intake.build_search_urls")
    @patch("builtins.input", return_value="notaurl, https://b.com/2")
    def test_filters_invalid(self, _inp, mock_urls) -> None:
        mock_urls.return_value.display.return_value = ""
        self.assertEqual(
            _collect_source_urls("PRADA", "wallet"), ["https://b.com/2"]
        )


class TestGetExchangeRate(unittest.TestCase):
    @patch("lib.intake.get_rate", return_value=160.0)
    @patch("builtins.input", return_value="")
    def test_uses_api_rate_on_empty_input(self, _inp, _rate) -> None:
        self.assertEqual(_get_exchange_rate("EUR"), 160.0)

    @patch("lib.intake.get_rate", return_value=160.0)
    @patch("builtins.input", return_value="170")
    def test_override_with_manual(self, _inp, _rate) -> None:
        self.assertEqual(_get_exchange_rate("EUR"), 170.0)

    @patch("lib.intake.get_rate", side_effect=RuntimeError("boom"))
    @patch("lib.intake._ask_float", return_value=155.0)
    def test_falls_back_on_error(self, _ask, _rate) -> None:
        self.assertEqual(_get_exchange_rate("EUR"), 155.0)


class TestRunDemandCheck(unittest.TestCase):
    @patch("lib.intake.BUYMADemandScraper")
    def test_returns_signal(self, mock_scraper) -> None:
        sig = mock_scraper.return_value.get_demand.return_value
        result = _run_demand_check("PRADA", "wallet")
        self.assertIs(result, sig)

    @patch("lib.intake.BUYMADemandScraper", side_effect=RuntimeError("x"))
    def test_returns_zero_signal_on_error(self, _m) -> None:
        result = _run_demand_check("PRADA", "wallet")
        self.assertEqual(result.favorites_count, 0)
        self.assertIsNone(result.min_price)


class TestSelectFallbackCandidate(unittest.TestCase):
    def test_skips_when_style_mismatch_reason(self) -> None:
        result = BestSourceResult(
            best=None, all_candidates=[_candidate()],
            reason="型番「ABC」一致なし", match_score=None,
        )
        url, price, _, sid, status = _select_fallback_candidate(
            result, "ABC", 50000.0, 160.0
        )
        self.assertEqual(url, "")
        self.assertEqual(price, 0.0)
        self.assertEqual(status, "unknown")

    def test_skips_negative_profit(self) -> None:
        result = BestSourceResult(
            best=None,
            all_candidates=[_candidate(profit=-100.0)],
            reason="", match_score=None,
        )
        url, price, _, _, _ = _select_fallback_candidate(
            result, "", 50000.0, 160.0
        )
        self.assertEqual(url, "")

    @patch("lib.scraper.price_sanity.is_plausible_supply_price", return_value=True)
    def test_selects_plausible_candidate(self, _p) -> None:
        cand = _candidate()
        result = BestSourceResult(
            best=None, all_candidates=[cand], reason="", match_score=None,
        )
        url, price, _, _, status = _select_fallback_candidate(
            result, "", 50000.0, 160.0
        )
        self.assertEqual(url, cand.url)
        self.assertEqual(price, 100.0)


class TestBuildRecord(unittest.TestCase):
    def test_builds_with_evaluate_score(self) -> None:
        score = _evaluate(
            "PRADA", "wallet", "財布", 2024,
            "https://shop.example.com/x", 100.0, "EUR", 160.0, 50000.0,
        )
        rec = _build_record(
            "PRADA", "wallet",
            "https://shop.example.com/x", 100.0,
            160.0, 50000.0,
            ["https://shop.example.com/x"],
            score,
            buyma_style_id="STYLE1",
        )
        self.assertEqual(rec.商品名, "PRADA wallet")
        self.assertEqual(rec.ブランド, "PRADA")
        self.assertEqual(rec.型番, "STYLE1")
        self.assertEqual(rec.在庫ステータス, "出品前")
        self.assertEqual(rec.BUYMA販売価格, "50000")


if __name__ == "__main__":
    unittest.main()
