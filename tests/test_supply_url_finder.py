"""supply_url_finder.py のユニットテスト（Playwright 不要）。"""

from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path

from lib.supply_url_finder import (
    SupplyUrlCandidate,
    _auto_site_defs,
    _candidate_from_product_url,
    _default_timeout_ms,
    _domain,
    _is_product_url,
    _merge_batch_results,
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
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)  # noqa: SIM115
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


class TestDomain(unittest.TestCase):
    def test_strips_www_and_lowercases(self) -> None:
        self.assertEqual(_domain("WWW.Ssense.com"), "ssense.com")

    def test_no_www(self) -> None:
        self.assertEqual(_domain("mytheresa.com"), "mytheresa.com")


class TestIsProductUrl(unittest.TestCase):
    def test_ssense_product_true(self) -> None:
        self.assertTrue(
            _is_product_url(
                "https://www.ssense.com/en-us/women/product/celine/bag/123",
                "ssense.com",
            )
        )

    def test_excluded_path_false(self) -> None:
        self.assertFalse(
            _is_product_url("https://www.ssense.com/en-us/search?q=bag", "ssense.com")
        )

    def test_double_dash_false(self) -> None:
        self.assertFalse(
            _is_product_url("https://www.ssense.com/women/product/a--b", "ssense.com")
        )

    def test_unknown_domain_falls_back_to_product_path(self) -> None:
        self.assertTrue(_is_product_url("https://x.com/product/abc", "x.com"))
        self.assertFalse(_is_product_url("https://x.com/category/abc", "x.com"))


class TestDefaultTimeout(unittest.TestCase):
    def test_default_value(self) -> None:
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SUPPLY_SEARCH_TIMEOUT_MS", None)
            self.assertEqual(_default_timeout_ms(), 45000)

    def test_env_override(self) -> None:
        with unittest.mock.patch.dict(
            "os.environ", {"SUPPLY_SEARCH_TIMEOUT_MS": "12000"}
        ):
            self.assertEqual(_default_timeout_ms(), 12000)

    def test_invalid_env_falls_back(self) -> None:
        with unittest.mock.patch.dict(
            "os.environ", {"SUPPLY_SEARCH_TIMEOUT_MS": "abc"}
        ):
            self.assertEqual(_default_timeout_ms(), 45000)


class TestAutoSiteDefs(unittest.TestCase):
    def test_returns_only_auto_sites(self) -> None:
        names = {s.name for s in _auto_site_defs()}
        self.assertIn("SSENSE", names)
        self.assertTrue(names)


class TestCandidateFromProductUrl(unittest.TestCase):
    def test_maps_domain_to_site_name(self) -> None:
        cand = _candidate_from_product_url(
            "https://www.ssense.com/en-us/women/product/x/y/1"
        )
        self.assertEqual(cand.domain, "ssense.com")
        self.assertEqual(cand.product_url.split("?")[0].split("/")[2], "www.ssense.com")
        self.assertTrue(cand.site_name)


class TestMergeBatchResults(unittest.TestCase):
    def _cand(self, domain: str, url: str) -> SupplyUrlCandidate:
        return SupplyUrlCandidate(
            site_name=domain, domain=domain, search_url="", product_url=url
        )

    def test_dedups_by_domain_and_returns_false_without_style_match(self) -> None:
        batch = [
            self._cand("ssense.com", "https://ssense.com/a"),
            self._cand("ssense.com", "https://ssense.com/b"),
        ]
        all_found: list[SupplyUrlCandidate] = []
        seen: set[str] = set()
        with unittest.mock.patch(
            "lib.supply_url_finder.url_is_valid_supply_candidate", return_value=True
        ), unittest.mock.patch(
            "lib.supply_url_finder.url_matches_style_hint", return_value=False
        ):
            stop = _merge_batch_results(
                batch, all_found, seen,
                norm_brand="CELINE", style_id_hint="", rank_context="bag", lines=[],
            )
        self.assertFalse(stop)
        self.assertEqual(len(all_found), 1)

    def test_style_match_inserts_front_and_returns_true(self) -> None:
        existing = self._cand("mytheresa.com", "https://mytheresa.com/x")
        all_found = [existing]
        seen = {"mytheresa.com"}
        batch = [self._cand("ssense.com", "https://ssense.com/match")]
        with unittest.mock.patch(
            "lib.supply_url_finder.url_is_valid_supply_candidate", return_value=True
        ), unittest.mock.patch(
            "lib.supply_url_finder.url_matches_style_hint", return_value=True
        ):
            stop = _merge_batch_results(
                batch, all_found, seen,
                norm_brand="CELINE", style_id_hint="ABC123", rank_context="bag",
                lines=[],
            )
        self.assertTrue(stop)
        self.assertEqual(all_found[0].domain, "ssense.com")

    def test_logs_when_all_excluded(self) -> None:
        batch = [self._cand("ssense.com", "https://ssense.com/a")]
        lines: list[str] = []
        with unittest.mock.patch(
            "lib.supply_url_finder.url_is_valid_supply_candidate", return_value=False
        ):
            _merge_batch_results(
                batch, [], set(),
                norm_brand="CELINE", style_id_hint="", rank_context="bag", lines=lines,
            )
        self.assertTrue(any("除外" in ln for ln in lines))


class TestFunnelPresetUrls(unittest.TestCase):
    def test_preset_urls_skip_search(self) -> None:
        with unittest.mock.patch(
            "lib.supply_url_finder.url_is_valid_supply_candidate", return_value=True
        ):
            out = discover_supply_urls_funnel(
                "CELINE",
                "bag",
                preset_urls=[
                    "https://www.ssense.com/en-us/women/product/celine/bag/1",
                ],
                use_site_search=True,
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].domain, "ssense.com")


if __name__ == "__main__":
    unittest.main()
