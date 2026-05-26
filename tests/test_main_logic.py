"""
メインロジック・設定・利益計算のユニットテスト。

- TestConfig           : Config の環境変数ロード・バリデーション
- TestProfitCalculator : calculate_profit / try_calculate_profit
- TestDetermineStatus  : determine_status の自動判定ロジック
- TestProcessProduct   : process_product の統合テスト（副作用なし）
- TestPrintSummary     : print_summary の出力テスト
"""

import os
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from lib.config import Config
from lib.profit_calculator import ProfitBreakdown, calculate_profit, try_calculate_profit
from lib.main import (
    STATUS_ACTIVE,
    STATUS_STOPPED,
    STATUS_WARNING_PREFIX,
    ProductResult,
    determine_status,
    is_scrapable_source_url,
    print_summary,
    process_product,
)
from lib.scraper.models import ScrapedResult
from lib.sheet_manager import ProductRecord


# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------

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
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_record(**overrides) -> ProductRecord:
    defaults = dict(
        商品名="テストバッグ",
        ブランド="GUCCI",
        型番="GG-001",
        仕入れURL="https://www.ssense.com/en-us/product/1",
        現地価格="800",
        為替="160",
        BUYMA販売価格="180000",
        在庫ステータス="出品中",
        利益額="",
    )
    defaults.update(overrides)
    return ProductRecord(**defaults)


