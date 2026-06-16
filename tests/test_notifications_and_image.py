"""
LINE通知・画像処理・BUYMA自動出品モジュールのユニットテスト。

- TestTreasureAlert        : TreasureAlert データクラス
- TestLINENotifyClient     : LINE Notify 送信（モック）
- TestLINEMessagingClient  : LINE Messaging API（モック）
- TestLINENotifier         : LINENotifier ファサード
- TestNotificationManager  : NotificationManager のお宝抽出・重複排除
- TestImageProcessor       : BUYMAImageProcessor（rembg なしで実行可能な部分）
- TestBUYMAAutomator       : BUYMAAutomator（Playwright モック）
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.line_notifier import (
    LINEMessagingClient,
    LINENotifier,
    LINENotifyClient,
    TreasureAlert,
)
from lib.notification_manager import NotificationManager

# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------

def _make_alert(
    profit=35000.0,
    profit_rate=0.18,
    brand="GUCCI",
    product_name="テストバッグ",
    stock="in_stock",
    grade="A",
) -> TreasureAlert:
    return TreasureAlert(
        product_name=product_name,
        brand=brand,
        buyma_price=195_000.0,
        profit=profit,
        profit_rate=profit_rate,
        source_url="https://www.ssense.com/en-us/product/1",
        stock_status=stock,
        grade=grade,
    )


def _make_product_result(
    product_name="テストバッグ",
    brand="GUCCI",
    profit=35000.0,
    profit_rate=0.18,
    stock="in_stock",
):
    from lib.profit_calculator import ProfitBreakdown
    from lib.scraper.models import ScrapedResult

    breakdown = ProfitBreakdown(
        local_price=800, exchange_rate=155, buyma_price=195_000,
        jpy_cost=124000, customs_cost=12400, shipping_cost=2000,
        buyma_fee=15015, total_cost=153415, profit=profit, profit_rate=profit_rate,
    )
    scrape = ScrapedResult(
        url="https://www.ssense.com/en-us/product/1",
        price=800.0, currency="USD",
        stock_status=stock, raw_price="$800",
        scraped_at=datetime.now(timezone.utc), success=True,
    )

    from lib.main import ProductResult
    from lib.sheet_manager import ProductRecord
    record = ProductRecord(
        商品名=product_name, ブランド=brand,
        型番="GG-001",
        仕入れURL="https://www.ssense.com/en-us/product/1",
        現地価格="800", 為替="155",
        BUYMA販売価格="195000", 在庫ステータス="出品中", 利益額=str(int(profit)),
    )
    return ProductResult(
        original=record, updated=record,
        scrape=scrape, breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# TreasureAlert
# ---------------------------------------------------------------------------

class TestTreasureAlert(unittest.TestCase):

    def test_profit_jpy_str(self):
        a = _make_alert(profit=35000)
        self.assertEqual(a.profit_jpy_str, "¥35,000")

    def test_profit_rate_str(self):
        a = _make_alert(profit_rate=0.18)
        self.assertEqual(a.profit_rate_str, "18.0%")

    def test_grade_is_optional(self):
        a = _make_alert(grade=None)
        self.assertIsNone(a.grade)


# ---------------------------------------------------------------------------
# LINENotifyClient
# ---------------------------------------------------------------------------

class TestLINENotifyClient(unittest.TestCase):

    def test_not_configured_without_token(self):
        with patch.dict(os.environ, {"LINE_NOTIFY_TOKEN": ""}):
            client = LINENotifyClient()
        self.assertFalse(client.is_configured)

    def test_configured_with_token(self):
        client = LINENotifyClient(token="test_token")
        self.assertTrue(client.is_configured)

    def test_send_success(self):
        client = LINENotifyClient(token="test_token")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = client.send("テストメッセージ")

        self.assertTrue(result.success)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]["headers"]["Authorization"], "Bearer test_token")
        self.assertEqual(call_args[1]["data"]["message"], "テストメッセージ")

    def test_send_truncates_long_message(self):
        client = LINENotifyClient(token="test_token")
        long_msg = "A" * 2000
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            client.send(long_msg)

        sent_msg = mock_post.call_args[1]["data"]["message"]
        self.assertLessEqual(len(sent_msg), 1000)

    def test_send_fails_without_token(self):
        with patch.dict(os.environ, {"LINE_NOTIFY_TOKEN": ""}):
            client = LINENotifyClient()
        result = client.send("message")
        self.assertFalse(result.success)
        self.assertIn("LINE_NOTIFY_TOKEN", result.error)

    def test_send_http_error_returns_failure(self):
        client = LINENotifyClient(token="bad_token")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

        with patch("requests.post", return_value=mock_resp):
            result = client.send("message")

        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# LINEMessagingClient
# ---------------------------------------------------------------------------

class TestLINEMessagingClient(unittest.TestCase):

    def test_not_configured_without_credentials(self):
        with patch.dict(os.environ, {
            "LINE_CHANNEL_ACCESS_TOKEN": "",
            "LINE_USER_ID": "",
        }):
            client = LINEMessagingClient()
        self.assertFalse(client.is_configured)

    def test_configured_with_credentials(self):
        client = LINEMessagingClient(channel_token="token", user_id="user123")
        self.assertTrue(client.is_configured)

    def test_send_treasure_card_builds_flex(self):
        client = LINEMessagingClient(channel_token="token", user_id="user123")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = client.send_treasure_card([_make_alert()])

        self.assertTrue(result.success)
        payload = json.loads(mock_post.call_args[1]["data"])
        self.assertEqual(payload["to"], "user123")
        self.assertEqual(payload["messages"][0]["type"], "flex")

    def test_flex_message_contains_brand_name(self):
        client = LINEMessagingClient(channel_token="t", user_id="u")
        alert = _make_alert(brand="HERMÈS", product_name="バーキン 30")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            client.send_treasure_card([alert])

        payload_str = mock_post.call_args[1]["data"]
        self.assertIn("HERMÈS", payload_str)
        self.assertIn("バーキン 30", payload_str)

    def test_send_max_5_messages_per_call(self):
        client = LINEMessagingClient(channel_token="t", user_id="u")
        alerts = [_make_alert(product_name=f"商品{i}") for i in range(8)]
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            client.send_treasure_card(alerts)

        payload = json.loads(mock_post.call_args[1]["data"])
        self.assertLessEqual(len(payload["messages"]), 5)


# ---------------------------------------------------------------------------
# LINENotifier ファサード
# ---------------------------------------------------------------------------

class TestLINENotifier(unittest.TestCase):

    def test_filter_treasures_by_threshold(self):
        notifier = LINENotifier(profit_threshold=30_000)
        records = [
            {"product_name": "A", "brand": "X", "buyma_price": 100000,
             "profit": 35000, "profit_rate": 0.35, "source_url": "x",
             "stock_status": "in_stock"},
            {"product_name": "B", "brand": "Y", "buyma_price": 100000,
             "profit": 15000, "profit_rate": 0.15, "source_url": "y",
             "stock_status": "in_stock"},
        ]
        alerts = notifier.filter_treasures(records)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].product_name, "A")

    def test_filter_treasures_excludes_out_of_stock(self):
        notifier = LINENotifier(profit_threshold=30_000)
        records = [
            {"product_name": "A", "brand": "X", "buyma_price": 100000,
             "profit": 50000, "profit_rate": 0.5, "source_url": "x",
             "stock_status": "out_of_stock"},
        ]
        alerts = notifier.filter_treasures(records)
        self.assertEqual(len(alerts), 0)

    def test_filter_treasures_sorts_by_profit_desc(self):
        notifier = LINENotifier(profit_threshold=0)
        records = [
            {"product_name": "A", "brand": "X", "buyma_price": 100000,
             "profit": 10000, "profit_rate": 0.1, "source_url": "a",
             "stock_status": "in_stock"},
            {"product_name": "B", "brand": "Y", "buyma_price": 100000,
             "profit": 50000, "profit_rate": 0.5, "source_url": "b",
             "stock_status": "in_stock"},
        ]
        alerts = notifier.filter_treasures(records)
        self.assertEqual(alerts[0].product_name, "B")

    def test_notify_treasure_uses_messaging_api_first(self):
        notifier = LINENotifier(
            messaging_token="msg_token", messaging_user_id="user_id"
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = notifier.notify_treasure(_make_alert())

        self.assertEqual(result.method, "LINE Messaging API")

    def test_notify_fallback_to_line_notify(self):
        notifier = LINENotifier(notify_token="notify_token")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = notifier.notify_treasure(_make_alert())

        self.assertEqual(result.method, "LINE Notify")

    def test_notify_empty_alerts(self):
        notifier = LINENotifier()
        result = notifier.notify_treasures([])
        self.assertTrue(result.success)


# ---------------------------------------------------------------------------
# NotificationManager
# ---------------------------------------------------------------------------

class TestNotificationManager(unittest.TestCase):

    def test_extract_treasures_from_results(self):
        manager = NotificationManager(profit_threshold=30_000)
        results = [
            _make_product_result(profit=35_000),
            _make_product_result(product_name="安商品", profit=5_000),
        ]
        treasures = manager._extract_treasures(results)
        self.assertEqual(len(treasures), 1)
        self.assertEqual(treasures[0].product_name, "テストバッグ")

    def test_extract_treasures_excludes_out_of_stock(self):
        manager = NotificationManager(profit_threshold=30_000)
        results = [
            _make_product_result(profit=50_000, stock="out_of_stock"),
        ]
        treasures = manager._extract_treasures(results)
        self.assertEqual(len(treasures), 0)

    def test_process_skips_duplicate_notifications(self):
        """同じ商品を2回 process() しても2回目は通知しない。"""
        manager = NotificationManager(profit_threshold=30_000)
        results = [_make_product_result(profit=35_000)]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "cache.json"
            with patch("lib.notification_manager._NOTIFIED_CACHE_FILE", cache_file), \
                    patch("requests.post") as mock_post:
                    mock_post.return_value.raise_for_status.return_value = None
                    manager._notifier = MagicMock()
                    manager._notifier.is_configured = False

                    # 1回目: 新規 → event.new_count = 1
                    event1 = manager.process(results)
                    # 2回目: 既通知 → event.new_count = 0
                    event2 = manager.process(results)

        self.assertEqual(event1.new_count, 1)
        self.assertEqual(event2.new_count, 0)

    def test_process_no_treasures_returns_zero_counts(self):
        manager = NotificationManager(profit_threshold=30_000)
        results = [_make_product_result(profit=5_000)]
        event = manager.process(results)
        self.assertEqual(event.detected_count, 0)
        self.assertFalse(event.notified)


# ---------------------------------------------------------------------------
# BUYMAImageProcessor（rembg なし部分のみテスト）
# ---------------------------------------------------------------------------

class TestImageProcessorBasics(unittest.TestCase):

    def test_url_to_filename(self):
        from lib.image_processor import _url_to_filename
        fn = _url_to_filename("https://www.ssense.com/en-us/women/product/gucci/gg-bag/12345")
        self.assertIsInstance(fn, str)
        self.assertGreater(len(fn), 0)
        self.assertNotIn("/", fn)

    def test_processor_not_configured_raises_on_rembg_missing(self):
        from lib.image_processor import RembgProcessor
        processor = RembgProcessor()
        with patch.dict("sys.modules", {"rembg": None}), self.assertRaises(ImportError):
            processor.remove_background(MagicMock())

    def test_auto_select_returns_rembg_by_default(self):
        from lib.image_processor import RembgProcessor, _auto_select_processor
        with patch.dict(os.environ, {"BG_REMOVAL_BACKEND": "rembg"}):
            p = _auto_select_processor()
        self.assertIsInstance(p, RembgProcessor)

    def test_auto_select_returns_removebg_when_configured(self):
        from lib.image_processor import RemoveBgAPIProcessor, _auto_select_processor
        with patch.dict(os.environ, {
            "BG_REMOVAL_BACKEND": "removebg",
            "REMOVE_BG_API_KEY": "test_key",
        }):
            p = _auto_select_processor()
        self.assertIsInstance(p, RemoveBgAPIProcessor)

    def test_auto_select_falls_back_without_api_key(self):
        from lib.image_processor import RembgProcessor, _auto_select_processor
        with patch.dict(os.environ, {
            "BG_REMOVAL_BACKEND": "removebg",
            "REMOVE_BG_API_KEY": "",
        }):
            p = _auto_select_processor()
        self.assertIsInstance(p, RembgProcessor)

    def test_nanobanana2_processor_reads_env(self):
        from lib.image_processor import NanoBanana2Processor
        with patch.dict(os.environ, {"NANO_BANANA2_API_KEY": "nb2_key"}):
            p = NanoBanana2Processor()
        self.assertEqual(p._api_key, "nb2_key")

    def test_background_style_defaults(self):
        from lib.image_processor import BUYMA_DEFAULT_BG
        self.assertEqual(BUYMA_DEFAULT_BG.mode, "gradient")
        self.assertTrue(BUYMA_DEFAULT_BG.add_shadow)


# ---------------------------------------------------------------------------
# BUYMAAutomator
# ---------------------------------------------------------------------------

class TestBUYMAAutomator(unittest.TestCase):

    def test_not_configured_without_credentials(self):
        from lib.buyma_automator import BUYMAAutomator
        with patch.dict(os.environ, {"BUYMA_EMAIL": "", "BUYMA_PASSWORD": ""}):
            a = BUYMAAutomator()
        self.assertFalse(a.is_configured)

    def test_configured_with_credentials(self):
        from lib.buyma_automator import BUYMAAutomator
        a = BUYMAAutomator(email="test@example.com", password="pass")
        self.assertTrue(a.is_configured)

    def test_post_listing_returns_error_without_credentials(self):
        from lib.buyma_automator import BUYMAAutomator, ListingData
        automator = BUYMAAutomator()
        listing = ListingData(
            product_name="テストバッグ", brand="GUCCI",
            model_number="GG-001", description="テスト",
            buyma_price=195_000,
        )
        result = automator.post_listing(listing)
        self.assertFalse(result.success)
        self.assertIn("未設定", result.error)

    def test_record_to_listing(self):
        from lib.buyma_automator import record_to_listing
        from lib.sheet_manager import ProductRecord
        record = ProductRecord(
            商品名="テストバッグ", ブランド="GUCCI", 型番="GG-001",
            仕入れURL="https://ssense.com/item/1",
            現地価格="800", 為替="155",
            BUYMA販売価格="195000",
            在庫ステータス="出品中", 利益額="30000",
        )
        listing = record_to_listing(record)
        self.assertEqual(listing.product_name, "テストバッグ")
        self.assertEqual(listing.brand, "GUCCI")
        self.assertAlmostEqual(listing.buyma_price, 195_000)
        self.assertIn("GUCCI", listing.description)

    def test_extract_item_id(self):
        from lib.buyma_automator import _extract_item_id
        self.assertEqual(_extract_item_id("https://www.buyma.com/items/12345/"), "12345")
        self.assertIsNone(_extract_item_id("https://www.buyma.com/my/"))

    def test_listing_data_defaults(self):
        from lib.buyma_automator import ListingData
        listing = ListingData(
            product_name="テストバッグ", brand="CELINE",
            model_number="CE-001", description="説明",
            buyma_price=210_000,
        )
        self.assertEqual(listing.stock_count, 1)
        self.assertEqual(listing.source_shop, "")
        self.assertEqual(listing.shipping_method, "DHL国際宅配便（追跡番号付き）")

    def test_record_to_listing_uses_template(self):
        from lib.buyma_automator import record_to_listing
        from lib.sheet_manager import ProductRecord
        record = ProductRecord(
            商品名="セリーヌ トリオバッグ", ブランド="CELINE", 型番="CE-001",
            仕入れURL="https://net-a-porter.com/item/1",
            現地価格="900", 為替="155",
            BUYMA販売価格="210000",
            在庫ステータス="出品中", 利益額="",
        )
        listing = record_to_listing(record, source_shop="フランス正規取扱店")
        self.assertIn("【ブランド】CELINE", listing.description)
        self.assertIn("【商品名】セリーヌ トリオバッグ", listing.description)
        self.assertIn("【買付先】フランス正規取扱店", listing.description)
        self.assertIn("正規品のみ取り扱い", listing.description)
        self.assertIn("BUYMAあんしんプラス", listing.description)
        self.assertEqual(listing.source_shop, "フランス正規取扱店")
        self.assertEqual(listing.stock_count, 1)


class TestBuildListingDescription(unittest.TestCase):

    def test_basic_template_contains_brand_and_product(self):
        from lib.buyma_automator import build_listing_description
        desc = build_listing_description("CELINE", "トリオバッグ スモール")
        self.assertIn("【ブランド】CELINE", desc)
        self.assertIn("【商品名】トリオバッグ スモール", desc)

    def test_optional_fields_included_when_provided(self):
        from lib.buyma_automator import build_listing_description
        desc = build_listing_description(
            "Balenciaga", "Triple S",
            color="ホワイト", size="43",
            source_shop="イタリア正規取扱店",
            shipping_method="FedEx国際宅配便",
        )
        self.assertIn("【カラー】ホワイト", desc)
        self.assertIn("【サイズ】43", desc)
        self.assertIn("【買付先】イタリア正規取扱店", desc)
        self.assertIn("【発送方法】FedEx国際宅配便", desc)

    def test_optional_fields_omitted_when_empty(self):
        from lib.buyma_automator import build_listing_description
        desc = build_listing_description("Jil Sander", "Tangle Bag")
        self.assertNotIn("【カラー】", desc)
        self.assertNotIn("【サイズ】", desc)
        self.assertNotIn("【買付先】", desc)

    def test_trust_phrases_always_included(self):
        from lib.buyma_automator import build_listing_description
        desc = build_listing_description("CELINE", "バッグ")
        self.assertIn("正規品のみ取り扱い", desc)
        self.assertIn("BUYMAあんしんプラス", desc)

    def test_body_text_appended(self):
        from lib.buyma_automator import build_listing_description
        desc = build_listing_description("CELINE", "バッグ", body="シンプルで上質なデザイン。")
        self.assertIn("シンプルで上質なデザイン。", desc)


class TestValidateListing(unittest.TestCase):

    def _make_listing(self, **kwargs):
        from lib.buyma_automator import ListingData, build_listing_description
        defaults = dict(
            product_name="CELINE トリオバッグ スモール",
            brand="CELINE",
            model_number="CE-001",
            description=build_listing_description("CELINE", "トリオバッグ スモール"),
            buyma_price=210_000,
            source_shop="フランス正規取扱店",
        )
        defaults.update(kwargs)
        return ListingData(**defaults)

    def test_valid_listing_passes(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing())
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)

    def test_empty_brand_fails(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(brand=""))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("ブランド名" in e for e in result.errors))

    def test_empty_product_name_fails(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(product_name=""))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("商品名" in e for e in result.errors))

    def test_zero_price_fails(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(buyma_price=0))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("販売価格" in e for e in result.errors))

    def test_brand_not_in_title_warns(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(product_name="トリオバッグ スモール"))
        self.assertTrue(any("ブランド名が含まれていません" in w for w in result.warnings))

    def test_forbidden_phrase_warns(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(description="100%本物です。正規品です。"))
        self.assertTrue(any("100%本物" in w for w in result.warnings))

    def test_high_stock_count_warns(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(stock_count=5))
        self.assertTrue(any("在庫数" in w for w in result.warnings))

    def test_stock_count_1_no_warning(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing(stock_count=1))
        self.assertFalse(any("在庫数" in w for w in result.warnings))

    def test_summary_contains_status(self):
        from lib.buyma_automator import validate_listing
        result = validate_listing(self._make_listing())
        self.assertIn("✅", result.summary())


if __name__ == "__main__":
    unittest.main(verbosity=2)
