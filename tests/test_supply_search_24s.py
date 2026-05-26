"""supply_search/twentyfoursevens.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search.twentyfoursevens import (
    build_24s_search_url,
    is_access_denied_html,
    is_valid_24s_product_url,
    merge_search_hits,
    parse_24s_search_html,
    rank_24s_catalog_items,
)

_JSON_LD_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Saffiano leather wallet",
  "brand": {"@type": "Brand", "name": "Prada"},
  "sku": "1ML506XYZ",
  "offers": {
    "@type": "Offer",
    "url": "https://www.24s.com/en-us/prada-saffiano-leather-wallet_1ML506XYZ"
  }
}
</script>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Bonnie shoulder bag",
  "brand": {"@type": "Brand", "name": "Prada"},
  "sku": "OTHER123",
  "offers": {
    "@type": "Offer",
    "url": "https://www.24s.com/en-us/prada-bonnie-shoulder-bag_OTHER123"
  }
}
</script>
</body></html>
"""

_ACCESS_DENIED_HTML = """
<html><body><title>Access Denied</title>
Reference #18.errors.edgesuite.net</body></html>
"""


class Test24sSearchParse(unittest.TestCase):
    def test_build_search_url(self) -> None:
        url = build_24s_search_url("PRADA wallet")
        self.assertIn("/en-us/search?q=", url)

    def test_valid_product_url_with_sku_suffix(self) -> None:
        url = "https://www.24s.com/en-us/celine-small-cabas-tote-bag_CESS24BAG001"
        self.assertTrue(is_valid_24s_product_url(url))

    def test_parse_json_ld_products(self) -> None:
        items = parse_24s_search_html(_JSON_LD_HTML, brand="PRADA")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].sku, "1ML506XYZ")

    def test_access_denied_returns_empty(self) -> None:
        self.assertTrue(is_access_denied_html(_ACCESS_DENIED_HTML))
        self.assertEqual(parse_24s_search_html(_ACCESS_DENIED_HTML), [])

    def test_wallet_ranks_first(self) -> None:
        items = parse_24s_search_html(_JSON_LD_HTML, brand="PRADA")
        ranked = rank_24s_catalog_items(
            items,
            style_id="1ML506",
            product_name="PRADA 1ML506 wallet",
            brand="PRADA",
        )
        self.assertIn("wallet", ranked[0][0].name.lower())

    def test_reject_search_path(self) -> None:
        self.assertFalse(
            is_valid_24s_product_url("https://www.24s.com/en-us/search?q=prada")
        )

    def test_merge_respects_brand_filter(self) -> None:
        from lib.supply_search.twentyfoursevens import TwentyFourSCatalogItem

        celine = TwentyFourSCatalogItem(
            name="Tote",
            brand="Celine",
            path="/en-us/celine-small-cabas-tote-bag_CESS24BAG001",
            sku="CESS24BAG001",
            source="json_ld_product",
        )
        urls = merge_search_hits(
            [celine],
            [],
            style_id="1ML506",
            product_name="wallet",
            brand="PRADA",
        )
        self.assertEqual(urls, [])


if __name__ == "__main__":
    unittest.main()
