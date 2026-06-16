"""scraper/engine.py のユニットテスト。"""

import unittest

from lib.scraper.engine import PriceScraper


class TestPriceScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = PriceScraper()

    def test_get_strategy_ssense(self):
        strategy = self.scraper.get_strategy("https://www.ssense.com/en-us/women/product/123")
        self.assertEqual(strategy.domain, "ssense.com")

    def test_get_strategy_farfetch(self):
        strategy = self.scraper.get_strategy("https://www.farfetch.com/shopping/women/123.aspx")
        self.assertEqual(strategy.domain, "farfetch.com")

    def test_get_strategy_unknown_returns_generic(self):
        strategy = self.scraper.get_strategy("https://www.example.com/product/123")
        self.assertEqual(strategy.domain, "__generic__")

    def test_is_heavy_site_true(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.selfridges.com/GB/en/product/123"))
        self.assertTrue(self.scraper.is_heavy_site("https://www.farfetch.com/shopping/123"))

    def test_is_heavy_site_false(self):
        self.assertFalse(self.scraper.is_heavy_site("https://www.ssense.com/en-us/product/123"))
        self.assertFalse(self.scraper.is_heavy_site("https://www.tessabit.com/product/123"))

    def test_navigation_wait_chain_normal(self):
        chain = self.scraper.navigation_wait_chain("https://www.ssense.com/en-us/product/123")
        self.assertEqual(chain, ["networkidle"])

    def test_navigation_wait_chain_farfetch(self):
        chain = self.scraper.navigation_wait_chain("https://www.farfetch.com/shopping/123")
        self.assertEqual(chain, ["domcontentloaded", "commit"])

    def test_navigation_wait_chain_heavy(self):
        chain = self.scraper.navigation_wait_chain("https://www.selfridges.com/GB/en/product/123")
        self.assertEqual(chain, ["domcontentloaded"])

    def test_register_custom_strategy(self):
        from lib.scraper.base import ScraperStrategy
        from lib.scraper.models import ScrapedResult

        class CustomStrategy(ScraperStrategy):
            domain = "custom.example.com"

            async def extract(self, page, url):
                return ScrapedResult(url=url, success=False)

        self.scraper.register(CustomStrategy())
        strategy = self.scraper.get_strategy("https://custom.example.com/product")
        self.assertEqual(strategy.domain, "custom.example.com")

    def test_all_default_strategies_registered(self):
        self.assertGreaterEqual(len(self.scraper._strategies), 17)


if __name__ == "__main__":
    unittest.main()
