"""intake.py の CLI ユーティリティ関数群。

対話入力・表示ヘルパーを分離して、intake.py のビジネスロジックから
UI 部分を切り離す。
"""

from __future__ import annotations

from lib.purchase_evaluator import PurchaseScore

_GRADE_ICONS = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "⛔"}


def print_header() -> None:
    print("\n" + "=" * 60)
    print("  BUYMA 商品取り込みツール")
    print("=" * 60)
    print("  【手動】基本情報入力・URLの確認・最終判断")
    print("  【自動】為替・需要・型番照合・スクレイプ・シート追加")
    print()


def print_step(n: int | float, label: str) -> None:
    print(f"\n── Step {n}: {label} {'─' * max(0, 44 - len(label) - len(str(n)))}")


def print_score(score: PurchaseScore) -> None:
    icon = _GRADE_ICONS.get(score.grade, "❓")
    print(f"\n  {icon} グレード: {score.grade}  スコア: {score.overall_score:.1f}")
    print(f"     実質利益率: {score.effective_profit_rate:.1%}", end="")
    if score.profit_breakdown:
        print(f"  利益額: ¥{score.profit_breakdown.profit:,.0f}")
    else:
        print()
    if score.critical_issues:
        print("  ⚠️  致命的問題:")
        for issue in score.critical_issues:
            print(f"       - {issue}")
    if score.improvements:
        print("  💡 改善提案（上位3件）:")
        for tip in score.improvements[:3]:
            print(f"       - {tip}")


def require(label: str, hint: str = "") -> str:
    hint_str = f"（{hint}）" if hint else ""
    while True:
        val = input(f"  {label}{hint_str}: ").strip()
        if val:
            return val
        print("    ⚠️  必須項目です。")


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
            print("    ⚠️  数値を入力してください（例: 210000）。")


def ask_int(label: str, default: int = 0) -> int:
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("    ⚠️  整数を入力してください。")


def ask_yn(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "はい", "1")
