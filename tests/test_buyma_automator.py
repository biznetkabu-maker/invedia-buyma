"""buyma_automator.py のユニットテスト。

ListingData, ListingResult, validate_listing, build_listing_description,
record_to_listing, BUYMAAutomator のテスト。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.buyma_automator import (
    BUYMAAutomator,
    ListingData,
    ListingResult,
    ListingValidationResult,
    build_listing_description,
    record_to_listing,
    validate_listing,
    _extract_item_id,
    _load_session_cookies,
    _random_jitter,
    _random_type_delay,
    _safe_fill,
    _safe_select,
    _save_session_cookies,
)
from lib.sheet_manager import ProductRecord


class TestListingData(unittest.TestCase):
    """ListingData のテスト。"""

    def test_defaults(self):
        ld = ListingData(
            product_name="Test", brand="PRADA",
            model_number="1BA123", description="desc",
            buyma_price=100000,
        )
        self.assertEqual(ld.condition, "新品")
        self.assertEqual(ld.shipping_from, "海外")
        self.assertEqual(ld.stock_count, 1)
        self.assertEqual(ld.image_paths, [])

    def test_image_paths_none_default(self):
        ld = ListingData(
            product_name="T", brand="B",
            model_number="M", description="D",
            buyma_price=1000,
        )
        self.assertIsInstance(ld.image_paths, list)
        self.assertEqual(len(ld.image_paths), 0)


class TestListingResult(unittest.TestCase):
    """ListingResult のテスト。"""

    def test_success_str(self):
        r = ListingResult(product_name="Test", success=True, url="https://buyma.com/item/123")
        self.assertIn("[OK]", str(r))
        self.assertIn("Test", str(r))

    def test_failure_str(self):
        r = ListingResult(product_name="Test", success=False, error="timeout")
        self.assertIn("[FAILED]", str(r))
        self.assertIn("timeout", str(r))

    def test_listed_at_auto(self):
        r = ListingResult(product_name="Test", success=True)
        self.assertIsNotNone(r.listed_at)


class TestBuildListingDescription(unittest.TestCase):
    """build_listing_description のテスト。"""

    def test_basic(self):
        desc = build_listing_description("PRADA", "Saffiano Wallet")
        self.assertIn("【ブランド】PRADA", desc)
        self.assertIn("【商品名】Saffiano Wallet", desc)
        self.assertIn("正規品のみ取り扱い", desc)
        self.assertIn("BUYMAあんしんプラス", desc)

    def test_with_color_and_size(self):
        desc = build_listing_description(
            "GUCCI", "GG Belt", color="ブラック", size="85cm"
        )
        self.assertIn("【カラー】ブラック", desc)
        self.assertIn("【サイズ】85cm", desc)

    def test_without_optional_fields(self):
        desc = build_listing_description("GUCCI", "GG Belt")
        self.assertNotIn("【カラー】", desc)
        self.assertNotIn("【サイズ】", desc)

    def test_with_source_shop(self):
        desc = build_listing_description(
            "PRADA", "Wallet", source_shop="イタリア正規店"
        )
        self.assertIn("【買付先】イタリア正規店", desc)

    def test_with_body(self):
        desc = build_listing_description("PRADA", "Wallet", body="追加説明テキスト")
        self.assertIn("追加説明テキスト", desc)

    def test_custom_shipping(self):
        desc = build_listing_description(
            "PRADA", "Wallet", shipping_method="FedEx"
        )
        self.assertIn("【発送方法】FedEx", desc)


class TestValidateListing(unittest.TestCase):
    """validate_listing のテスト。"""

    def _make_listing(self, **overrides):
        defaults = dict(
            product_name="PRADA Saffiano Wallet",
            brand="PRADA",
            model_number="1BA123",
            description="【ブランド】PRADA\n正規品のみ取り扱い。",
            buyma_price=100000,
        )
        defaults.update(overrides)
        return ListingData(**defaults)

    def test_valid_listing(self):
        r = validate_listing(self._make_listing())
        self.assertTrue(r.is_valid)
        self.assertEqual(r.errors, [])

    def test_empty_brand_error(self):
        r = validate_listing(self._make_listing(brand=""))
        self.assertFalse(r.is_valid)
        self.assertTrue(any("ブランド名" in e for e in r.errors))

    def test_empty_product_name_error(self):
        r = validate_listing(self._make_listing(product_name=""))
        self.assertFalse(r.is_valid)
        self.assertTrue(any("商品名" in e for e in r.errors))

    def test_zero_price_error(self):
        r = validate_listing(self._make_listing(buyma_price=0))
        self.assertFalse(r.is_valid)
        self.assertTrue(any("販売価格" in e for e in r.errors))

    def test_brand_not_in_title_warning(self):
        r = validate_listing(self._make_listing(product_name="Saffiano Wallet"))
        self.assertTrue(r.is_valid)
        self.assertTrue(any("ブランド名" in w and "商品名" in w for w in r.warnings))

    def test_empty_description_warning(self):
        r = validate_listing(self._make_listing(description=""))
        self.assertTrue(any("説明文が空" in w for w in r.warnings))

    def test_high_stock_warning(self):
        r = validate_listing(self._make_listing(stock_count=5))
        self.assertTrue(any("在庫数" in w for w in r.warnings))

    def test_forbidden_phrase_warning(self):
        r = validate_listing(
            self._make_listing(description="PRADA 100%本物です！最高品質！")
        )
        self.assertTrue(any("誇大表現" in w for w in r.warnings))

    def test_no_source_shop_warning(self):
        r = validate_listing(self._make_listing(source_shop=""))
        self.assertTrue(any("買付先" in w for w in r.warnings))


class TestRecordToListing(unittest.TestCase):
    """record_to_listing のテスト。"""

    def test_basic_conversion(self):
        rec = ProductRecord(
            商品名="PRADA Wallet",
            ブランド="PRADA",
            型番="1BA123",
            BUYMA販売価格="80000",
        )
        listing = record_to_listing(rec)
        self.assertEqual(listing.product_name, "PRADA Wallet")
        self.assertEqual(listing.brand, "PRADA")
        self.assertEqual(listing.model_number, "1BA123")
        self.assertEqual(listing.buyma_price, 80000.0)
        self.assertIn("PRADA", listing.description)

    def test_custom_description(self):
        rec = ProductRecord(
            商品名="Test", ブランド="B",
            型番="M", BUYMA販売価格="1000",
        )
        listing = record_to_listing(rec, description_template="Custom desc")
        self.assertEqual(listing.description, "Custom desc")

    def test_image_paths(self):
        rec = ProductRecord(
            商品名="Test", ブランド="B",
            型番="M", BUYMA販売価格="1000",
        )
        listing = record_to_listing(rec, image_paths=["/tmp/a.jpg", "/tmp/b.jpg"])
        self.assertEqual(listing.image_paths, ["/tmp/a.jpg", "/tmp/b.jpg"])

    def test_zero_price(self):
        rec = ProductRecord(
            商品名="Test", ブランド="B",
            型番="", BUYMA販売価格="",
        )
        listing = record_to_listing(rec)
        self.assertEqual(listing.buyma_price, 0.0)


class TestExtractItemId(unittest.TestCase):
    """_extract_item_id のテスト。"""

    def test_extracts_from_url(self):
        self.assertEqual(_extract_item_id("https://buyma.com/items/12345"), "12345")

    def test_extracts_singular(self):
        self.assertEqual(_extract_item_id("https://buyma.com/item/67890"), "67890")

    def test_no_match(self):
        self.assertIsNone(_extract_item_id("https://buyma.com/search"))


class TestBUYMAAutomatorInit(unittest.TestCase):
    """BUYMAAutomator の初期化テスト。"""

    def test_not_configured_without_env(self):
        with patch.dict("os.environ", {}, clear=True):
            auto = BUYMAAutomator(email="", password="")
            self.assertFalse(auto.is_configured)

    def test_configured_with_creds(self):
        auto = BUYMAAutomator(email="test@example.com", password="pass123")
        self.assertTrue(auto.is_configured)


class TestListingValidationResult(unittest.TestCase):
    """ListingValidationResult のテスト。"""

    def test_summary_ok(self):
        r = ListingValidationResult(is_valid=True, errors=[], warnings=[])
        self.assertIn("OK", r.summary())

    def test_summary_with_errors(self):
        r = ListingValidationResult(
            is_valid=False, errors=["エラー1"], warnings=["警告1"]
        )
        s = r.summary()
        self.assertIn("エラー", s)
        self.assertIn("警告", s)


class TestPostListingNotConfigured(unittest.TestCase):
    def test_returns_failure_when_not_configured(self):
        auto = BUYMAAutomator(email="", password="")
        result = asyncio.run(auto.post_listing_async(
            ListingData(brand="X", product_name="Y", model_number="M1",
                        description="desc", buyma_price=1000)
        ))
        self.assertFalse(result.success)
        self.assertIn("未設定", result.error)


class TestRandomHelpers(unittest.TestCase):
    def test_jitter_within_range(self):
        for _ in range(50):
            v = _random_jitter(1.0, 3.0)
            self.assertGreaterEqual(v, 1.0)
            self.assertLessEqual(v, 3.0)

    def test_type_delay_within_range(self):
        for _ in range(50):
            v = _random_type_delay()
            self.assertGreaterEqual(v, 80)
            self.assertLessEqual(v, 200)


class TestSessionCookies(unittest.TestCase):
    def test_save_and_load_roundtrip(self, ):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "cookies.json"
            cookies = [{"name": "sid", "value": "abc"}]
            with patch("lib.buyma_automator._SESSION_COOKIE_FILE", f):
                _save_session_cookies(cookies)
                loaded = _load_session_cookies()
        self.assertEqual(loaded, cookies)

    def test_load_invalid_returns_empty(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "missing.json"
            with patch("lib.buyma_automator._SESSION_COOKIE_FILE", f):
                self.assertEqual(_load_session_cookies(), [])


class TestSafeFillSelect(unittest.TestCase):
    def test_safe_fill_when_present(self):
        el = AsyncMock()
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        asyncio.run(_safe_fill(page, "#name", "value"))
        el.fill.assert_awaited_once_with("value")

    def test_safe_fill_when_absent(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        asyncio.run(_safe_fill(page, "#name", "value"))  # no exception

    def test_safe_fill_swallows_exception(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=RuntimeError("boom"))
        asyncio.run(_safe_fill(page, "#name", "value"))  # no exception

    def test_safe_select_when_present(self):
        el = AsyncMock()
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        asyncio.run(_safe_select(page, "#sz", "M"))
        el.select_option.assert_awaited_once_with(value="M")


if __name__ == "__main__":
    unittest.main()
