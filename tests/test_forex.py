"""
forex.py のユニットテスト。

- TestGetAllRates    : キャッシュとAPIモックのテスト
- TestGetRate        : 単一通貨レート取得
- TestGetRatesForSheet : 複数通貨一括取得
- TestCacheLogic     : キャッシュ有効期限
"""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os


class TestForexCacheLogic(unittest.TestCase):

    def setUp(self):
        # テスト用の一時キャッシュファイルを使う
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        import lib.forex as fx_module
        self._orig_cache = fx_module._CACHE_FILE
        fx_module._CACHE_FILE = Path(self.tmp.name)

    def tearDown(self):
        import lib.forex as fx_module
        fx_module._CACHE_FILE = self._orig_cache
        os.unlink(self.tmp.name)

    def test_cache_valid_within_ttl(self):
        from lib.forex import _is_cache_valid
        cache = {
            "rates_JPY": {
                "rates": {"USD": 0.0065},
                "fetched_at": time.time() - 1800,  # 30分前
            }
        }
        self.assertTrue(_is_cache_valid(cache, "rates_JPY"))

    def test_cache_invalid_after_ttl(self):
        from lib.forex import _is_cache_valid
        cache = {
            "rates_JPY": {
                "rates": {"USD": 0.0065},
                "fetched_at": time.time() - 7200,  # 2時間前
            }
        }
        self.assertFalse(_is_cache_valid(cache, "rates_JPY"))

    def test_cache_invalid_when_missing(self):
        from lib.forex import _is_cache_valid
        self.assertFalse(_is_cache_valid({}, "rates_JPY"))


class TestGetAllRates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        import lib.forex as fx_module
        self._orig_cache = fx_module._CACHE_FILE
        fx_module._CACHE_FILE = Path(self.tmp.name)

    def tearDown(self):
        import lib.forex as fx_module
        fx_module._CACHE_FILE = self._orig_cache
        os.unlink(self.tmp.name)

    def test_returns_rates_from_api(self):
        from lib.forex import get_all_rates
        mock_rates = {"USD": 0.00644, "EUR": 0.00595, "GBP": 0.00509}

        with patch("lib.forex._fetch_from_primary", return_value=mock_rates):
            result = get_all_rates(base="JPY")

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["USD"], 0.00644)

    def test_falls_back_to_secondary_on_primary_failure(self):
        from lib.forex import get_all_rates
        mock_rates = {"USD": 0.00640}

        with patch("lib.forex._fetch_from_primary", return_value=None), \
             patch("lib.forex._fetch_from_fallback", return_value=mock_rates):
            result = get_all_rates(base="JPY")

        self.assertIsNotNone(result)
        self.assertIn("USD", result)

    def test_uses_cache_when_valid(self):
        import lib.forex as fx_module
        cached_rates = {"USD": 0.0064, "EUR": 0.0060}
        fx_module._CACHE_FILE.write_text(json.dumps({
            "rates_JPY": {
                "rates": cached_rates,
                "fetched_at": time.time() - 100,  # 100秒前 (TTL内)
            }
        }))

        with patch("lib.forex._fetch_from_primary") as mock_api:
            from lib.forex import get_all_rates
            result = get_all_rates(base="JPY")
            mock_api.assert_not_called()  # API は呼ばれない

        self.assertEqual(result["USD"], 0.0064)

    def test_returns_none_when_both_apis_fail_and_no_cache(self):
        from lib.forex import get_all_rates
        with patch("lib.forex._fetch_from_primary", return_value=None), \
             patch("lib.forex._fetch_from_fallback", return_value=None):
            result = get_all_rates(base="JPY")
        self.assertIsNone(result)


class TestGetRate(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        import lib.forex as fx_module
        self._orig_cache = fx_module._CACHE_FILE
        fx_module._CACHE_FILE = Path(self.tmp.name)

    def tearDown(self):
        import lib.forex as fx_module
        fx_module._CACHE_FILE = self._orig_cache
        os.unlink(self.tmp.name)

    def test_same_currency_returns_one(self):
        from lib.forex import get_rate
        self.assertEqual(get_rate("JPY", "JPY"), 1.0)

    def test_returns_correct_jpy_rate(self):
        from lib.forex import get_rate
        # USD ベースのレートを返す mock
        mock_rates = {"JPY": 155.43, "EUR": 0.923}
        with patch("lib.forex._fetch_from_primary", return_value=mock_rates), \
             patch("lib.forex._fetch_from_fallback", return_value=None):
            result = get_rate("USD", "JPY")
        self.assertAlmostEqual(result, 155.43)

    def test_returns_none_on_failure(self):
        from lib.forex import get_rate
        with patch("lib.forex.get_all_rates", return_value=None):
            result = get_rate("USD", "JPY")
        self.assertIsNone(result)


class TestGetRatesForSheet(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        import lib.forex as fx_module
        self._orig_cache = fx_module._CACHE_FILE
        fx_module._CACHE_FILE = Path(self.tmp.name)

    def tearDown(self):
        import lib.forex as fx_module
        fx_module._CACHE_FILE = self._orig_cache
        os.unlink(self.tmp.name)

    def test_returns_dict_for_all_currencies(self):
        from lib.forex import get_rates_for_sheet
        # JPY ベースで USD=0.00644 → 1/0.00644 ≈ 155.3
        mock_rates = {"USD": 0.00644, "EUR": 0.00594, "GBP": 0.00509}
        with patch("lib.forex._fetch_from_primary", return_value=mock_rates):
            result = get_rates_for_sheet(["USD", "EUR", "GBP"])

        self.assertIn("USD", result)
        self.assertIn("EUR", result)
        self.assertIn("GBP", result)
        # USD レートが 150〜165 の範囲であることを確認
        self.assertIsNotNone(result["USD"])
        self.assertGreater(result["USD"], 100)

    def test_same_currency_returns_one(self):
        from lib.forex import get_rates_for_sheet
        mock_rates = {"USD": 0.00644}
        with patch("lib.forex._fetch_from_primary", return_value=mock_rates):
            result = get_rates_for_sheet(["JPY", "USD"], to_currency="JPY")
        self.assertEqual(result["JPY"], 1.0)


class TestConfigOperationMode(unittest.TestCase):

    def test_operation_mode_defaults_to_monitor(self):
        from lib.config import Config
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            __import__("os").environ,
            {"SPREADSHEET_ID": "test", "OPERATION_MODE": "monitor"},
            clear=False,
        ):
            config = Config.from_env()
        self.assertEqual(config.operation_mode, "monitor")

    def test_auto_forex_defaults_to_true(self):
        from lib.config import Config
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            __import__("os").environ,
            {"SPREADSHEET_ID": "test"},
            clear=False,
        ):
            config = Config.from_env()
        self.assertTrue(config.auto_forex)

    def test_unknown_alert_threshold_default(self):
        from lib.config import Config
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            __import__("os").environ,
            {"SPREADSHEET_ID": "test"},
            clear=False,
        ):
            config = Config.from_env()
        self.assertEqual(config.unknown_alert_threshold, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
