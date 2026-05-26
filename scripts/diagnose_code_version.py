#!/usr/bin/env python3
"""実行中のコードが最新版か確認する（Windows で py intake 前に実行推奨）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _git_head() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "（git 不明）"


def _git_branch() -> str:
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip() or "（detached）"
    except Exception:
        pass
    return "（不明）"


def main() -> int:
    print("=== invedia-automation コード診断 ===")
    print(f"  フォルダ: {_ROOT}")
    print(f"  ブランチ: {_git_branch()}")
    print(f"  コミット: {_git_head()}")
    print()

    ok = True
    bad = "https://www.farfetch.com/jp/shopping/women/prada--item-30953.aspx"

    try:
        from lib.supply_search_utils import is_valid_farfetch_product_url
    except ImportError:
        print("NG: supply_search_utils に is_valid_farfetch_product_url がありません")
        print("    → 最新_仕入れ自動化を取得.bat を実行してください")
        return 1

    if is_valid_farfetch_product_url(bad):
        print("NG: 壊れた FARFETCH URL を通してしまいます（古いコード）")
        ok = False
    else:
        print("OK: prada--item 形式の FARFETCH URL は除外されます")

    try:
        import intake
        import intake_funnel
        from lib.supply_url_finder import discover_supply_urls_funnel

        if not hasattr(intake, "_check_auto_intake_features"):
            print("NG: intake 自動チェックなし")
            ok = False
        elif not callable(discover_supply_urls_funnel):
            print("NG: discover_supply_urls_funnel なし（古いコード）")
            ok = False
        else:
            print("OK: intake 漏斗 v7（intake_funnel + site検索）")
    except ImportError as e:
        print(f"NG: intake / 漏斗モジュール: {e}")
        ok = False

    engine_py = _ROOT / "scraper" / "engine.py"
    if engine_py.is_file():
        eng = engine_py.read_text(encoding="utf-8")
        if "_goto_with_fallback" in eng:
            print("OK: FARFETCH は domcontentloaded（networkidle 不使用）")
        else:
            print("NG: scraper/engine.py が古い（networkidle のまま）→ 修復 bat 実行")
            ok = False
    else:
        print("NG: scraper/engine.py がありません")
        ok = False

    print()
    if ok:
        print("この環境で py intake.py --auto-sheet を実行して問題ありません。")
        print("自動モード開始時に [intake 自動 v7] と漏斗モード表示を確認してください。")
        return 0

    print("対処:")
    print("  1. 最新_仕入れ自動化を取得.bat をダブルクリック")
    print("  2. py scripts\\verify_intake_version.py")
    print("  3. py intake.py --auto-sheet --limit 1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
