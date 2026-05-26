"""supply_url_finder.py のユニットテスト（Playwright 不要）。"""

from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path

from lib.supply_url_finder import (
    build_style_search_urls,
    discover_supply_urls_funnel,
    filter_product_urls,
)


class TestFilterProductUrls(unittest.TestCase):

    def test_ssense_product_only(self) -> None:
        links = [
            "https://www.ssense.com/en-us/women/product/abc/123",
            "https://www.ssense.com/en-us/search?q=celine",
            "https://www.ssense.com/en-us/cart",
        ]
        out = filter_product_urls(links, "ssense.com", limit=2)
        self.assertEqual(len(out), 1)
        self.assertIn("/product/", out[0])

    def test_farfetch_item_aspx(self) -> None:
        links = [
            "https://www.farfetch.com/shopping/women/prada-mini-pouch-item-12345.aspx",
            "https://www.farfetch.com/jp/shopping/women/prada--item-30953.aspx",
            "https://www.farfetch.com/shopping/women/search.aspx?q=x",
        ]
        out = filter_product_urls(links, "farfetch.com")
        self.assertEqual(len(out), 1)
        self.assertIn("item-", out[0])
        self.assertNotIn("--", out[0])


class TestBuildStyleSearchUrls(unittest.TestCase):

    def test_style_id_replaces_query(self) -> None:
        pairs = build_style_search_urls("CELINE", "bag", style_id="ARC58-BLK", search_query="ARC58-BLK")
        self.assertGreater(len(pairs), 0)
        for _site, url in pairs:
            self.assertIn("ARC58", url)

    def test_without_style_id_uses_brand_name(self) -> None:
        pairs = build_style_search_urls("CELINE", "トリオバッグ", search_query="CELINE トリオ")
        self.assertGreater(len(pairs), 0)
        joined = " ".join(u for _, u in pairs)
        self.assertTrue("CELINE" in joined or "celine" in joined.lower())




class TestDiscoverFunnelCache(unittest.TestCase):

    def test_cache_hit_skips_site_search(self) -> None:
        import os
        import tempfile
        import lib.supply_url_cache as cache_mod
        from lib.supply_url_finder import discover_supply_urls_funnel

        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        orig = cache_mod._DEFAULT_CACHE_FILE
        cache_mod._DEFAULT_CACHE_FILE = Path(tmp.name)
        try:
            os.environ["SUPPLY_URL_CACHE"] = "1"
            cache_mod.store_supply_urls("PRADA", "1ML506", [url], match_grade="A")
            log: list[str] = []
            with unittest.mock.patch(
                "lib.supply_site_search.discover_urls_by_style_id",
                side_effect=AssertionError("site search should be skipped"),
            ):
                result = discover_supply_urls_funnel(
                    "PRADA",
                    "wallet",
                    "1ML506",
                    log_lines=log,
                )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].product_url, url)
            self.assertTrue(any("キャッシュヒット" in ln for ln in log))
        finally:
            cache_mod._DEFAULT_CACHE_FILE = orig
            os.unlink(tmp.name)
            os.environ.pop("SUPPLY_URL_CACHE", None)


class TestOfficialEnglishNamePassthrough(unittest.TestCase):

    def test_async_accepts_official_english_name_kwarg(self) -> None:
        import inspect

        from lib.supply_url_finder import discover_supply_urls_async

        params = inspect.signature(discover_supply_urls_async).parameters
        self.assertIn("official_english_name", params)
        self.assertEqual(params["official_english_name"].default, "")

    def test_funnel_playwright_path_forwards_official_english_name(self) -> None:
        with unittest.mock.patch(
            "lib.supply_url_finder.discover_supply_urls_sync",
            return_value=[],
        ) as mock_sync:
            discover_supply_urls_funnel(
                "PRADA",
                "コットンキャンバス スモール ハンドバッグ",
                "1BG464",
                official_english_name=(
                    "Prada Jardiniere small cotton canvas bag"
                ),
                use_site_search=False,
            )

        kwargs = mock_sync.call_args.kwargs
        self.assertEqual(
            kwargs.get("official_english_name"),
            "Prada Jardiniere small cotton canvas bag",
        )


if __name__ == "__main__":
    unittest.main()
