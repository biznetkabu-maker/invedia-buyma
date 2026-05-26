#!/usr/bin/env python3
"""SSENSE 検索の F12 解析をローカルで記録（docs/SSENSE_SEARCH_F12.md 更新用）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="SSENSE 検索 F12 キャプチャ")
    parser.add_argument("style_id", nargs="?", default="1ML506", help="型番例 1ML506")
    parser.add_argument("--brand", "-b", default="PRADA", help="ブランド")
    parser.add_argument(
        "--product", "-p", default="wallet",
        help="カテゴリ補助（wallet / shoulder-bag / sunglasses 等）",
    )
    parser.add_argument("--query", "-q", default="", help="検索クエリ直接指定")
    parser.add_argument(
        "--department", "-d", default="women", choices=("women", "men"),
        help="women または men",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="JSON-LD/XHR 診断を表示",
    )
    args = parser.parse_args()

    query = (args.query or "").strip()
    if not query:
        query = f"{args.brand} {args.style_id} {args.product}".strip()

    from lib.supply_search.ssense import lookup_ssense_search_diagnose

    print(f"検索: {query}")
    print(f"型番: {args.style_id}  部門: {args.department}")

    urls, diag = lookup_ssense_search_diagnose(
        query,
        brand=args.brand,
        style_id=args.style_id,
        product_name=(query if args.query else f"{args.product} {args.style_id}".strip()),
        department=args.department,
    )

    if args.verbose:
        print("\n--- 診断 ---")
        print(f"  Playwright: {'OK' if diag.playwright_ok else 'NG'}")
        if diag.playwright_error:
            print(f"  PWエラー: {diag.playwright_error[:200]}")
        print(f"  検索URL: {diag.search_url}")
        print(f"  0件メッセージ: {'あり' if diag.no_results else 'なし'}")
        print(f"  JSON-LD Product: {diag.json_ld_items} 件")
        print(f"  HTML リンク: {diag.html_link_items} 件")
        print(f"  XHR JSON 捕捉: {diag.xhr_blobs} 件")
        print(f"  候補URL数: {diag.candidate_count}")
        for c in diag.top_candidates[:8]:
            print(
                f"    score={c['score']} [{c['source']}] "
                f"{c.get('brand','')[:20]} {c['name'][:40]} sku={c.get('sku','')} "
                f"→ {c['url'][:70]}"
            )
        if diag.no_results:
            print("\n  ⚠️  SSENSE は複合クエリで 0 件になることがあります")
            print("     例: py scripts\\capture_ssense_f12.py -q prada -v")

    if not urls:
        print("\nNG: 商品 URL 候補なし")
        print("  1) py -m playwright install chromium")
        print(f"  2) py scripts\\capture_ssense_f12.py {args.style_id} -v")
        print("  3) 検索 URL: https://www.ssense.com/en-us/women?q=...")
        print("  4) F12 → Elements → JSON-LD Product / Network → XHR")
        print("  5) 方針A: 候補URLs に正 URL を貼り intake --auto-sheet")
        return 1

    print(json.dumps({
        "query": query,
        "style_id": args.style_id,
        "product_urls": urls[:5],
        "top_candidate": diag.top_candidates[0] if diag.top_candidates else None,
        "sources": {
            "no_results": diag.no_results,
            "json_ld_items": diag.json_ld_items,
            "html_link_items": diag.html_link_items,
            "xhr_blobs": diag.xhr_blobs,
        },
    }, ensure_ascii=False, indent=2))
    print("\nOK: docs/SSENSE_SEARCH_F12.md のテンプレに追記してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
