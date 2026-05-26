"""
新規追加11サイトのStrategyテスト + ステルスモジュールテスト。

テスト分類:
  TestStealth            : stealth.py のユニットテスト
  TestStrategyRouting    : 全18サイト URL → Strategy マッピング
  TestFARFETCH           : FARFETCHStrategy（モックページ）
  TestMATCHESFASHION     : MATCHESFASHIONStrategy
  TestMYTHERESA          : MYTHERESAStrategy
  TestSELFRIDGES         : SELFRIDGESStrategy
  TestSAKS               : SAKSStrategy
  TestHARRODS            : HARRODSStrategy
  TestHARVEYNICHOLS      : HARVEYNICHOLSStrategy
  TestNEIMANMARCUS       : NEIMANMARCUSStrategy
  TestLUISAVIAROMA       : LUISAVIAROMAStrategy
  TestGIGLIO             : GIGLIOStrategy
  TestBIFFI              : BIFFIStrategy
  TestNETAPORTER         : NETAPORTERStrategy
  TestMRPORTER           : MRPORTERStrategy
  TestYOOX               : YOOXStrategy
  TestTHEOUTNET          : THEOUTNETStrategy
  TestTWENTYFOURS        : TWENTYFOURSStrategy
  IntegrationTests       : 実URLリスト（SCRAPER_INTEGRATION_TEST=1 で実行）
"""

import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from lib.scraper.stealth import (
    LAUNCH_ARGS,
    STEALTH_INIT_SCRIPT,
    random_user_agent,
    random_viewport,
    random_wait_ms,
    stealth_context_options,
)
from lib.scraper.strategies.farfetch import FARFETCHStrategy
from lib.scraper.strategies.matchesfashion import MATCHESFASHIONStrategy
from lib.scraper.strategies.mytheresa import MYTHERESAStrategy
from lib.scraper.strategies.selfridges import SELFRIDGESStrategy
from lib.scraper.strategies.saks import SAKSStrategy
from lib.scraper.strategies.harrods import HARRODSStrategy
from lib.scraper.strategies.harveynichols import HARVEYNICHOLSStrategy
from lib.scraper.strategies.neimanmarcus import NEIMANMARCUSStrategy
from lib.scraper.strategies.luisaviaroma import LUISAVIAROMAStrategy
from lib.scraper.strategies.giglio import GIGLIOStrategy
from lib.scraper.strategies.biffi import BIFFIStrategy
from lib.scraper.strategies.netaporter import NETAPORTERStrategy
from lib.scraper.strategies.mrporter import MRPORTERStrategy
from lib.scraper.strategies.yoox import YOOXStrategy
from lib.scraper.strategies.theoutnet import THEOUTNETStrategy
from lib.scraper.strategies.twentyfoursevens import TWENTYFOURSStrategy
from lib.scraper.engine import PriceScraper


# ---------------------------------------------------------------------------
# ヘルパー: モックページ生成
# ---------------------------------------------------------------------------

def _make_page(
    body_text: str = "",
    selectors: dict[str, str] | None = None,
    js_results: dict[str, str | None] | None = None,
    url: str = "https://example.com/product",
) -> MagicMock:
    page = MagicMock()
    page.url = url

    async def _inner_text(selector: str = "body") -> str:
        return body_text
    page.inner_text = AsyncMock(side_effect=_inner_text)

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

    async def _evaluate(js: str):
        if js_results:
            for key, val in js_results.items():
                if key in js:
                    return val
        return None
    page.evaluate = AsyncMock(side_effect=_evaluate)

    async def _wait_for_selector(sel: str, **kw):
        pass
    page.wait_for_selector = AsyncMock(side_effect=_wait_for_selector)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.add_init_script = AsyncMock(return_value=None)

    return page


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# stealth.py
# ---------------------------------------------------------------------------

