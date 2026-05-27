"""intake_cli モジュールのテスト。"""

from __future__ import annotations

from unittest.mock import patch

from lib.intake_cli import ask, ask_float, ask_int, ask_yn, print_header, print_step


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
