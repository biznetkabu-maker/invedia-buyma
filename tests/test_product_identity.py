"""product_identity（VariantKey / MatchScore）のテスト。"""

from __future__ import annotations

import unittest

from lib.product_identity import (
    MatchScore,
    VariantKey,
    score_from_best_candidate,
    score_when_no_supply,
    summarize_best_source_result,
)
from lib.sheet_manager import ProductRecord
from lib.style_id_utils import scraped_matches_buyma_style


class TestVariantKey(unittest.TestCase):

    def test_resolve_from_product_name(self) -> None:
        vk = VariantKey.resolve(
            brand="PRADA",
            product_name="財布 2M0738",
            sheet_style_id="100113400",
        )
        self.assertEqual(vk.match_ref, "2M0738")
        self.assertEqual(vk.buyma_item_id, "100113400")

    def test_numeric_sheet_id_is_reference_only(self) -> None:
        vk = VariantKey.resolve(
            brand="PRADA",
            product_name="ミニポーチ",
            sheet_style_id="100452904",
        )
        self.assertEqual(vk.buyma_item_id, "100452904")
        self.assertFalse(vk.has_match_ref)

    def test_from_record(self) -> None:
        rec = ProductRecord(
            商品名="PRADA 2M0738 財布",
            ブランド="PRADA",
            型番="2M0738",
        )
        self.assertEqual(VariantKey.from_record(rec).match_ref, "2M0738")


class TestMatchScore(unittest.TestCase):

    def test_grade_s_with_url_hint(self) -> None:
        vk = VariantKey.resolve(brand="PRADA", sheet_style_id="2M0738")
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-2m0738-wallet-item-12345.aspx"
        )
        ms = summarize_best_source_result(
            vk,
            best_url=url,
            best_style_id="2M0738",
            best_stock="in_stock",
            best_price_ok=True,
            purchase_grade="B",
        )
        self.assertEqual(ms.grade, "S")
        self.assertTrue(ms.allows_auto_reflect())

    def test_grade_f_style_mismatch(self) -> None:
        vk = VariantKey.resolve(brand="PRADA", sheet_style_id="1BB108")
        ms = score_from_best_candidate(
            vk,
            scraped_style_id="ARQUE-S",
            stock_status="in_stock",
            price_ok=True,
            purchase_grade="A",
        )
        self.assertEqual(ms.grade, "F")
        self.assertFalse(ms.allows_auto_reflect())

    def test_grade_f_no_style(self) -> None:
        vk = VariantKey.resolve(brand="PRADA", product_name="ポーチ")
        self.assertEqual(score_when_no_supply(vk).grade, "F")

    def test_scraped_matches_integration(self) -> None:
        self.assertTrue(scraped_matches_buyma_style("2M0738", "2M0738"))
        self.assertFalse(scraped_matches_buyma_style("ARQUE-S", "1BB108"))


class TestMatchScoreSheetFields(unittest.TestCase):

    def test_format_console(self) -> None:
        ms = MatchScore("A", "型番=2M0738", "EUR 1200")
        text = ms.format_console()
        self.assertIn("同一性スコア", text)
        self.assertIn("A", text)


if __name__ == "__main__":
    unittest.main()