class TestStealth(unittest.TestCase):

    def test_random_user_agent_returns_string(self):
        ua = random_user_agent()
        self.assertIsInstance(ua, str)
        self.assertIn("Mozilla", ua)

    def test_random_user_agent_varies(self):
        agents = {random_user_agent() for _ in range(50)}
        # 50回試して少なくとも2種類は出る
        self.assertGreater(len(agents), 1)

    def test_random_viewport_structure(self):
        vp = random_viewport()
        self.assertIn("width", vp)
        self.assertIn("height", vp)
        self.assertGreater(vp["width"], 0)
        self.assertGreater(vp["height"], 0)

    def test_random_wait_ms_in_range(self):
        for _ in range(100):
            w = random_wait_ms(500, 1000)
            self.assertGreaterEqual(w, 500)
            self.assertLessEqual(w, 1000)

    def test_stealth_context_options_keys(self):
        opts = stealth_context_options()
        self.assertIn("user_agent", opts)
        self.assertIn("viewport", opts)
        self.assertIn("extra_http_headers", opts)
        self.assertIn("Accept-Language", opts["extra_http_headers"])

    def test_launch_args_contains_automation_flag(self):
        self.assertIn("--disable-blink-features=AutomationControlled", LAUNCH_ARGS)

    def test_stealth_script_removes_webdriver(self):
        self.assertIn("webdriver", STEALTH_INIT_SCRIPT)
        self.assertIn("undefined", STEALTH_INIT_SCRIPT)

    def test_stealth_script_mocks_chrome(self):
        self.assertIn("window.chrome", STEALTH_INIT_SCRIPT)

    def test_stealth_script_mocks_plugins(self):
        self.assertIn("plugins", STEALTH_INIT_SCRIPT)


# ---------------------------------------------------------------------------
# Strategy routing
# ---------------------------------------------------------------------------

class TestStrategyRoutingExtended(unittest.TestCase):

    def setUp(self):
        self.s = PriceScraper()

    def _assert_strategy(self, url: str, expected_cls):
        st = self.s.get_strategy(url)
        self.assertIsInstance(st, expected_cls, f"URL {url} should use {expected_cls.__name__}")

    def test_farfetch(self):
        self._assert_strategy("https://www.farfetch.com/shopping/women/gucci/item-1.aspx", FARFETCHStrategy)

    def test_matchesfashion(self):
        self._assert_strategy("https://www.matchesfashion.com/products/item", MATCHESFASHIONStrategy)

    def test_mytheresa(self):
        self._assert_strategy("https://www.mytheresa.com/en-us/women/item.html", MYTHERESAStrategy)

    def test_selfridges(self):
        self._assert_strategy("https://www.selfridges.com/GB/en/cat/product", SELFRIDGESStrategy)

    def test_saks(self):
        self._assert_strategy("https://www.saksfifthavenue.com/product/gucci-bag.html", SAKSStrategy)

    def test_harrods(self):
        self._assert_strategy("https://www.harrods.com/en-gb/shopping/gucci-bag", HARRODSStrategy)

    def test_luisaviaroma(self):
        self._assert_strategy("https://www.luisaviaroma.com/en-us/shop/item", LUISAVIAROMAStrategy)

    def test_giglio(self):
        self._assert_strategy("https://www.giglio.com/en/item.html", GIGLIOStrategy)

    def test_biffi(self):
        self._assert_strategy("https://www.biffi.com/en/item.html", BIFFIStrategy)

    def test_yoox(self):
        self._assert_strategy("https://www.yoox.com/us/item/12345678", YOOXStrategy)

    def test_theoutnet(self):
        self._assert_strategy("https://www.theoutnet.com/en-us/shop/product/item", THEOUTNETStrategy)

    def test_netaporter(self):
        self._assert_strategy("https://www.net-a-porter.com/en-us/shop/product/celine/item", NETAPORTERStrategy)

    def test_mrporter(self):
        self._assert_strategy("https://www.mrporter.com/en-us/shop/product/jil-sander/item", MRPORTERStrategy)

    def test_twentyfours(self):
        self._assert_strategy("https://www.24s.com/en-us/celine-bag-item", TWENTYFOURSStrategy)

    def test_neimanmarcus(self):
        self._assert_strategy("https://www.neimanmarcus.com/p/balenciaga-item", NEIMANMARCUSStrategy)

    def test_harveynichols(self):
        self._assert_strategy("https://www.harveynichols.com/int/brand/celine/item", HARVEYNICHOLSStrategy)


# ---------------------------------------------------------------------------
# 各 Strategy のモックページテスト
# ---------------------------------------------------------------------------

