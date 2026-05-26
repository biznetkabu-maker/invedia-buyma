"""
multi_source.py / buyma_researcher.py のユニットテスト。

- TestSourceCandidate   : SourceCandidate.is_available / summary
- TestBestSourceFinder  : _select_best ロジック（モックスクレイプ結果）
- TestBestSourceResult  : BestSourceResult プロパティ
- TestBUYMAResearcher   : _filter / _parse_int
- TestProductRecordCandidateURLs : sheet_manager の候補URL対応
"""

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from lib.multi_source import (
    BestSourceFinder,
    BestSourceResult,
    SourceCandidate,
)
from lib.buyma_researcher import BUYMAResearcher, ResearchCandidate, _parse_int, _build_search_urls
from lib.sheet_manager import ProductRecord, COLUMNS


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_candidate(
    url="https://ssense.com/item/1",
    price=900.0,
    currency="USD",
    stock_status="in_stock",
    profit_rate=0.18,
    profit=30000.0,
    error=None,
) -> SourceCandidate:
    return SourceCandidate(
        url=url,
        price=price,
        currency=currency,
        stock_status=stock_status,
        jpy_cost=148500.0,
        profit=profit,
        profit_rate=profit_rate,
        breakdown=None,
        error=error,
    )


# ---------------------------------------------------------------------------
# SourceCandidate
# ---------------------------------------------------------------------------

class TestSourceCandidate(unittest.TestCase):

    def test_is_available_in_stock_positive_profit(self):
        c = _make_candidate(stock_status="in_stock", profit=10000, profit_rate=0.15)
        self.assertTrue(c.is_available)

    def test_not_available_if_out_of_stock(self):
        c = _make_candidate(stock_status="out_of_stock")
        self.assertFalse(c.is_available)

    def test_not_available_if_no_price(self):
        c = _make_candidate(price=None)
        self.assertFalse(c.is_available)

    def test_not_available_if_negative_profit(self):
        c = _make_candidate(profit=-5000, profit_rate=-0.03)
        self.assertFalse(c.is_available)

    def test_summary_contains_url_and_profit(self):
        c = _make_candidate()
        s = c.summary()
        self.assertIn("ssense.com", s)
        self.assertIn("in_stock", s)


# ---------------------------------------------------------------------------
# BestSourceFinder._select_best
# ---------------------------------------------------------------------------

class TestBestSourceFinderSelectBest(unittest.TestCase):

    def test_selects_highest_profit_rate(self):
        candidates = [
            _make_candidate("https://site1.com", profit_rate=0.12, profit=20000),
            _make_candidate("https://site2.com", profit_rate=0.20, profit=35000),  # 最高
            _make_candidate("https://site3.com", profit_rate=0.15, profit=26000),
        ]
        best, reason = BestSourceFinder._select_best(candidates)
        self.assertEqual(best.url, "https://site2.com")
        self.assertIn("在庫あり", reason)

    def test_ignores_out_of_stock(self):
        candidates = [
            _make_candidate("https://cheap.com", profit_rate=0.25, profit=40000, stock_status="out_of_stock"),
            _make_candidate("https://avail.com", profit_rate=0.15, profit=26000, stock_status="in_stock"),
        ]
        best, _ = BestSourceFinder._select_best(candidates)
        self.assertEqual(best.url, "https://avail.com")

    def test_returns_none_when_all_out_of_stock(self):
        candidates = [
            _make_candidate(stock_status="out_of_stock"),
            _make_candidate(stock_status="unknown"),
        ]
        best, reason = BestSourceFinder._select_best(candidates)
        self.assertIsNone(best)
        self.assertIn("在庫ありの仕入先なし", reason)

    def test_tiebreak_by_lower_price(self):
        candidates = [
            _make_candidate("https://expensive.com", price=950.0, profit_rate=0.18, profit=30000),
            _make_candidate("https://cheap.com",     price=850.0, profit_rate=0.18, profit=30000),
        ]
        best, _ = BestSourceFinder._select_best(candidates)
        self.assertEqual(best.url, "https://cheap.com")

    def test_empty_candidates_returns_none(self):
        best, reason = BestSourceFinder._select_best([])
        self.assertIsNone(best)


# ---------------------------------------------------------------------------
# BestSourceResult
# ---------------------------------------------------------------------------

