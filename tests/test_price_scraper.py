"""
PriceScraper のテストスイート。

- TestParsePriceString : utils.parse_price_string のユニットテスト
- TestScrapedResult    : ScrapedResult のユニットテスト
- TestStrategyRouting  : PriceScraper のStrategy選択ロジックテスト
- TestSSENSEStrategy   : SSENSEStrategy のモックページテスト
- TestTESSABITStrategy : TESSABITStrategy のモックページテスト
- TestGenericStrategy  : GenericStrategy のモックページテスト
- TestPriceScraper     : エンジン全体の統合モックテスト
- IntegrationTests     : 実URLを使ったオプション統合テスト（ネットワーク必要）
"""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from lib.scraper.models import ScrapedResult
from lib.scraper.utils import parse_price_string
from lib.scraper.strategies.ssense import SSENSEStrategy
from lib.scraper.strategies.tessabit import TESSABITStrategy
from lib.scraper.strategies.generic import GenericStrategy
from lib.scraper.engine import PriceScraper


# ---------------------------------------------------------------------------
# ヘルパー: モックページ生成
# ---------------------------------------------------------------------------

def _make_page(
    body_text: str = "",
    selectors: dict[str, str] | None = None,
    url: str = "https://example.com/product",
    js_results: dict[str, str | None] | None = None,
) -> MagicMock:
    """Playwright Page を模倣したモックオブジェクトを生成する。

    Args:
        body_text: page.inner_text("body") の返却値。
        selectors: {selector: text} のマッピング。query_selector + inner_text をモック。
        url: page.url の値。
        js_results: {js_snippet_substring: return_value} page.evaluate のモック。
    """
    page = MagicMock()
    page.url = url

    # inner_text
    async def _inner_text(selector: str = "body") -> str:
        return body_text
    page.inner_text = AsyncMock(side_effect=_inner_text)

    # query_selector
    async def _qs(selector: str):
        if selectors and selector in selectors:
            el = MagicMock()
            text = selectors[selector]
            el.inner_text = AsyncMock(return_value=text)
            el.is_visible = AsyncMock(return_value=True)
            el.is_enabled = AsyncMock(return_value=True)
            return el
        return None
    page.query_selector = AsyncMock(side_effect=_qs)

    # evaluate
    async def _evaluate(js: str):
        if js_results:
            for key, val in js_results.items():
                if key in js:
                    return val
        return None
    page.evaluate = AsyncMock(side_effect=_evaluate)

    # wait_for_timeout
    page.wait_for_timeout = AsyncMock(return_value=None)

    return page


def _run(coro):
    """テスト内でコルーチンを同期実行するヘルパー。"""
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# parse_price_string
# ---------------------------------------------------------------------------

class TestParsePriceString(unittest.TestCase):

    def test_usd_dollar_sign(self):
        self.assertEqual(parse_price_string("$1,550"), (1550.0, "USD"))

    def test_eur_sign(self):
        self.assertEqual(parse_price_string("€2,450"), (2450.0, "EUR"))

    def test_eur_european_format(self):
        val, cur = parse_price_string("€ 2.450,00")
        self.assertEqual(cur, "EUR")
        self.assertAlmostEqual(val, 2450.0)

    def test_cad_prefix(self):
        val, cur = parse_price_string("CA$1,550.00")
        self.assertEqual(cur, "CAD")
        self.assertAlmostEqual(val, 1550.0)

    def test_gbp_sign(self):
        val, cur = parse_price_string("£899")
        self.assertEqual(cur, "GBP")
        self.assertAlmostEqual(val, 899.0)

    def test_code_suffix(self):
        val, cur = parse_price_string("1,550 USD")
        self.assertEqual(cur, "USD")
        self.assertAlmostEqual(val, 1550.0)

    def test_empty_string(self):
        self.assertEqual(parse_price_string(""), (None, None))

    def test_no_numeric(self):
        val, _ = parse_price_string("N/A")
        self.assertIsNone(val)

    def test_plain_number(self):
        val, cur = parse_price_string("1234.56")
        self.assertAlmostEqual(val, 1234.56)
        self.assertIsNone(cur)

    def test_yen_sign(self):
        val, cur = parse_price_string("¥15,000")
        self.assertEqual(cur, "JPY")
        self.assertAlmostEqual(val, 15000.0)


