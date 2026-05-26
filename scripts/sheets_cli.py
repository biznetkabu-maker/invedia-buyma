#!/usr/bin/env python3
"""Google Sheets API の接続確認・読み取り・分析 CLI（Cursor Agent 向け）。

例:
  python3 scripts/sheets_cli.py ping
  python3 scripts/sheets_cli.py analyze
  python3 scripts/sheets_cli.py analyze --top 5
  python3 scripts/sheets_cli.py search --q バッグ
  python3 scripts/sheets_cli.py list --status 出品中 --limit 10
  python3 scripts/sheets_cli.py get --name "商品名"
  python3 scripts/sheets_cli.py set-status --name "商品名" --status 停止中
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.config import Config
from lib.sheet_manager import COLUMNS, SheetManager, ProductRecord


def _manager(cfg: Config) -> SheetManager:
    return SheetManager(
        spreadsheet_id=cfg.spreadsheet_id,
        worksheet_name=cfg.worksheet_name,
        credentials_path=cfg.credentials_path,
    )


def _record_to_dict(record: ProductRecord) -> dict[str, str]:
    return {col: str(getattr(record, col)) for col in COLUMNS}


def _print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))




def cmd_tabs(cfg: Config) -> int:
    manager = _manager(cfg)
    titles = manager.list_worksheet_titles()
    _print_json(
        {
            "configured_worksheet": cfg.worksheet_name,
            "available_worksheets": titles,
            "match": cfg.worksheet_name in titles,
        }
    )
    if cfg.worksheet_name not in titles:
        print(
            "# worksheet_name.txt のタブ名が一致しません。上記 available のいずれかに修正してください。",
            file=sys.stderr,
        )
        return 1
    return 0

def cmd_ping(cfg: Config) -> int:
    errors = cfg.validate()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    manager = _manager(cfg)
    ws = manager.get_worksheet()
    title = ws.spreadsheet.title
    _print_json(
        {
            "ok": True,
            "spreadsheet_title": title,
            "spreadsheet_id": cfg.spreadsheet_id,
            "worksheet": cfg.worksheet_name,
            "row_count": ws.row_count,
        }
    )
    return 0


def cmd_columns(_cfg: Config) -> int:
    _print_json(COLUMNS)
    return 0


def cmd_list(cfg: Config, *, status: str | None, limit: int | None) -> int:
    manager = _manager(cfg)
    records = manager.get_all_records()
    if status:
        records = [r for r in records if r.在庫ステータス == status]
    if limit is not None and limit >= 0:
        records = records[:limit]
    payload = [_record_to_dict(r) for r in records]
    _print_json(payload)
    print(f"# total: {len(payload)}", file=sys.stderr)
    return 0


def cmd_get(cfg: Config, product_name: str) -> int:
    manager = _manager(cfg)
    record = manager.get_record_by_product_name(product_name)
    if record is None:
        _print_json({"found": False, "商品名": product_name})
        return 1
    _print_json({"found": True, **_record_to_dict(record)})
    return 0


def cmd_search(
    cfg: Config,
    *,
    query: str,
    field: str,
    limit: int | None,
) -> int:
    manager = _manager(cfg)
    records = manager.search_records(query, field=field, limit=limit)
    _print_json([_record_to_dict(r) for r in records])
    print(f"# matched: {len(records)}", file=sys.stderr)
    return 0


def cmd_status_summary(cfg: Config) -> int:
    manager = _manager(cfg)
    report = manager.analyze(
        buyma_fee_rate=cfg.buyma_fee_rate,
        customs_rate=cfg.customs_rate,
        shipping_cost_jpy=cfg.shipping_cost_jpy,
        target_profit_rate=cfg.target_profit_rate,
        top_n=0,
    )
    _print_json(report.status_counts)
    return 0


def cmd_analyze(cfg: Config, *, top: int) -> int:
    manager = _manager(cfg)
    report = manager.analyze(
        buyma_fee_rate=cfg.buyma_fee_rate,
        customs_rate=cfg.customs_rate,
        shipping_cost_jpy=cfg.shipping_cost_jpy,
        target_profit_rate=cfg.target_profit_rate,
        top_n=top,
    )
    _print_json(report.to_dict())
    return 0


def cmd_set_status(cfg: Config, *, name: str, status: str) -> int:
    manager = _manager(cfg)
    ok = manager.update_status(name, status)
    _print_json({"updated": ok, "商品名": name, "在庫ステータス": status})
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Google Sheets API CLI (SheetManager + analyze)",
        epilog=(
            "例（リポジトリのフォルダで実行）:\n"
            "  py scripts\\sheets_cli.py tabs\n"
            "  py scripts\\sheets_cli.py ping\n"
            "  py scripts\\sheets_cli.py list --status BUYMA候補 --limit 5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("tabs", help="スプレッドシートのタブ名一覧（設定確認）")
    sub.add_parser("ping", help="認証・接続を確認")
    sub.add_parser("columns", help="列名一覧")
    sub.add_parser("status-summary", help="在庫ステータス別件数（軽量）")

    p_analyze = sub.add_parser(
        "analyze",
        help="利益・ステータスを集計（top_profit / needs_attention 含む）",
    )
    p_analyze.add_argument("--top", type=int, default=10, help="上位/下位・要注意の件数")

    p_search = sub.add_parser("search", help="部分一致検索")
    p_search.add_argument("--q", required=True, help="検索文字列")
    p_search.add_argument("--field", default="商品名", help=f"検索列（既定: 商品名）")
    p_search.add_argument("--limit", type=int, default=None)

    p_list = sub.add_parser("list", help="行を JSON 出力")
    p_list.add_argument("--status", help="在庫ステータスでフィルタ")
    p_list.add_argument("--limit", type=int, default=None)

    p_get = sub.add_parser("get", help="商品名で1件（完全一致）")
    p_get.add_argument("--name", required=True)

    p_set = sub.add_parser("set-status", help="在庫ステータスだけ更新")
    p_set.add_argument("--name", required=True)
    p_set.add_argument("--status", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        print(
            "\nタブ名の確認: py scripts\\sheets_cli.py tabs",
            file=sys.stderr,
        )
        return 2

    cfg = Config.from_env()
    try:
        if args.command == "tabs":
            return cmd_tabs(cfg)
        if args.command == "ping":
            return cmd_ping(cfg)
        if args.command == "columns":
            return cmd_columns(cfg)
        if args.command == "list":
            return cmd_list(cfg, status=args.status, limit=args.limit)
        if args.command == "get":
            return cmd_get(cfg, args.name)
        if args.command == "search":
            return cmd_search(cfg, query=args.q, field=args.field, limit=args.limit)
        if args.command == "status-summary":
            return cmd_status_summary(cfg)
        if args.command == "analyze":
            return cmd_analyze(cfg, top=args.top)
        if args.command == "set-status":
            return cmd_set_status(cfg, name=args.name, status=args.status)
        parser.error(f"unknown command: {args.command}")
        return 2
    finally:
        cfg.cleanup()


if __name__ == "__main__":
    sys.exit(main())
