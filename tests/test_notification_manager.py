"""notification_manager のユニットテスト。"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lib.notification_manager import (
    NotificationEvent,
    NotificationManager,
    _cache_key,
)
from lib.line_notifier import TreasureAlert


class TestNotificationEvent(unittest.TestCase):
    def test_defaults(self):
        e = NotificationEvent(detected_count=5, new_count=3, notified=True)
        self.assertEqual(e.detected_count, 5)
        self.assertEqual(e.new_count, 3)
        self.assertTrue(e.notified)
        self.assertEqual(e.listed_count, 0)
        self.assertEqual(e.images_processed, 0)
        self.assertEqual(e.errors, [])
        self.assertIsInstance(e.executed_at, datetime)


class TestCacheKey(unittest.TestCase):
    def test_format(self):
        alert = TreasureAlert(
            product_name="テストバッグ",
            brand="PRADA",
            buyma_price=80000,
            profit=20000,
            profit_rate=0.25,
            source_url="https://example.com/bag",
            stock_status="in_stock",
        )
        key = _cache_key(alert)
        self.assertEqual(key, "PRADA::テストバッグ::https://example.com/bag")


def _make_result(name, brand, price, profit, stock="in_stock"):
    """テスト用 ProductResult 風オブジェクトを生成。"""
    breakdown = SimpleNamespace(profit=profit, profit_rate=profit / price if price else 0)
    updated = SimpleNamespace(
        商品名=name, ブランド=brand, BUYMA販売価格=str(price), 仕入れURL="https://example.com"
    )
    scrape = SimpleNamespace(stock_status=stock)
    return SimpleNamespace(updated=updated, breakdown=breakdown, scrape=scrape)


class TestNotificationManagerExtract(unittest.TestCase):
    def test_extract_above_threshold(self):
        mgr = NotificationManager(profit_threshold=10000)
        results = [
            _make_result("A", "PRADA", 80000, 20000),
            _make_result("B", "GUCCI", 60000, 5000),  # below threshold
        ]
        alerts = mgr._extract_treasures(results)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].product_name, "A")

    def test_exclude_out_of_stock(self):
        mgr = NotificationManager(profit_threshold=10000)
        results = [_make_result("A", "PRADA", 80000, 20000, stock="out_of_stock")]
        alerts = mgr._extract_treasures(results)
        self.assertEqual(len(alerts), 0)

    def test_sorted_by_profit_desc(self):
        mgr = NotificationManager(profit_threshold=10000)
        results = [
            _make_result("Lo", "A", 80000, 15000),
            _make_result("Hi", "B", 80000, 30000),
        ]
        alerts = mgr._extract_treasures(results)
        self.assertEqual(alerts[0].product_name, "Hi")
        self.assertEqual(alerts[1].product_name, "Lo")

    def test_none_breakdown_skipped(self):
        mgr = NotificationManager(profit_threshold=10000)
        r = SimpleNamespace(
            updated=SimpleNamespace(商品名="X", ブランド="Y", BUYMA販売価格="0", 仕入れURL=""),
            breakdown=None,
            scrape=None,
        )
        alerts = mgr._extract_treasures([r])
        self.assertEqual(len(alerts), 0)


class TestNotificationManagerProcess(unittest.TestCase):
    @patch("lib.notification_manager._save_notified_cache")
    @patch("lib.notification_manager._load_notified_cache", return_value={})
    def test_process_new_treasures(self, mock_load, mock_save):
        mgr = NotificationManager(profit_threshold=10000)
        mgr._notifier = MagicMock()
        mgr._notifier.is_configured = True
        mgr._notifier.notify_treasures.return_value = SimpleNamespace(success=True)

        results = [_make_result("A", "PRADA", 80000, 20000)]
        event = mgr.process(results)

        self.assertEqual(event.detected_count, 1)
        self.assertEqual(event.new_count, 1)
        self.assertTrue(event.notified)
        mock_save.assert_called_once()

    @patch("lib.notification_manager._save_notified_cache")
    @patch("lib.notification_manager._load_notified_cache")
    def test_process_already_notified(self, mock_load, mock_save):
        mock_load.return_value = {"PRADA::A::https://example.com": "2026-01-01T00:00:00"}
        mgr = NotificationManager(profit_threshold=10000)
        results = [_make_result("A", "PRADA", 80000, 20000)]
        event = mgr.process(results)
        self.assertEqual(event.new_count, 0)
        self.assertFalse(event.notified)

    def test_process_no_treasures(self):
        mgr = NotificationManager(profit_threshold=100000)
        results = [_make_result("A", "PRADA", 80000, 5000)]
        event = mgr.process(results)
        self.assertEqual(event.detected_count, 0)
        self.assertFalse(event.notified)


if __name__ == "__main__":
    unittest.main()
