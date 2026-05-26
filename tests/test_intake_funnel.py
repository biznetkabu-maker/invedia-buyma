"""intake_funnel.py のテスト。"""

from __future__ import annotations

import unittest

from lib.intake_funnel import (
    SKIP_NO_STYLE,
    SKIP_OUT_OF_SCOPE,
    assess_record_eligibility,
    filter_eligible_records,
    weekly_auto_limit,
)
from lib.sheet_manager import ProductRecord


class TestIntakeFunnel(unittest.TestCase):
    def test_weekly_limit_default(self) -> None:
        self.assertGreaterEqual(weekly_auto_limit(), 1)

    def test_re_nylon_pouch_skip(self) -> None:
        rec = ProductRecord(
            商品名="PRADA Re-Nylon ミニポーチ",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
        )
        v = assess_record_eligibility(rec)
        self.assertFalse(v.eligible)
        self.assertEqual(v.skip_status, SKIP_OUT_OF_SCOPE)

    def test_no_style_skip(self) -> None:
        rec = ProductRecord(
            商品名="PRADA バッグ",
            型番="100452904",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
        )
        v = assess_record_eligibility(rec)
        self.assertFalse(v.eligible)
        self.assertEqual(v.skip_status, SKIP_NO_STYLE)

    def test_perfume_skip(self) -> None:
        rec = ProductRecord(
            商品名="PRADA ルナロッサ オードパルファム 50ml",
            型番="50ml",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
        )
        v = assess_record_eligibility(rec)
        self.assertFalse(v.eligible)
        self.assertEqual(v.skip_status, SKIP_OUT_OF_SCOPE)

    def test_sunglasses_eligible_policy_a(self) -> None:
        """方針A: サングラスも型番ありなら自動探索対象。"""
        rec = ProductRecord(
            商品名="PRADA サングラス PR09ZS",
            型番="PR09ZS",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
        )
        v = assess_record_eligibility(rec)
        self.assertTrue(v.eligible)

    def test_sunglasses_ok_with_preset_url(self) -> None:
        rec = ProductRecord(
            商品名="PRADA サングラス PR09ZS",
            型番="PR09ZS",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
            候補URLs=(
                "https://www.farfetch.com/jp/shopping/women/"
                "prada-pr09zs-sunglasses-item-99999999.aspx"
            ),
        )
        v = assess_record_eligibility(rec)
        self.assertTrue(v.eligible)

    def test_style_ok(self) -> None:
        rec = ProductRecord(
            商品名="PRADA ショルダーバッグ 1BB108",
            型番="1BB108",
            在庫ステータス="BUYMA候補",
            仕入れURL="https://www.buyma.com/items/1/",
            BUYMA販売価格="400000",
        )
        v = assess_record_eligibility(rec)
        self.assertTrue(v.eligible)

    def test_filter_cap(self) -> None:
        rows = [
            ProductRecord(
                商品名=f"PRADA bag {i} 2M0738",
                型番="2M0738",
                在庫ステータス="BUYMA候補",
                仕入れURL="https://www.buyma.com/items/1/",
            )
            for i in range(5)
        ]
        eligible, skipped = filter_eligible_records(rows, limit=2)
        self.assertEqual(len(eligible), 2)

    def test_is_eyewear_product_name(self) -> None:
        from lib.funnel_policy import is_eyewear_product_name

        self.assertTrue(is_eyewear_product_name("PRADA サングラス PR09ZS"))
        self.assertFalse(is_eyewear_product_name("PRADA セール 1Y656I"))


if __name__ == "__main__":
    unittest.main()
