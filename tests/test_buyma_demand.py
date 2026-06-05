"""buyma_demand モジュールのユニットテスト。"""

import asyncio
import unittest
from unittest.mock import patch

from lib.buyma_demand import (
    BUYMADemandScraper,
    BUYMADemandSignal,
    _extract_all_jpy_prices,
    _extract_jpy_price,
    _extract_number,
    _extract_number_with_keyword,
)


class TestBUYMADemandSignal(unittest.TestCase):
    def _make(self, **kwargs) -> BUYMADemandSignal:
        defaults = dict(
            brand="CELINE",
            product_name="トリオバッグ",
            favorites_count=0,
            listing_count=0,
            min_price=None,
            max_price=None,
            order_count=0,
            has_cart=False,
            search_url="https://www.buyma.com/buy/search/?q=CELINE",
        )
        defaults.update(kwargs)
        return BUYMADemandSignal(**defaults)

    def test_demand_level_high_favorites(self):
        s = self._make(favorites_count=25)
        self.assertEqual(s.demand_level, "高")

    def test_demand_level_high_orders(self):
        s = self._make(order_count=5)
        self.assertEqual(s.demand_level, "高")

    def test_demand_level_medium(self):
        s = self._make(favorites_count=15)
        self.assertEqual(s.demand_level, "中")

    def test_demand_level_low(self):
        s = self._make(listing_count=5, favorites_count=3)
        self.assertEqual(s.demand_level, "低")

    def test_demand_level_no_data(self):
        s = self._make(listing_count=0)
        self.assertEqual(s.demand_level, "データなし")

    def test_competition_level_low(self):
        s = self._make(listing_count=2)
        self.assertEqual(s.competition_level, "少（参入しやすい）")

    def test_competition_level_medium(self):
        s = self._make(listing_count=7)
        self.assertEqual(s.competition_level, "中（標準的）")

    def test_competition_level_high(self):
        s = self._make(listing_count=15)
        self.assertEqual(s.competition_level, "多（価格競争になりやすい）")

    def test_summary_contains_brand(self):
        s = self._make(favorites_count=10, listing_count=5)
        text = s.summary()
        self.assertIn("CELINE", text)
        self.assertIn("トリオバッグ", text)

    def test_summary_with_price_range(self):
        s = self._make(min_price=190000, max_price=250000)
        text = s.summary()
        self.assertIn("190,000", text)
        self.assertIn("250,000", text)

    def test_to_evaluation_kwargs(self):
        s = self._make(favorites_count=20, has_cart=True)
        kw = s.to_evaluation_kwargs()
        self.assertEqual(kw["favorites_count"], 20)
        self.assertTrue(kw["has_cart_addition"])


class TestExtractUtils(unittest.TestCase):
    def test_extract_number(self):
        self.assertEqual(_extract_number("お気に入り 1,234 件"), 1234)
        self.assertIsNone(_extract_number("なし"))

    def test_extract_number_fullwidth_comma(self):
        self.assertEqual(_extract_number("12，345"), 12345)

    def test_extract_number_with_keyword(self):
        self.assertEqual(
            _extract_number_with_keyword("お気に入り 42", ["お気に入り"]), 42
        )
        self.assertIsNone(
            _extract_number_with_keyword("価格 1000円", ["お気に入り"])
        )

    def test_extract_jpy_price(self):
        self.assertEqual(_extract_jpy_price("¥198,000"), 198000)
        self.assertEqual(_extract_jpy_price("250,000 円"), 250000)
        self.assertIsNone(_extract_jpy_price("価格未定"))

    def test_extract_all_jpy_prices_filters_range(self):
        prices = _extract_all_jpy_prices("¥500 ¥198,000 ¥99,999,999")
        # 500 は下限未満、99,999,999 は上限超過で除外
        self.assertEqual(prices, [198000])


# ── 非同期解析メソッドのテスト（fake page を使用） ────────────────────────


class _FakeEl:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _FakePage:
    def __init__(self, *, single=None, cards=None, body=""):
        self._single = single
        self._cards = cards or []
        self._body = body

    async def query_selector(self, sel):
        return _FakeEl(self._single) if self._single is not None else None

    async def query_selector_all(self, sel):
        return [_FakeEl(t) for t in self._cards]

    async def inner_text(self, sel):
        return self._body


class TestAsyncExtract(unittest.TestCase):
    def setUp(self):
        self.scraper = BUYMADemandScraper()

    def test_extract_listing_count_from_selector(self):
        page = _FakePage(single="検索結果 256件")
        n = asyncio.run(self.scraper._extract_listing_count(page))
        self.assertEqual(n, 256)

    def test_extract_listing_count_counts_cards(self):
        page = _FakePage(single=None, cards=["a", "b", "c"])
        n = asyncio.run(self.scraper._extract_listing_count(page))
        self.assertEqual(n, 3)

    def test_extract_item_cards(self):
        gap = " " * 20  # キーワード近接抽出が他の数値を拾わないよう十分離す
        cards = [
            f"お気に入り25{gap}¥198,000",
            f"注文3{gap}¥210,000",
        ]
        page = _FakePage(cards=cards)
        favs, prices, orders = asyncio.run(self.scraper._extract_item_cards(page))
        self.assertIn(25, favs)
        self.assertIn(198000, prices)
        self.assertIn(3, orders)

    def test_extract_demand_builds_signal(self):
        gap = " " * 20
        cards = [f"注文5{gap}お気に入り25{gap}¥198,000"]
        page = _FakePage(single="100件", cards=cards)
        signal = asyncio.run(
            self.scraper._extract_demand(page, "CELINE", "トリオ", "https://e.com")
        )
        self.assertEqual(signal.favorites_count, 25)
        self.assertEqual(signal.order_count, 5)
        self.assertEqual(signal.min_price, 198000)
        self.assertTrue(signal.has_cart)

    def test_extract_demand_body_fallback(self):
        # カードから取れず body フォールバックを使う
        page = _FakePage(single=None, cards=[], body="CELINE お気に入り 12 ¥230,000")
        signal = asyncio.run(
            self.scraper._extract_demand(page, "CELINE", "トリオ", "https://e.com")
        )
        self.assertEqual(signal.favorites_count, 12)
        self.assertEqual(signal.min_price, 230000)


class TestGetDemandSync(unittest.TestCase):
    def test_get_demand_wraps_async(self):
        scraper = BUYMADemandScraper()
        sentinel = object()

        async def _fake(brand, name, timeout_ms):
            return sentinel

        with patch.object(scraper, "get_demand_async", side_effect=_fake):
            result = scraper.get_demand("CELINE", "トリオ")
        self.assertIs(result, sentinel)


if __name__ == "__main__":
    unittest.main()
