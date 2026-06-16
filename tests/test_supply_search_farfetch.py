"""supply_search/farfetch.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search.farfetch import (
    merge_search_hits,
    parse_farfetch_search_html,
    rank_farfetch_catalog_items,
)

_JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "Product",
      "name": "small Saffiano leather wallet",
      "offers": {
        "@type": "Offer",
        "url": "/jp/shopping/women/prada-small-saffiano-leather-wallet-item-36404881.aspx"
      }
    },
    {
      "@type": "Product",
      "name": "Prada Bonnie レザーハンドバッグ M",
      "offers": {
        "@type": "Offer",
        "url": "/jp/shopping/women/prada-prada-bonnie-m-item-32967501.aspx"
      }
    },
    {
      "@type": "Product",
      "name": "Prada PR A14S サングラス",
      "offers": {
        "@type": "Offer",
        "url": "/jp/shopping/women/prada-eyewear-prada-pr-a14s-item-23298064.aspx"
      }
    }
  ]
}
</script>
</head><body></body></html>
"""

_APOLLO_SNIPPET = (
    'ProductCatalogItem:23298064\\":{\\"__typename\\":\\"ProductCatalogItem\\",'
    '\\"shortDescription\\":\\"small Saffiano leather wallet\\",'
    '\\"resourceIdentifier\\":{\\"path\\":\\"/shopping/women/'
    'prada-small-saffiano-leather-wallet-item-36404881.aspx\\"}}'
)


class TestFarfetchSearchParse(unittest.TestCase):
    def test_parse_json_ld_itemlist(self) -> None:
        items = parse_farfetch_search_html(_JSON_LD_HTML)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(i.source == "json_ld_itemlist" for i in items))
        self.assertIn("wallet", items[0].name.lower())
        self.assertIn("item-36404881", items[0].url)

    def test_wallet_ranks_above_bonnie_for_wallet_query(self) -> None:
        items = parse_farfetch_search_html(_JSON_LD_HTML)
        ranked = rank_farfetch_catalog_items(
            items,
            style_id="1ML506",
            product_name="PRADA 1ML506 wallet",
            brand="PRADA",
        )
        self.assertGreaterEqual(len(ranked), 2)
        top_name = ranked[0][0].name.lower()
        self.assertIn("wallet", top_name)
        self.assertNotIn("bonnie", top_name)

    def test_shoulder_bag_query_ranks_bonnie_above_wallet(self) -> None:
        items = parse_farfetch_search_html(_JSON_LD_HTML)
        ranked = rank_farfetch_catalog_items(
            items,
            style_id="1BH026",
            product_name="PRADA 1BH026 shoulder bag",
            brand="PRADA",
        )
        top_name = ranked[0][0].name.lower()
        self.assertIn("bonnie", top_name)

    def test_apollo_fallback_when_no_json_ld(self) -> None:
        items = parse_farfetch_search_html(_APOLLO_SNIPPET)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0].source, "apollo_catalog")

    def test_merge_rejects_invalid_farfetch_slug(self) -> None:
        from lib.supply_search.farfetch import FarfetchCatalogItem

        bad = FarfetchCatalogItem(
            name="broken",
            path="/shopping/women/prada--item-30953.aspx",
            source="json_ld_itemlist",
        )
        urls = merge_search_hits(
            [bad],
            [],
            style_id="1ML506",
            product_name="wallet",
            brand="PRADA",
        )
        self.assertEqual(urls, [])


if __name__ == "__main__":
    unittest.main()
