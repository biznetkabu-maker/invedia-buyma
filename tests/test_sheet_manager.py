"""
SheetManager のユニットテスト。

gspread / oauth2client への実際のネットワーク接続は行わず、
unittest.mock を使って全外部依存をスタブ化します。
"""

import unittest
from unittest.mock import MagicMock, patch, call
from lib.sheet_manager import SheetManager, ProductRecord, COLUMNS


# ---------------------------------------------------------------------------
# ヘルパー: テスト用のモックワークシートを生成
# ---------------------------------------------------------------------------

def _make_worksheet(rows: list[list[str]]) -> MagicMock:
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    ws.row_values.side_effect = lambda i: rows[i - 1] if i <= len(rows) else []
    ws.col_values.side_effect = lambda col: [row[col - 1] if len(row) >= col else "" for row in rows]
    return ws


def _make_manager(ws: MagicMock) -> SheetManager:
    manager = SheetManager("fake_id", "fake_sheet", credentials_path="fake.json")
    manager._worksheet = ws
    return manager


# ---------------------------------------------------------------------------
# ProductRecord
# ---------------------------------------------------------------------------

class TestProductRecord(unittest.TestCase):

    def test_from_row_full(self):
        row = ["商品A", "GUCCI", "GG-001", "https://x.com", "800", "160", "160000", "在庫あり", "16000"]
        r = ProductRecord.from_row(row)
        self.assertEqual(r.商品名, "商品A")
        self.assertEqual(r.利益額, "16000")

    def test_from_row_short(self):
        r = ProductRecord.from_row(["商品B"])
        self.assertEqual(r.ブランド, "")

    def test_to_row_roundtrip(self):
        row = [
            "商品C", "LV", "M-001", "https://y.com", "500", "155", "90000",
            "残り1点", "10000", "https://a.com,https://b.com", "A", "EUR 500",
        ]
        self.assertEqual(ProductRecord.from_row(row).to_row(), row)

    def test_to_row_roundtrip_legacy_10col(self):
        """旧10列データを読み込んでも新列は空で補完（後方互換）。"""
        old_row = [
            "商品C", "LV", "M-001", "https://y.com", "500", "155",
            "90000", "残り1点", "10000", "https://a.com",
        ]
        result = ProductRecord.from_row(old_row).to_row()
        self.assertEqual(len(result), len(COLUMNS))
        self.assertEqual(result[9], "https://a.com")
        self.assertEqual(result[10], "")
        self.assertEqual(result[11], "")

    def test_to_row_length(self):
        self.assertEqual(len(ProductRecord().to_row()), len(COLUMNS))


# ---------------------------------------------------------------------------
# SheetManager.get_all_records
# ---------------------------------------------------------------------------

class TestGetAllRecords(unittest.TestCase):

    def test_returns_data_rows(self):
        rows = [COLUMNS, ["商品A", "GUCCI", "GG-001", "", "800", "160", "160000", "在庫あり", "16000"]]
        manager = _make_manager(_make_worksheet(rows))
        records = manager.get_all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].商品名, "商品A")

    def test_empty_sheet_returns_empty_list(self):
        manager = _make_manager(_make_worksheet([COLUMNS]))
        self.assertEqual(manager.get_all_records(), [])

    def test_no_header_returns_empty_list(self):
        manager = _make_manager(_make_worksheet([]))
        self.assertEqual(manager.get_all_records(), [])


# ---------------------------------------------------------------------------
# SheetManager.get_record_by_product_name
# ---------------------------------------------------------------------------

class TestGetRecordByProductName(unittest.TestCase):

    def _setup(self):
        rows = [
            COLUMNS,
            ["商品A", "GUCCI", "GG-001", "", "800", "160", "160000", "在庫あり", "16000"],
            ["商品B", "LV", "M-001", "", "500", "155", "90000", "残り1点", "10000"],
        ]
        return _make_manager(_make_worksheet(rows))

    def test_found(self):
        r = self._setup().get_record_by_product_name("商品B")
        self.assertIsNotNone(r)
        self.assertEqual(r.ブランド, "LV")

    def test_not_found(self):
        r = self._setup().get_record_by_product_name("存在しない")
        self.assertIsNone(r)


