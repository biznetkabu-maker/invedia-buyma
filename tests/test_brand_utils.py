"""brand_utils モジュールのテスト。"""

from __future__ import annotations

from lib.brand_utils import (
    brand_slug,
    is_marketplace_brand_noise,
    normalize_brand_name,
    resolve_merchandise_brand,
    url_matches_brand,
)


class TestNormalizeBrandName:
    def test_simple_brand(self):
        assert normalize_brand_name("PRADA") == "PRADA"

    def test_decorated_brand(self):
        assert normalize_brand_name("♪直営アウトレット♪PRADA") == "PRADA"

    def test_bracket_brand(self):
        assert normalize_brand_name("【PRADA】Re-Nylon") == "PRADA"

    def test_japanese_brand(self):
        assert normalize_brand_name("プラダ☆キルティング") == "PRADA"

    def test_sale_tag_ignored(self):
        assert normalize_brand_name("【VIPセール】GUCCI") == "GUCCI"

    def test_empty(self):
        assert normalize_brand_name("") == ""


class TestBrandSlug:
    def test_normal(self):
        assert brand_slug("PRADA") == "prada"

    def test_multi_word(self):
        slug = brand_slug("SAINT LAURENT")
        assert "laurent" in slug


class TestIsMarketplaceBrandNoise:
    def test_buyma(self):
        assert is_marketplace_brand_noise("BUYMA") is True

    def test_normal_brand(self):
        assert is_marketplace_brand_noise("PRADA") is False


class TestResolveMerchandiseBrand:
    def test_from_bracket(self):
        assert resolve_merchandise_brand("【GUCCI】バッグ") == "GUCCI"

    def test_from_japanese(self):
        assert resolve_merchandise_brand("プラダ トートバッグ") == "PRADA"

    def test_empty(self):
        assert resolve_merchandise_brand("") == ""

    def test_skip_buyma(self):
        assert resolve_merchandise_brand("BUYMA", "PRADA") == "PRADA"


class TestUrlMatchesBrand:
    def test_match(self):
        assert url_matches_brand("PRADA", "https://www.prada.com/product") is True

    def test_no_match(self):
        assert url_matches_brand("PRADA", "https://www.gucci.com/product") is False

    def test_short_brand_always_matches(self):
        assert url_matches_brand("AB", "https://example.com") is True
