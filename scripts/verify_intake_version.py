#!/usr/bin/env python3
"""intake 自動モードの修正版が入っているか確認する。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BUILD_ID = "20250521-v11-fragment-case"


def main() -> int:
    ok = True
    print(f"intake 自動モード ビルド ID: {BUILD_ID}")
    print()

    try:
        import intake
    except ImportError as e:
        print(f"NG: intake.py を読めません: {e}")
        return 1

    if not hasattr(intake, "_write_to_sheet_quiet"):
        print("NG: _write_to_sheet_quiet がありません → git pull が必要です")
        ok = False
    else:
        print("OK: _write_to_sheet_quiet")

    try:
        from lib.supply_search_utils import (
            build_supply_search_queries,
            normalize_brand_name,
            url_matches_brand,
        )
    except ImportError as e:
        print(f"NG: supply_search_utils: {e}")
        return 1

    brand = normalize_brand_name("【VIPセール】PRADA")
    if brand != "PRADA":
        print(f"NG: ブランド正規化 → {brand!r}（PRADA であるべき）")
        ok = False
    else:
        print("OK: ブランド正規化 → PRADA")
    ja = normalize_brand_name("プラダ☆ロゴ刺繍")
    if ja != "PRADA":
        print(f"NG: 日本語ブランド正規化 → {ja!r}")
        ok = False
    else:
        print("OK: 日本語ブランド正規化（プラダ☆ロゴ刺繍 → PRADA）")

    qs = build_supply_search_queries("PRADA", "財布 2M0738", "100113400")
    if "PRADA 2M0738" not in qs:
        print(f"NG: 型番クエリなし → {qs[:3] if qs else []}")
        ok = False
    else:
        print("OK: 検索クエリに PRADA 2M0738 を含む")

    pouch_qs = build_supply_search_queries(
        "PRADA", "ミニポーチ 小物入れ ロゴ付き", "100452904"
    )
    if not pouch_qs or "ミニポーチ" not in pouch_qs[0]:
        print(f"NG: ポーチ検索クエリ → {pouch_qs[:2] if pouch_qs else []}")
        ok = False
    else:
        print("OK: Re-Nylon ポーチ向け検索クエリ")

    try:
        from lib.supply_search_utils import (
            category_site_search_extras,
            url_has_category_path_mismatch,
            url_is_valid_supply_candidate,
        )

        wicker_raw = "ウィッカーバケットバッグ ロゴ 1BE083"
        wicker_extras = category_site_search_extras(wicker_raw)
        if wicker_extras[:1] != ["wicker"]:
            print(f"NG: ウィッカーバケット extras → {wicker_extras[:3]}")
            ok = False
        else:
            print("OK: ウィッカーバケット → wicker クエリ")

        wicker_qs = build_supply_search_queries(
            "PRADA", wicker_raw, "1BE083", raw_product_name=wicker_raw,
        )
        if not wicker_qs or wicker_qs[0] != "PRADA 1BE083 wicker":
            print(f"NG: ウィッカーバケット検索クエリ → {wicker_qs[:3] if wicker_qs else []}")
            ok = False
        else:
            print("OK: ウィッカーバケット検索クエリ（PRADA 1BE083 wicker）")

        darling = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-prada-darling-item-23861581.aspx"
        )
        if not url_has_category_path_mismatch(wicker_raw, darling):
            print("NG: prada-darling をウィッカーバケットと誤判定")
            ok = False
        elif url_is_valid_supply_candidate(
            "PRADA", darling, style_id="1BE083", product_name=wicker_raw,
        ):
            print("NG: prada-darling URL を Step3 で通してしまう → git pull 要")
            ok = False
        else:
            print("OK: prada-darling をウィッカーバケット探索から除外")

        sandal_raw = "プラダ 限定数量セール！サンダル 1X1030"
        generic_sandal = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-strappy-leather-sandals-item-36384231.aspx"
        )
        if url_is_valid_supply_candidate(
            "PRADA", generic_sandal, style_id="1X1030", product_name=sandal_raw,
        ):
            print("NG: 汎用 sandal URL を Step3 で通してしまう → git pull 要")
            ok = False
        else:
            print("OK: 汎用 sandal（型番スラッグなし）を Step3 で除外")

        if normalize_brand_name("【PRADA】2X3119 3LKK") != "PRADA":
            print("NG: 【PRADA】タグからブランド抽出できない → git pull 要")
            ok = False
        else:
            print("OK: 【PRADA】タグ → PRADA ブランド正規化")

        fragment_raw = "数量限定 1MC038 フラグメントケース"
        fragment_qs = build_supply_search_queries(
            "PRADA", fragment_raw, "1MC038", raw_product_name=fragment_raw,
        )
        if not fragment_qs or fragment_qs[0] != "PRADA 1MC038 fragment":
            print(f"NG: フラグメントケース検索クエリ → {fragment_qs[:3] if fragment_qs else []}")
            ok = False
        else:
            print("OK: フラグメントケース検索クエリ（PRADA 1MC038 fragment）")
        generic_wallet = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        if url_is_valid_supply_candidate(
            "PRADA", generic_wallet, style_id="1MC038", product_name=fragment_raw,
        ):
            print("NG: 汎用 wallet をフラグメントケース Step3 で通してしまう")
            ok = False
        else:
            print("OK: フラグメントケース探索から汎用 wallet を除外")
    except ImportError as e:
        print(f"NG: ウィッカーバケット修正: {e}")
        ok = False

    bad = "https://www.farfetch.com/jp/shopping/women/dsquared2-item.aspx"
    good = "https://www.farfetch.com/jp/shopping/women/prada-wallet.aspx"
    if url_matches_brand("PRADA", bad):
        print("NG: Dsquared2 URL を PRADA と誤判定")
        ok = False
    elif not url_matches_brand("PRADA", good):
        print("NG: PRADA URL を除外してしまう")
        ok = False
    else:
        print("OK: ブランド不一致 URL 除外")

    try:
        from lib.supply_search_utils import is_valid_farfetch_product_url

        bad_ff = "https://www.farfetch.com/jp/shopping/women/prada--item-30953.aspx"
        if is_valid_farfetch_product_url(bad_ff):
            print("NG: prada--item FARFETCH URL を通してしまう → git pull 要")
            ok = False
        else:
            print("OK: 不正 FARFETCH URL（prada--item）を除外")
    except ImportError as e:
        print(f"NG: is_valid_farfetch_product_url: {e}")
        ok = False

    try:
        from lib.scraper.engine import PriceScraper, _HEAVY_SITE_DOMAINS
    except ImportError as e:
        print(f"NG: scraper.engine: {e}")
        ok = False
    else:
        if "farfetch.com" not in _HEAVY_SITE_DOMAINS:
            print("NG: farfetch.com が重いサイト一覧にありません")
            ok = False
        else:
            print("OK: FARFETCH は domcontentloaded（networkidle 不使用）")
        chain = PriceScraper().navigation_wait_chain(
            "https://www.farfetch.com/jp/shopping/women/prada-item.aspx"
        )
        if chain != ["domcontentloaded", "commit"]:
            print(f"NG: FARFETCH navigation → {chain}")
            ok = False
        else:
            print("OK: FARFETCH は commit までフォールバック")

    try:
        import intake_funnel
        from lib.supply_url_finder import discover_supply_urls_funnel
        from lib.supply_site_search import discover_urls_by_style_id

        if not hasattr(intake_funnel, "filter_eligible_records"):
            print("NG: intake_funnel 不完整")
            ok = False
        else:
            print("OK: intake_funnel（漏斗・自動見送り）")
        if not callable(discover_supply_urls_funnel):
            print("NG: discover_supply_urls_funnel がありません")
            ok = False
        else:
            print("OK: discover_supply_urls_funnel（候補URLs→site検索）")
    except ImportError as e:
        print(f"NG: 漏斗モジュール: {e}")
        ok = False

    try:
        from lib.supply_search_utils import url_matches_style_hint

        bad = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-prada-arque-s-item-36082423.aspx"
        )
        if url_matches_style_hint("1BB108", bad):
            print("NG: 型番不一致 URL を通してしまう")
            ok = False
        else:
            print("OK: URL スラッグ型番チェック")
    except ImportError as e:
        print(f"NG: url_matches_style_hint: {e}")
        ok = False

    try:
        from lib.product_identity import VariantKey, summarize_best_source_result
        from lib.sheet_manager import COLUMNS

        if "同一性スコア" not in COLUMNS or "価格根拠" not in COLUMNS:
            print("NG: シート列に同一性スコア/価格根拠がありません")
            ok = False
        else:
            print("OK: シート列（同一性スコア・価格根拠）")

        vk = VariantKey.resolve(
            brand="PRADA", product_name="2M0738", sheet_style_id="2M0738",
        )
        if vk.match_ref != "2M0738":
            print(f"NG: VariantKey → {vk.match_ref!r}")
            ok = False
        else:
            print("OK: VariantKey 型番解決")

        ms = summarize_best_source_result(
            vk,
            best_url=(
                "https://www.farfetch.com/jp/shopping/women/"
                "prada-2m0738-bag-item-99999.aspx"
            ),
            best_style_id="2M0738",
            best_stock="in_stock",
            best_price_ok=True,
            purchase_grade="B",
        )
        if ms.grade != "S":
            print(f"NG: MatchScore 期待 S → {ms.grade}")
            ok = False
        else:
            print("OK: MatchScore（S=型番+URLヒント+在庫+価格）")
    except ImportError as e:
        print(f"NG: product_identity: {e}")
        ok = False

    try:
        from lib.funnel_policy import POLICY_ID, weekly_auto_limit, official_prada_enabled
        from lib.official_catalog.prada import lookup_prada_official_sync

        if POLICY_ID != "A":
            print("NG: funnel_policy POLICY_ID")
            ok = False
        else:
            print(f"OK: 方針{POLICY_ID}（週次上限 {weekly_auto_limit()}）")
        if not official_prada_enabled():
            print("NG: INTAKE_OFFICIAL_PRADA が OFF")
            ok = False
        else:
            print("OK: PRADA 公式照合モジュール")
        # オフライン: HTML フィクスチャ相当は test_official_prada で検証
    except ImportError as e:
        print(f"NG: funnel_policy / official_catalog: {e}")
        ok = False

    print()
    if ok:
        print(
            "すべて OK。漏斗運用: py intake.py --auto-sheet --limit 1 "
            "（型番あり候補）"
        )
        return 0
    print("NG あり。git checkout main && git pull 後に再確認してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
