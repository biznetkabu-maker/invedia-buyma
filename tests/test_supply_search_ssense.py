"""supply_search/ssense.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search.ssense import (
    build_ssense_search_url,
    is_no_results_html,
    is_valid_ssense_product_url,
    merge_search_hits,
    parse_ssense_search_html,
    rank_ssense_catalog_items,
)

_JSON_LD_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Black Saffiano Wallet",
  "brand": {"@type": "Brand", "name": "Prada"},
  "sku": "1ML506ABC",
  "offers": {
    "@type": "Offer",
    "url": "https://www.ssense.com/en-us/women/product/prada/black-saffiano-wallet/12345678"
  }
}
</script>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Bonnie Shoulder Bag",
  "brand": {"@type": "Brand", "name": "Prada"},
  "sku": "OTHER123",
  "offers": {
    "@type": "Offer",
    "url": "https://www.ssense.com/en-us/women/product/prada/bonnie-shoulder-bag/87654321"
  }
}
</script>
</body></html>
"""

_NO_RESULTS_HTML = """
<html><body>
<h1>There are no WOMENSWEAR products that match 'PRADA 1ML506 WALLET' for now.</h1>
<script type="application/ld+json">
{"@type": "Product", "name": "Unrelated Bag", "brand": {"name": "Gucci"},
 "offers": {"url": "https://www.ssense.com/en-us/women/product/gucci/bag/11111111"}}
</script>
</body></html>
"""


class TestSsenseSearchParse(unittest.TestCase):
    def test_build_search_url_uses_women_path(self) -> None:
        url = build_ssense_search_url("PRADA wallet")
        self.assertIn("/en-us/women?q=", url)
        self.assertNotIn("/search?", url)

    def test_parse_json_ld_products(self) -> None:
        items = parse_ssense_search_html(_JSON_LD_HTML, brand="PRADA")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "json_ld_product")

    def test_no_results_skips_fallback_products(self) -> None:
        self.assertTrue(is_no_results_html(_NO_RESULTS_HTML))
        self.assertEqual(parse_ssense_search_html(_NO_RESULTS_HTML, brand="PRADA"), [])

    def test_style_id_in_sku_ranks_highest(self) -> None:
        items = parse_ssense_search_html(_JSON_LD_HTML, brand="PRADA")
        ranked = rank_ssense_catalog_items(
            items,
            style_id="1ML506",
            product_name="PRADA 1ML506 wallet",
            brand="PRADA",
        )
        self.assertIn("wallet", ranked[0][0].name.lower())

    def test_valid_product_url(self) -> None:
        url = (
            "https://www.ssense.com/en-us/women/product/prada-eyewear/"
            "black-prada-symbole-sunglasses/19213711"
        )
        self.assertTrue(is_valid_ssense_product_url(url))

    def test_reject_old_search_path(self) -> None:
        self.assertFalse(
            is_valid_ssense_product_url("https://www.ssense.com/en-us/search?q=prada")
        )

    def test_brand_only_query_no_category_penalty(self) -> None:
        from lib.supply_search.ssense import SsenseCatalogItem

        item = SsenseCatalogItem(
            name="Black Symbole Sunglasses",
            brand="Prada Eyewear",
            path="/en-us/women/product/prada-eyewear/black-symbole-sunglasses/19213711",
            sku="261208F005019",
            source="json_ld_product",
        )
        ranked = rank_ssense_catalog_items(
            [item],
            style_id="",
            product_name="prada",
            brand="PRADA",
        )
        self.assertGreater(ranked[0][1], 0)

    def test_merge_respects_brand_filter(self) -> None:
        from lib.supply_search.ssense import SsenseCatalogItem

        gucci = SsenseCatalogItem(
            name="Bag",
            brand="Gucci",
            path="/en-us/women/product/gucci/bag/11111111",
            sku="X",
            source="json_ld_product",
        )
        urls = merge_search_hits(
            [gucci],
            [],
            style_id="1ML506",
            product_name="wallet",
            brand="PRADA",
        )
        self.assertEqual(urls, [])


if __name__ == "__main__":
    unittest.main()
