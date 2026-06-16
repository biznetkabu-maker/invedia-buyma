"""main.py のサブ関数統合テスト。

_load_sheet_data, _compare_candidate_urls, _execute_scraping,
_write_results_to_sheet, _send_notifications, run のテスト。
"""

import asyncio
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from lib.config import Config
from lib.main import (
    ProductResult,
    _compare_candidate_urls,
    _execute_scraping,
    _get_priority_products,
    _load_sheet_data,
    _send_notifications,
    _write_results_to_sheet,
    run,
)
from lib.sheet_manager import ProductRecord


def _make_config(**overrides) -> Config:
    defaults = dict(
        spreadsheet_id="test-id",
        worksheet_name="Sheet1",
        credentials_path="creds.json",
        operation_mode="all",
        priority_tier="all",
        auto_forex=False,
        forex_update_sheet=False,
        scraper_headless=True,
        scraper_timeout_ms=10000,
        scraper_max_retries=1,
        scraper_concurrency=2,
        high_profit_threshold=0.15,
        medium_profit_threshold=0.05,
        customs_rate=0.10,
        shipping_cost_jpy=2000.0,
        buyma_fee_rate=0.077,
        target_profit_rate=0.10,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_record(**overrides) -> ProductRecord:
    defaults = dict(
        商品名="Test Product",
        ブランド="PRADA",
        型番="1BA123",
        仕入れURL="https://www.farfetch.com/shopping/item.aspx",
        現地価格="$500",
        為替="155",
        BUYMA販売価格="100000",
        在庫ステータス="in_stock",
        利益額="20000",
        候補URLs="",
        同一性スコア="",
        価格根拠="",
    )
    defaults.update(overrides)
    return ProductRecord(**defaults)


def _make_result(record=None, **overrides) -> ProductResult:
    r = record or _make_record()
    defaults = dict(
        original=r,
        updated=overrides.pop("updated", r),
        scrape=None,
        breakdown=None,
        error=None,
    )
    defaults.update(overrides)
    return ProductResult(**defaults)


class TestLoadSheetData(unittest.TestCase):
    """_load_sheet_data のテスト。"""

    @patch("lib.main.SheetManager")
    def test_load_returns_manager_and_records(self, MockSM):
        manager = MockSM.return_value
        r1 = _make_record(商品名="Product A")
        r2 = _make_record(商品名="Product B")
        manager.get_all_records.return_value = [r1, r2]
        manager.ensure_header.return_value = None

        config = _make_config()
        mgr, all_recs, target = asyncio.run(_load_sheet_data(config))

        self.assertEqual(len(all_recs), 2)
        self.assertIs(mgr, manager)
        manager.ensure_header.assert_called_once()

    @patch("lib.main.SheetManager")
    def test_empty_sheet_returns_empty(self, MockSM):
        manager = MockSM.return_value
        manager.get_all_records.return_value = []
        manager.ensure_header.return_value = None

        config = _make_config()
        mgr, all_recs, target = asyncio.run(_load_sheet_data(config))

        self.assertEqual(all_recs, [])
        self.assertEqual(target, [])


class TestGetPriorityProducts(unittest.TestCase):
    """_get_priority_products のフィルタテスト。"""

    def test_all_tier_returns_all(self):
        records = [_make_record(商品名="A"), _make_record(商品名="B")]
        result = _get_priority_products(records, "all", 0.15, 0.05)
        self.assertEqual(len(result), 2)

    def test_high_tier_filters(self):
        r1 = _make_record(利益額="50000", BUYMA販売価格="100000")
        r2 = _make_record(利益額="1000", BUYMA販売価格="100000")
        result = _get_priority_products([r1, r2], "high", 0.15, 0.05)
        self.assertEqual(len(result), 1)

    def test_medium_tier_filters(self):
        r1 = _make_record(利益額="10000", BUYMA販売価格="100000")
        r2 = _make_record(利益額="1000", BUYMA販売価格="100000")
        result = _get_priority_products([r1, r2], "medium", 0.15, 0.05)
        self.assertEqual(len(result), 1)


class TestCompareCandidateUrls(unittest.TestCase):
    """_compare_candidate_urls のテスト。"""

    def test_no_candidates_returns_unchanged(self):
        records = [(0, _make_record(候補URLs=""))]
        result = asyncio.run(_compare_candidate_urls(records, _make_config(), None))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1].仕入れURL, records[0][1].仕入れURL)


