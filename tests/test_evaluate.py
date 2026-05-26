"""evaluate.py のテスト。

_prompt / interactive_mode は入力が必要なため除外し、
ロジック部分（_record_to_input, demo_mode, _export_csv, main）をテストする。
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lib.evaluate import (
    _export_csv,
    _record_to_input,
    demo_mode,
    main,
)
from lib.purchase_evaluator import EvaluationInput, PurchaseEvaluator, PurchaseScore


# ── _record_to_input テスト ──────────────────────────────────────────────


class _FakeRecord:
    """ProductRecord の最小互換スタブ。"""

    def __init__(
        self,
        *,
        name="テストバッグ",
        brand="GUCCI",
        price="800",
        rate="155",
        buyma="180000",
        url="https://example.com/product",
    ):
        self.商品名 = name
        self.ブランド = brand
        self.現地価格 = price
        self.為替 = rate
        self.BUYMA販売価格 = buyma
        self.仕入れURL = url
        self.在庫ステータス = "出品中"
        self.利益額 = "30000"


class _FakeConfig:
    """Config の最小互換スタブ。"""

    customs_rate = 0.10
    shipping_cost_jpy = 2000.0
    buyma_fee_rate = 0.077
    target_profit_rate = 0.15
    spreadsheet_id = "dummy"
    worksheet_name = "sheet1"
    credentials_path = "creds.json"

    def validate(self):
        return []

    @classmethod
    def from_env(cls):
        return cls()


class TestRecordToInput:
    """_record_to_input の単体テスト。"""

    def test_valid_record(self):
        rec = _FakeRecord()
        cfg = _FakeConfig()
        inp = _record_to_input(rec, cfg)
        assert inp is not None
        assert inp.product_name == "テストバッグ"
        assert inp.brand == "GUCCI"
        assert inp.source_price == 800.0
        assert inp.exchange_rate == 155.0
        assert inp.buyma_price == 180000.0
        assert inp.customs_rate == 0.10
        assert inp.source_type == "select"

    def test_zero_price_returns_none(self):
        rec = _FakeRecord(price="0")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_zero_rate_returns_none(self):
        rec = _FakeRecord(rate="0")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_zero_buyma_returns_none(self):
        rec = _FakeRecord(buyma="0")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_negative_price_returns_none(self):
        rec = _FakeRecord(price="-100")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_non_numeric_price_returns_none(self):
        rec = _FakeRecord(price="abc")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_empty_price_returns_none(self):
        rec = _FakeRecord(price="")
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_none_price_returns_none(self):
        rec = _FakeRecord(price=None)
        assert _record_to_input(rec, _FakeConfig()) is None

    def test_defaults_applied(self):
        rec = _FakeRecord()
        cfg = _FakeConfig()
        inp = _record_to_input(rec, cfg)
        assert inp.model_year == 2024
        assert inp.currency == "USD"
        assert inp.dispatch_days == 5
        assert inp.japan_arrival_days == 10
        assert inp.is_realtime_stock is True
        assert inp.packaging_quality == "good"
        assert inp.japan_retail_price == 0.0


# ── demo_mode テスト ──────────────────────────────────────────────────────


class TestDemoMode:
    """demo_mode の統合テスト（実際に PurchaseEvaluator が動く）。"""

    def test_demo_returns_scores(self):
        scores = demo_mode()
        assert len(scores) == 3
        for s in scores:
            assert hasattr(s, "grade")
            assert s.grade in ("A", "B", "C", "D", "E")

    def test_demo_grades_order(self):
        scores = demo_mode()
        grades = [s.grade for s in scores]
        assert all(g in "ABCDE" for g in grades)

    def test_demo_has_product_names(self):
        scores = demo_mode()
        names = {s.product_name for s in scores}
        assert "GG マーモント ミニバッグ (黒)" in names
        assert "バーキン 30 (エトゥープ)" in names


# ── _export_csv テスト ────────────────────────────────────────────────────


class TestExportCsv:
    """_export_csv のテスト。"""

    def _make_score(self, name: str = "テスト商品", grade: str = "A") -> PurchaseScore:
        inp = EvaluationInput(
            product_name=name,
            brand="GUCCI",
            model_year=2025,
            source_url="https://example.com",
            source_price=800.0,
            currency="USD",
            exchange_rate=155.0,
            buyma_price=180000,
            japan_retail_price=200000,
            dispatch_days=3,
            japan_arrival_days=7,
            is_realtime_stock=True,
            packaging_quality="excellent",
            buyma_rank=5,
            sns_trending=True,
            japan_soldout=True,
            japan_exclusive=False,
            favorites_count=35,
            has_cart_addition=True,
            source_type="authorized",
            is_volume_zone=True,
            customs_rate=0.10,
            shipping_cost_jpy=2000,
            buyma_fee_rate=0.077,
            fx_buffer_rate=0.03,
            target_profit_rate=0.15,
        )
        evaluator = PurchaseEvaluator()
        return evaluator.evaluate(inp)

    def test_csv_file_created(self, tmp_path):
        scores = [self._make_score()]
        csv_path = str(tmp_path / "test.csv")
        _export_csv(scores, csv_path)
        assert os.path.exists(csv_path)

    def test_csv_has_header(self, tmp_path):
        scores = [self._make_score()]
        csv_path = str(tmp_path / "test.csv")
        _export_csv(scores, csv_path)
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
        assert "商品名" in headers
        assert "グレード" in headers
        assert "総合スコア" in headers

    def test_csv_correct_rows(self, tmp_path):
        scores = [self._make_score("商品A"), self._make_score("商品B")]
        csv_path = str(tmp_path / "test.csv")
        _export_csv(scores, csv_path)
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["商品名"] == "商品A"
        assert rows[1]["商品名"] == "商品B"

    def test_csv_empty_scores(self, tmp_path):
        csv_path = str(tmp_path / "empty.csv")
        _export_csv([], csv_path)
        assert not os.path.exists(csv_path)


# ── main テスト ───────────────────────────────────────────────────────────


class TestMain:
    """main() の引数パース・分岐テスト。"""

    def test_demo_flag(self):
        with patch("sys.argv", ["evaluate.py", "--demo"]):
            ret = main()
        assert ret == 0

    def test_sheet_without_config_fails(self):
        with patch("sys.argv", ["evaluate.py", "--sheet"]):
            with patch("lib.evaluate.Config") as MockConfig:
                mock_cfg = MagicMock()
                mock_cfg.validate.return_value = ["SPREADSHEET_ID missing"]
                MockConfig.from_env.return_value = mock_cfg
                ret = main()
        assert ret == 1