def _make_strategy_tests(strategy_cls, domain_url: str, price_selector: str, price_text: str):
    """各 Strategy に共通するテストケースを動的生成するファクトリー。"""

    class _Tests(unittest.TestCase):

        def setUp(self):
            self.strategy = strategy_cls()

        def test_domain(self):
            self.assertIsInstance(self.strategy.domain, str)
            self.assertTrue(len(self.strategy.domain) > 0)

        def test_price_via_selector(self):
            page = _make_page(
                selectors={price_selector: price_text},
                body_text="add to bag",
            )
            result = _run(self.strategy.extract(page))
            self.assertEqual(result.get("price"), price_text)

        def test_price_via_json_ld(self):
            page = _make_page(
                body_text="add to bag",
                js_results={"application/ld+json": "USD500"},
            )
            result = _run(self.strategy.extract(page))
            self.assertEqual(result.get("price"), "USD500")

        def test_stock_in_stock_via_text(self):
            page = _make_page(body_text=f"Price: {price_text} add to bag")
            result = _run(self.strategy.extract(page))
            self.assertEqual(result["stock_status"], "in_stock")

        def test_stock_out_of_stock_via_text(self):
            page = _make_page(body_text="Sold out")
            result = _run(self.strategy.extract(page))
            self.assertEqual(result["stock_status"], "out_of_stock")

        def test_stock_unknown_when_ambiguous(self):
            page = _make_page(body_text="Product description here.")
            result = _run(self.strategy.extract(page))
            self.assertEqual(result["stock_status"], "unknown")

        def test_no_price_when_nothing_matches(self):
            page = _make_page(body_text="add to bag")
            result = _run(self.strategy.extract(page))
            self.assertNotIn("price", result)

    _Tests.__name__ = f"Test{strategy_cls.__name__.replace('Strategy', '')}"
    _Tests.__qualname__ = _Tests.__name__
    return _Tests


# 各サイトのテストクラスを動的生成
TestFARFETCH = _make_strategy_tests(
    FARFETCHStrategy, "farfetch.com",
    "[data-tstid='pd-price']", "$1,250",
)
TestMATCHESFASHION = _make_strategy_tests(
    MATCHESFASHIONStrategy, "matchesfashion.com",
    "[data-testid='product-price']", "£895",
)
TestMYTHERESA = _make_strategy_tests(
    MYTHERESAStrategy, "mytheresa.com",
    "[class*='pricing__prices']", "€ 1.250,00",
)
TestSELFRIDGES = _make_strategy_tests(
    SELFRIDGESStrategy, "selfridges.com",
    "[class*='ProductPrice']", "£1,050",
)
TestSAKS = _make_strategy_tests(
    SAKSStrategy, "saksfifthavenue.com",
    "[data-testid='product-price']", "$2,350",
)
TestHARRODS = _make_strategy_tests(
    HARRODSStrategy, "harrods.com",
    "[class*='product__price']", "£3,200",
)
TestLUISAVIAROMA = _make_strategy_tests(
    LUISAVIAROMAStrategy, "luisaviaroma.com",
    "[class*='ProductPrice']", "€ 950",
)
TestGIGLIO = _make_strategy_tests(
    GIGLIOStrategy, "giglio.com",
    "[class*='PriceBox-module__price']", "€760",
)
TestBIFFI = _make_strategy_tests(
    BIFFIStrategy, "biffi.com",
    "[class*='price-final']", "€580",
)
TestYOOX = _make_strategy_tests(
    YOOXStrategy, "yoox.com",
    "[class*='d-price']", "€195",
)
TestTHEOUTNET = _make_strategy_tests(
    THEOUTNETStrategy, "theoutnet.com",
    "[data-testid='product-price']", "£320",
)
TestNETAPORTER = _make_strategy_tests(
    NETAPORTERStrategy, "net-a-porter.com",
    "[data-testid='product-price']", "£2,150",
)
TestMRPORTER = _make_strategy_tests(
    MRPORTERStrategy, "mrporter.com",
    "[data-testid='product-price']", "£890",
)
TestTWENTYFOURS = _make_strategy_tests(
    TWENTYFOURSStrategy, "24s.com",
    "[class*='ProductPrice']", "€1,450",
)
TestNEIMANMARCUS = _make_strategy_tests(
    NEIMANMARCUSStrategy, "neimanmarcus.com",
    "[class*='product-price']", "$2,650",
)
TestHARVEYNICHOLS = _make_strategy_tests(
    HARVEYNICHOLSStrategy, "harveynichols.com",
    "[class*='product__price']", "£1,890",
)


# ---------------------------------------------------------------------------
# イタリア語在庫テキスト（GIGLIO / BIFFI）
# ---------------------------------------------------------------------------

