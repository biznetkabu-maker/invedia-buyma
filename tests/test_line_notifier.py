"""LINE 通知モジュールのユニットテスト。"""

import unittest
from unittest.mock import MagicMock, patch

import requests

from lib.line_notifier import (
    LINEMessagingClient,
    LINENotifier,
    LINENotifyClient,
    TreasureAlert,
)


def _make_alert(**kwargs) -> TreasureAlert:
    defaults = dict(
        product_name="CELINE トリオ",
        brand="CELINE",
        buyma_price=210_000,
        profit=35_000,
        profit_rate=0.167,
        source_url="https://www.ssense.com/celine/trio",
        stock_status="in_stock",
    )
    defaults.update(kwargs)
    return TreasureAlert(**defaults)


class TestTreasureAlert(unittest.TestCase):
    def test_profit_jpy_str(self):
        a = _make_alert(profit=35000)
        self.assertEqual(a.profit_jpy_str, "¥35,000")

    def test_profit_rate_str(self):
        a = _make_alert(profit_rate=0.167)
        self.assertEqual(a.profit_rate_str, "16.7%")


class TestLINEMessagingClient(unittest.TestCase):
    def test_not_configured_returns_false(self):
        client = LINEMessagingClient(channel_token="", user_id="")
        self.assertFalse(client.is_configured)

    def test_configured_with_both(self):
        client = LINEMessagingClient(channel_token="tok", user_id="uid")
        self.assertTrue(client.is_configured)

    def test_send_text_unconfigured(self):
        client = LINEMessagingClient(channel_token="", user_id="")
        result = client.send_text("hello")
        self.assertFalse(result.success)

    @patch("lib.line_notifier.requests.post")
    def test_send_text_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        client = LINEMessagingClient(channel_token="tok", user_id="uid")
        result = client.send_text("hello")
        self.assertTrue(result.success)
        mock_post.assert_called_once()

    @patch("lib.line_notifier.requests.post")
    def test_send_treasure_card_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        client = LINEMessagingClient(channel_token="tok", user_id="uid")
        result = client.send_treasure_card([_make_alert()])
        self.assertTrue(result.success)


class TestLINENotifier(unittest.TestCase):
    def test_not_configured(self):
        notifier = LINENotifier(
            notify_token="", messaging_token="", messaging_user_id=""
        )
        self.assertFalse(notifier.is_configured)

    def test_empty_alerts(self):
        notifier = LINENotifier(
            notify_token="", messaging_token="", messaging_user_id=""
        )
        result = notifier.notify_treasures([])
        self.assertTrue(result.success)

    @patch("lib.line_notifier.requests.post")
    def test_messaging_preferred_over_notify(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        notifier = LINENotifier(
            messaging_token="tok", messaging_user_id="uid", notify_token=""
        )
        result = notifier.notify_treasure(_make_alert())
        self.assertTrue(result.success)
        self.assertIn("Messaging", result.method)


class TestLINENotifyClient(unittest.TestCase):
    def test_send_unconfigured(self):
        client = LINENotifyClient(token="")
        result = client.send("hi")
        self.assertFalse(result.success)

    @patch("lib.line_notifier.requests.post")
    def test_send_success_with_image_and_sticker(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        client = LINENotifyClient(token="tok")
        result = client.send(
            "hi", image_url="http://img", sticker_package_id=1, sticker_id=2
        )
        self.assertTrue(result.success)
        sent = mock_post.call_args.kwargs["data"]
        self.assertEqual(sent["imageFullsize"], "http://img")
        self.assertEqual(sent["stickerId"], 2)

    @patch("lib.line_notifier.requests.post")
    def test_send_http_error(self, mock_post):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "unauthorized"
        resp.raise_for_status.side_effect = requests.HTTPError("401")
        mock_post.return_value = resp
        client = LINENotifyClient(token="tok")
        result = client.send("hi")
        self.assertFalse(result.success)
        self.assertIn("401", result.error)


class TestNotifyTreasuresUnconfigured(unittest.TestCase):
    def test_returns_failure(self):
        notifier = LINENotifier(
            notify_token="", messaging_token="", messaging_user_id=""
        )
        result = notifier.notify_treasures([_make_alert()])
        self.assertFalse(result.success)
        self.assertIn("未設定", result.error)


class TestNotifyDailySummary(unittest.TestCase):
    def test_unconfigured(self):
        notifier = LINENotifier(
            notify_token="", messaging_token="", messaging_user_id=""
        )
        result = notifier.notify_daily_summary([_make_alert()])
        self.assertFalse(result.success)

    @patch("lib.line_notifier.requests.post")
    def test_messaging_path(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        notifier = LINENotifier(
            messaging_token="tok", messaging_user_id="uid", notify_token=""
        )
        result = notifier.notify_daily_summary([_make_alert(), _make_alert(profit=5000)])
        self.assertTrue(result.success)


class TestFilterTreasures(unittest.TestCase):
    def test_filters_below_threshold_and_out_of_stock(self):
        notifier = LINENotifier(notify_token="x")
        notifier._threshold = 30000
        records = [
            {"product_name": "A", "profit": 50000, "stock_status": "in_stock"},
            {"product_name": "B", "profit": 10000, "stock_status": "in_stock"},
            {"product_name": "C", "profit": 90000, "stock_status": "out_of_stock"},
        ]
        alerts = notifier.filter_treasures(records)
        self.assertEqual([a.product_name for a in alerts], ["A"])


class TestBuildText(unittest.TestCase):
    def test_build_notify_text(self):
        text = LINENotifier._build_notify_text([_make_alert(grade="S")])
        self.assertIn("お宝発見", text)
        self.assertIn("[S]", text)

    def test_build_summary_text(self):
        alerts = [_make_alert(profit=35000)]
        text = LINENotifier._build_summary_text(alerts, alerts, 35000, "2026-01-01")
        self.assertIn("サマリー", text)
        self.assertIn("35,000", text)


if __name__ == "__main__":
    unittest.main()
