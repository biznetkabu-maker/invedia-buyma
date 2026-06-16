"""buyma_style_id.py / style_id_utils / multi_source の型番突合まわりのテスト。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lib.buyma_style_id import (
    _is_plausible_code,
    extract_primary_style_id_from_buyma_html,
    extract_style_id_candidates_from_html,
    fetch_buyma_style_id_from_url_sync,
    is_buyma_item_url,
)
from lib.multi_source import style_id_consistent_with_buyma
from lib.scraper.models import ScrapedResult
from lib.style_id_utils import normalize_style_id, scraped_matches_buyma_style, style_ids_equivalent


class TestBUYMAStyleIdHtml(unittest.TestCase):

    def test_label_colon_japanese(self):
        html = "<div>この商品の型番：ARC58-BLK</div>"
        self.assertEqual(
            extract_primary_style_id_from_buyma_html(html),
            "ARC58-BLK",
        )

    def test_style_english_label(self):
        html = '<span>Style ID: 502460-AAA12</span>'
        self.assertEqual(
            extract_primary_style_id_from_buyma_html(html),
            "502460-AAA12",
        )

    def test_data_model_attr(self):
        html = '<meta data-model="GH-4422K" />'
        c = extract_style_id_candidates_from_html(html)
        self.assertIn("GH-4422K", c)

    def test_json_snippet_in_html(self):
        html = r'<script>var x = {"sku": "M-77-X"};</script>'
        self.assertEqual(
            extract_primary_style_id_from_buyma_html(html),
            "M-77-X",
        )


class TestIsBUYMAItemUrl(unittest.TestCase):

    def test_items_path(self):
        self.assertTrue(
            is_buyma_item_url("https://www.buyma.com/items/12345678/")
        )

    def test_search_not_detail(self):
        self.assertFalse(
            is_buyma_item_url("https://www.buyma.com/buy/search/?keyword=CELINE")
        )

    def test_item_id_in_path(self):
        self.assertTrue(is_buyma_item_url("https://buyma.com/item/99887766"))

    def test_non_buyma_url(self):
        self.assertFalse(is_buyma_item_url("https://example.com/items/1"))

    def test_empty_url(self):
        self.assertFalse(is_buyma_item_url(""))


class TestPlausibleCode(unittest.TestCase):
    def test_too_short(self):
        self.assertFalse(_is_plausible_code("AB1"))

    def test_too_long(self):
        self.assertFalse(_is_plausible_code("A" * 49))

    def test_long_all_digits_rejected(self):
        self.assertFalse(_is_plausible_code("123456789012345"))

    def test_url_rejected(self):
        self.assertFalse(_is_plausible_code("http://x.com/abc"))

    def test_valid_code(self):
        self.assertTrue(_is_plausible_code("ARC58-BLK"))


class TestExtractEdgeCases(unittest.TestCase):
    def test_empty_html_returns_empty(self):
        self.assertEqual(extract_style_id_candidates_from_html(""), [])

    def test_primary_none_when_no_match(self):
        self.assertIsNone(extract_primary_style_id_from_buyma_html("<div>なし</div>"))

    def test_excluded_normalized_filtered(self):
        # SIZE / COLOR は除外語
        html = "<div>型番：SIZE</div><div>品番：COLOR</div>"
        self.assertEqual(extract_style_id_candidates_from_html(html), [])


class TestFetchSyncWrapper(unittest.TestCase):
    def test_sync_wrapper_returns_async_result(self):
        async def _fake(url, **kwargs):
            return "ABC-123"

        with patch("lib.buyma_style_id.fetch_buyma_style_id_from_url", side_effect=_fake):
            result = fetch_buyma_style_id_from_url_sync("https://buyma.com/items/1/")
        self.assertEqual(result, "ABC-123")


class TestStyleIdUtils(unittest.TestCase):

    def test_normalize(self):
        self.assertEqual(normalize_style_id(" A-bc/12 "), "A-BC-12")

    def test_equivalent_suffix(self):
        self.assertTrue(style_ids_equivalent("PREFIX-XY12", "XY12"))

    def test_scraped_matches_buyma(self):
        self.assertTrue(
            scraped_matches_buyma_style("arc58-blk", "ARC58/BLK"),
        )
        self.assertFalse(
            scraped_matches_buyma_style("OTHER", "ARC58"),
        )


class TestStyleIdConsistentMultiSource(unittest.TestCase):

    def test_no_buyma_id_skips_check(self):
        s = ScrapedResult(
            url="https://example.com/x",
            price=1.0,
            currency="USD",
            stock_status="in_stock",
            raw_price="$1",
            style_id=None,
            scraped_at=datetime.now(timezone.utc),
            success=True,
        )
        self.assertTrue(style_id_consistent_with_buyma(s, ""))

    def test_mismatch_when_both_present(self):
        s = ScrapedResult(
            url="https://example.com/x",
            price=1.0,
            currency="USD",
            stock_status="in_stock",
            raw_price="$1",
            style_id="AAA",
            scraped_at=datetime.now(timezone.utc),
            success=True,
        )
        self.assertFalse(style_id_consistent_with_buyma(s, "BBB"))


if __name__ == "__main__":
    unittest.main()
