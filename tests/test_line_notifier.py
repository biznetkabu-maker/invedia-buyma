"""LINE 通知モジュールのユニットテスト。"""

import unittest
from unittest.mock import MagicMock, patch

from lib.line_notifier import (
    LINEMessagingClient,
    LINENotifier,
    NotificationResult,
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


if __name__ == "__main__":
    unittest.main()
