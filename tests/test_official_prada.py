"""official_catalog.prada のテスト（ネットワーク不要）。"""

from __future__ import annotations

import unittest

from lib.official_catalog.prada import (
    PradaOfficialMatch,
    _Candidate,
    _ddg_queries,
    _extract_prada_pdp_urls,
    _mpn_matches,
    _normalize_mpn,
    _parse_html_product,
    _pick_best,
    _score_candidate,
    _search_urls,
    _to_int,
    _walk_json,
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


class TestPradaPureHelpers(unittest.TestCase):

    def test_normalize_mpn(self) -> None:
        self.assertEqual(_normalize_mpn("pr 09-zs/1ab"), "PR09ZS1AB")
        self.assertEqual(_normalize_mpn(""), "")
        self.assertEqual(_normalize_mpn(None), "")  # type: ignore[arg-type]

    def test_mpn_matches_short_query_no_prefix(self) -> None:
        # 5 文字未満の前方一致は不成立
        self.assertFalse(_mpn_matches("PR09", "PR09ZS-1AB"))
        self.assertTrue(_mpn_matches("PR09ZS", "PR09ZS"))
        self.assertFalse(_mpn_matches("", "PR09ZS"))

    def test_to_int(self) -> None:
        self.assertEqual(_to_int(5), 5)
        self.assertEqual(_to_int(3.9), 3)
        self.assertEqual(_to_int(True), 1)
        self.assertEqual(_to_int("42"), 42)
        self.assertEqual(_to_int("-7"), -7)
        self.assertEqual(_to_int("abc"), 0)
        self.assertEqual(_to_int(None), 0)
        self.assertEqual(_to_int(object()), 0)

    def test_score_candidate(self) -> None:
        c = _Candidate(
            sku="PR09ZS-1AB",
            url="https://www.prada.com/jp/ja/p/x/PR09ZS-1AB.html",
            name="Symbole",
            score=0,
        )
        # sku一致(+100) + prada/p(+40) + name(+10) + mpn in url(+30)
        self.assertEqual(_score_candidate(c, "PR09ZS"), 180)
        empty = _Candidate()
        self.assertEqual(_score_candidate(empty, "PR09ZS"), 0)

    def test_search_urls(self) -> None:
        urls = _search_urls("PR 09ZS")
        self.assertEqual(len(urls), 4)
        self.assertTrue(all("PR+09ZS" in u for u in urls))
        self.assertTrue(all(u.startswith("https://www.prada.com") for u in urls))

    def test_ddg_queries_eyewear(self) -> None:
        qs = _ddg_queries("PR09ZS", product_name="Symbole サングラス")
        self.assertIn("sunglasses", qs[0])
        plain = _ddg_queries("1BG023", product_name="ナイロンバッグ")
        self.assertNotIn("sunglasses", plain[0])

    def test_extract_prada_pdp_urls_dedup(self) -> None:
        html = (
            'a https://www.prada.com/jp/ja/p/x/PR09ZS-1AB.html?foo=1 '
            'b https://www.prada.com/jp/ja/p/x/PR09ZS-1AB.html?bar=2 '
            'c https://www.prada.com/us/en/p/y/1BG023.html'
        )
        urls = _extract_prada_pdp_urls(html)
        self.assertEqual(len(urls), 2)  # クエリ違いは重複排除
        self.assertEqual(_extract_prada_pdp_urls(""), [])

    def test_parse_html_product_path_match(self) -> None:
        html = (
            'link <a href="/jp/ja/p/symbole/PR09ZS-1AB1O1.html">x</a> '
            'noise /jp/ja/p/other/ZZ99.html'
        )
        out = _parse_html_product(html, "PR09ZS", "")
        # mpn を含む path のみ拾う
        self.assertTrue(any(c.source == "html_path" for c in out))
        self.assertTrue(all("PR09ZS" in c.url.upper() for c in out if c.source == "html_path"))

    def test_parse_html_embedded_partnumber(self) -> None:
        html = '{"partNumber":"PR09ZS-1AB1O1"}'
        out = _parse_html_product(html, "PR09ZS", "https://page")
        self.assertTrue(any(c.source == "html_embedded" for c in out))

    def test_pick_best_returns_none_for_empty(self) -> None:
        self.assertIsNone(_pick_best([], "PR09ZS"))

    def test_pick_best_pdp_url_score(self) -> None:
        # sku 一致なしでも prada PDP URL に mpn 含めば score>=50 で採用
        cands = [
            _Candidate(
                url="https://www.prada.com/jp/ja/p/x/PR09ZS-1AB.html",
                source="ddg_only",
                score=0,
            ),
        ]
        best = _pick_best(cands, "PR09ZS")
        self.assertIsNotNone(best)
        self.assertGreaterEqual(best.score, 50)  # +40(/p/) +30(mpn in url)

    def test_pick_best_low_score_rejected(self) -> None:
        # sku 一致なし・PDP でもなく低スコアは不採用
        cands = [_Candidate(name="random", source="ddg_only", score=0)]
        self.assertIsNone(_pick_best(cands, "PR09ZS"))


if __name__ == "__main__":
    unittest.main()