class TestBestSourceResult(unittest.TestCase):

    def test_in_stock_count(self):
        result = BestSourceResult(
            best=None,
            all_candidates=[
                _make_candidate(stock_status="in_stock"),
                _make_candidate(stock_status="in_stock"),
                _make_candidate(stock_status="out_of_stock"),
            ],
            reason="test",
        )
        self.assertEqual(result.in_stock_count, 2)

    def test_cheapest_available(self):
        c1 = _make_candidate("https://a.com", price=800, stock_status="in_stock")
        c2 = _make_candidate("https://b.com", price=900, stock_status="in_stock")
        c3 = _make_candidate("https://c.com", price=700, stock_status="out_of_stock")
        result = BestSourceResult(best=c1, all_candidates=[c1, c2, c3], reason="test")
        self.assertEqual(result.cheapest_available.price, 800)

    def test_cheapest_available_none_when_no_stock(self):
        c = _make_candidate(stock_status="out_of_stock")
        result = BestSourceResult(best=None, all_candidates=[c], reason="test")
        self.assertIsNone(result.cheapest_available)

    def test_summary_contains_key_info(self):
        best = _make_candidate()
        result = BestSourceResult(best=best, all_candidates=[best], reason="利益率最大")
        s = result.summary()
        self.assertIn("利益率最大", s)
        self.assertIn("ssense.com", s)


# ---------------------------------------------------------------------------
# find_best_async (モック)
# ---------------------------------------------------------------------------

class TestBestSourceFinderAsync(unittest.IsolatedAsyncioTestCase):

    async def test_find_best_returns_highest_profit_candidate(self):
        from lib.scraper.models import ScrapedResult

        mock_scrapes = [
            ScrapedResult(
                url="https://ssense.com/1", price=900.0, currency="USD",
                stock_status="in_stock", raw_price="$900",
                scraped_at=datetime.now(timezone.utc), success=True,
            ),
            ScrapedResult(
                url="https://nap.com/1", price=850.0, currency="USD",
                stock_status="in_stock", raw_price="$850",
                scraped_at=datetime.now(timezone.utc), success=True,
            ),
        ]

        with patch("lib.multi_source.PriceScraper") as MockScraper:
            instance = MockScraper.return_value
            instance.scrape_many_async = AsyncMock(return_value=mock_scrapes)

            finder = BestSourceFinder()
            result = await finder.find_best_async(
                candidate_urls=["https://ssense.com/1", "https://nap.com/1"],
                buyma_price=200_000,
                exchange_rate=155.0,
            )

        # $850 < $900 なので NAPの方が利益率高い
        self.assertIsNotNone(result.best)
        self.assertEqual(result.best.url, "https://nap.com/1")
        self.assertEqual(len(result.all_candidates), 2)

    async def test_find_best_with_empty_urls(self):
        finder = BestSourceFinder()
        result = await finder.find_best_async(
            candidate_urls=[], buyma_price=200_000, exchange_rate=155.0
        )
        self.assertIsNone(result.best)
        self.assertEqual(result.all_candidates, [])

    async def test_find_best_when_all_out_of_stock(self):
        from lib.scraper.models import ScrapedResult

        mock_scrapes = [
            ScrapedResult(
                url="https://ssense.com/1", price=900.0, currency="USD",
                stock_status="out_of_stock", raw_price="$900",
                scraped_at=datetime.now(timezone.utc), success=True,
            ),
        ]

        with patch("lib.multi_source.PriceScraper") as MockScraper:
            instance = MockScraper.return_value
            instance.scrape_many_async = AsyncMock(return_value=mock_scrapes)

            finder = BestSourceFinder()
            result = await finder.find_best_async(
                candidate_urls=["https://ssense.com/1"],
                buyma_price=200_000,
                exchange_rate=155.0,
            )

        self.assertIsNone(result.best)


# ---------------------------------------------------------------------------
# _build_search_urls
# ---------------------------------------------------------------------------

class TestBuildSearchUrls(unittest.TestCase):

    def test_returns_multiple_urls(self):
        urls = _build_search_urls("CELINE", "トリオバッグ スモール")
        self.assertGreater(len(urls), 3)
        for url in urls:
            self.assertIn("http", url)

    def test_urls_contain_encoded_query(self):
        urls = _build_search_urls("Saint Laurent", "envelope bag")
        # 少なくともブランド名かアイテム名が含まれる
        self.assertTrue(any("Saint" in u or "saint" in u.lower() for u in urls))




# ---------------------------------------------------------------------------
# _select_best + buyma_style_id
# ---------------------------------------------------------------------------

class TestSelectBestStyleId(unittest.TestCase):

    def test_select_best_filters_mismatched_style_id(self):
        match = _make_candidate(
            url="https://ssense.com/match",
            price=900.0,
            profit_rate=0.20,
            profit=40000.0,
        )
        match = replace(match, style_id="ARC58-BLK")
        mismatch = _make_candidate(
            url="https://nap.com/cheap",
            price=700.0,
            profit_rate=0.25,
            profit=50000.0,
        )
        mismatch = replace(mismatch, style_id="OTHER-CODE")

        best, reason = BestSourceFinder._select_best(
            [mismatch, match],
            buyma_style_id="ARC58-BLK",
        )
        self.assertIsNotNone(best)
        self.assertEqual(best.url, "https://ssense.com/match")
        self.assertIn("型番", reason)

    def test_select_best_no_match_when_all_style_mismatch(self):
        c = replace(_make_candidate(), style_id="WRONG")
        best, reason = BestSourceFinder._select_best(
            [c],
            buyma_style_id="ARC58",
        )
        self.assertIsNone(best)
        self.assertIn("型番", reason)

    def test_select_best_ignores_style_when_buyma_style_empty(self):
        cheap = _make_candidate(
            url="https://nap.com/1",
            price=700.0,
            profit_rate=0.25,
        )
        expensive = _make_candidate(
            url="https://ssense.com/1",
            price=900.0,
            profit_rate=0.15,
        )
        best, _ = BestSourceFinder._select_best(
            [expensive, cheap],
            buyma_style_id=None,
        )
        self.assertEqual(best.url, "https://nap.com/1")
