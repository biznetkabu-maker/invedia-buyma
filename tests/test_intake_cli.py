"""intake_cli モジュールのテスト。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from lib.intake_cli import (
    ask,
    ask_float,
    ask_int,
    ask_yn,
    cli_print,
    print_header,
    print_score,
    print_step,
    require,
)


class TestPrintHeader:
    def test_no_error(self, capsys):
        print_header()
        out = capsys.readouterr().out
        assert "BUYMA" in out


class TestPrintStep:
    def test_format(self, capsys):
        print_step(1, "テスト")
        out = capsys.readouterr().out
        assert "Step 1" in out
        assert "テスト" in out


class TestAsk:
    @patch("builtins.input", return_value="hello")
    def test_returns_input(self, _mock):
        assert ask("label") == "hello"

    @patch("builtins.input", return_value="")
    def test_returns_default(self, _mock):
        assert ask("label", default="fallback") == "fallback"


class TestAskFloat:
    @patch("builtins.input", return_value="210000")
    def test_parses_float(self, _mock):
        assert ask_float("price") == 210000.0

    @patch("builtins.input", return_value="")
    def test_default(self, _mock):
        assert ask_float("price", default=99.9) == 99.9

    @patch("builtins.input", side_effect=["abc", "100"])
    def test_retries_on_invalid(self, _mock):
        assert ask_float("price") == 100.0


class TestAskInt:
    @patch("builtins.input", return_value="42")
    def test_parses_int(self, _mock):
        assert ask_int("count") == 42

    @patch("builtins.input", return_value="")
    def test_default(self, _mock):
        assert ask_int("count", default=5) == 5


class TestAskYn:
    @patch("builtins.input", return_value="y")
    def test_yes(self, _mock):
        assert ask_yn("continue?") is True

    @patch("builtins.input", return_value="n")
    def test_no(self, _mock):
        assert ask_yn("continue?") is False

    @patch("builtins.input", return_value="")
    def test_default_true(self, _mock):
        assert ask_yn("continue?", default=True) is True

    @patch("builtins.input", return_value="")
    def test_default_false(self, _mock):
        assert ask_yn("continue?", default=False) is False


class TestAskIntRetry:
    @patch("builtins.input", side_effect=["xx", "7"])
    def test_retries_on_invalid(self, _mock):
        assert ask_int("count") == 7


class TestRequire:
    @patch("builtins.input", side_effect=["", "value"])
    def test_reprompts_until_nonempty(self, _mock):
        assert require("name") == "value"


class TestCliPrintLoggerMode:
    @patch.dict("os.environ", {"BUYMA_CLI_LOG": "1"})
    def test_routes_to_logger(self, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="buyma.cli"):
            cli_print("hello world")
        assert "hello world" in caplog.text

    @patch.dict("os.environ", {"BUYMA_CLI_LOG": "1"})
    def test_blank_message_skipped(self, capsys):
        cli_print("   ")
        assert capsys.readouterr().out == ""


class TestPrintScore:
    def _score(self, **kw):
        defaults = dict(
            grade="A",
            overall_score=82.5,
            effective_profit_rate=0.18,
            profit_breakdown=SimpleNamespace(profit=35000),
            critical_issues=[],
            improvements=[],
        )
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def test_full_output(self, capsys):
        score = self._score(
            critical_issues=["在庫リスク"],
            improvements=["価格見直し", "画像追加", "説明強化", "4件目"],
        )
        print_score(score)
        out = capsys.readouterr().out
        assert "グレード: A" in out
        assert "35,000" in out
        assert "在庫リスク" in out
        assert "価格見直し" in out
        # 改善提案は上位3件のみ
        assert "4件目" not in out

    def test_no_breakdown(self, capsys):
        print_score(self._score(profit_breakdown=None))
        out = capsys.readouterr().out
        assert "グレード: A" in out
