"""forex のユニットテスト（API 呼び出しはモック化）。"""

import json
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import lib.forex as forex
from lib.forex import (
    SUPPORTED_CURRENCIES,
    _fetch_from_fallback,
    _fetch_from_primary,
    _is_cache_valid,
    get_all_rates,
    get_rate,
    get_rates_for_sheet,
    update_sheet_exchange_rates,
)


def _fake_urlopen(payload: dict):
    """urlopen のコンテキストマネージャを模した MagicMock を返す。"""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


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


class TestGetRatesForSheetInverse(unittest.TestCase):
    @patch("lib.forex.get_all_rates")
    def test_inverse_conversion(self, mock_rates):
        # JPY ベース: 1 JPY = 0.0064 USD → 1 USD = 156.25 JPY
        mock_rates.return_value = {"USD": 0.0064, "EUR": 0.005}
        result = get_rates_for_sheet(["USD", "EUR", "JPY"], "JPY")
        self.assertEqual(result["JPY"], 1.0)
        self.assertAlmostEqual(result["USD"], round(1 / 0.0064, 4))
        self.assertAlmostEqual(result["EUR"], round(1 / 0.005, 4))

    @patch("lib.forex.get_all_rates")
    def test_zero_rate_yields_none(self, mock_rates):
        mock_rates.return_value = {"USD": 0.0}
        result = get_rates_for_sheet(["USD", "XXX"], "JPY")
        self.assertIsNone(result["USD"])
        self.assertIsNone(result["XXX"])


class TestFetchHelpers(unittest.TestCase):
    def test_fetch_primary_success(self):
        with patch("lib.forex.urlopen", return_value=_fake_urlopen({"rates": {"JPY": 155.0}})):
            self.assertEqual(_fetch_from_primary("USD"), {"JPY": 155.0})

    def test_fetch_primary_empty_returns_none(self):
        with patch("lib.forex.urlopen", return_value=_fake_urlopen({"rates": {}})):
            self.assertIsNone(_fetch_from_primary("USD"))

    def test_fetch_primary_urlerror_returns_none(self):
        with patch("lib.forex.urlopen", side_effect=URLError("boom")):
            self.assertIsNone(_fetch_from_primary("USD"))

    def test_fetch_fallback_success(self):
        payload = {"result": "success", "rates": {"JPY": 156.0}}
        with patch("lib.forex.urlopen", return_value=_fake_urlopen(payload)):
            self.assertEqual(_fetch_from_fallback("USD"), {"JPY": 156.0})

    def test_fetch_fallback_non_success_returns_none(self):
        payload = {"result": "error", "rates": {"JPY": 156.0}}
        with patch("lib.forex.urlopen", return_value=_fake_urlopen(payload)):
            self.assertIsNone(_fetch_from_fallback("USD"))


class TestGetAllRates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._patch = patch.object(forex, "_CACHE_FILE", Path(self._tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_uses_fresh_cache(self):
        cache = {"rates_JPY": {"rates": {"USD": 0.0064}, "fetched_at": time.time()}}
        Path(self._tmp.name).write_text(json.dumps(cache), encoding="utf-8")
        with patch("lib.forex._fetch_from_primary") as mock_p:
            result = get_all_rates("JPY")
            mock_p.assert_not_called()
        self.assertEqual(result, {"USD": 0.0064})

    def test_fetches_and_saves_when_no_cache(self):
        with patch("lib.forex._fetch_from_primary", return_value={"USD": 0.0064}):
            result = get_all_rates("JPY")
        self.assertEqual(result, {"USD": 0.0064})
        saved = json.loads(Path(self._tmp.name).read_text(encoding="utf-8"))
        self.assertIn("rates_JPY", saved)

    def test_falls_back_to_stale_cache(self):
        cache = {"rates_JPY": {"rates": {"USD": 0.0064}, "fetched_at": time.time() - 99999}}
        Path(self._tmp.name).write_text(json.dumps(cache), encoding="utf-8")
        with patch("lib.forex._fetch_from_primary", return_value=None), \
             patch("lib.forex._fetch_from_fallback", return_value=None):
            result = get_all_rates("JPY")
        self.assertEqual(result, {"USD": 0.0064})

    def test_returns_none_when_no_cache_and_fetch_fails(self):
        with patch("lib.forex._fetch_from_primary", return_value=None), \
             patch("lib.forex._fetch_from_fallback", return_value=None):
            self.assertIsNone(get_all_rates("JPY"))


@dataclass
class _FakeRecord:
    商品名: str
    仕入れURL: str
    為替: str


class _FakeManager:
    def __init__(self, records):
        self._records = records
        self.updated = []

    def get_all_records(self):
        return self._records

    def update_record(self, name, rec):
        self.updated.append((name, rec))


class TestUpdateSheetExchangeRates(unittest.TestCase):
    def test_no_records_returns_empty(self):
        mgr = _FakeManager([])
        self.assertEqual(update_sheet_exchange_rates(mgr), {})

    @patch("lib.forex.get_rates_for_sheet")
    def test_detects_currency_and_updates(self, mock_rates):
        mock_rates.return_value = {"USD": 156.0, "GBP": 196.0, "EUR": 168.0}
        records = [
            _FakeRecord("A", "https://www.ssense.com/x", "100"),       # USD
            _FakeRecord("B", "https://www.net-a-porter.com/y", "100"),  # GBP
            _FakeRecord("C", "https://www.farfetch.com/z", "168.0"),    # EUR 変化なし
            _FakeRecord("D", "https://unknown.example.com/q", "100"),   # スキップ
        ]
        mgr = _FakeManager(records)
        update_sheet_exchange_rates(mgr)
        updated_names = {n for n, _ in mgr.updated}
        self.assertIn("A", updated_names)
        self.assertIn("B", updated_names)
        self.assertNotIn("C", updated_names)  # 為替が一致 → 更新なし
        self.assertNotIn("D", updated_names)  # 通貨判定不可 → スキップ


if __name__ == "__main__":
    unittest.main()
