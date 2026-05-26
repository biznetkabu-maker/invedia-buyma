"""official_catalog.prada のテスト（ネットワーク不要）。"""

from __future__ import annotations

import json
import unittest

from lib.official_catalog.prada import (
    PradaOfficialMatch,
    _mpn_matches,
    _parse_html_product,
    _pick_best,
    _walk_json,
    _Candidate,
)


class TestPradaMpn(unittest.TestCase):

    def test_mpn_prefix_match(self) -> None:
        self.assertTrue(_mpn_matches("PR09ZS", "PR09ZS-1AB1O1-1BO1O1"))
        self.assertFalse(_mpn_matches("PR09ZS", "1BB108"))

    def test_json_ld_html(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type":"Product","name":"Prada Symbole Sunglasses",
         "sku":"PR09ZS-1AB1O1-1BO1O1",
         "url":"https://www.prada.com/jp/ja/p/test/PR09ZS-1AB1O1-1BO1O1.html",
         "offers":{"price":"61000","priceCurrency":"JPY"}}
        </script>
        """
        found = _parse_html_product(html, "PR09ZS", "")
        best = _pick_best(found, "PR09ZS")
        self.assertIsNotNone(best)
        self.assertIn("PR09ZS", best.sku)

    def test_walk_search_api(self) -> None:
        data = {
            "products": [
                {
                    "partNumber": "PR09ZS-1AB1O1-1BO1O1",
                    "productUrl": "https://www.prada.com/jp/ja/p/symbole/PR09ZS-1AB1O1-1BO1O1.html",
                    "name": "Symbole sunglasses",
                }
            ]
        }
        out: list[_Candidate] = []
        _walk_json(data, "PR09ZS", out)
        best = _pick_best(out, "PR09ZS")
        self.assertIsNotNone(best)
        self.assertEqual(best.source, "xhr_json")

    def test_official_match_helper(self) -> None:
        m = PradaOfficialMatch(
            mpn_query="PR09ZS",
            product_url="https://www.prada.com/jp/ja/p/x/PR09ZS-1AB1O1-1BO1O1.html",
            sku="PR09ZS-1AB1O1-1BO1O1",
            english_name="Symbole",
            price_note="61000",
            source="json_ld",
            identity_note="test",
        )
        self.assertTrue(m.matches_mpn("PR09ZS"))


if __name__ == "__main__":
    unittest.main()
