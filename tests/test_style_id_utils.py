"""style_id_utils のユニットテスト。"""

import unittest

from lib.style_id_utils import (
    normalize_style_id,
    scraped_matches_buyma_style,
    style_ids_equivalent,
)


class TestNormalizeStyleId(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_style_id("abc-123"), "ABC-123")

    def test_slashes(self):
        self.assertEqual(normalize_style_id("1BA 274/ZO6"), "1BA-274-ZO6")

    def test_dots(self):
        self.assertEqual(normalize_style_id("2VG.024.ZO6"), "2VG-024-ZO6")

    def test_none(self):
        self.assertEqual(normalize_style_id(None), "")

    def test_empty(self):
        self.assertEqual(normalize_style_id(""), "")

    def test_strips_hyphens(self):
        self.assertEqual(normalize_style_id("-ABC-"), "ABC")

    def test_double_hyphens(self):
        self.assertEqual(normalize_style_id("A--B"), "A-B")


class TestStyleIdsEquivalent(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(style_ids_equivalent("1BA274", "1BA274"))

    def test_case_insensitive(self):
        self.assertTrue(style_ids_equivalent("abc123", "ABC123"))

    def test_suffix_match(self):
        self.assertTrue(style_ids_equivalent("1BA-274-ZO6", "274-ZO6"))

    def test_no_match(self):
        self.assertFalse(style_ids_equivalent("ABC123", "XYZ789"))

    def test_empty_both(self):
        self.assertFalse(style_ids_equivalent("", ""))

    def test_one_empty(self):
        self.assertFalse(style_ids_equivalent("ABC123", ""))

    def test_short_suffix_no_match(self):
        self.assertFalse(style_ids_equivalent("ABCDEF", "EF"))


class TestScrapedMatchesBuymaStyle(unittest.TestCase):
    def test_both_none(self):
        self.assertTrue(scraped_matches_buyma_style(None, None))

    def test_one_none(self):
        self.assertFalse(scraped_matches_buyma_style("ABC", None))

    def test_match(self):
        self.assertTrue(scraped_matches_buyma_style("1BA-274", "1BA 274"))

    def test_no_match(self):
        self.assertFalse(scraped_matches_buyma_style("ABC", "XYZ"))


if __name__ == "__main__":
    unittest.main()