# ---------------------------------------------------------------------------
# ScrapedResult
# ---------------------------------------------------------------------------

class TestScrapedResult(unittest.TestCase):

    def test_is_available_in_stock(self):
        r = ScrapedResult(url="x", price=100.0, currency="USD", stock_status="in_stock", raw_price="$100")
        self.assertTrue(r.is_available)

    def test_is_available_out_of_stock(self):
        r = ScrapedResult(url="x", price=100.0, currency="USD", stock_status="out_of_stock", raw_price="$100")
        self.assertFalse(r.is_available)

    def test_str_success(self):
        r = ScrapedResult(url="x", price=1550.0, currency="USD", stock_status="in_stock", raw_price="$1,550")
        self.assertIn("USD", str(r))
        self.assertIn("in_stock", str(r))

    def test_str_failure(self):
        r = ScrapedResult(url="x", price=None, currency=None, stock_status="unknown", raw_price=None,
                          success=False, error="timeout")
        self.assertIn("FAILED", str(r))
        self.assertIn("timeout", str(r))


# ---------------------------------------------------------------------------
# Strategy ルーティング
# ---------------------------------------------------------------------------

class TestStrategyRouting(unittest.TestCase):

    def setUp(self):
        self.scraper = PriceScraper()

    def test_ssense_url(self):
        s = self.scraper.get_strategy("https://www.ssense.com/en-us/women/product/gucci/item")
        self.assertIsInstance(s, SSENSEStrategy)

    def test_tessabit_url(self):
        s = self.scraper.get_strategy("https://www.tessabit.com/en/gucci-bag")
        self.assertIsInstance(s, TESSABITStrategy)

    def test_unknown_url_returns_generic(self):
        s = self.scraper.get_strategy("https://www.unknown-shop.com/product/123")
        self.assertIsInstance(s, GenericStrategy)

    def test_custom_strategy_registration(self):
        from lib.scraper.base import ScraperStrategy

        class MyStrategy(ScraperStrategy):
            @property
            def domain(self):
                return "myshop.com"
            async def extract(self, page):
                return {"price": "$99", "stock_status": "in_stock"}

        self.scraper.register(MyStrategy())
        s = self.scraper.get_strategy("https://www.myshop.com/item/1")
        self.assertIsInstance(s, MyStrategy)


# ---------------------------------------------------------------------------
# SSENSEStrategy
# ---------------------------------------------------------------------------

