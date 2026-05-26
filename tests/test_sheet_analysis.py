"""sheet_analysis のユニットテスト。"""

import unittest

from lib.sheet_analysis import analyze_records
from lib.sheet_manager import ProductRecord


class TestAnalyzeRecords(unittest.TestCase):

    def test_empty(self):
        report = analyze_records([])
        self.assertEqual(report.total_rows, 0)
        self.assertEqual(report.status_counts, {})

    def test_status_counts_and_top_profit(self):
        records = [
            ProductRecord(
                商品名="A",
                ブランド="X",
                現地価格="100",
                為替="150",
                BUYMA販売価格="50000",
                在庫ステータス="出品中",
            ),
            ProductRecord(
                商品名="B",
                ブランド="Y",
                現地価格="50",
                為替="150",
                BUYMA販売価格="30000",
                在庫ステータス="停止中",
            ),
        ]
        report = analyze_records(records, top_n=1)
        self.assertEqual(report.total_rows, 2)
        self.assertEqual(report.status_counts["出品中"], 1)
        self.assertEqual(report.status_counts["停止中"], 1)
        self.assertEqual(len(report.top_profit), 1)
        self.assertGreater(report.top_profit[0].利益額 or 0, 0)
        self.assertTrue(any(i.商品名 == "B" for i in report.needs_attention))

    def test_missing_price(self):
        records = [ProductRecord(商品名="C", 在庫ステータス="BUYMA候補")]
        report = analyze_records(records)
        self.assertEqual(report.missing_price_rows, 1)
        self.assertEqual(report.calculable_rows, 0)


if __name__ == "__main__":
    unittest.main()