# ---------------------------------------------------------------------------
# BUYMAResearcher._filter / _parse_int
# ---------------------------------------------------------------------------

class TestBUYMAResearcherFilter(unittest.TestCase):

    def _make_rc(self, brand, product, favorites, category="バッグ"):
        return ResearchCandidate(
            brand=brand, product_name=product,
            category=category, favorites_count=favorites,
            listing_count=5, buyma_url="https://buyma.com/test",
        )

    def test_filter_by_min_favorites(self):
        candidates = [
            self._make_rc("CELINE", "バッグ", 5),
            self._make_rc("CELINE", "バッグB", 15),
        ]
        result = BUYMAResearcher._filter(
            candidates, min_favorites=10,
            recommended_only=False, stable_category_only=False,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].product_name, "バッグB")

    def test_filter_recommended_brand_only(self):
        candidates = [
            self._make_rc("GUCCI", "バッグ", 20),
            self._make_rc("CELINE", "バッグ", 20),
        ]
        result = BUYMAResearcher._filter(
            candidates, min_favorites=5,
            recommended_only=True, stable_category_only=False,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].brand, "CELINE")

    def test_filter_stable_category_only(self):
        # 非推奨ブランドのサングラスは定番カテゴリ外なので除外される
        candidates = [
            self._make_rc("GUCCI", "サングラス", 20, "アクセサリー"),
            self._make_rc("GUCCI", "トリオバッグ", 20, "バッグ"),
        ]
        result = BUYMAResearcher._filter(
            candidates, min_favorites=5,
            recommended_only=False, stable_category_only=True,
        )
        self.assertEqual(len(result), 1)
        self.assertIn("バッグ", result[0].product_name)

    def test_recommended_brand_high_favorites_passes_non_stable_category(self):
        """推奨ブランド × お気に入り20件以上は定番カテゴリ外でも通す。"""
        candidates = [
            self._make_rc("Balenciaga", "サングラス", 25, "アクセサリー"),
        ]
        result = BUYMAResearcher._filter(
            candidates, min_favorites=5,
            recommended_only=False, stable_category_only=True,
        )
        self.assertEqual(len(result), 1)


class TestParseInt(unittest.TestCase):

    def test_parse_simple_number(self):
        self.assertEqual(_parse_int("23"), 23)

    def test_parse_with_text(self):
        self.assertEqual(_parse_int("お気に入り 45件"), 45)

    def test_parse_with_comma(self):
        self.assertEqual(_parse_int("1,234"), 1234)

    def test_parse_empty(self):
        self.assertEqual(_parse_int(""), 0)

    def test_parse_no_number(self):
        self.assertEqual(_parse_int("出品中"), 0)


# ---------------------------------------------------------------------------
# ProductRecord.candidate_url_list
# ---------------------------------------------------------------------------

class TestProductRecordCandidateURLs(unittest.TestCase):

    def test_empty_candidate_urls_returns_empty_list(self):
        r = ProductRecord(商品名="test", 候補URLs="")
        self.assertEqual(r.candidate_url_list(), [])

    def test_single_url(self):
        r = ProductRecord(商品名="test", 候補URLs="https://ssense.com/item/1")
        self.assertEqual(r.candidate_url_list(), ["https://ssense.com/item/1"])

    def test_multiple_urls_comma_separated(self):
        r = ProductRecord(
            商品名="test",
            候補URLs="https://ssense.com/1, https://nap.com/2, https://24s.com/3",
        )
        urls = r.candidate_url_list()
        self.assertEqual(len(urls), 3)
        self.assertIn("https://ssense.com/1", urls)
        self.assertIn("https://nap.com/2", urls)
        self.assertIn("https://24s.com/3", urls)

    def test_candidate_urls_column_exists(self):
        self.assertIn("候補URLs", COLUMNS)

    def test_from_row_backward_compatible(self):
        """既存の9列データが10列目（候補URLs）なしでも正常に読める。"""
        old_row = ["商品A", "GUCCI", "GG-001", "https://ssense.com/1", "800", "155", "195000", "出品中", "30000"]
        r = ProductRecord.from_row(old_row)
        self.assertEqual(r.商品名, "商品A")
        self.assertEqual(r.候補URLs, "")
        self.assertEqual(r.candidate_url_list(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