class TestExecuteScraping(unittest.TestCase):
    """_execute_scraping のテスト。"""

    def test_no_urls_returns_empty_map(self):
        records = [(0, _make_record(仕入れURL=""))]
        config = _make_config()
        result = asyncio.run(_execute_scraping(records, config, None))
        self.assertEqual(result, {})


class TestWriteResultsToSheet(unittest.TestCase):
    """_write_results_to_sheet のテスト。"""

    def test_no_changes_skips_update(self):
        manager = MagicMock()
        r = _make_record()
        result = _make_result(record=r)
        _write_results_to_sheet(manager, [result])
        manager.update_record.assert_not_called()

    def test_changed_record_updates(self):
        manager = MagicMock()
        manager.update_record.return_value = True
        r = _make_record()
        updated = replace(r, 在庫ステータス="out_of_stock")
        result = _make_result(record=r, updated=updated)
        _write_results_to_sheet(manager, [result])
        manager.update_record.assert_called_once_with(r.商品名, updated)

    def test_update_error_logged(self):
        manager = MagicMock()
        manager.update_record.side_effect = RuntimeError("API error")
        r = _make_record()
        updated = replace(r, 在庫ステータス="out_of_stock")
        result = _make_result(record=r, updated=updated)
        _write_results_to_sheet(manager, [result])
        manager.update_record.assert_called_once()


class TestSendNotifications(unittest.TestCase):
    """_send_notifications のテスト。"""

    @patch("lib.main.NotificationManager")
    def test_creates_manager_and_processes(self, MockNM):
        nm = MockNM.return_value
        nm.process.return_value = MagicMock(
            detected_count=1, new_count=1, notified=True, listed_count=0
        )
        results = [_make_result()]
        _send_notifications(results)
        nm.process.assert_called_once_with(results)


class TestRunOrchestrator(unittest.TestCase):
    """run() のオーケストレータテスト。"""

    @patch("lib.main._send_notifications")
    @patch("lib.main._write_results_to_sheet")
    @patch("lib.main._check_style_id_mismatches")
    @patch("lib.main._check_scraper_health")
    @patch("lib.main.process_product")
    @patch("lib.main._execute_scraping")
    @patch("lib.main._compare_candidate_urls")
    @patch("lib.main.ProxyRotator")
    @patch("lib.main._load_sheet_data")
    def test_run_empty_records_returns_empty(
        self, mock_load, mock_proxy, mock_compare, mock_scrape,
        mock_process, mock_health, mock_sid, mock_write, mock_notify,
    ):
        mock_load.return_value = (MagicMock(), [], [])
        config = _make_config()
        result = asyncio.run(run(config))
        self.assertEqual(result, [])
        mock_compare.assert_not_called()

    @patch("lib.logging_config.get_metrics")
    @patch("lib.main._send_notifications")
    @patch("lib.main._write_results_to_sheet")
    @patch("lib.main._check_style_id_mismatches")
    @patch("lib.main._check_scraper_health")
    @patch("lib.main.process_product")
    @patch("lib.main._execute_scraping")
    @patch("lib.main._compare_candidate_urls")
    @patch("lib.main.ProxyRotator")
    @patch("lib.main._load_sheet_data")
    def test_run_with_records_processes_all(
        self, mock_load, mock_proxy, mock_compare, mock_scrape,
        mock_process, mock_health, mock_sid, mock_write, mock_notify, mock_metrics,
    ):
        r = _make_record()
        target = [(0, r)]
        mock_load.return_value = (MagicMock(), [r], target)
        mock_proxy.from_env.return_value = None
        mock_compare.return_value = target
        mock_scrape.return_value = {}
        mock_process.return_value = _make_result(record=r)
        mock_metrics.return_value = MagicMock(sites={})

        config = _make_config()
        result = asyncio.run(run(config))

        self.assertEqual(len(result), 1)
        mock_process.assert_called_once()
        mock_write.assert_called_once()
        mock_notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
