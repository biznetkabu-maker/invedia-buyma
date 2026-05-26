#!/usr/bin/env python3
"""FARFETCH 検索の F12 解析をローカルで記録（docs/FARFETCH_SEARCH_F12.md 更新用）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="FARFETCH 検索 F12 キャプチャ")
    parser.add_argument("style_id", nargs="?", default="1ML506", help="型番例 1ML506")
    parser.add_argument("--brand", "-b", default="PRADA", help="ブランド")
    parser.add_argument(
        "--product", "-p", default="wallet",
        help="カテゴリ補助（wallet / shoulder-bag / sunglasses 等）",
    )
    parser.add_argument(
        "--query", "-q", default="",
        help="検索クエリを直接指定（未指定時は brand + style_id + product）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="JSON-LD/XHR/スコア診断を表示",
    )
    args = parser.parse_args()

    query = (args.query or "").strip()
    if not query:
        query = f"{args.brand} {args.style_id} {args.product}".strip()

    from lib.supply_search.farfetch import lookup_farfetch_search_diagnose

    print(f"検索: {query}")
    print(f"型番: {args.style_id}  ブランド: {args.brand}")

    urls, diag = lookup_farfetch_search_diagnose(
        query,
        brand=args.brand,
        style_id=args.style_id,
        product_name=f"{args.product} {args.style_id}".strip(),
    )

    if args.verbose:
        print("\n--- 診断 ---")
        print(f"  Playwright: {'OK' if diag.playwright_ok else 'NG'}")
        if diag.playwright_error:
            print(f"  PWエラー: {diag.playwright_error[:200]}")
        print(f"  検索URL: {diag.search_url}")
        print(f"  JSON-LD ItemList: {diag.json_ld_items} 件")
        print(f"  Apollo キャッシュ: {diag.apollo_items} 件")
        print(f"  XHR JSON 捕捉: {diag.xhr_blobs} 件")
        print(f"  候補URL数: {diag.candidate_count}")
        for c in diag.top_candidates[:8]:
            print(
                f"    score={c['score']} [{c['source']}] "
                f"{c['name'][:50]} → {c['url'][:85]}"
            )

    if not urls:
        print("\nNG: 商品 URL 候補なし")
        print("  1) py -m playwright install chromium")
        print(f"  2) py scripts\\capture_farfetch_f12.py {args.style_id} -v")
        print("  3) Chrome で FARFETCH 検索を開き F12 → Network → Fetch/XHR を確認")
        print("  4) docs/FARFETCH_SEARCH_F12.md のテンプレに XHR URL を追記")
        print("  5) 方針A: シート候補URLsに正 URL を貼り intake --auto-sheet")
        return 1

    print(json.dumps({
        "query": query,
        "style_id": args.style_id,
        "product_urls": urls[:5],
        "top_candidate": diag.top_candidates[0] if diag.top_candidates else None,
        "sources": {
            "json_ld_items": diag.json_ld_items,
            "apollo_items": diag.apollo_items,
            "xhr_blobs": diag.xhr_blobs,
        },
    }, ensure_ascii=False, indent=2))
    print("\nOK: 先頭 URL を docs/FARFETCH_SEARCH_F12.md に追記してください。")
    print("※ 一覧に型番が無い商品は Step4 JSON-LD で型番照合されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
