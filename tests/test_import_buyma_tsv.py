"""scripts/import_buyma_tsv.py のユニットテスト（ネットワーク・シート接続なし）。"""

from __future__ import annotations

import importlib.util
import pathlib
import unittest
from unittest.mock import MagicMock

from lib.sheet_manager import ProductRecord


def _load_import_module():
    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "scripts" / "import_buyma_tsv.py"
    spec = importlib.util.spec_from_file_location("import_buyma_tsv", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestImportBuymaTsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_import_module()

    def test_parse_tsv_text_parses_header_and_rows(self) -> None:
        raw = (
            "buyma_url\ttitle_guess\tlist_page_url\n"
            "https://www.buyma.com/item/12345/\tCELINE Bag\thttps://www.buyma.com/buy/\n"
        )
        rows = self.mod.parse_tsv_text(raw)
        self.assertEqual(len(rows), 1)
        self.assertIn("12345", rows[0]["buyma_url"])
        self.assertEqual(rows[0]["title_guess"], "CELINE Bag")

    def test_row_to_record_builds_buyma_candidate(self) -> None:
        rec = self.mod.row_to_record(
            {
                "buyma_url": "https://www.buyma.com/item/99999/",
                "title_guess": "テスト商品",
            }
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.在庫ステータス, self.mod.STATUS_BUYMA_CANDIDATE)
        self.assertEqual(rec.型番, "99999")
        self.assertEqual(rec.商品名, "テスト商品")
        self.assertEqual(rec.BUYMA販売価格, "")

    def test_row_to_record_maps_optional_list_price_guess(self) -> None:
        rec = self.mod.row_to_record(
            {
                "buyma_url": "https://www.buyma.com/item/99999/",
                "title_guess": "PRADA 財布",
                "price_guess_jpy": "59800",
            }
        )
        assert rec is not None
        self.assertEqual(rec.BUYMA販売価格, "59800")

    def test_row_to_record_rejects_non_buyma_url(self) -> None:
        self.assertIsNone(
            self.mod.row_to_record({"buyma_url": "https://www.ssense.com/product/1"})
        )

    def test_existing_buyma_urls_collects_normalized_urls(self) -> None:
        manager = MagicMock()
        manager.get_all_records.return_value = [
            ProductRecord(仕入れURL="https://www.BUYMA.com/item/1/"),
            ProductRecord(仕入れURL="https://www.ssense.com/x"),
        ]
        urls = self.mod.existing_buyma_urls(manager)
        self.assertEqual(urls, {"https://www.buyma.com/item/1"})


if __name__ == "__main__":
    unittest.main()
