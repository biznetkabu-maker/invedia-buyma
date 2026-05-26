#!/usr/bin/env python3
"""
ブックマークレットがコピーした TSV を Google スプレッドシートに追記する。

使い方（いちばん手軽）:
  1. BUYMA でブックマークレット → 「TSV をコピー」
  2. リポジトリルートで:
       python3 scripts/import_buyma_tsv.py --clipboard

ファイル経由:
       python3 scripts/import_buyma_tsv.py candidates.tsv

前提:
  - .env に SPREADSHEET_ID, WORKSHEET_NAME, CREDENTIALS_PATH
  - サービスアカウントをシートの「編集者」に追加済み

追記される行:
  - 商品名: title_guess（空なら BUYMA 商品ID）
  - 型番: 商品ID（数字）
  - 仕入れURL: buyma_url（参照用。main.py は buyma.com をスクレイプしません）
  - 在庫ステータス: BUYMA候補
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
from pathlib import Path

# リポジトリルートを import パスに追加
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.config import Config
from lib.sheet_manager import ProductRecord, SheetManager

STATUS_BUYMA_CANDIDATE = "BUYMA候補"
_ITEM_ID_RE = re.compile(r"/item/(\d+)", re.I)


def _item_id_from_url(url: str) -> str:
    m = _ITEM_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def parse_tsv_text(raw: str) -> list[dict[str, str]]:
    """TSV 文字列をパースする（UTF-8 BOM 付きも可）。"""
    if not raw.strip():
        return []
    # utf-8-sig 相当: BOM を除去
    if raw.startswith("\ufeff"):
        raw = raw.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    if not reader.fieldnames:
        return []
    out: list[dict[str, str]] = []
    for row in reader:
        norm = {_normalize_header(k): (v or "").strip() for k, v in row.items()}
        out.append(
            {
                "buyma_url": norm.get("buyma_url", ""),
                "title_guess": norm.get("title_guess", ""),
                "list_page_url": norm.get("list_page_url", ""),
                "price_guess_jpy": norm.get("price_guess_jpy", ""),
            }
        )
    return out


def load_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return parse_tsv_text(f.read())


def read_clipboard_text() -> str:
    """OS のクリップボードからテキストを取得する（追加ライブラリ不要）。"""
    import platform

    system = platform.system()
    if system == "Darwin":
        return subprocess.check_output(["pbpaste"], text=True)
    if system == "Windows":
        # -Raw: 改行入り TSV を1ブロックとして取得
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Clipboard -Raw",
        ]
        return subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    for cmd in (
        ["wl-paste", "-n"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        try:
            return subprocess.check_output(cmd, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError(
        "クリップボードを読めませんでした。"
        " candidates.tsv に保存してファイル指定するか、"
        " Linux では wl-clipboard / xclip をインストールしてください。"
    )


def row_to_record(row: dict[str, str]) -> ProductRecord | None:
    url = row.get("buyma_url", "").strip()
    if not url or "buyma.com" not in url.lower():
        return None
    item_id = _item_id_from_url(url)
    title = row.get("title_guess", "").strip()
    name = title if title else (f"BUYMA 商品 {item_id}" if item_id else "BUYMA 候補")
    price_guess = (row.get("price_guess_jpy") or "").strip().replace(",", "")
    return ProductRecord(
        商品名=name,
        ブランド="",
        型番=item_id,
        仕入れURL=url,
        現地価格="",
        為替="",
        BUYMA販売価格=price_guess,
        在庫ステータス=STATUS_BUYMA_CANDIDATE,
        利益額="",
        候補URLs="",
    )


def existing_buyma_urls(manager: SheetManager) -> set[str]:
    urls: set[str] = set()
    for r in manager.get_all_records():
        u = (r.仕入れURL or "").strip().lower()
        if u and "buyma.com" in u:
            urls.add(u.rstrip("/"))
    return urls


def _resolve_tsv_text(args: argparse.Namespace) -> str:
    if args.clipboard or args.file is None:
        print("クリップボードから TSV を読み込み中...")
        return read_clipboard_text()
    if args.file == "-":
        return sys.stdin.read()
    path = Path(args.file)
    if not path.is_file():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return path.read_text(encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ブックマークレットの TSV を Google スプレッドシートに追記する",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="TSV ファイル（省略時はクリップボード）。'-' で標準入力",
    )
    parser.add_argument(
        "--clipboard",
        "-c",
        action="store_true",
        help="クリップボードから取り込む（引数省略時と同じ）",
    )
    args = parser.parse_args()

    try:
        raw = _resolve_tsv_text(args)
    except FileNotFoundError as e:
        print(e)
        return 1
    except RuntimeError as e:
        print(e)
        return 1

    rows = parse_tsv_text(raw)
    if not rows:
        print("TSV にデータ行がありません。")
        print("ヒント: ブックマークレットで「TSV をコピー」した直後に実行してください。")
        return 1

    config = Config.from_env()
    errors = config.validate()
    if errors:
        print("設定が不足しています（初回だけ設定.bat を実行）:")
        for e in errors:
            print(f"  - {e}")
        return 1

    manager = SheetManager(
        spreadsheet_id=config.spreadsheet_id,
        worksheet_name=config.worksheet_name,
        credentials_path=config.credentials_path,
    )
    manager.ensure_header()

    seen = existing_buyma_urls(manager)
    to_add: list[ProductRecord] = []
    skipped = 0

    for row in rows:
        rec = row_to_record(row)
        if rec is None:
            skipped += 1
            continue
        key = rec.仕入れURL.strip().lower().rstrip("/")
        if key in seen:
            skipped += 1
            continue
        to_add.append(rec)
        seen.add(key)

    added = 0
    if to_add:
        print(f"  シートへ一括書き込み中（{len(to_add)} 件）…")
        try:
            manager.append_records(to_add)
        except Exception as exc:
            if "429" in str(exc):
                print()
                print("  ⚠ Google の書き込み制限に達しました。")
                print("    1〜2分待ってから BUYMA取込.bat をもう一度実行してください。")
                print("    すでにシートに入った URL は次回スキップされます。")
            raise
        added = len(to_add)
        print(f"  OK: {added} 件を追加しました。")
        if added <= 5:
            for rec in to_add:
                print(f"    · {rec.商品名[:45]}")
        else:
            print(f"    · {to_add[0].商品名[:45]} … ほか {added - 1} 件")

    if skipped:
        print(f"  （重複などでスキップ: {skipped} 件）")
    print(f"\n完了: 追加 {added} 件 / スキップ {skipped} 件")
    print(f"シート: {config.worksheet_name}（在庫ステータス={STATUS_BUYMA_CANDIDATE}）")
    print("次: 気になる行を python3 intake.py で本登録（仕入れURL・価格を埋める）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