class TestSSENSEStrategy(unittest.TestCase):

    def _run(self, coro):
        return _run(coro)

    def test_price_via_selector(self):
        page = _make_page(
            selectors={"[class*='Price__priceItem']": "$1,550"},
            body_text="Add to Bag",
        )
        result = self._run(SSENSEStrategy().extract(page))
        self.assertEqual(result["price"], "$1,550")

    def test_price_via_json_ld(self):
        page = _make_page(
            body_text="Add to Bag",
            js_results={"application/ld+json": "USD1550"},
        )
        result = self._run(SSENSEStrategy().extract(page))
        self.assertEqual(result["price"], "USD1550")

    def test_stock_in_stock(self):
        page = _make_page(body_text="Add to Bag $1,550")
        result = self._run(SSENSEStrategy().extract(page))
        self.assertEqual(result["stock_status"], "in_stock")

    def test_stock_out_of_stock_text(self):
        page = _make_page(body_text="Sold Out")
        result = self._run(SSENSEStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_stock_unknown_when_ambiguous(self):
        page = _make_page(body_text="Product details here")
        result = self._run(SSENSEStrategy().extract(page))
        self.assertEqual(result["stock_status"], "unknown")

    def test_no_price_returns_none(self):
        page = _make_page(body_text="Add to Bag")
        result = self._run(SSENSEStrategy().extract(page))
        self.assertNotIn("price", result)


# ---------------------------------------------------------------------------
# TESSABITStrategy
# ---------------------------------------------------------------------------

class TestTESSABITStrategy(unittest.TestCase):

    def _run(self, coro):
        return _run(coro)

    def test_price_via_selector(self):
        page = _make_page(
            selectors={"[data-price-type='finalPrice'] .price": "€ 2.450,00"},
            body_text="Add to Cart",
        )
        result = self._run(TESSABITStrategy().extract(page))
        self.assertEqual(result["price"], "€ 2.450,00")

    def test_price_via_meta(self):
        page = _make_page(
            body_text="Add to Cart",
            js_results={"product:price:amount": "EUR2450"},
        )
        result = self._run(TESSABITStrategy().extract(page))
        self.assertEqual(result["price"], "EUR2450")

    def test_in_stock_via_text(self):
        page = _make_page(body_text="€2,450 add to cart")
        result = self._run(TESSABITStrategy().extract(page))
        self.assertEqual(result["stock_status"], "in_stock")

    def test_out_of_stock_italian(self):
        page = _make_page(body_text="Esaurito")
        result = self._run(TESSABITStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_out_of_stock_via_selector(self):
        page = _make_page(
            selectors={".unavailable": "Sold out"},
            body_text="",
        )
        result = self._run(TESSABITStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")


# ---------------------------------------------------------------------------
# GenericStrategy
# ---------------------------------------------------------------------------

class TestGenericStrategy(unittest.TestCase):

    def _run(self, coro):
        return _run(coro)

    def test_price_via_json_ld(self):
        page = _make_page(
            body_text="Add to cart",
            js_results={"@graph": "USD 890"},
        )
        result = self._run(GenericStrategy().extract(page))
        self.assertEqual(result["price"], "USD 890")

    def test_price_via_selector(self):
        page = _make_page(
            selectors={"[itemprop='price']": "£450"},
            body_text="buy now",
        )
        result = self._run(GenericStrategy().extract(page))
        self.assertEqual(result["price"], "£450")

    def test_out_of_stock(self):
        page = _make_page(body_text="This item is out of stock.")
        result = self._run(GenericStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_unknown_when_no_hints(self):
        page = _make_page(body_text="Lorem ipsum dolor sit amet.")
        result = self._run(GenericStrategy().extract(page))
        self.assertEqual(result["stock_status"], "unknown")


# ---------------------------------------------------------------------------
# PriceScraper エンジン（async_playwright をパッチしてブラウザ起動を回避）
# ---------------------------------------------------------------------------

def _make_mock_playwright_ctx():
    """async_playwright() コンテキストマネージャを模倣するモックを返す。

    browser.close() / context.close() など全ての await 呼び出しを AsyncMock にする。
    """
    import lib.scraper.engine as eng_module
    from contextlib import asynccontextmanager

    fake_browser = MagicMock()
    fake_browser.close = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        pw = MagicMock()
        pw.chromium.launch = AsyncMock(return_value=fake_browser)
        yield pw

    return patch.object(eng_module, "async_playwright", new=_ctx)


class TestPriceScraper(unittest.IsolatedAsyncioTestCase):

    async def test_successful_scrape_price_parsing(self):
        """_scrape_with_browser が成功結果を返す場合、scrape_async がそれをそのまま返す。"""
        url = "https://www.ssense.com/en-us/women/product/gucci/bag"
        expected = ScrapedResult(
            url=url, price=1550.0, currency="USD",
            stock_status="in_stock", raw_price="$1,550",
            scraped_at=datetime.now(timezone.utc), success=True,
        )

        scraper = PriceScraper(headless=True, max_retries=1)

        async def _fake(u, browser, strategy):
            return expected

        with _make_mock_playwright_ctx():
            with patch.object(scraper, "_scrape_with_browser", new=_fake):
                result = await scraper.scrape_async(url)

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.price, 1550.0)
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.stock_status, "in_stock")

    async def test_error_result_when_scrape_raises(self):
        """_scrape_with_browser が例外を throw した場合、失敗結果が返る。"""
        url = "https://www.ssense.com/item/1"
        scraper = PriceScraper(headless=True, max_retries=1)

        async def _fail(u, browser, strategy):
            raise RuntimeError("network error")

        with _make_mock_playwright_ctx():
            with patch.object(scraper, "_scrape_with_browser", new=_fail):
                result = await scraper.scrape_async(url)

        self.assertFalse(result.success)
        self.assertIn("network error", result.error)
        self.assertEqual(result.stock_status, "unknown")
        self.assertIsNone(result.price)

    async def test_scrape_many_async_returns_all_results(self):
        """scrape_many_async が全URLの結果をリストで返す。"""
        urls = [
            "https://www.ssense.com/en-us/women/product/a",
            "https://www.tessabit.com/en/product-b",
        ]
        scraper = PriceScraper(headless=True, max_retries=1)

        async def _ok(url, browser, strategy):
            return ScrapedResult(
                url=url, price=100.0, currency="USD",
                stock_status="in_stock", raw_price="$100",
                scraped_at=datetime.now(timezone.utc), success=True,
            )

        with _make_mock_playwright_ctx():
            with patch.object(scraper, "_scrape_with_browser", new=_ok):
                results = await scraper.scrape_many_async(urls, concurrency=2)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_make_error_result(self):
        """_make_error_result が正しい失敗 ScrapedResult を生成する。"""
        url = "https://example.com"
        result = PriceScraper._make_error_result(url, ValueError("bad selector"))
        self.assertFalse(result.success)
        self.assertEqual(result.url, url)
        self.assertIn("bad selector", result.error)
        self.assertIsNone(result.price)
        self.assertEqual(result.stock_status, "unknown")


# ---------------------------------------------------------------------------
# 統合テスト（実URL / ネットワーク必要 — デフォルトでスキップ）
# ---------------------------------------------------------------------------

import os

INTEGRATION = os.getenv("SCRAPER_INTEGRATION_TEST", "").lower() in ("1", "true", "yes")


@unittest.skipUnless(INTEGRATION, "SCRAPER_INTEGRATION_TEST=1 を設定すると実行されます")
class IntegrationTests(unittest.TestCase):
    """実際のURLに対するスクレイピングテスト。
    実行には Playwright ブラウザのインストールが必要です:
        playwright install chromium
    実行方法:
        SCRAPER_INTEGRATION_TEST=1 python3 -m pytest test_price_scraper.py::IntegrationTests -v
    """

    def setUp(self):
        self.scraper = PriceScraper(headless=True, max_retries=1)

    def _assert_result(self, result: ScrapedResult, expected_currency: str = None):
        print(f"\n  → {result}")
        self.assertTrue(result.success, f"スクレイピング失敗: {result.error}")
        self.assertIsNotNone(result.price, "価格が取得できませんでした")
        self.assertGreater(result.price, 0, "価格が0以下です")
        if expected_currency:
            self.assertEqual(result.currency, expected_currency)
        self.assertIn(result.stock_status, ("in_stock", "out_of_stock", "unknown"))

    def test_ssense_product(self):
        url = "https://www.ssense.com/en-us/women/product/bottega-veneta/green-intrecciato-mini-jodie-bag/14506881"
        result = self.scraper.scrape(url)
        self._assert_result(result)

    def test_tessabit_product(self):
        url = "https://www.tessabit.com/en/women/bags/shoulder-bags"
        result = self.scraper.scrape(url)
        self._assert_result(result)

    def test_generic_fallback(self):
        # 汎用Strategyが動作することを確認（SSENSE以外のサイト）
        url = "https://www.farfetch.com/shopping/women/gucci-gg-marmont-shoulder-bag-item-17891765.aspx"
        result = self.scraper.scrape(url)
        # 汎用なので失敗しても良いが、クラッシュしないことを確認
        self.assertIsNotNone(result)
        self.assertFalse(result.success is None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
