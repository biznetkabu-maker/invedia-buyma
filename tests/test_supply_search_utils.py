"""supply_search_utils.py のテスト。"""

from __future__ import annotations

import unittest

from lib.supply_search_utils import (
    build_supply_search_queries,
    clean_product_name_for_search,
    dedupe_product_phrase,
    extract_model_codes,
    is_plausible_model_code,
    is_valid_farfetch_product_url,
    normalize_brand_name,
    sheet_style_id_value,
    supplemental_search_queries,
    url_is_retail_supply_candidate,
    style_id_for_matching,
    url_is_valid_supply_candidate,
    url_matches_style_hint,
)


class TestSupplySearchUtils(unittest.TestCase):
    def test_extract_2m0738(self) -> None:
        title = "【VIPセール】PRADA プラダ 二つ折り 財布 2M0738"
        self.assertIn("2M0738", extract_model_codes(title))

    def test_reject_volume_as_model_code(self) -> None:
        self.assertFalse(is_plausible_model_code("50ml"))
        self.assertFalse(is_plausible_model_code("100ml"))
        self.assertEqual(
            sheet_style_id_value("PRADA ルナロッサ オードパルファム 50ml", "50ml"),
            "",
        )
        self.assertEqual(style_id_for_matching("50ml", ""), "")

    def test_skip_long_numeric_id(self) -> None:
        qs = build_supply_search_queries("PRADA", "wallet 2M0738", "100113400")
        self.assertIn("PRADA 2M0738", qs)
        self.assertNotIn("100113400", qs)

    def test_clean_brackets(self) -> None:
        s = clean_product_name_for_search("【VIPセール】PRADA 財布", "PRADA")
        self.assertNotIn("VIP", s)

    def test_normalize_prada_re_nylon(self) -> None:
        self.assertEqual(normalize_brand_name("PRADA◆Re-Nylon"), "PRADA")

    def test_bracket_prada_tag(self) -> None:
        self.assertEqual(
            normalize_brand_name("【PRADA】2X3119 3LKK"),
            "PRADA",
        )

    def test_normalize_outlet_prefix_brand(self) -> None:
        self.assertEqual(normalize_brand_name("♪直営アウトレット♪PRADA"), "PRADA")

    def test_normalize_japanese_prada_decorated(self) -> None:
        self.assertEqual(normalize_brand_name("プラダ☆キルティング"), "PRADA")
        self.assertEqual(normalize_brand_name("プラダ☆ロゴ刺繍"), "PRADA")

    def test_crochet_tote_query(self) -> None:
        qs = build_supply_search_queries(
            "PRADA", "クロシェトートバッグ 1BG493", "1BG493",
        )
        self.assertTrue(any("crochet" in q.lower() or "tote" in q.lower() for q in qs))

    def test_shoulder_bag_skips_bare_style_query(self) -> None:
        qs = build_supply_search_queries(
            "PRADA", "2wayショルダーバッグ 1BH026", "1BH026",
        )
        self.assertIn("PRADA 1BH026 shoulder-bag", qs)
        self.assertNotIn("PRADA 1BH026", qs)

    def test_compress_long_prada_sku_for_search(self) -> None:
        from lib.supply_search_utils import compress_style_id_for_search, style_id_for_site_search

        self.assertEqual(compress_style_id_for_search("2VG1312CYAF0216"), "2VG131")
        self.assertEqual(style_id_for_site_search("1ML506"), "1ML506")

    def test_dog_carrier_query_not_pouch(self) -> None:
        qs = build_supply_search_queries(
            "PRADA", "ドックキャリーバッグ 2VC039", "2VC039",
        )
        self.assertTrue(any("carrier" in q.lower() or "bag" in q.lower() for q in qs))
        self.assertNotIn("PRADA 2VC039 pouch", qs)

    def test_apparel_query_uses_shirt_not_wallet(self) -> None:
        qs = build_supply_search_queries("PRADA", "Tシャツ UJN880", "UJN880")
        self.assertTrue(any("shirt" in q.lower() or "t-shirt" in q.lower() for q in qs))
        self.assertNotIn("PRADA UJN880 wallet", qs)

    def test_footwear_query_uses_sandal_not_wallet(self) -> None:
        qs = build_supply_search_queries(
            "PRADA", "モノリス ラバーサンダル 2X3083", "2X3083",
        )
        self.assertTrue(any("sandal" in q.lower() for q in qs))
        self.assertNotIn("PRADA 2X3083 wallet", qs)

    def test_clean_prada_mini_pouch(self) -> None:
        cleaned = clean_product_name_for_search(
            "PRADA◆Re-Nylon ミニポーチ 小物入れ ロゴ付き", "PRADA"
        )
        self.assertIn("ミニポーチ", cleaned)
        self.assertNotIn("◆", cleaned)
        self.assertNotIn("Re-Nylon", cleaned)

    def test_dedupe_repeated_phrase(self) -> None:
        s = "ミニポーチ 小物入れ ロゴ付き ミニポーチ 小物入れ ロゴ付き"
        self.assertEqual(dedupe_product_phrase(s), "ミニポーチ 小物入れ ロゴ付き")

    def test_clean_duplicate_brand_prefix(self) -> None:
        cleaned = clean_product_name_for_search(
            "PRADA PRADA◆Re-Nylon ミニポーチ 小物入れ", "PRADA"
        )
        self.assertIn("ミニポーチ", cleaned)
        self.assertNotIn("PRADA◆", cleaned)
        parts = cleaned.upper().split()
        self.assertEqual(parts.count("PRADA"), 0)

    def test_buyma_item_id_not_style_id(self) -> None:
        self.assertEqual(
            sheet_style_id_value("PRADA ミニポーチ", "100452904"),
            "",
        )
        self.assertEqual(style_id_for_matching("", "100452904"), "")

    def test_reject_pre_owned_url(self) -> None:
        self.assertFalse(
            url_is_retail_supply_candidate(
                "https://www.farfetch.com/jp/shopping/women/prada-pre-owned-wallet.aspx"
            )
        )

    def test_supplemental_re_nylon_pouch(self) -> None:
        extra = supplemental_search_queries(
            "PRADA", "PRADA◆Re-Nylon ミニポーチ 小物入れ"
        )
        self.assertIn("PRADA re nylon mini pouch", extra)

    def test_build_queries_includes_english_for_re_nylon(self) -> None:
        qs = build_supply_search_queries(
            "PRADA",
            "ミニポーチ 小物入れ ロゴ付き",
            raw_product_name="PRADA◆Re-Nylon ミニポーチ 小物入れ ロゴ付き",
        )
        self.assertTrue(any("re nylon" in q.lower() for q in qs))

    def test_reject_malformed_farfetch_slug(self) -> None:
        bad = "https://www.farfetch.com/jp/shopping/women/prada--item-30953.aspx"
        self.assertFalse(is_valid_farfetch_product_url(bad))
        self.assertFalse(url_is_valid_supply_candidate("PRADA", bad))

    def test_accept_farfetch_product_url(self) -> None:
        good = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-re-nylon-mini-pouch-item-35764397.aspx"
        )
        self.assertTrue(is_valid_farfetch_product_url(good))
        self.assertTrue(url_is_valid_supply_candidate("PRADA", good))

    def test_farfetch_url_without_style_in_slug_allowed_for_discovery(self) -> None:
        """型番は JSON-LD 照合。URL 探索ではスラッグ不一致を許容（1ML506 等）。"""
        wallet = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-saffiano-leather-zip-around-wallet-item-12345678.aspx"
        )
        self.assertFalse(url_matches_style_hint("1ML506", wallet))
        self.assertTrue(
            url_is_valid_supply_candidate("PRADA", wallet, style_id="1ML506")
        )

    def test_strict_style_in_url_mode(self) -> None:
        wrong = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-prada-arque-s-item-36082423.aspx"
        )
        self.assertFalse(url_matches_style_hint("1BB108", wrong))
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", wrong, style_id="1BB108", require_style_in_url=True
            )
        )

    def test_rank_wallet_urls(self) -> None:
        from lib.supply_search_utils import rank_supply_urls_for_discovery

        boot = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-monolith-leather-chelsea-boots-item-111.aspx"
        )
        wallet = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-saffiano-leather-wallet-item-222.aspx"
        )
        ranked = rank_supply_urls_for_discovery(
            [boot, wallet], style_id="1ML506", product_name="財布",
        )
        self.assertEqual(ranked[0], wallet)

    def test_rank_penalizes_eyewear_for_style_only_name(self) -> None:
        from lib.supply_search_utils import rank_supply_urls_for_discovery

        eyewear = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-eyewear-14wv-item-22974537.aspx"
        )
        wallet = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-saffiano-leather-wallet-item-222.aspx"
        )
        ranked = rank_supply_urls_for_discovery(
            [eyewear, wallet], style_id="1Y656I", product_name="セール 1Y656I",
        )
        self.assertEqual(ranked[0], wallet)

    def test_style_only_query_includes_wallet(self) -> None:
        qs = build_supply_search_queries("PRADA", "セール 1Y656I", "1Y656I")
        self.assertTrue(any("wallet" in q.lower() for q in qs))
        self.assertIn("PRADA 1Y656I wallet", qs)


    def test_belt_body_bag_queries_and_department(self) -> None:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            infer_supply_category_hints,
            infer_supply_department,
            apply_department_to_search_template,
        )
        from lib.product_finder import SITE_BY_DOMAIN

        raw = "メンズ ボディバッグ ナイロン ベルトバッグ 2VL977 *SALE"
        self.assertEqual(infer_supply_department(raw), "men")
        pos, neg = infer_supply_category_hints(raw)
        self.assertIn("belt-bag", pos)
        self.assertIn("wallet", neg)
        qs = build_supply_search_queries("PRADA", raw, "2VL977", raw_product_name=raw)
        self.assertEqual(qs[0], "PRADA 2VL977 belt-bag")
        self.assertNotIn("PRADA 2VL977 shoulder", qs[:3])

        ssense = SITE_BY_DOMAIN["ssense.com"].search_url_template
        self.assertIn("/men", apply_department_to_search_template(ssense, "men", "ssense.com"))

    def test_farfetch_wallet_penalized_for_belt_bag(self) -> None:
        from lib.supply_search.farfetch import FarfetchCatalogItem, rank_farfetch_catalog_items

        wallet = FarfetchCatalogItem(
            name="nappa-leather wallet with shoulder-strap",
            path="/jp/shopping/women/prada-nappa-leather-wallet-with-shoulder-strap-item-36347074.aspx",
            source="json_ld_itemlist",
        )
        belt = FarfetchCatalogItem(
            name="Re-Nylon belt bag",
            path="/jp/shopping/men/prada-re-nylon-belt-bag-item-12345678.aspx",
            source="json_ld_itemlist",
        )
        raw = "メンズ ボディバッグ ナイロン ベルトバッグ 2VL977"
        ranked = rank_farfetch_catalog_items(
            [wallet, belt], style_id="2VL977", product_name=raw, brand="PRADA",
        )
        self.assertEqual(ranked[0][0].name, belt.name)


    def test_sneaker_with_pouch_accessory_not_pouch_query(self) -> None:
        raw = "ADIDAS x 2TG193 ポーチ付 スニーカー"
        qs = build_supply_search_queries("PRADA", raw, "2TG193", raw_product_name=raw)
        self.assertEqual(qs[0], "PRADA 2TG193 sneaker")
        self.assertNotIn("PRADA 2TG193 pouch", qs[:3])
        from lib.supply_search_utils import is_primary_pouch_product_name
        self.assertFalse(is_primary_pouch_product_name(raw))

    def test_mini_pouch_still_primary_pouch(self) -> None:
        from lib.supply_search_utils import is_primary_pouch_product_name, category_site_search_extras
        raw = "PRADA◆Re-Nylon ミニポーチ 小物入れ"
        self.assertTrue(is_primary_pouch_product_name(raw))
        self.assertEqual(category_site_search_extras(raw)[0], "pouch")


    def test_monolith_sandal_prefers_monolith_query(self) -> None:
        raw = "モノリス ラバー プラットフォーム 厚底サンダル 1XX751"
        qs = build_supply_search_queries("PRADA", raw, "1XX751", raw_product_name=raw)
        self.assertEqual(qs[0], "PRADA 1XX751 monolith")
        self.assertIn("PRADA 1XX751 mules", qs[:4])

    def test_monolith_farfetch_ranks_above_wish_nylon(self) -> None:
        from lib.supply_search.farfetch import FarfetchCatalogItem, rank_farfetch_catalog_items
        raw = "モノリス ラバー プラットフォーム 厚底サンダル 1XX751"
        wrong = FarfetchCatalogItem(
            name="Wish Re-Nylon",
            path="/jp/shopping/women/prada-wish-re-nylon-item-36082430.aspx",
            source="json_ld_itemlist",
        )
        right = FarfetchCatalogItem(
            name="Monolith rubber mules",
            path="/jp/shopping/women/prada-monolith-rubber-mules-item-12345678.aspx",
            source="json_ld_itemlist",
        )
        ranked = rank_farfetch_catalog_items(
            [wrong, right], style_id="1XX751", product_name=raw, brand="PRADA",
        )
        self.assertIn("monolith", ranked[0][0].name.lower())

    def test_handbag_queries_and_rejects_eyewear_url(self) -> None:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            category_site_search_extras,
            infer_supply_category_hints,
            url_has_category_path_mismatch,
            url_is_valid_supply_candidate,
        )

        raw = "コットンキャンバス スモール ハンドバッグ 1BG464"
        self.assertEqual(
            category_site_search_extras(raw)[:2],
            ["hand-bag", "handbag"],
        )
        pos, neg = infer_supply_category_hints(raw)
        self.assertIn("hand-bag", pos)
        self.assertIn("eyewear", neg)
        qs = build_supply_search_queries(
            "PRADA", raw, "1BG464", raw_product_name=raw,
        )
        self.assertEqual(qs[0], "PRADA 1BG464 hand-bag")

        eyewear = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-eyewear-14wv-1ab1o1-item-22974537.aspx"
        )
        self.assertTrue(url_has_category_path_mismatch(raw, eyewear))
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", eyewear, style_id="1BG464", product_name=raw,
            )
        )

        bag = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-jardiniere-small-cotton-canvas-bag-item-99999999.aspx"
        )
        self.assertFalse(url_has_category_path_mismatch(raw, bag))
        self.assertTrue(
            url_is_valid_supply_candidate(
                "PRADA", bag, style_id="1BG464", product_name=raw,
            )
        )

    def test_wicker_bucket_queries_and_rejects_darling_url(self) -> None:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            category_site_search_extras,
            infer_supply_category_hints,
            url_has_category_path_mismatch,
            url_is_valid_supply_candidate,
        )

        raw = "ウィッカーバケットバッグ ロゴ 1BE083"
        self.assertEqual(
            category_site_search_extras(raw)[:2],
            ["wicker", "bucket-bag"],
        )
        pos, neg = infer_supply_category_hints(raw)
        self.assertIn("wicker", pos)
        self.assertIn("bucket-bag", pos)
        self.assertIn("darling", neg)
        qs = build_supply_search_queries(
            "PRADA", raw, "1BE083", raw_product_name=raw,
        )
        self.assertEqual(qs[0], "PRADA 1BE083 wicker")

        darling = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-prada-darling-item-23861581.aspx"
        )
        self.assertTrue(url_has_category_path_mismatch(raw, darling))
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", darling, style_id="1BE083", product_name=raw,
            )
        )

        bucket = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-wicker-mini-bucket-bag-item-88888888.aspx"
        )
        self.assertFalse(url_has_category_path_mismatch(raw, bucket))
        self.assertTrue(
            url_is_valid_supply_candidate(
                "PRADA", bucket, style_id="1BE083", product_name=raw,
            )
        )

    def test_footwear_rejects_generic_sandal_without_style_slug(self) -> None:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            url_has_line_or_style_slug_match,
            url_is_valid_supply_candidate,
        )

        raw = "プラダ 限定数量セール！サンダル 1X1030"
        generic = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-strappy-leather-sandals-item-36384231.aspx"
        )
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", generic, style_id="1X1030", product_name=raw,
            )
        )
        qs = build_supply_search_queries(
            "PRADA", raw, "1X1030", raw_product_name=raw,
        )
        self.assertEqual(qs[0], "PRADA 1X1030 sandal")

        monolith_raw = "モノリス ラバー プラットフォーム 厚底サンダル 1XX751"
        monolith = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-monolith-rubber-mules-item-12345678.aspx"
        )
        self.assertTrue(
            url_has_line_or_style_slug_match(monolith_raw, "1XX751", monolith)
        )
        self.assertTrue(
            url_is_valid_supply_candidate(
                "PRADA", monolith, style_id="1XX751", product_name=monolith_raw,
            )
        )

    def test_fragment_case_queries_and_rejects_generic_wallet(self) -> None:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            category_site_search_extras,
            url_is_valid_supply_candidate,
        )

        raw = "数量限定 1MC038 フラグメントケース"
        self.assertEqual(
            category_site_search_extras(raw)[:2],
            ["fragment", "card-holder"],
        )
        qs = build_supply_search_queries(
            "PRADA", raw, "1MC038", raw_product_name=raw,
        )
        self.assertEqual(qs[0], "PRADA 1MC038 fragment")

        generic_wallet = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        self.assertFalse(
            url_is_valid_supply_candidate(
                "PRADA", generic_wallet, style_id="1MC038", product_name=raw,
            )
        )

        fragment = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-fragment-saffiano-leather-card-holder-item-88888888.aspx"
        )
        self.assertTrue(
            url_is_valid_supply_candidate(
                "PRADA", fragment, style_id="1MC038", product_name=raw,
            )
        )


if __name__ == "__main__":
    unittest.main()
