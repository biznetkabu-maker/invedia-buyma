"""json_walk モジュールのテスト。"""

from __future__ import annotations

import json

from lib.supply_search.json_walk import (
    SearchHit,
    collect_hits_from_json_text,
    normalize_style_token,
    style_id_matches,
    walk_json_for_hits,
)


class TestNormalizeStyleToken:
    def test_basic(self):
        assert normalize_style_token("AB-123") == "AB123"

    def test_empty(self):
        assert normalize_style_token("") == ""

    def test_lowercase(self):
        assert normalize_style_token("abc") == "ABC"


class TestStyleIdMatches:
    def test_exact(self):
        assert style_id_matches("AB123", "AB-123") is True

    def test_prefix(self):
        assert style_id_matches("AB12345", "AB12345-001") is True

    def test_short_no_match(self):
        assert style_id_matches("AB1", "AB12345") is False

    def test_empty(self):
        assert style_id_matches("", "AB123") is False


class TestWalkJsonForHits:
    def test_finds_product_url(self):
        data = {
            "url": "https://www.farfetch.com/en/shopping/women/test-item-12345678.aspx",
            "name": "Test Product",
            "sku": "SKU123",
        }
        hits: list[SearchHit] = []
        walk_json_for_hits(data, "SKU123", hits)
        assert len(hits) == 1
        assert hits[0].url.endswith(".aspx")

    def test_nested_data(self):
        data = {
            "products": [
                {
                    "url": "https://www.farfetch.com/en/shopping/men/bag-item-99999999.aspx",
                    "name": "Bag",
                }
            ]
        }
        hits: list[SearchHit] = []
        walk_json_for_hits(data, "", hits)
        assert len(hits) == 1

    def test_no_product_url_skipped(self):
        data = {"url": "https://example.com/search", "name": "search"}
        hits: list[SearchHit] = []
        walk_json_for_hits(data, "", hits)
        assert len(hits) == 0

    def test_depth_limit(self):
        nested: dict = {"url": "https://www.farfetch.com/shopping/women/x-item-12345.aspx"}
        for _ in range(20):
            nested = {"child": nested}
        hits: list[SearchHit] = []
        walk_json_for_hits(nested, "", hits)
        assert len(hits) == 0


class TestCollectHitsFromJsonText:
    def test_valid_json(self):
        data = {
            "items": [
                {
                    "url": "/en-jp/shopping/women/prada-bag-item-12345678.aspx",
                    "name": "Prada Bag",
                    "sku": "1BA274",
                }
            ]
        }
        hits = collect_hits_from_json_text(
            json.dumps(data), "1BA274", source="test",
        )
        assert len(hits) >= 1

    def test_invalid_json(self):
        hits = collect_hits_from_json_text("not json", "123", source="test")
        assert hits == []
