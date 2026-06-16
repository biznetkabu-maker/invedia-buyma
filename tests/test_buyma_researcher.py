"""buyma_researcher モジュールのユニットテスト。"""

import asyncio
import unittest
from unittest.mock import AsyncMock

from lib.buyma_researcher import (
    BUYMAResearcher,
    ResearchCandidate,
    _build_search_urls,
    _parse_int,
)


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


class TestParseInt(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_parse_int("お気に入り 23件"), 23)

    def test_comma(self):
        self.assertEqual(_parse_int("1,234件"), 1234)

    def test_fullwidth_comma(self):
        self.assertEqual(_parse_int("12，345"), 12345)

    def test_empty(self):
        self.assertEqual(_parse_int(""), 0)

    def test_no_digits(self):
        self.assertEqual(_parse_int("なし"), 0)


class TestFilter(unittest.TestCase):
    def _c(self, **kw) -> ResearchCandidate:
        d = dict(
            brand="CELINE", product_name="レザーバッグ", category="バッグ",
            favorites_count=25, listing_count=5,
            buyma_url="https://www.buyma.com/item/1/",
        )
        d.update(kw)
        return ResearchCandidate(**d)

    def test_filters_below_min_favorites(self):
        out = BUYMAResearcher._filter(
            [self._c(favorites_count=5)], min_favorites=10,
            recommended_only=False, stable_category_only=False,
        )
        self.assertEqual(out, [])

    def test_recommended_only(self):
        out = BUYMAResearcher._filter(
            [self._c(brand="NONAME_XYZ")], min_favorites=10,
            recommended_only=True, stable_category_only=False,
        )
        self.assertEqual(out, [])

    def test_stable_category_exception_for_popular_recommended(self):
        # 推奨ブランド+お気に入り20以上なら定番カテゴリ外でも残る
        out = BUYMAResearcher._filter(
            [self._c(product_name="香水", category="フレグランス", favorites_count=30)],
            min_favorites=10, recommended_only=True, stable_category_only=True,
        )
        self.assertEqual(len(out), 1)

    def test_passes_valid_candidate(self):
        out = BUYMAResearcher._filter(
            [self._c()], min_favorites=10,
            recommended_only=True, stable_category_only=True,
        )
        self.assertEqual(len(out), 1)


class TestExtractText(unittest.TestCase):
    def test_returns_first_match(self):
        child = AsyncMock()
        child.inner_text = AsyncMock(return_value="  CELINE  ")
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=child)
        text = asyncio.run(BUYMAResearcher._extract_text(el, ["[class*='brand']"]))
        self.assertEqual(text, "CELINE")

    def test_returns_empty_when_none(self):
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        text = asyncio.run(BUYMAResearcher._extract_text(el, ["a", "b"]))
        self.assertEqual(text, "")


class TestParseItemElement(unittest.TestCase):
    def _researcher(self) -> BUYMAResearcher:
        return BUYMAResearcher(headless=True)

    def test_empty_text_returns_none(self):
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="   ")
        result = asyncio.run(self._researcher()._parse_item_element(el, "https://x"))
        self.assertIsNone(result)

    def test_missing_brand_returns_none(self):
        r = self._researcher()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="some text")
        el.query_selector = AsyncMock(return_value=None)
        r._extract_text = AsyncMock(return_value="")  # type: ignore[method-assign]
        result = asyncio.run(r._parse_item_element(el, "https://x"))
        self.assertIsNone(result)

    def test_builds_candidate(self):
        r = self._researcher()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="full text")
        link = AsyncMock()
        link.get_attribute = AsyncMock(return_value="/item/999/")
        el.query_selector = AsyncMock(return_value=link)
        texts = iter(["CELINE", "トリオバッグ", "30件", "5件"])
        r._extract_text = AsyncMock(side_effect=lambda *a, **k: next(texts))  # type: ignore[method-assign]
        result = asyncio.run(r._parse_item_element(el, "https://www.buyma.com/x"))
        self.assertIsNotNone(result)
        self.assertEqual(result.brand, "CELINE")
        self.assertEqual(result.favorites_count, 30)
        self.assertEqual(result.buyma_url, "https://www.buyma.com/item/999/")


if __name__ == "__main__":
    unittest.main()
