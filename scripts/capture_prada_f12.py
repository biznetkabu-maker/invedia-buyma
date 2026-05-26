#!/usr/bin/env python3
"""prada.com の F12 XHR をローカルで記録（docs/PRADA_OFFICIAL_F12.md 更新用）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="PRADA 公式 F12 キャプチャ")
    parser.add_argument("mpn", nargs="?", default="PR09ZS", help="型番例 PR09ZS")
    parser.add_argument(
        "--product", "-p", default="sunglasses",
        help="検索補助（sunglasses / wallet 等）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="DDG URL・候補・Playwright エラーを表示",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Playwright を使わず DDG のみ",
    )
    args = parser.parse_args()

    from lib.official_catalog.prada import (
        lookup_prada_official_diagnose,
        lookup_prada_official_sync,
    )

    print(f"照合: {args.mpn}  補助: {args.product}")
    if args.verbose:
        match, diag = lookup_prada_official_diagnose(
            args.mpn,
            product_name=args.product,
            use_playwright=not args.no_browser,
        )
        print("\n--- 診断 ---")
        print(f"  Playwright: {'OK' if diag.playwright_ok else 'NG'}")
        if diag.playwright_error:
            print(f"  PWエラー: {diag.playwright_error[:200]}")
        print(f"  検索HTMLに型番: {'あり' if diag.mpn_in_search_html else 'なし'}")
        print(f"  検索ページ内PDPリンク: {diag.prada_pdp_links_in_html}")
        if diag.search_final_url:
            print(f"  最終URL: {diag.search_final_url}")
        print(f"  DDG(urllib): {diag.ddg_urllib}  DDG(PW): {diag.ddg_playwright}")
        print(f"  DDG URL数(urllibのみ表示): {len(diag.ddg_urls)}")
        for u in diag.ddg_urls[:5]:
            print(f"    {u[:100]}")
        print(f"  候補数: {diag.candidate_count}")
        for c in diag.top_candidates:
            print(f"    score={c['score']} {c['source']} sku={c['sku']} url={c['url']}")
    else:
        match = lookup_prada_official_sync(
            args.mpn,
            product_name=args.product,
            use_playwright=not args.no_browser,
        )

    if not match:
        print("\nNG: 公式一致なし")
        print("  1) py -m playwright install chromium")
        print("  2) py scripts\\capture_prada_f12.py PR09ZS -v")
        print("  3) ブラウザで prada.com を開いてから再実行")
        print("  4) 方針A: シート候補URLsに仕入URLを貼り intake --auto-sheet")
        if not args.verbose:
            print("  （詳細は -v を付けて再実行）")
        return 1

    print(json.dumps({
        "mpn_query": match.mpn_query,
        "product_url": match.product_url,
        "sku": match.sku,
        "english_name": match.english_name,
        "price_note": match.price_note,
        "source": match.source,
        "identity_note": match.identity_note,
    }, ensure_ascii=False, indent=2))
    print("\nOK: docs/PRADA_OFFICIAL_F12.md のテンプレに貼り付けてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