def _make_scrape(
    price: float = 800.0,
    currency: str = "USD",
    stock_status: str = "in_stock",
    success: bool = True,
    error: str = None,
    url: str = "https://www.ssense.com/en-us/product/1",
) -> ScrapedResult:
    return ScrapedResult(
        url=url,
        price=price if success else None,
        currency=currency if success else None,
        stock_status=stock_status,
        raw_price=f"${price}" if success else None,
        scraped_at=datetime.now(timezone.utc),
        success=success,
        error=error,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):

    def test_from_env_defaults(self):
        env = {
            "SPREADSHEET_ID": "abc123",
        }
        with patch.dict(os.environ, env, clear=False):
            # credentials.json がない環境でも from_env は例外を出さない
            # (validate() で検出する設計)
            config = Config.from_env()
        self.assertEqual(config.spreadsheet_id, "abc123")
        self.assertAlmostEqual(config.buyma_fee_rate, 0.077)
        self.assertAlmostEqual(config.customs_rate, 0.10)
        self.assertAlmostEqual(config.shipping_cost_jpy, 2000.0)
        self.assertAlmostEqual(config.target_profit_rate, 0.10)
        self.assertEqual(config.scraper_concurrency, 3)
        self.assertTrue(config.scraper_headless)

    def test_from_env_custom_values(self):
        env = {
            "SPREADSHEET_ID": "xyz",
            "BUYMA_FEE_RATE": "0.15",
            "CUSTOMS_RATE": "0.05",
            "SHIPPING_COST_JPY": "3000",
            "TARGET_PROFIT_RATE": "0.20",
            "SCRAPER_CONCURRENCY": "5",
            "SCRAPER_HEADLESS": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            config = Config.from_env()
        self.assertAlmostEqual(config.buyma_fee_rate, 0.15)
        self.assertAlmostEqual(config.customs_rate, 0.05)
        self.assertAlmostEqual(config.shipping_cost_jpy, 3000.0)
        self.assertAlmostEqual(config.target_profit_rate, 0.20)
        self.assertEqual(config.scraper_concurrency, 5)
        self.assertFalse(config.scraper_headless)

    def test_validate_missing_spreadsheet_id(self):
        config = _make_config(spreadsheet_id="", credentials_path="credentials.json")
        with patch("os.path.exists", return_value=True):
            errors = config.validate()
        self.assertTrue(any("SPREADSHEET_ID" in e for e in errors))

    def test_validate_missing_credentials(self):
        config = _make_config(credentials_path="/nonexistent/credentials.json")
        errors = config.validate()
        self.assertTrue(any("認証情報" in e for e in errors))

    def test_validate_invalid_fee_rate(self):
        config = _make_config(buyma_fee_rate=1.5, credentials_path="credentials.json")
        with patch("os.path.exists", return_value=True):
            errors = config.validate()
        self.assertTrue(any("BUYMA_FEE_RATE" in e for e in errors))

    def test_validate_ok(self):
        config = _make_config()
        with patch("os.path.exists", return_value=True):
            errors = config.validate()
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# ProfitCalculator
# ---------------------------------------------------------------------------

class TestProfitCalculator(unittest.TestCase):

    def test_basic_calculation(self):
        # 仕入原価 800USD × 160 = 128,000 JPY
        # 関税 128,000 × 0.10 = 12,800
        # 送料 2,000
        # BUYMA手数料 180,000 × 0.11 = 19,800
        # 総コスト = 128,000 + 12,800 + 2,000 + 19,800 = 162,600
        # 利益 = 180,000 - 162,600 = 17,400
        b = calculate_profit(
            local_price=800,
            exchange_rate=160,
            buyma_price=180000,
            customs_rate=0.10,
            shipping_cost=2000,
            buyma_fee_rate=0.11,
        )
        self.assertAlmostEqual(b.jpy_cost, 128000.0)
        self.assertAlmostEqual(b.customs_cost, 12800.0)
        self.assertAlmostEqual(b.buyma_fee, 19800.0)
        self.assertAlmostEqual(b.total_cost, 162600.0)
        self.assertAlmostEqual(b.profit, 17400.0)
        self.assertAlmostEqual(b.profit_rate, 17400.0 / 180000.0, places=4)

    def test_negative_profit(self):
        b = calculate_profit(
            local_price=1000,
            exchange_rate=160,
            buyma_price=100000,
        )
        self.assertLess(b.profit, 0)
        self.assertFalse(b.is_profitable)

    def test_raises_on_invalid_exchange_rate(self):
        with self.assertRaises(ValueError):
            calculate_profit(local_price=800, exchange_rate=0, buyma_price=180000)

    def test_raises_on_negative_price(self):
        with self.assertRaises(ValueError):
            calculate_profit(local_price=-1, exchange_rate=160, buyma_price=180000)

    def test_try_calculate_valid(self):
        b = try_calculate_profit("800", "160", "180000")
        self.assertIsNotNone(b)
        self.assertAlmostEqual(b.profit, 23340.0)

    def test_try_calculate_empty_strings(self):
        self.assertIsNone(try_calculate_profit("", "", ""))

    def test_try_calculate_zero_values(self):
        self.assertIsNone(try_calculate_profit("0", "160", "180000"))

    def test_try_calculate_non_numeric(self):
        self.assertIsNone(try_calculate_profit("N/A", "160", "180000"))

    def test_summary_contains_key_info(self):
        b = calculate_profit(800, 160, 180000)
        s = b.summary()
        self.assertIn("¥180,000", s)
        self.assertIn("¥23,340", s)


# ---------------------------------------------------------------------------
# determine_status
# ---------------------------------------------------------------------------

class TestIsScrapableSourceUrl(unittest.TestCase):

    def test_accepts_overseas_supplier_url(self) -> None:
        self.assertTrue(is_scrapable_source_url("https://www.ssense.com/en-us/product/1"))

    def test_rejects_buyma_product_url(self) -> None:
        self.assertFalse(is_scrapable_source_url("https://www.buyma.com/item/12345/"))

    def test_rejects_empty_url(self) -> None:
        self.assertFalse(is_scrapable_source_url("  "))


class TestDetermineStatus(unittest.TestCase):

    def _bd(self, profit_rate: float) -> ProfitBreakdown:
        return ProfitBreakdown(
            local_price=800, exchange_rate=160, buyma_price=180000,
            jpy_cost=128000, customs_cost=12800, shipping_cost=2000,
            buyma_fee=19800, total_cost=162600,
            profit=180000 * profit_rate,
            profit_rate=profit_rate,
        )

    def test_out_of_stock_returns_stopped(self):
        scrape = _make_scrape(stock_status="out_of_stock")
        status = determine_status(scrape, self._bd(0.15), 0.10)
        self.assertEqual(status, STATUS_STOPPED)

    def test_in_stock_profitable_returns_active(self):
        scrape = _make_scrape(stock_status="in_stock")
        status = determine_status(scrape, self._bd(0.15), 0.10)
        self.assertEqual(status, STATUS_ACTIVE)

    def test_in_stock_low_profit_returns_warning(self):
        scrape = _make_scrape(stock_status="in_stock")
        status = determine_status(scrape, self._bd(0.05), 0.10)
        self.assertTrue(status.startswith(STATUS_WARNING_PREFIX))
        self.assertIn("5.0%", status)

    def test_scrape_failed_returns_empty(self):
        scrape = _make_scrape(success=False, error="timeout")
        status = determine_status(scrape, None, 0.10)
        self.assertEqual(status, "")

    def test_no_scrape_returns_empty(self):
        status = determine_status(None, None, 0.10)
        self.assertEqual(status, "")

    def test_unknown_stock_with_good_profit_returns_empty(self):
        # "unknown" は在庫確認できないため変更なし
        scrape = _make_scrape(stock_status="unknown")
        status = determine_status(scrape, self._bd(0.20), 0.10)
        self.assertEqual(status, "")

    def test_unknown_stock_low_profit_returns_warning(self):
        scrape = _make_scrape(stock_status="unknown")
        status = determine_status(scrape, self._bd(0.03), 0.10)
        self.assertTrue(status.startswith(STATUS_WARNING_PREFIX))




# ---------------------------------------------------------------------------
# style_id_status_override
# ---------------------------------------------------------------------------

class TestStyleIdStatusOverride(unittest.TestCase):

    def test_mismatch_sets_warning(self):
        from lib.main import style_id_status_override, STATUS_ACTIVE, STYLE_ID_WARNING
        from lib.scraper.models import ScrapedResult
        from datetime import datetime, timezone

        record = _make_record(型番="ARC58-BLK")
        scrape = _make_scrape(stock_status="in_stock")
        scrape = replace(scrape, style_id="OTHER-CODE")
        status = style_id_status_override(record, scrape, STATUS_ACTIVE)
        self.assertEqual(status, STYLE_ID_WARNING)

    def test_match_keeps_status(self):
        from lib.main import style_id_status_override, STATUS_ACTIVE
        record = _make_record(型番="ARC58-BLK")
        scrape = _make_scrape(stock_status="in_stock")
        scrape = replace(scrape, style_id="arc58/blk")
        status = style_id_status_override(record, scrape, STATUS_ACTIVE)
        self.assertEqual(status, STATUS_ACTIVE)

    def test_no_sheet_style_id_skips(self):
        from lib.main import style_id_status_override, STATUS_ACTIVE
        record = _make_record(型番="")
        scrape = _make_scrape(stock_status="in_stock")
        scrape = replace(scrape, style_id="X")
        self.assertEqual(
            style_id_status_override(record, scrape, STATUS_ACTIVE),
            STATUS_ACTIVE,
        )

    def test_stopped_priority_over_style_mismatch(self):
        from lib.main import style_id_status_override, STATUS_STOPPED
        record = _make_record(型番="ARC58")
        scrape = _make_scrape(stock_status="out_of_stock")
        scrape = replace(scrape, style_id="WRONG")
        self.assertEqual(
            style_id_status_override(record, scrape, STATUS_STOPPED),
            STATUS_STOPPED,
        )
# ---------------------------------------------------------------------------
# process_product
# ---------------------------------------------------------------------------

class TestProcessProduct(unittest.TestCase):

    def setUp(self):
        self.config = _make_config()

    def test_updates_price_on_success(self):
        record = _make_record(現地価格="800")
        scrape = _make_scrape(price=850.0)
        result = process_product(record, scrape, self.config)
        self.assertEqual(result.updated.現地価格, "850.0")

    def test_keeps_original_price_on_failure(self):
        record = _make_record(現地価格="800")
        scrape = _make_scrape(success=False, error="timeout")
        result = process_product(record, scrape, self.config)
        self.assertEqual(result.updated.現地価格, "800")

    def test_calculates_profit(self):
        record = _make_record(現地価格="800", 為替="160", BUYMA販売価格="180000")
        scrape = _make_scrape(price=800.0)
        result = process_product(record, scrape, self.config)
        self.assertEqual(result.updated.利益額, "17400")

    def test_status_set_to_active(self):
        # 利益率 > 10% になる設定: 800 * 160 = 128,000 → 利益 35,200 / 200,000 = 17.6%
        record = _make_record(型番="", 現地価格="800", 為替="160", BUYMA販売価格="200000")
        scrape = _make_scrape(stock_status="in_stock", price=800.0)
        result = process_product(record, scrape, self.config)
        self.assertEqual(result.updated.在庫ステータス, STATUS_ACTIVE)

    def test_status_set_to_stopped_on_out_of_stock(self):
        record = _make_record()
        scrape = _make_scrape(stock_status="out_of_stock")
        result = process_product(record, scrape, self.config)
        self.assertEqual(result.updated.在庫ステータス, STATUS_STOPPED)

    def test_status_warning_on_low_profit(self):
        # 利益率が下がる価格設定
        record = _make_record(現地価格="1200", 為替="160", BUYMA販売価格="180000")
        scrape = _make_scrape(price=1200.0, stock_status="in_stock")
        result = process_product(record, scrape, self.config)
        self.assertTrue(result.updated.在庫ステータス.startswith(STATUS_WARNING_PREFIX))

    def test_no_url_scrape_is_none(self):
        record = _make_record(仕入れURL="")
        result = process_product(record, None, self.config)
        # URL がない場合はスクレイプ結果なし → 元のステータス維持
        self.assertEqual(result.scrape, None)

    def test_original_record_not_mutated(self):
        record = _make_record(現地価格="800", 在庫ステータス="出品中")
        scrape = _make_scrape(price=900.0, stock_status="out_of_stock")
        result = process_product(record, scrape, self.config)
        # dataclasses.replace() を使っているので元は変更されない
        self.assertEqual(record.現地価格, "800")
        self.assertEqual(record.在庫ステータス, "出品中")

    def test_result_ok_on_success(self):
        record = _make_record()
        scrape = _make_scrape()
        result = process_product(record, scrape, self.config)
        self.assertTrue(result.ok)

    def test_result_not_ok_on_scrape_failure(self):
        record = _make_record()
        scrape = _make_scrape(success=False, error="timeout")
        result = process_product(record, scrape, self.config)
        self.assertFalse(result.ok)


# ---------------------------------------------------------------------------
# print_summary（出力テスト）
# ---------------------------------------------------------------------------

class TestPrintSummary(unittest.TestCase):

    def _make_result(self, status: str, profit: float = 17400.0) -> ProductResult:
        record = _make_record(在庫ステータス=status)
        updated = replace(record, 在庫ステータス=status, 利益額=str(round(profit)))
        scrape = _make_scrape(stock_status="in_stock")
        bd = ProfitBreakdown(
            local_price=800, exchange_rate=160, buyma_price=180000,
            jpy_cost=128000, customs_cost=12800, shipping_cost=2000,
            buyma_fee=19800, total_cost=162600,
            profit=profit, profit_rate=profit / 180000,
        )
        return ProductResult(original=record, updated=updated, scrape=scrape, breakdown=bd)

    def test_summary_runs_without_error(self):
        config = _make_config()
        results = [
            self._make_result(STATUS_ACTIVE, 17400),
            self._make_result(STATUS_STOPPED, -5000),
            self._make_result(f"{STATUS_WARNING_PREFIX} (利益率 5.0%)", 9000),
        ]
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_summary(results, config)
        output = buf.getvalue()
        self.assertIn("出品中", output)
        self.assertIn("停止中", output)
        self.assertIn("要確認", output)

    def test_summary_counts_correctly(self):
        config = _make_config()
        results = [
            self._make_result(STATUS_ACTIVE),
            self._make_result(STATUS_ACTIVE),
            self._make_result(STATUS_STOPPED),
        ]
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_summary(results, config)
        output = buf.getvalue()
        self.assertIn("出品中  : 2 件", output)
        self.assertIn("停止中  : 1 件", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
