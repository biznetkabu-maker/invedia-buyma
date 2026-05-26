#!/usr/bin/env python3
"""初回1回だけ: spreadsheet_id.txt / worksheet_name.txt を作る（.env 不要）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def extract_spreadsheet_id(text: str) -> str:
    text = text.strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if m:
        return m.group(1)
    return text


def main() -> int:
    print()
    print("=" * 50)
    print("  BUYMA 簡易セットアップ（初回だけ）")
    print("=" * 50)
    print()
    print("Google スプレッドシートをブラウザで開き、")
    print("アドレスバーの URL をそのまま貼り付けて Enter:")
    print("（ID だけでも可）")
    print()
    raw = input("> ").strip()
    if not raw:
        print("キャンセルしました。")
        return 1

    sid = extract_spreadsheet_id(raw)
    (_ROOT / "spreadsheet_id.txt").write_text(sid + "\n", encoding="utf-8")
    print(f"\n保存しました: spreadsheet_id.txt")

    print()
    print("シートのタブ名（下のタブ）を入力して Enter")
    print("（空 Enter = PurchaseControl。Google の下タブ名と完全一致させる）")
    tab = input("> ").strip() or "PurchaseControl"
    (_ROOT / "worksheet_name.txt").write_text(tab + "\n", encoding="utf-8")
    print(f"保存しました: worksheet_name.txt → {tab}")
    print()
    print("Google シート側のタブ名も同じ名前にしてください。")
    print("確認: py scripts/sheets_cli.py tabs  または  シート接続確認.bat")

    cred = _ROOT / "credentials.json"
    print()
    if cred.is_file():
        print("OK: credentials.json があります。")
    else:
        print("次に credentials.json をこのフォルダに置いてください:")
        print(f"  {_ROOT}")
        print("サービスアカウントをシートの「編集者」に追加も忘れずに。")

    print()
    print("-" * 50)
    print("セットアップ完了。")
    print("日常は: BUYMA で TSV コピー → BUYMA取込.bat をダブルクリック")
    print("-" * 50)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
