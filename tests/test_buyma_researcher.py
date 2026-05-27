"""buyma_researcher モジュールのユニットテスト。"""

import unittest

from lib.buyma_researcher import ResearchCandidate, _build_search_urls


class TestBuildSearchUrls(unittest.TestCase):
    def test_returns_multiple_urls(self):
        urls = _build_search_urls("CELINE", "トリオバッグ")
        self.assertTrue(len(urls) >= 5)

    def test_urls_contain_query(self):
        urls = _build_search_urls("GUCCI", "Marmont")
        for url in urls:
            self.assertIn("GUCCI", url)
            self.assertIn("Marmont", url)

    def test_urls_are_valid(self):
        urls = _build_search_urls("PRADA", "ガレリア")
        for url in urls:
            self.assertTrue(url.startswith("https://"))


class TestResearchCandidate(unittest.TestCase):
    def _make(self, **kwargs) -> ResearchCandidate:
        defaults = dict(
            brand="CELINE",
            product_name="トリオバッグ スモール",
            category="バッグ",
            favorites_count=25,
            listing_count=8,
            buyma_url="https://www.buyma.com/item/12345/",
        )
        defaults.update(kwargs)
        return ResearchCandidate(**defaults)

    def test_is_recommended_brand_true(self):
        c = self._make(brand="CELINE")
        self.assertTrue(c.is_recommended_brand)

    def test_is_recommended_brand_false(self):
        c = self._make(brand="UNKNOWN_BRAND_XYZ")
        self.assertFalse(c.is_recommended_brand)

    def test_is_stable_category_true(self):
        c = self._make(product_name="レザーバッグ", category="バッグ")
        self.assertTrue(c.is_stable_category)

    def test_str_contains_brand(self):
        c = self._make()
        text = str(c)
        self.assertIn("CELINE", text)
        self.assertIn("25件", text)

    def test_candidate_source_urls_default_empty(self):
        c = self._make()
        self.assertEqual(c.candidate_source_urls, [])


if __name__ == "__main__":
    unittest.main()