class TestItalianStockText(unittest.TestCase):

    def test_giglio_esaurito(self):
        page = _make_page(body_text="Esaurito")
        result = _run(GIGLIOStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_biffi_non_disponibile(self):
        page = _make_page(body_text="Non disponibile")
        result = _run(BIFFIStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_giglio_aggiungi_al_carrello(self):
        page = _make_page(body_text="€760 aggiungi al carrello")
        result = _run(GIGLIOStrategy().extract(page))
        self.assertEqual(result["stock_status"], "in_stock")


# ---------------------------------------------------------------------------
# THE OUTNET ウィッシュリスト専用セレクター（在庫切れ）
# ---------------------------------------------------------------------------

class TestTHEOUTNETWishlist(unittest.TestCase):

    def test_wishlist_only_returns_out_of_stock(self):
        page = _make_page(
            selectors={"[data-testid='add-to-wishlist-only']": "Add to Wish List"},
            body_text="£320",
        )
        result = _run(THEOUTNETStrategy().extract(page))
        self.assertEqual(result["stock_status"], "out_of_stock")


# ---------------------------------------------------------------------------
# エンジン stealth 統合テスト（ブラウザ起動なし）
# ---------------------------------------------------------------------------

class TestEngineStealthEnabled(unittest.IsolatedAsyncioTestCase):

    async def test_stealth_context_options_used_when_enabled(self):
        """use_stealth=True のとき _scrape_with_browser に stealth UA が渡る。"""
        from unittest.mock import patch
        from lib.scraper.models import ScrapedResult
        import lib.scraper.engine as eng

        captured = {}

        async def _fake_new_context(**kwargs):
            captured.update(kwargs)
            ctx = MagicMock()
            ctx.close = AsyncMock()
            ctx.route = AsyncMock()
            page = _make_page(body_text="add to bag")
            page.goto = AsyncMock()
            ctx.new_page = AsyncMock(return_value=page)
            return ctx

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_pw():
            fake_browser = MagicMock()
            fake_browser.close = AsyncMock()
            fake_browser.new_context = AsyncMock(side_effect=_fake_new_context)
            pw = MagicMock()
            pw.chromium.launch = AsyncMock(return_value=fake_browser)
            yield pw

        scraper = PriceScraper(use_stealth=True, max_retries=1, extra_wait_ms=0)

        with patch.object(eng, "async_playwright", new=_fake_pw):
            await scraper.scrape_async("https://www.farfetch.com/shopping/item/1")

        # stealth context options が使われていることを確認
        self.assertIn("user_agent", captured)
        self.assertIn("viewport", captured)
        self.assertIn("extra_http_headers", captured)

    async def test_non_stealth_uses_fixed_ua(self):
        """use_stealth=False のとき固定 UA が使われる。"""
        from unittest.mock import patch
        import lib.scraper.engine as eng

        captured = {}

        async def _fake_new_context(**kwargs):
            captured.update(kwargs)
            ctx = MagicMock()
            ctx.close = AsyncMock()
            ctx.route = AsyncMock()
            page = _make_page(body_text="add to bag")
            page.goto = AsyncMock()
            ctx.new_page = AsyncMock(return_value=page)
            return ctx

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_pw():
            fake_browser = MagicMock()
            fake_browser.close = AsyncMock()
            fake_browser.new_context = AsyncMock(side_effect=_fake_new_context)
            pw = MagicMock()
            pw.chromium.launch = AsyncMock(return_value=fake_browser)
            yield pw

        scraper = PriceScraper(
            use_stealth=False,
            user_agent="TestUA/1.0",
            max_retries=1,
            extra_wait_ms=0,
        )

        with patch.object(eng, "async_playwright", new=_fake_pw):
            await scraper.scrape_async("https://www.farfetch.com/shopping/item/1")

        self.assertEqual(captured.get("user_agent"), "TestUA/1.0")


# ---------------------------------------------------------------------------
# 統合テスト（実URL — SCRAPER_INTEGRATION_TEST=1 で有効化）
# ---------------------------------------------------------------------------

INTEGRATION = os.getenv("SCRAPER_INTEGRATION_TEST", "").lower() in ("1", "true", "yes")

# テスト対象URLリスト（各サイトの実在する商品ページ）
INTEGRATION_TEST_URLS: list[dict] = [
    # --- 定番 ---
    {
        "site": "FARFETCH",
        "url": "https://www.farfetch.com/shopping/women/gucci-horsebit-1955-shoulder-bag-item-18025673.aspx",
        "expected_currency": "USD",
    },
    {
        "site": "MATCHESFASHION",
        "url": "https://www.matchesfashion.com/products/Bottega-Veneta-Intrecciato-leather-coin-purse-1482302",
        "expected_currency": "GBP",
    },
    {
        "site": "MYTHERESA",
        "url": "https://www.mytheresa.com/en-us/women/handbags/shoulder-bags/mini-jo-nappa-leather-shoulder-bag-gucci-p00892014.html",
        "expected_currency": "USD",
    },
    # --- デパート ---
    {
        "site": "SELFRIDGES",
        "url": "https://www.selfridges.com/GB/en/cat/gucci-gg-marmont-mini-top-handle-bag_R04006826/",
        "expected_currency": "GBP",
    },
    {
        "site": "SAKS",
        "url": "https://www.saksfifthavenue.com/product/gucci-gg-marmont-small-shoulder-bag-0400015543271.html",
        "expected_currency": "USD",
    },
    {
        "site": "HARRODS",
        "url": "https://www.harrods.com/en-gb/shopping/gucci-gg-marmont-small-shoulder-bag-16830799",
        "expected_currency": "GBP",
    },
    # --- 欧州セレクト ---
    {
        "site": "LUISAVIAROMA",
        "url": "https://www.luisaviaroma.com/en-us/shop/women/bags/shoulder-bags/gucci/72I-Z6V014",
        "expected_currency": "USD",
    },
    {
        "site": "GIGLIO",
        "url": "https://www.giglio.com/en/gucci-gg-marmont-bag-GUCMINI0000GUC.html",
        "expected_currency": "EUR",
    },
    {
        "site": "BIFFI",
        "url": "https://www.biffi.com/en/gucci/gg-marmont-mini-top-handle-bag",
        "expected_currency": "EUR",
    },
    # --- アウトレット ---
    {
        "site": "YOOX",
        "url": "https://www.yoox.com/us/45627000IU/item",
        "expected_currency": "USD",
    },
    {
        "site": "THE OUTNET",
        "url": "https://www.theoutnet.com/en-us/shop/product/gucci/bags/shoulder-bags/gg-marmont-small-leather-shoulder-bag/10741660776355148",
        "expected_currency": "USD",
    },
    # --- YNAP グループ ---
    {
        "site": "NET-A-PORTER",
        "url": "https://www.net-a-porter.com/en-us/shop/product/celine/bags/tote-bags/medium-cabas-leather-tote/1647597310916060",
        "expected_currency": "USD",
    },
    {
        "site": "MR PORTER",
        "url": "https://www.mrporter.com/en-us/shop/product/maison-margiela/clothing/t-shirts/printed-cotton-jersey-t-shirt/1647597310864148",
        "expected_currency": "USD",
    },
    # --- LVMH グループ ---
    {
        "site": "24S",
        "url": "https://www.24s.com/en-us/celine-small-cabas-tote-bag_CESS24BAG001",
        "expected_currency": "USD",
    },
    # --- 米国デパート ---
    {
        "site": "NEIMAN MARCUS",
        "url": "https://www.neimanmarcus.com/p/balenciaga-hourglass-xs-top-handle-bag-prod250560126",
        "expected_currency": "USD",
    },
    # --- 英国デパート ---
    {
        "site": "HARVEY NICHOLS",
        "url": "https://www.harveynichols.com/int/brand/celine/4200066-mini-16-bag-in-grained-calfskin/p4628827/",
        "expected_currency": "GBP",
    },
]


@unittest.skipUnless(INTEGRATION, "SCRAPER_INTEGRATION_TEST=1 を設定すると実行されます")
class IntegrationTests(unittest.TestCase):
    """実際のURLに対するスクレイピング統合テスト。

    実行方法:
        SCRAPER_INTEGRATION_TEST=1 python3 -m pytest test_new_strategies.py::IntegrationTests -v -s
    """

    def setUp(self):
        self.scraper = PriceScraper(headless=True, max_retries=1, use_stealth=True)

    def _assert_result(self, result, site: str, expected_currency: str | None = None):
        print(f"\n  [{site}] → {result}")
        self.assertIsNotNone(result, f"{site}: result is None")
        # クラッシュしないことを最低条件とし、取得できた場合はより詳細に検証
        if result.success:
            if result.price is not None:
                self.assertGreater(result.price, 0, f"{site}: price <= 0")
            if expected_currency and result.currency:
                self.assertEqual(result.currency, expected_currency,
                                 f"{site}: currency mismatch")
        self.assertIn(result.stock_status, ("in_stock", "out_of_stock", "unknown"),
                      f"{site}: invalid stock_status")

    def test_all_sites(self):
        for item in INTEGRATION_TEST_URLS:
            with self.subTest(site=item["site"]):
                result = self.scraper.scrape(item["url"])
                self._assert_result(result, item["site"], item.get("expected_currency"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
