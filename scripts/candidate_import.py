#!/usr/bin/env python3
"""候補取込のシンプル入口（クリップボード / 貼り付け / 件数確認）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.config import Config
from lib.sheet_manager import SheetManager

STATUS = "BUYMA候補"


class ImportResult:
    """TSV 取込の結果（CLI / ローカル HTTP サーバー共通）。"""

    __slots__ = ("ok", "added", "skipped", "worksheet", "message")

    def __init__(
        self,
        *,
        ok: bool,
        added: int = 0,
        skipped: int = 0,
        worksheet: str = "",
        message: str = "",
    ) -> None:
        self.ok = ok
        self.added = added
        self.skipped = skipped
        self.worksheet = worksheet
        self.message = message

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "added": self.added,
            "skipped": self.skipped,
            "worksheet": self.worksheet,
            "message": self.message,
        }


def _diagnose_clipboard(raw: str) -> None:
    """クリップボードが TSV でないときのヒントを表示。"""
    preview = (raw or "").strip().replace("\r\n", "\n")
    if not preview:
        print("  → クリップボードが空です。")
    elif preview.startswith("(function") or preview.startswith("function"):
        print("  → 貼られているのは「抽出スクリプト」です（TSV ではありません）。")
        print("     BUYMA の白い画面で「TSV をコピー」を押してから 2_候補_取込.bat を実行してください。")
    elif "buyma_url" in preview.split("\n", 1)[0] and "\n" not in preview.strip():
        print("  → ヘッダー行だけの可能性があります。白い画面で商品にチェックが付いているか確認。")
    elif "buyma_url" in preview and preview.count("\n") == 0:
        print("  → 1行だけの可能性があります。TSV は複数行（ヘッダー＋商品行）です。")
    else:
        head = preview[:120].replace("\n", "\\n")
        print(f"  → 先頭120文字: {head}")
    print()
    print("  手順: 白パネル → TSVをコピー → すぐ 2_候補_取込.bat")
    print("  代替: py scripts\\candidate_import.py paste （下の枠にTSVを貼る）")


def _load_import_module():
    import importlib.util

    path = _ROOT / "scripts" / "import_buyma_tsv.py"
    spec = importlib.util.spec_from_file_location("import_buyma_tsv", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def cmd_status() -> int:
    config = Config.from_env()
    errors = config.validate()
    if errors:
        print("設定が足りません（初回だけ設定.bat を実行）:")
        for e in errors:
            print(f"  · {e}")
        return 1
    manager = SheetManager(
        config.spreadsheet_id,
        config.worksheet_name,
        config.credentials_path,
    )
    try:
        rows = manager.get_all_records()
        candidates = [r for r in rows if r.在庫ステータス == STATUS]
        priced = sum(1 for r in candidates if (r.BUYMA販売価格 or "").strip())
        print()
        print(f"  シート: {config.worksheet_name}")
        print(f"  候補（{STATUS}）: {len(candidates)} 件")
        if candidates:
            pct = 100.0 * priced / len(candidates)
            print(f"  うち一覧価格あり: {priced} 件（{pct:.0f}%）")
        print()
        print("  次: 気になる商品だけ py intake.py")
        print()
        return 0
    finally:
        config.cleanup()


def cmd_paste() -> int:
    print()
    print("  TSV を貼り付けてください。")
    print("  終わったら空行だけの行で Enter を1回押してください。")
    print()
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        lines.append(line)
    if not lines:
        print("データがありません。")
        return 1
    mod = _load_import_module()
    rows = mod.parse_tsv_text("\n".join(lines))
    if not rows:
        print("TSV として読めませんでした。")
        return 1
    return _import_rows(mod, rows)


def import_tsv_text(raw: str, *, verbose: bool = False) -> ImportResult:
    """TSV 文字列をシートに追記する（ブックマークレット → ローカルサーバー用）。"""
    mod = _load_import_module()
    rows = mod.parse_tsv_text(raw)
    if not rows:
        return ImportResult(
            ok=False,
            message="TSV にデータ行がありません。白パネルで商品にチェックが付いているか確認してください。",
        )

    config = Config.from_env()
    errors = config.validate()
    if errors:
        return ImportResult(
            ok=False,
            message="設定が足りません: " + " / ".join(errors),
        )

    manager = SheetManager(
        config.spreadsheet_id,
        config.worksheet_name,
        config.credentials_path,
    )
    manager.ensure_header()
    seen = mod.existing_buyma_urls(manager)
    to_add = []
    skipped = 0
    try:
        for row in rows:
            rec = mod.row_to_record(row)
            if rec is None:
                skipped += 1
                continue
            key = rec.仕入れURL.strip().lower().rstrip("/")
            if key in seen:
                skipped += 1
                continue
            to_add.append(rec)
            seen.add(key)
        if to_add:
            if verbose:
                print(f"  書き込み中… {len(to_add)} 件")
            manager.append_records(to_add)
        if not to_add and not skipped:
            return ImportResult(
                ok=False,
                worksheet=config.worksheet_name,
                message="取り込める行がありませんでした。",
            )
        msg = f"追加 {len(to_add)} 件 / スキップ {skipped} 件"
        if verbose:
            print(f"\n  完了: {msg}")
            print(f"  シート: {config.worksheet_name}")
        return ImportResult(
            ok=True,
            added=len(to_add),
            skipped=skipped,
            worksheet=config.worksheet_name,
            message=msg,
        )
    finally:
        config.cleanup()


def _rows_to_tsv(rows: list[dict[str, str]]) -> str:
    lines = ["buyma_url\ttitle_guess\tlist_page_url\tprice_guess_jpy"]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    row.get("buyma_url", ""),
                    row.get("title_guess", ""),
                    row.get("list_page_url", ""),
                    row.get("price_guess_jpy", ""),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _import_rows(_mod, rows: list[dict[str, str]]) -> int:
    result = import_tsv_text(_rows_to_tsv(rows), verbose=True)
    return 0 if result.ok else 1


def cmd_clipboard() -> int:
    mod = _load_import_module()
    try:
        raw = mod.read_clipboard_text()
    except RuntimeError as e:
        print(e)
        print("\n  代替: py scripts/candidate_import.py paste")
        return 1
    rows = mod.parse_tsv_text(raw)
    if not rows:
        print("クリップボードに TSV がありません。")
        _diagnose_clipboard(raw)
        return 1
    result = import_tsv_text(raw, verbose=True)
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="BUYMA 候補 → シート（シンプル取込）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="候補件数を表示")
    sub.add_parser("paste", help="TSV をターミナルに貼り付けて取込")
    sub.add_parser("clipboard", help="クリップボードから取込（既定）")

    args = parser.parse_args()
    cmd = args.command or "clipboard"
    if cmd == "status":
        return cmd_status()
    if cmd == "paste":
        return cmd_paste()
    return cmd_clipboard()


if __name__ == "__main__":
    sys.exit(main())
