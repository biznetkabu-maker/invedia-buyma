"""buyma_demand モジュールのユニットテスト。"""

import unittest

from lib.buyma_demand import BUYMADemandSignal


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


if __name__ == "__main__":
    unittest.main()