# ---------------------------------------------------------------------------
# SheetManager.get_records_by_status
# ---------------------------------------------------------------------------

class TestGetRecordsByStatus(unittest.TestCase):

    def test_filter_by_status(self):
        rows = [
            COLUMNS,
            ["商品A", "", "", "", "", "", "", "在庫あり", ""],
            ["商品B", "", "", "", "", "", "", "残り1点", ""],
            ["商品C", "", "", "", "", "", "", "在庫あり", ""],
        ]
        manager = _make_manager(_make_worksheet(rows))
        result = manager.get_records_by_status("在庫あり")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# SheetManager.append_record
# ---------------------------------------------------------------------------

class TestAppendRecord(unittest.TestCase):

    def test_append_calls_worksheet(self):
        ws = _make_worksheet([COLUMNS])
        manager = _make_manager(ws)
        record = ProductRecord(商品名="新商品", ブランド="PRADA")
        manager.append_record(record)
        ws.append_rows.assert_called_once()
        args = ws.append_rows.call_args[0][0]
        self.assertEqual(args[0][0], "新商品")
        self.assertEqual(args[0][1], "PRADA")


# ---------------------------------------------------------------------------
# SheetManager.update_record
# ---------------------------------------------------------------------------

class TestUpdateRecord(unittest.TestCase):

    def test_update_existing(self):
        rows = [
            COLUMNS,
            ["商品A", "GUCCI", "GG-001", "", "800", "160", "160000", "在庫あり", "16000"],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        record = ProductRecord(商品名="商品A", 在庫ステータス="残り1点")
        result = manager.update_record("商品A", record)
        self.assertTrue(result)
        ws.update.assert_called_once()

    def test_update_nonexistent_returns_false(self):
        ws = _make_worksheet([COLUMNS])
        manager = _make_manager(ws)
        result = manager.update_record("存在しない", ProductRecord())
        self.assertFalse(result)
        ws.update.assert_not_called()


# ---------------------------------------------------------------------------
# SheetManager.upsert_record
# ---------------------------------------------------------------------------

class TestUpsertRecord(unittest.TestCase):

    def test_upsert_existing_calls_update(self):
        rows = [COLUMNS, ["商品A", "", "", "", "", "", "", "", ""]]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        result = manager.upsert_record(ProductRecord(商品名="商品A"))
        self.assertEqual(result, "updated")

    def test_upsert_new_calls_append(self):
        ws = _make_worksheet([COLUMNS])
        manager = _make_manager(ws)
        result = manager.upsert_record(ProductRecord(商品名="新商品"))
        self.assertEqual(result, "appended")
        ws.append_rows.assert_called_once()


# ---------------------------------------------------------------------------
# SheetManager.delete_record
# ---------------------------------------------------------------------------

class TestDeleteRecord(unittest.TestCase):

    def test_delete_existing(self):
        rows = [COLUMNS, ["商品A", "", "", "", "", "", "", "", ""]]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        result = manager.delete_record("商品A")
        self.assertTrue(result)
        ws.delete_rows.assert_called_once_with(2)

    def test_delete_nonexistent(self):
        ws = _make_worksheet([COLUMNS])
        manager = _make_manager(ws)
        result = manager.delete_record("存在しない")
        self.assertFalse(result)
        ws.delete_rows.assert_not_called()


# ---------------------------------------------------------------------------
# SheetManager.recalculate_profit
# ---------------------------------------------------------------------------

class TestRecalculateProfit(unittest.TestCase):

    def test_recalculates_profit(self):
        rows = [
            COLUMNS,
            ["商品A", "GUCCI", "GG-001", "", "800", "160", "160000", "在庫あり", ""],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        count = manager.recalculate_profit(exchange_rate=160.0)
        self.assertEqual(count, 1)
        # 利益額 = 160000
        #         - (800 × 160)           JPY仕入原価 = 128000
        #         - 128000 × 0.10         関税       = 12800
        #         - 2000                  国際送料    = 2000
        #         - 160000 × 0.077        BUYMA手数料 = 12320
        #         = 4880
        ws.update_cell.assert_called_once_with(2, COLUMNS.index("利益額") + 1, "4880.0")

    def test_recalculates_profit_with_custom_rates(self):
        rows = [
            COLUMNS,
            ["商品B", "CELINE", "CE-001", "", "500", "155", "120000", "在庫あり", ""],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        count = manager.recalculate_profit(
            exchange_rate=155.0, fee_rate=0.077, customs_rate=0.10, shipping_cost_jpy=2000
        )
        self.assertEqual(count, 1)
        # jpy_cost = 500 × 155 = 77500
        # customs = 77500 × 0.10 = 7750
        # buyma_fee = 120000 × 0.077 = 9240
        # profit = 120000 - 77500 - 7750 - 2000 - 9240 = 23510
        ws.update_cell.assert_called_once_with(2, COLUMNS.index("利益額") + 1, "23510.0")

    def test_skips_non_numeric_rows(self):
        rows = [
            COLUMNS,
            ["商品B", "", "", "", "N/A", "N/A", "N/A", "", ""],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        count = manager.recalculate_profit()
        self.assertEqual(count, 0)

    def test_empty_sheet_returns_zero(self):
        ws = _make_worksheet([COLUMNS])
        manager = _make_manager(ws)
        self.assertEqual(manager.recalculate_profit(), 0)


# ---------------------------------------------------------------------------
# SheetManager._col_letter
# ---------------------------------------------------------------------------

class TestColLetter(unittest.TestCase):

    def test_single_letters(self):
        self.assertEqual(SheetManager._col_letter(1), "A")
        self.assertEqual(SheetManager._col_letter(26), "Z")

    def test_double_letters(self):
        self.assertEqual(SheetManager._col_letter(27), "AA")
        self.assertEqual(SheetManager._col_letter(52), "AZ")
        self.assertEqual(SheetManager._col_letter(53), "BA")


# ---------------------------------------------------------------------------
# SheetManager.search_records / update_status
# ---------------------------------------------------------------------------

class TestSheetManagerSearchAndStatus(unittest.TestCase):

    def test_search_records_by_product_name(self):
        rows = [
            COLUMNS,
            ["Gucci Bag", "GUCCI", "", "", "", "", "", "出品中", "", ""],
            ["Other Item", "LV", "", "", "", "", "", "出品中", "", ""],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        found = manager.search_records("gucci", field="商品名")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].商品名, "Gucci Bag")

    def test_update_status(self):
        rows = [
            COLUMNS,
            ["商品X", "BR", "", "", "", "", "", "在庫あり", "", ""],
        ]
        ws = _make_worksheet(rows)
        manager = _make_manager(ws)
        ok = manager.update_status("商品X", "停止中")
        self.assertTrue(ok)
        status_col = COLUMNS.index("在庫ステータス") + 1
        ws.update_cell.assert_called_with(2, status_col, "停止中")


# SheetManager.ensure_header
# ---------------------------------------------------------------------------

class TestEnsureHeader(unittest.TestCase):

    def test_writes_header_when_empty(self):
        ws = MagicMock()
        ws.row_values.return_value = []
        manager = SheetManager.__new__(SheetManager)
        manager._worksheet = ws
        manager.ensure_header()
        ws.append_row.assert_called_once_with(COLUMNS)

    def test_does_not_overwrite_existing_header(self):
        ws = MagicMock()
        ws.row_values.return_value = COLUMNS
        manager = SheetManager.__new__(SheetManager)
        manager._worksheet = ws
        manager.ensure_header()
        ws.append_row.assert_not_called()


if __name__ == "__main__":
    unittest.main()
