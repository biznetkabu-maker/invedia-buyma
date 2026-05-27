"""product_finder モジュールのユニットテスト。"""

import unittest

from lib.product_finder import (
    ALL_SITES,
    SITE_BY_DOMAIN,
    build_search_urls,
    get_all_candidate_urls,
    site_name_from_url,
)


class TestBuildSearchUrls(unittest.TestCase):
    def test_returns_all_categories(self):
        result = build_search_urls("CELINE", "トリオバッグ")
        self.assertIn("グローバルセレクト", result.by_category)
        self.assertIn("百貨店", result.by_category)
        self.assertIn("欧州セレクト", result.by_category)

    def test_query_encoded_in_urls(self):
        result = build_search_urls("CELINE", "Trio Bag")
        for items in result.by_category.values():
            for _, url in items:
                self.assertIn("CELINE", url)

    def test_filter_by_sites(self):
        result = build_search_urls("GUCCI", "マーモント", sites=["SSENSE"])
        total = sum(len(v) for v in result.by_category.values())
        self.assertEqual(total, 1)

    def test_display_contains_brand(self):
        result = build_search_urls("PRADA", "ガレリア")
        text = result.display()
        self.assertIn("PRADA", text)
        self.assertIn("ガレリア", text)


class TestGetAllCandidateUrls(unittest.TestCase):
    def test_returns_all_site_urls(self):
        urls = get_all_candidate_urls("LV", "ネヴァーフル")
        self.assertEqual(len(urls), len(ALL_SITES))
        for url in urls:
            self.assertTrue(url.startswith("http"))


class TestSiteNameFromUrl(unittest.TestCase):
    def test_known_site(self):
        self.assertEqual(
            site_name_from_url("https://www.ssense.com/en-us/women/product/celine/123"),
            "SSENSE",
        )

    def test_unknown_site(self):
        result = site_name_from_url("https://www.example.com/product/123")
        self.assertEqual(result, "www.example.com")


class TestSiteDefinitions(unittest.TestCase):
    def test_all_sites_have_template(self):
        for site in ALL_SITES:
            self.assertIn("{q}", site.search_url_template)

    def test_site_by_domain_complete(self):
        for site in ALL_SITES:
            self.assertIn(site.domain, SITE_BY_DOMAIN)


if __name__ == "__main__":
    unittest.main()
