#!/usr/bin/env python3
"""スプレッドシートのタブ名一覧を表示し、worksheet_name.txt との一致を確認する。

古い sheets_cli.py に tabs が無い場合も使える。

  py scripts\\list_sheet_tabs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.config import Config
from lib.sheet_manager import SCOPES, SheetManager
from oauth2client.service_account import ServiceAccountCredentials
import gspread


def main() -> int:
    cfg = Config.from_env()
    errors = cfg.validate()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            cfg.credentials_path, SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(cfg.spreadsheet_id)
        titles = [ws.title for ws in spreadsheet.worksheets()]
    except Exception as e:
        print(f"ERROR: 接続失敗: {e}", file=sys.stderr)
        return 1

    configured = cfg.worksheet_name
    match = configured in titles

    print()
    print(f"スプレッドシート: {spreadsheet.title}")
    print(f"設定中のタブ名 (worksheet_name.txt): {configured!r}")
    print()
    print("利用可能なタブ:")
    for i, t in enumerate(titles, 1):
        mark = "  ← 一致" if t == configured else ""
        print(f"  {i}. {t}{mark}")
    print()

    if match:
        print("OK: タブ名は一致しています。")
        return 0

    print("NG: タブ名が一致していません。")
    print("  → メモ帳で worksheet_name.txt を開き、上のタブ名のどれかを1行だけ貼って保存")
    return 1


if __name__ == "__main__":
    sys.exit(main())
