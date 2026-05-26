"""supply_site_search.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_site_search import (
    build_site_queries,
    extract_urls_from_ddg_html,
)
from lib.supply_search_utils import url_is_valid_supply_candidate


class TestSupplySiteSearch(unittest.TestCase):
    def test_build_queries(self) -> None:
        qs = build_site_queries("PRADA", "1BB108", domains=("farfetch.com",))
        self.assertEqual(len(qs), 1)
        self.assertIn("site:farfetch.com", qs[0])
        self.assertIn("1BB108", qs[0])

    def test_extract_ddg_links(self) -> None:
        html = '''
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.farfetch.com%2Fjp%2Fitem.aspx">
        '''
        urls = extract_urls_from_ddg_html(html, domain_hint="farfetch.com")
        self.assertEqual(len(urls), 1)
        self.assertIn("farfetch.com", urls[0])

    def test_extract_uddg_anywhere(self) -> None:
        html = 'uddg=https%3A%2F%2Fwww.prada.com%2Fjp%2Fja%2Fp%2Fx%2FPR09ZS.html&rut=1'
        urls = extract_urls_from_ddg_html(html, domain_hint="prada.com")
        self.assertEqual(len(urls), 1)
        self.assertIn("prada.com", urls[0])

    def test_style_site_queries_use_wicker_for_bucket_bag(self) -> None:
        from lib.supply_site_search import _style_site_queries

        raw = "ウィッカーバケットバッグ ロゴ 1BE083"
        qs = _style_site_queries("PRADA", "1BE083", product_name=raw, domains=("farfetch.com",))
        self.assertIn("site:farfetch.com PRADA 1BE083 wicker", qs)
        self.assertNotIn("site:farfetch.com PRADA 1BE083 bag", qs[:3])

    def test_site_search_rejects_darling_for_wicker_bucket(self) -> None:
        raw = "ウィッカーバケットバッグ ロゴ 1BE083"
        darling = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-prada-darling-item-23861581.aspx"
        )
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", darling, style_id="1BE083", product_name=raw,
            )
        )


if __name__ == "__main__":
    unittest.main()
