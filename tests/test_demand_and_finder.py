"""
buyma_demand.py / product_finder.py のユニットテスト（再構築後）。

- TestBUYMADemandSignal  : データモデルのプロパティ
- TestExtractHelpers     : _extract_number / _extract_jpy_price / _extract_all_jpy_prices
- TestBUYMADemandAsync   : モックページでの需要抽出
- TestProductFinderSites : SiteDefinition の基本チェック
- TestBuildSearchURLs    : 検索URL生成
- TestSiteByDomain       : ドメインマップ
"""

import asyncio
import unittest
from unittest.mock import patch

from lib.buyma_demand import (
    BUYMADemandSignal,
    BUYMADemandScraper,
    _extract_number,
    _extract_number_with_keyword,
    _extract_jpy_price,
    _extract_all_jpy_prices,
)
from lib.product_finder import (
    build_search_urls,
    ALL_SITES,
    SITE_BY_DOMAIN,
    site_name_from_url,
    SiteDefinition,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# BUYMADemandSignal
# ---------------------------------------------------------------------------

class TestBUYMADemandSignal(unittest.TestCase):

    def _make(self, favorites=0, listing=0, orders=0, has_cart=False, min_price=None, max_price=None):
        return BUYMADemandSignal(
            brand="CELINE", product_name="トリオバッグ",
            favorites_count=favorites, listing_count=listing,
            min_price=min_price, max_price=max_price,
            order_count=orders, has_cart=has_cart,
            search_url="https://buyma.com/buy/search/?keyword=CELINE",
        )

    def test_demand_level_high_by_favorites(self):
        self.assertEqual(self._make(favorites=20).demand_level, "高")

    def test_demand_level_high_by_orders(self):
        self.assertEqual(self._make(orders=5).demand_level, "高")

    def test_demand_level_medium_by_favorites(self):
        self.assertEqual(self._make(favorites=12).demand_level, "中")

    def test_demand_level_low(self):
        self.assertEqual(self._make(favorites=3, listing=5).demand_level, "低")

    def test_demand_level_no_data(self):
        self.assertEqual(self._make().demand_level, "データなし")

    def test_competition_none(self):
        self.assertEqual(self._make().competition_level, "データなし")

    def test_competition_low(self):
        self.assertEqual(self._make(listing=2).competition_level, "少（参入しやすい）")

    def test_competition_medium(self):
        self.assertEqual(self._make(listing=7).competition_level, "中（標準的）")

    def test_competition_high(self):
        self.assertEqual(self._make(listing=15).competition_level, "多（価格競争になりやすい）")

    def test_to_evaluation_kwargs(self):
        s = self._make(favorites=25, has_cart=True)
        kw = s.to_evaluation_kwargs()
        self.assertEqual(kw["favorites_count"], 25)
        self.assertTrue(kw["has_cart_addition"])

    def test_summary_contains_key_info(self):
        s = self._make(favorites=15, listing=5, orders=2, min_price=190000, max_price=250000)
        summary = s.summary()
        self.assertIn("15", summary)
        self.assertIn("5", summary)
        self.assertIn("需要", summary)
        self.assertIn("190,000", summary)


# ---------------------------------------------------------------------------
# extract helpers
# ---------------------------------------------------------------------------

class TestExtractHelpers(unittest.TestCase):

    def test_extract_number_basic(self):
        self.assertEqual(_extract_number("23件"), 23)

    def test_extract_number_comma(self):
        self.assertEqual(_extract_number("1,234"), 1234)

    def test_extract_number_none(self):
        self.assertIsNone(_extract_number(""))

    def test_extract_with_keyword_found(self):
        self.assertEqual(_extract_number_with_keyword("お気に入り 45件", ["お気に入り"]), 45)

    def test_extract_with_keyword_not_found(self):
        self.assertIsNone(_extract_number_with_keyword("商品説明", ["お気に入り"]))

    def test_extract_jpy_yen_mark(self):
        self.assertEqual(_extract_jpy_price("¥195,000"), 195000)

    def test_extract_jpy_kanji(self):
        self.assertEqual(_extract_jpy_price("195000円"), 195000)

    def test_extract_jpy_too_small(self):
        self.assertIsNone(_extract_jpy_price("¥500"))

    def test_extract_jpy_no_price(self):
        self.assertIsNone(_extract_jpy_price("商品説明"))

    def test_extract_all_jpy_prices_multiple(self):
        text = "¥198,000 ¥210,000 ¥245,000"
        prices = _extract_all_jpy_prices(text)
        self.assertEqual(len(prices), 3)
        self.assertIn(198000, prices)
        self.assertIn(245000, prices)

    def test_extract_all_jpy_prices_dedup(self):
        text = "¥198,000 ¥198,000"
        prices = _extract_all_jpy_prices(text)
        self.assertEqual(len(prices), 1)

    def test_extract_all_jpy_prices_empty(self):
        self.assertEqual(_extract_all_jpy_prices("no price here"), [])


# ---------------------------------------------------------------------------
# BUYMADemandScraper (失敗時の挙動)
# ---------------------------------------------------------------------------

class TestBUYMADemandScraper(unittest.IsolatedAsyncioTestCase):

    async def test_returns_zero_signal_on_playwright_error(self):
        scraper = BUYMADemandScraper(headless=True)
        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.side_effect = RuntimeError("接続失敗")
            signal = await scraper.get_demand_async("CELINE", "トリオバッグ")

        self.assertEqual(signal.brand, "CELINE")
        self.assertEqual(signal.favorites_count, 0)
        self.assertEqual(signal.listing_count, 0)
        self.assertIsNone(signal.min_price)


# ---------------------------------------------------------------------------
# ProductFinder — サイト定義
# ---------------------------------------------------------------------------

class TestProductFinderSites(unittest.TestCase):

    def test_site_count_at_least_15(self):
        self.assertGreaterEqual(len(ALL_SITES), 15)

    def test_no_outlet_sites(self):
        names = {s.name for s in ALL_SITES}
        self.assertNotIn("YOOX", names)
        self.assertNotIn("THE OUTNET", names)

    def test_all_categories_present(self):
        cats = {s.category for s in ALL_SITES}
        self.assertIn("グローバルセレクト", cats)
        self.assertIn("百貨店", cats)
        self.assertIn("欧州セレクト", cats)

    def test_department_stores_included(self):
        names = {s.name for s in ALL_SITES}
        for expected in ["HARRODS", "SELFRIDGES", "SAKS FIFTH AVENUE",
                         "HARVEY NICHOLS", "NEIMAN MARCUS"]:
            with self.subTest(site=expected):
                self.assertIn(expected, names)

    def test_global_selects_included(self):
        names = {s.name for s in ALL_SITES}
        for expected in ["SSENSE", "NET-A-PORTER", "MR PORTER",
                         "MYTHERESA", "FARFETCH", "24S（LVMHグループ）",
                         "LUISAVIAROMA", "MATCHESFASHION"]:
            with self.subTest(site=expected):
                self.assertIn(expected, names)

    def test_all_sites_have_valid_search_template(self):
        for site in ALL_SITES:
            with self.subTest(site=site.name):
                self.assertIn("{q}", site.search_url_template)
                self.assertIn("https://", site.search_url_template)

    def test_all_sites_have_valid_currency(self):
        for site in ALL_SITES:
            with self.subTest(site=site.name):
                self.assertIn(site.currency, ("USD", "EUR", "GBP"))


# ---------------------------------------------------------------------------
# build_search_urls
# ---------------------------------------------------------------------------

class TestBuildSearchURLs(unittest.TestCase):

    def test_returns_all_categories(self):
        result = build_search_urls("CELINE", "トリオバッグ スモール")
        self.assertIn("グローバルセレクト", result.by_category)
        self.assertIn("百貨店", result.by_category)
        self.assertIn("欧州セレクト", result.by_category)

    def test_search_url_contains_brand(self):
        result = build_search_urls("Balenciaga", "Triple S")
        for items in result.by_category.values():
            for _, url in items:
                self.assertIn("http", url)

    def test_display_returns_non_empty_string(self):
        result = build_search_urls("CELINE", "バッグ")
        display = result.display()
        self.assertGreater(len(display), 100)
        self.assertIn("CELINE", display)

    def test_site_filter_works(self):
        result = build_search_urls("CELINE", "バッグ", sites=["SSENSE", "HARRODS"])
        all_names = [name for items in result.by_category.values() for name, _ in items]
        self.assertIn("SSENSE", all_names)
        self.assertIn("HARRODS", all_names)
        self.assertEqual(len(all_names), 2)


# ---------------------------------------------------------------------------
# SITE_BY_DOMAIN / site_name_from_url
# ---------------------------------------------------------------------------

class TestSiteByDomain(unittest.TestCase):

    def test_ssense_domain_in_map(self):
        self.assertIn("ssense.com", SITE_BY_DOMAIN)

    def test_harrods_domain_in_map(self):
        self.assertIn("harrods.com", SITE_BY_DOMAIN)

    def test_site_name_from_url_ssense(self):
        name = site_name_from_url("https://www.ssense.com/en-us/women/product/celine/bag/12345678")
        self.assertEqual(name, "SSENSE")

    def test_site_name_from_url_unknown(self):
        name = site_name_from_url("https://unknown-site.com/product/123")
        self.assertIn("unknown-site.com", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
