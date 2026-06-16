"""intake.py の CLI ユーティリティ関数群。

対話入力・表示ヘルパーを分離して、intake.py のビジネスロジックから
UI 部分を切り離す。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from lib.purchase_evaluator import PurchaseScore

_GRADE_ICONS = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "⛔"}

_cli_logger = logging.getLogger("buyma.cli")


def _use_logger() -> bool:
    """CI / 非対話実行では BUYMA_CLI_LOG=1 で出力を logger に集約する。"""
    return os.getenv("BUYMA_CLI_LOG", "").strip().lower() in ("1", "true", "yes", "on")


def cli_print(*args: Any, sep: str = " ", end: str = "\n", flush: bool = False) -> None:
    """対話CLI向けの出力。

    既定では ``print`` と同じ挙動。環境変数 ``BUYMA_CLI_LOG=1`` のときは
    ``logger.info`` に流し、GitHub Actions 等で構造化ログと混在しないようにする。
    """
    if _use_logger():
        msg = sep.join(str(a) for a in args).rstrip()
        if msg:
            _cli_logger.info(msg)
    else:
        print(*args, sep=sep, end=end, flush=flush)


def print_header() -> None:
    cli_print("\n" + "=" * 60)
    cli_print("  BUYMA 商品取り込みツール")
    cli_print("=" * 60)
    cli_print("  【手動】基本情報入力・URLの確認・最終判断")
    cli_print("  【自動】為替・需要・型番照合・スクレイプ・シート追加")
    cli_print()


def print_step(n: int | float, label: str) -> None:
    cli_print(f"\n── Step {n}: {label} {'─' * max(0, 44 - len(label) - len(str(n)))}")


def print_score(score: PurchaseScore) -> None:
    icon = _GRADE_ICONS.get(score.grade, "❓")
    cli_print(f"\n  {icon} グレード: {score.grade}  スコア: {score.overall_score:.1f}")
    cli_print(f"     実質利益率: {score.effective_profit_rate:.1%}", end="")
    if score.profit_breakdown:
        cli_print(f"  利益額: ¥{score.profit_breakdown.profit:,.0f}")
    else:
        cli_print()
    if score.critical_issues:
        cli_print("  ⚠️  致命的問題:")
        for issue in score.critical_issues:
            cli_print(f"       - {issue}")
    if score.improvements:
        cli_print("  💡 改善提案（上位3件）:")
        for tip in score.improvements[:3]:
            cli_print(f"       - {tip}")


def require(label: str, hint: str = "") -> str:
    hint_str = f"（{hint}）" if hint else ""
    while True:
        val = input(f"  {label}{hint_str}: ").strip()
        if val:
            return val
        cli_print("    ⚠️  必須項目です。")


def ask(label: str, default: str = "", hint: str = "") -> str:
    hint_str = f"（{hint}）" if hint else ""
    raw = input(f"  {label}{hint_str} [{default}]: ").strip()
    return raw if raw else default


def ask_float(label: str, default: float = 0.0) -> float:
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            cli_print("    ⚠️  数値を入力してください（例: 210000）。")


def ask_int(label: str, default: int = 0) -> int:
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            cli_print("    ⚠️  整数を入力してください。")


def ask_yn(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "はい", "1")
