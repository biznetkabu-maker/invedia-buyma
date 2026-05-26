"""forex のユニットテスト（API 呼び出しはモック化）。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.forex import (
    SUPPORTED_CURRENCIES,
    _is_cache_valid,
    get_all_rates,
    get_rate,
    get_rates_for_sheet,
)


class TestGetRate(unittest.TestCase):
    def test_same_currency(self):
        self.assertEqual(get_rate("JPY", "JPY"), 1.0)

    @patch("lib.forex.get_all_rates", return_value={"JPY": 155.0, "EUR": 0.93})
    def test_returns_rate(self, mock_rates):
        rate = get_rate("USD", "JPY")
        self.assertEqual(rate, 155.0)

    @patch("lib.forex.get_all_rates", return_value=None)
    def test_returns_none_on_failure(self, mock_rates):
        self.assertIsNone(get_rate("USD", "JPY"))


class TestGetRatesForSheet(unittest.TestCase):
    @patch("lib.forex.get_all_rates")
    def test_batch_rates(self, mock_rates):
        mock_rates.return_value = {"USD": 0.0064, "EUR": 0.0059, "GBP": 0.0051}
        result = get_rates_for_sheet(["USD", "EUR"], "JPY")
        self.assertIn("USD", result)
        self.assertIn("EUR", result)
        self.assertIsNotNone(result["USD"])
        self.assertIsNotNone(result["EUR"])

    @patch("lib.forex.get_all_rates", return_value=None)
    @patch("lib.forex.get_rate", return_value=155.0)
    def test_fallback_individual(self, mock_single, mock_batch):
        result = get_rates_for_sheet(["USD"], "JPY")
        self.assertEqual(result["USD"], 155.0)


class TestCacheValid(unittest.TestCase):
    def test_missing_key(self):
        self.assertFalse(_is_cache_valid({}, "rates_JPY"))

    def test_fresh(self):
        import time
        cache = {"rates_JPY": {"rates": {}, "fetched_at": time.time()}}
        self.assertTrue(_is_cache_valid(cache, "rates_JPY"))

    def test_expired(self):
        import time
        cache = {"rates_JPY": {"rates": {}, "fetched_at": time.time() - 7200}}
        self.assertFalse(_is_cache_valid(cache, "rates_JPY"))


class TestSupportedCurrencies(unittest.TestCase):
    def test_includes_jpy(self):
        self.assertIn("JPY", SUPPORTED_CURRENCIES)

    def test_includes_usd(self):
        self.assertIn("USD", SUPPORTED_CURRENCIES)


if __name__ == "__main__":
    unittest.main()
