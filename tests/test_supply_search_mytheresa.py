"""supply_search/mytheresa.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search.mytheresa import (
    is_bot_blocked_html,
    is_valid_mytheresa_product_url,
    merge_search_hits,
    parse_mytheresa_search_html,
    rank_mytheresa_catalog_items,
)

_JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "name": "Saffiano leather wallet",
      "url": "https://www.mytheresa.com/en-us/women/accessories/wallets/saffiano-leather-wallet-prada-p12345678.html"
    },
    {
      "@type": "ListItem",
      "position": 2,
      "name": "Bonnie leather shoulder bag",
      "url": "https://www.mytheresa.com/en-us/women/bags/shoulder-bags/bonnie-leather-shoulder-bag-prada-p87654321.html"
    }
  ]
}
</script>
</head><body></body></html>
"""

_BOT_HTML = """
<html><body>Something went wrong. Please try again. REPORT ISSUE Reference BOT: 0.123</body></html>
"""


class TestMytheresaSearchParse(unittest.TestCase):
    def test_parse_json_ld_itemlist(self) -> None:
        items = parse_mytheresa_search_html(_JSON_LD_HTML)
        self.assertEqual(len(items), 2)
        self.assertIn("wallet", items[0].name.lower())

    def test_bot_blocked_returns_empty(self) -> None:
        self.assertTrue(is_bot_blocked_html(_BOT_HTML))
        self.assertEqual(parse_mytheresa_search_html(_BOT_HTML), [])

    def test_wallet_ranks_above_shoulder_bag_for_wallet_query(self) -> None:
        items = parse_mytheresa_search_html(_JSON_LD_HTML)
        ranked = rank_mytheresa_catalog_items(
            items,
            style_id="1ML506",
            product_name="PRADA 1ML506 wallet",
            brand="PRADA",
        )
        self.assertIn("wallet", ranked[0][0].name.lower())

    def test_shoulder_bag_query_ranks_bag_item(self) -> None:
        items = parse_mytheresa_search_html(_JSON_LD_HTML)
        ranked = rank_mytheresa_catalog_items(
            items,
            style_id="1BH026",
            product_name="PRADA 1BH026 shoulder bag",
            brand="PRADA",
        )
        top = ranked[0][0].name.lower()
        self.assertTrue("shoulder" in top or "bonnie" in top)

    def test_valid_product_url_multi_segment_path(self) -> None:
        url = (
            "https://www.mytheresa.com/en-us/women/handbags/shoulder-bags/"
            "mini-jo-nappa-leather-shoulder-bag-gucci-p00892014.html"
        )
        self.assertTrue(is_valid_mytheresa_product_url(url))

    def test_reject_search_path(self) -> None:
        url = "https://www.mytheresa.com/en-us/search/?q=PRADA"
        self.assertFalse(is_valid_mytheresa_product_url(url))

    def test_merge_skips_invalid(self) -> None:
        from lib.supply_search.mytheresa import MytheresaCatalogItem

        bad = MytheresaCatalogItem(
            name="search",
            path="/en-us/search/",
            source="html_link",
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
