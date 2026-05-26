"""supply_search/netaporter.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search.netaporter import (
    build_netaporter_search_url,
    is_access_denied_html,
    is_valid_netaporter_product_url,
    merge_search_hits,
    parse_netaporter_search_html,
    rank_netaporter_catalog_items,
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
    "url": "https://www.net-a-porter.com/en-us/shop/product/prada/accessories/wallets/saffiano-leather-wallet/1647597310916060"
  }
}
</script>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Bonnie shoulder bag",
  "brand": {"@type": "Brand", "name": "Prada"},
  "sku": "OTHER",
  "offers": {
    "@type": "Offer",
    "url": "https://www.net-a-porter.com/en-us/shop/product/prada/bags/shoulder-bags/bonnie-shoulder-bag/1647597310916061"
  }
}
</script>
</body></html>
"""

_ACCESS_DENIED_HTML = """
<html><body><title>Access Denied</title>
You don't have permission to access this server.
Reference #18.errors.edgesuite.net</body></html>
"""


class TestNetaporterSearchParse(unittest.TestCase):
    def test_build_search_url(self) -> None:
        url = build_netaporter_search_url("PRADA wallet")
        self.assertIn("/en-us/search?q=", url)

    def test_parse_json_ld_products(self) -> None:
        items = parse_netaporter_search_html(_JSON_LD_HTML, brand="PRADA")
        self.assertEqual(len(items), 2)

    def test_access_denied_returns_empty(self) -> None:
        self.assertTrue(is_access_denied_html(_ACCESS_DENIED_HTML))
        self.assertEqual(parse_netaporter_search_html(_ACCESS_DENIED_HTML), [])

    def test_wallet_ranks_first_for_wallet_query(self) -> None:
        items = parse_netaporter_search_html(_JSON_LD_HTML, brand="PRADA")
        ranked = rank_netaporter_catalog_items(
            items,
            style_id="1ML506",
            product_name="PRADA 1ML506 wallet",
            brand="PRADA",
        )
        self.assertIn("wallet", ranked[0][0].name.lower())

    def test_valid_multi_segment_product_url(self) -> None:
        url = (
            "https://www.net-a-porter.com/en-us/shop/product/celine/bags/tote-bags/"
            "medium-cabas-leather-tote/1647597310916060"
        )
        self.assertTrue(is_valid_netaporter_product_url(url))

    def test_merge_respects_brand_filter(self) -> None:
        from lib.supply_search.netaporter import NetaporterCatalogItem

        celine = NetaporterCatalogItem(
            name="Tote",
            brand="Celine",
            path="/en-us/shop/product/celine/bags/tote/1647597310916060",
            sku="X",
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
