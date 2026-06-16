"""lib.intake_pipeline のテスト。"""

from unittest.mock import MagicMock, patch

from lib import intake_pipeline
from lib.purchase_evaluator import PurchaseScore
from lib.sheet_manager import ProductRecord


class TestEvaluate:
    def test_returns_purchase_score(self):
        score = intake_pipeline.evaluate(
            brand="PRADA",
            product_name="Re-Nylon bag",
            category="バッグ",
            model_year=2024,
            source_url="https://www.prada.com/p/x.html",
            source_price=1000.0,
            currency="EUR",
            exchange_rate=160.0,
            buyma_price=250000.0,
        )
        assert isinstance(score, PurchaseScore)
        assert score.grade in {"A", "B", "C", "D", "F"}

    def test_floors_non_positive_prices(self):
        # source_price/buyma_price=0 でも例外なく評価できる
        score = intake_pipeline.evaluate(
            brand="GUCCI",
            product_name="wallet",
            category="財布",
            model_year=2023,
            source_url="",
            source_price=0.0,
            currency="EUR",
            exchange_rate=160.0,
            buyma_price=0.0,
        )
        assert isinstance(score, PurchaseScore)

    def test_uses_demand_signal_when_present(self):
        signal = MagicMock()
        signal.favorites_count = 99
        signal.has_cart = True
        score = intake_pipeline.evaluate(
            brand="PRADA", product_name="bag", category="バッグ",
            model_year=2024, source_url="https://x", source_price=500.0,
            currency="EUR", exchange_rate=160.0, buyma_price=120000.0,
            demand_signal=signal,
        )
        assert isinstance(score, PurchaseScore)


class TestBuildRecord:
    def _score(self, profit=None):
        s = MagicMock()
        if profit is None:
            s.profit_breakdown = None
        else:
            s.profit_breakdown.profit = profit
        return s

    def test_basic_fields(self):
        rec = intake_pipeline.build_record(
            brand="PRADA", product_name="Re-Nylon bag",
            source_url="https://www.prada.com/p/x.html",
            source_price=1234.567, exchange_rate=160.12,
            buyma_price=250000.0, candidate_urls=["u1"],
            score=self._score(profit=54321.0),
            buyma_style_id=" 1BG023 ",
        )
        assert isinstance(rec, ProductRecord)
        assert rec.ブランド == "PRADA"
        assert rec.商品名 == "PRADA Re-Nylon bag"
        assert rec.型番 == "1BG023"  # trim 済み
        assert rec.現地価格 == "1234.57"
        assert rec.為替 == "160.12"
        assert rec.BUYMA販売価格 == "250000"
        assert rec.利益額 == "54321"
        assert rec.在庫ステータス == "出品前"

    def test_no_profit_breakdown_and_single_candidate(self):
        rec = intake_pipeline.build_record(
            brand="X", product_name="y", source_url="",
            source_price=0.0, exchange_rate=160.0, buyma_price=0.0,
            candidate_urls=["only"], score=self._score(profit=None),
        )
        assert rec.利益額 == ""
        assert rec.現地価格 == ""
        assert rec.BUYMA販売価格 == ""
        assert rec.候補URLs == ""  # 候補1件はまとめない

    def test_multiple_candidates_joined(self):
        rec = intake_pipeline.build_record(
            brand="X", product_name="y", source_url="",
            source_price=10.0, exchange_rate=160.0, buyma_price=1000.0,
            candidate_urls=["a", "b", "c"], score=self._score(profit=1.0),
        )
        assert rec.候補URLs == "a,b,c"

    def test_match_score_grade_and_note(self):
        ms = MagicMock()
        ms.grade = "S"
        ms.price_note = "official " * 100  # 200 文字超で切り詰め確認
        rec = intake_pipeline.build_record(
            brand="X", product_name="y", source_url="",
            source_price=10.0, exchange_rate=160.0, buyma_price=1000.0,
            candidate_urls=[], score=self._score(profit=1.0),
            match_score=ms,
        )
        assert rec.同一性スコア == "S"
        assert len(rec.価格根拠) <= 200


def _record() -> ProductRecord:
    return ProductRecord(
        商品名="PRADA bag", ブランド="PRADA", 型番="1BG023",
        仕入れURL="https://x", 現地価格="1000", 為替="160",
        BUYMA販売価格="250000", 在庫ステータス="出品前", 利益額="50000",
    )


class TestWriteToSheet:
    def test_skips_when_manager_unavailable(self):
        with patch.object(
            intake_pipeline, "_build_manager",
            return_value=(None, ["設定エラー"]),
        ):
            # 例外を出さずに return することを確認
            intake_pipeline.write_to_sheet(_record())

    def test_writes_via_manager(self):
        mgr = MagicMock()
        mgr.upsert_record.return_value = "appended"
        with patch.object(
            intake_pipeline, "_build_manager", return_value=(mgr, []),
        ):
            intake_pipeline.write_to_sheet(_record())
        mgr.ensure_header.assert_called_once()
        mgr.upsert_record.assert_called_once()

    def test_handles_manager_exception(self):
        mgr = MagicMock()
        mgr.upsert_record.side_effect = RuntimeError("boom")
        with patch.object(
            intake_pipeline, "_build_manager", return_value=(mgr, []),
        ):
            intake_pipeline.write_to_sheet(_record())  # 例外は握って出力


class TestWriteToSheetQuiet:
    def test_returns_false_when_unavailable(self):
        with patch.object(
            intake_pipeline, "_build_manager", return_value=(None, ["e"]),
        ):
            assert intake_pipeline.write_to_sheet_quiet(_record()) is False

    def test_returns_true_on_success(self):
        mgr = MagicMock()
        mgr.upsert_record.return_value = "updated"
        with patch.object(
            intake_pipeline, "_build_manager", return_value=(mgr, []),
        ):
            assert intake_pipeline.write_to_sheet_quiet(_record()) is True

    def test_returns_false_on_exception(self):
        mgr = MagicMock()
        mgr.ensure_header.side_effect = RuntimeError("boom")
        with patch.object(
            intake_pipeline, "_build_manager", return_value=(mgr, []),
        ):
            assert intake_pipeline.write_to_sheet_quiet(_record()) is False


class TestBuildManager:
    def test_returns_none_when_config_invalid(self):
        cfg = MagicMock()
        cfg.validate.return_value = ["missing creds"]
        with patch("lib.config.Config.from_env", return_value=cfg):
            mgr, errors = intake_pipeline._build_manager()
        assert mgr is None
        assert errors == ["missing creds"]

    def test_builds_manager_when_config_valid(self):
        cfg = MagicMock()
        cfg.validate.return_value = []
        cfg.spreadsheet_id = "sid"
        cfg.worksheet_name = "ws"
        cfg.credentials_path = "creds.json"
        with patch("lib.config.Config.from_env", return_value=cfg), \
                patch("lib.intake_pipeline.SheetManager") as SM:
            mgr, errors = intake_pipeline._build_manager()
        assert errors == []
        SM.assert_called_once_with(
            spreadsheet_id="sid", worksheet_name="ws",
            credentials_path="creds.json",
        )
        assert mgr is SM.return_value
