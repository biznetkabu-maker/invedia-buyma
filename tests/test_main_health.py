"""main.py のヘルスチェック・優先度フィルタ・書き戻し・通知ヘルパーのテスト。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.config import Config
from lib.main import (
    ProductResult,
    _check_scraper_health,
    _check_style_id_mismatches,
    _get_priority_products,
    _send_notifications,
    _write_results_to_sheet,
    process_product,
)
from lib.scraper.models import ScrapedResult
from lib.sheet_manager import ProductRecord


def _make_config(**overrides) -> Config:
    defaults = dict(
        spreadsheet_id="test-id",
        worksheet_name="Sheet1",
        credentials_path="credentials.json",
        buyma_fee_rate=0.11,
        customs_rate=0.10,
        shipping_cost_jpy=2000.0,
        target_profit_rate=0.10,
        scraper_concurrency=3,
        scraper_headless=True,
        scraper_timeout_ms=30000,
        scraper_max_retries=2,
        priority_tier="all",
        high_profit_threshold=0.20,
        medium_profit_threshold=0.10,
        unknown_alert_threshold=3,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_record(**overrides) -> ProductRecord:
    defaults = {
        "商品名": "テストバッグ",
        "ブランド": "GUCCI",
        "型番": "GG-001",
        "仕入れURL": "https://www.ssense.com/en-us/product/1",
        "現地価格": "800",
        "為替": "160",
        "BUYMA販売価格": "180000",
        "在庫ステータス": "出品中",
        "利益額": "",
    }
    defaults.update(overrides)
    return ProductRecord(**defaults)


def _make_scrape(
    price=800.0, currency="USD", stock_status="in_stock",
    success=True, style_id=None, url="https://www.ssense.com/en-us/product/1",
) -> ScrapedResult:
    return ScrapedResult(
        url=url,
        price=price if success else None,
        currency=currency if success else None,
        stock_status=stock_status,
        raw_price=f"${price}" if success else None,
        style_id=style_id,
        scraped_at=datetime.now(timezone.utc),
        success=success,
    )


def _result(record, scrape) -> ProductResult:
    config = _make_config()
    return process_product(record, scrape, config)


class TestGetPriorityProducts(unittest.TestCase):
    def test_all_tier_returns_everything(self):
        recs = [_make_record(), _make_record(商品名="B")]
        out = _get_priority_products(recs, "all", 0.2, 0.1)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], 0)

    def test_high_tier_filters_by_rate(self):
        recs = [
            _make_record(利益額="40000", BUYMA販売価格="100000"),  # 40%
            _make_record(商品名="低", 利益額="5000", BUYMA販売価格="100000"),  # 5%
        ]
        out = _get_priority_products(recs, "high", 0.2, 0.1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1].利益額, "40000")

    def test_medium_tier(self):
        recs = [_make_record(利益額="15000", BUYMA販売価格="100000")]  # 15%
        out = _get_priority_products(recs, "medium", 0.2, 0.1)
        self.assertEqual(len(out), 1)

    def test_invalid_numbers_treated_as_zero(self):
        recs = [_make_record(利益額="abc", BUYMA販売価格="xyz")]
        out = _get_priority_products(recs, "high", 0.2, 0.1)
        self.assertEqual(out, [])


class TestCheckStyleIdMismatches(unittest.TestCase):
    def test_no_alert_when_consistent(self):
        rec = _make_record(型番="ABC123")
        scrape = _make_scrape(style_id="ABC123")
        notifier = MagicMock()
        with patch("lib.line_notifier.LINENotifier", return_value=notifier):
            _check_style_id_mismatches([_result(rec, scrape)])
        notifier.send_text.assert_not_called()

    def test_alert_on_mismatch(self):
        rec = _make_record(型番="ABC123")
        scrape = _make_scrape(style_id="ZZZ999")
        notifier = MagicMock()
        notifier.is_configured = True
        with patch("lib.line_notifier.LINENotifier", return_value=notifier):
            _check_style_id_mismatches([_result(rec, scrape)])
        notifier.send_text.assert_called_once()

    def test_skips_when_no_buyma_style_id(self):
        rec = _make_record(型番="")
        scrape = _make_scrape(style_id="ZZZ")
        with patch("lib.line_notifier.LINENotifier") as Notifier:
            _check_style_id_mismatches([_result(rec, scrape)])
        Notifier.assert_not_called()


class TestCheckScraperHealth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history_file = Path(self.tmp.name) / "hist.json"
        self.patcher = patch("lib.main._UNKNOWN_HISTORY_FILE", self.history_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_alert_after_threshold(self):
        rec = _make_record()
        scrape = _make_scrape(success=False, stock_status="unknown")
        config = _make_config(unknown_alert_threshold=2)
        notifier = MagicMock()
        notifier.is_configured = True
        with patch("lib.line_notifier.LINENotifier", return_value=notifier):
            # 2回連続 unknown でアラート
            _check_scraper_health([_result(rec, scrape)], config)
            _check_scraper_health([_result(rec, scrape)], config)
        notifier.send_text.assert_called_once()

    def test_success_resets_history(self):
        rec = _make_record()
        bad = _make_scrape(success=False, stock_status="unknown")
        good = _make_scrape(success=True, stock_status="in_stock")
        config = _make_config(unknown_alert_threshold=2)
        _check_scraper_health([_result(rec, bad)], config)
        _check_scraper_health([_result(rec, good)], config)
        # リセット後はアラートが出ない
        notifier = MagicMock()
        notifier.is_configured = True
        with patch("lib.line_notifier.LINENotifier", return_value=notifier):
            _check_scraper_health([_result(rec, bad)], config)
        notifier.send_text.assert_not_called()


class TestWriteResultsToSheet(unittest.TestCase):
    def test_updates_changed_records_only(self):
        manager = MagicMock()
        manager.update_record.return_value = True
        rec = _make_record()
        changed = _result(rec, _make_scrape(price=900.0))
        unchanged = ProductResult(
            original=rec, updated=rec, scrape=None, breakdown=None
        )
        _write_results_to_sheet(manager, [changed, unchanged])
        manager.update_record.assert_called_once()

    def test_handles_update_exception(self):
        manager = MagicMock()
        manager.update_record.side_effect = RuntimeError("boom")
        rec = _make_record()
        changed = _result(rec, _make_scrape(price=900.0))
        # 例外は飲み込まれる
        _write_results_to_sheet(manager, [changed])
        manager.update_record.assert_called_once()


class TestSendNotifications(unittest.TestCase):
    def test_delegates_to_notification_manager(self):
        event = MagicMock(
            detected_count=1, new_count=1, notified=True, listed_count=0
        )
        mgr = MagicMock()
        mgr.process.return_value = event
        with patch("lib.main.NotificationManager", return_value=mgr):
            _send_notifications([])
        mgr.process.assert_called_once()


if __name__ == "__main__":
    unittest.main()
