"""supply_url_finder が import エラーなく動くこと。"""

from __future__ import annotations

import unittest

from lib.supply_url_finder import filter_product_urls


class TestSupplyUrlFinderImports(unittest.TestCase):
    def test_filter_product_urls_with_brand(self) -> None:
        links = [
            "https://www.farfetch.com/shopping/women/prada-re-nylon-bag-item-12345678.aspx",
            "https://www.farfetch.com/shopping/women/other-brand-bag-item-87654321.aspx",
        ]
        out = filter_product_urls(links, "farfetch.com", limit=1, brand="PRADA")
        self.assertEqual(len(out), 1)
        self.assertIn("prada", out[0].lower())


if __name__ == "__main__":
    unittest.main()
