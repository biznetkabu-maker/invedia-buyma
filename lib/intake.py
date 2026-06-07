"""
商品取り込み CLI — 新商品を効率的にスプレッドシートへ追加するためのツール。

【手動/自動の境界】
  手動パート（人が判断・入力する）:
    ① ブランド名・商品名・BUYMA予定価格の入力
    ② 各仕入先サイトで商品ページを確認し、URLを貼り付ける
    ③ 仕入れるかどうかの最終判断

  自動パート（ツールが行う）:
    → 型番の照合（入力 or BUYMA URL から取得 → 仕入先 style_id と突合）
    → 為替レートの取得（frankfurter.app API）
    → BUYMA 公開検索ページでの需要確認（お気に入り数・競合数・価格帯）
    → 15サイト分の検索URLを生成・カテゴリ別に表示
    → 貼り付けられたURLの並列スクレイプ・最安値選択
    → A〜E グレード判定
    → スプレッドシートへの書き込み

【設計原則】
  - 各ステップは独立して失敗できる（1ステップが失敗しても続行）
  - 自動化が失敗した場合は手動入力にフォールバック
  - 判断が必要な箇所では人間に確認を求める

使い方:
    python3 intake.py                              # 対話モード（1件ずつ）
    python3 intake.py --auto-buyma <BUYMA商品URL>  # BUYMA URL から仕入先を自動探索
    python3 intake.py --auto-sheet                 # シートの BUYMA候補 行を一括処理
    python3 intake.py --batch file.csv             # CSV 一括評価（スクレイプなし・高速）

CSV フォーマット（--batch 用）:
    brand,product_name,buyma_price,exchange_rate,model_year,category
    CELINE,トリオバッグ スモール,210000,170,2025,バッグ
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.multi_source import BestSourceResult
    from lib.product_identity import MatchScore, VariantKey

logger = logging.getLogger(__name__)

from lib.buyma_demand import BUYMADemandScraper, BUYMADemandSignal
from lib.forex import get_rate
from lib.intake_cli import (
    ask as _ask,
)
from lib.intake_cli import (
    ask_float as _ask_float,
)
from lib.intake_cli import (
    ask_int as _ask_int,
)
from lib.intake_cli import (
    ask_yn as _ask_yn,
)
from lib.intake_cli import (
    cli_print,
)
from lib.intake_cli import (
    print_header as _print_header,
)
from lib.intake_cli import (
    print_score as _print_score,
)
from lib.intake_cli import (
    print_step as _print_step,
)
from lib.intake_cli import (
    require as _require,
)
from lib.product_finder import build_search_urls
from lib.purchase_evaluator import (
    EvaluationInput,
    PurchaseEvaluator,
    PurchaseScore,
    _is_recommended_brand,
    _is_stable_category,
)
from lib.sheet_manager import ProductRecord, SheetManager

# ============================================================================
# 定数
# ============================================================================

_GRADE_ICONS = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "⛔"}
_SEPARATOR = "  " + "─" * 56


# ============================================================================
# 対話モード
# ============================================================================

def interactive_intake() -> None:
    """対話形式で1商品を取り込む。"""
    _print_header()

    # ════════════════════════════════════════════════════════════
    # Step 1: 基本情報の入力（手動）
    # ════════════════════════════════════════════════════════════
    _print_step(1, "基本情報の入力（手動）")

    brand        = _require("ブランド名", hint="例: CELINE")
    product_name = _require("商品名", hint="例: トリオバッグ スモール ブラック")
    category     = _ask("カテゴリ", default="バッグ")
    model_year   = _ask_int("モデル年", default=2025)
    buyma_manual, buyma_auto = _ask_buyma_price_mode()

    currency = _ask("仕入れ通貨コード", default="EUR",
                    hint="EUR=欧州系、USD=米国系、GBP=英国系")
    exchange_rate = _get_exchange_rate(currency)
    buyma_style_id = _collect_buyma_style_id()

    # ════════════════════════════════════════════════════════════
    # Step 2: BUYMA 需要確認（自動）
    # ════════════════════════════════════════════════════════════
    _print_step(2, "BUYMA 需要確認（自動）")
    demand = _run_demand_check(brand, product_name)
    cli_print(demand.summary())

    buyma_price = _resolve_buyma_price_from_demand(
        demand, manual_jpy=buyma_manual, use_auto=buyma_auto
    )

    # ════════════════════════════════════════════════════════════
    # Step 3: 仕入先URLの確認（半自動：検索URLを表示→人がURLを貼る）
    # ════════════════════════════════════════════════════════════
    _print_step(3, "仕入先URL の確認（半自動）")
    candidate_urls = _collect_source_urls(brand, product_name)

    # ════════════════════════════════════════════════════════════
    # Step 4: スクレイプ & 最安値選択（自動）
    # ════════════════════════════════════════════════════════════
    source_url, source_price = "", 0.0

    if candidate_urls:
        _print_step(4, f"{len(candidate_urls)}件のURLを並列スクレイプ（自動）")
        source_url, source_price, _, _, _ = _scrape_and_select(
            candidate_urls=candidate_urls,
            buyma_price=buyma_price,
            exchange_rate=exchange_rate,
            buyma_style_id=buyma_style_id,
            brand=brand,
        )
    else:
        _print_step(4, "URLなし → 価格を手動入力")
        source_price = _ask_float("現地価格（手動入力）", default=0)

    # ════════════════════════════════════════════════════════════
    # Step 5: 仕入れ判断（自動）
    # ════════════════════════════════════════════════════════════
    _print_step(5, "仕入れ判断（自動）")
    score = _evaluate(
        brand=brand, product_name=product_name, category=category,
        model_year=model_year, source_url=source_url,
        source_price=source_price, currency=currency,
        exchange_rate=exchange_rate, buyma_price=buyma_price,
        demand_signal=demand,
    )
    _print_score(score)

    # ════════════════════════════════════════════════════════════
    # Step 6: シートへ追加（自動 — D/Eのみ確認あり）
    # ════════════════════════════════════════════════════════════
    _print_step(6, "スプレッドシートへ追加")

    if score.grade in ("D", "E"):
        cli_print(f"  ⚠️  グレード {score.grade} — 追加を推奨しません。")
        if not _ask_yn("  それでも追加しますか？", default=False):
            cli_print("  キャンセルしました。")
            return

    record = _build_record(
        brand=brand, product_name=product_name,
        source_url=source_url, source_price=source_price,
        exchange_rate=exchange_rate, buyma_price=buyma_price,
        candidate_urls=candidate_urls, score=score,
        buyma_style_id=buyma_style_id,
    )
    _write_to_sheet(record)


# ============================================================================
# バッチモード
# ============================================================================

def batch_intake(csv_path: str) -> None:
    """CSV ファイルから商品を一括評価する（スクレイプなし・高速）。"""
    cli_print(f"\n  バッチ評価モード: {csv_path}")
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        cli_print(f"  ❌ ファイルが見つかりません: {csv_path}")
        sys.exit(1)

    cli_print(f"  {len(rows)} 件を評価します...\n")

    for i, row in enumerate(rows, 1):
        brand        = row.get("brand", "").strip()
        product_name = row.get("product_name", "").strip()
        if not brand or not product_name:
            cli_print(f"  [{i:3}] ⚠️  スキップ（ブランドまたは商品名が空）")
            continue

        buyma_price   = float(row.get("buyma_price", 0) or 0)
        exchange_rate = float(row.get("exchange_rate", 155) or 155)
        model_year    = int(row.get("model_year", 2025) or 2025)
        category      = row.get("category", "").strip()

        score = _evaluate(
            brand=brand, product_name=product_name, category=category,
            model_year=model_year, source_url="", source_price=0,
            currency="EUR", exchange_rate=exchange_rate,
            buyma_price=buyma_price,
        )

        icon     = _GRADE_ICONS.get(score.grade, "❓")
        rec_b    = "⭐" if _is_recommended_brand(brand) else "  "
        rec_c    = "📦" if _is_stable_category(product_name, category) else "  "
        rate_str = f"{score.effective_profit_rate:.1%}" if score.effective_profit_rate else "  N/A"

        cli_print(
            f"  [{i:3}] {icon}{rec_b}{rec_c} [{score.grade}]  "
            f"{brand} {product_name[:28]:<28}  利益率 {rate_str}"
        )

    cli_print("\n  ヒント: A/B グレードの商品を python3 intake.py で1件ずつ登録してください。")



def _check_auto_intake_features() -> None:
    """自動モード v7 が入っているか確認（古いコードはここで停止）。"""
    missing: list[str] = []
    if not callable(globals().get("_write_to_sheet_quiet")):
        missing.append("_write_to_sheet_quiet")
    try:
        from lib.supply_search_utils import (
            clean_product_name_for_search,
            is_valid_farfetch_product_url,
            normalize_brand_name,
            url_is_retail_supply_candidate,
            url_is_valid_supply_candidate,
            url_matches_brand,
        )
        if normalize_brand_name("【VIPセール】PRADA") != "PRADA":
            missing.append("ブランド正規化")
        if url_matches_brand("PRADA", "https://x/dsquared2-y.aspx"):
            missing.append("URLブランド除外")
        if url_is_retail_supply_candidate(
            "https://www.farfetch.com/jp/shopping/women/prada-pre-owned-x.aspx"
        ):
            missing.append("中古URL除外")
        bad_ff = "https://www.farfetch.com/jp/shopping/women/prada--item-30953.aspx"
        if is_valid_farfetch_product_url(bad_ff):
            missing.append("FARFETCH不正URL除外")
        if url_is_valid_supply_candidate("PRADA", bad_ff):
            missing.append("FARFETCH supply候補除外")
        dup = clean_product_name_for_search(
            "PRADA PRADA◆Re-Nylon ミニポーチ", "PRADA"
        )
        if "PRADA" in dup.upper().split():
            missing.append("商品名の重複ブランド除去")
    except ImportError:
        missing.append("supply_search_utils")
    engine_py = Path(__file__).resolve().parent / "scraper" / "engine.py"
    if not engine_py.is_file() or "_goto_with_fallback" not in engine_py.read_text(
        encoding="utf-8"
    ):
        missing.append("FARFETCH domcontentloaded（engine.py 古い）")
    if missing:
        cli_print("  ⚠️  古い intake.py です。次を実行してください:")
        cli_print("      git fetch origin cursor/buyma-style-id-supply-f043")
        cli_print("      git checkout cursor/buyma-style-id-supply-f043")
        cli_print("      git pull origin cursor/buyma-style-id-supply-f043")
        cli_print("      py scripts\\verify_intake_version.py")
        cli_print(f"      不足: {', '.join(missing)}")
        sys.exit(1)
    try:
        import lib.intake_funnel  # noqa: F401
    except ImportError:
        missing.append("intake_funnel")
    cli_print(
        "  [intake 自動 v7] 漏斗モード・型番site検索・"
        "自動見送り・候補URLs優先"
    )


# ============================================================================
# 自動モード（BUYMA URL → 仕入先探索 → スクレイプ → シート）
#   実装は lib/intake_auto.py に分離。後方互換のため再エクスポートする。
# ============================================================================

from lib.intake_auto import _guess_currency_from_url as _guess_currency_from_url  # noqa: E402
from lib.intake_auto import _is_buyma_reference_url as _is_buyma_reference_url  # noqa: E402
from lib.intake_auto import _product_name_without_brand as _product_name_without_brand  # noqa: E402
from lib.intake_auto import _resolve_buyma_price_auto as _resolve_buyma_price_auto  # noqa: E402
from lib.intake_auto import auto_intake_from_buyma as auto_intake_from_buyma  # noqa: E402
from lib.intake_auto import auto_intake_from_sheet as auto_intake_from_sheet  # noqa: E402


def _open_sheet_manager() -> Optional[SheetManager]:
    """Config を検証し SheetManager を返す。失敗時は None。"""
    try:
        from lib.config import Config

        config = Config.from_env()
        errors = config.validate()
        if errors:
            cli_print("  ❌ シート設定が未完了です:")
            for e in errors:
                cli_print(f"       - {e}")
            return None
        manager = SheetManager(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_path=config.credentials_path,
        )
        manager.ensure_header()
        return manager
    except Exception as e:
        cli_print("  ❌ シート接続失敗:")
        for line in str(e).splitlines():
            cli_print(f"     {line}")
        try:
            titles = SheetManager(
                spreadsheet_id=config.spreadsheet_id,
                worksheet_name=config.worksheet_name,
                credentials_path=config.credentials_path,
            ).list_worksheet_titles()
            cli_print(f"     現在の設定タブ名: {config.worksheet_name}")
            cli_print(f"     利用可能なタブ: {', '.join(titles)}")
        except Exception:
            logger.debug("ワークシートタブ一覧取得失敗", exc_info=True)
        return None


# ============================================================================
# 内部ヘルパー — 各ステップ
# ============================================================================

def _price_factor() -> float:
    """競合最安に掛ける係数（既定 0.97 = 3% 下）。"""
    try:
        return float(os.environ.get("BUYMA_PRICE_FACTOR", "0.97"))
    except ValueError:
        return 0.97


def _ask_buyma_price_mode() -> tuple[float, bool]:
    """(手入力価格, 自動フラグ)。自動時は Step2 後に競合最安×係数で決定。"""
    factor = _price_factor()
    cli_print(f"  ※ Enter / auto → Step2 後に競合最安値 × {factor} で自動設定")
    while True:
        raw = input("  BUYMA予定販売価格（JPY）[auto]: ").strip()
        if not raw or raw.lower() in ("auto", "a", "自動"):
            return 0.0, True
        try:
            return float(raw.replace(",", "")), False
        except ValueError:
            cli_print("    ⚠️  数値を入力するか、auto と入力してください。")


def _resolve_buyma_price_from_demand(
    demand: BUYMADemandSignal,
    *,
    manual_jpy: float,
    use_auto: bool,
) -> float:
    """BUYMA 予定売価を決定する。use_auto 時は demand.min_price × BUYMA_PRICE_FACTOR。"""
    factor = _price_factor()

    if manual_jpy > 0 and not use_auto:
        return manual_jpy

    if demand.min_price:
        suggested = int(round(demand.min_price * factor))
        cli_print(
            f"\n  売価案: 競合最安 ¥{demand.min_price:,} × {factor} "
            f"= ¥{suggested:,}"
        )
        if use_auto:
            cli_print("  → 自動でこの売価を使用します。")
            return float(suggested)
        if _ask_yn("  この売価で進めますか？", default=True):
            return float(suggested)

    if manual_jpy > 0:
        return manual_jpy

    cli_print("  ⚠️  競合最安が取得できませんでした。売価を手入力してください。")
    return _ask_float("BUYMA予定販売価格（JPY）", default=0.0)


def _get_exchange_rate(currency: str) -> float:
    """為替レートを API から取得して返す。失敗時は手動入力にフォールバック。"""
    try:
        rate = get_rate(currency, "JPY")
        if rate:
            cli_print(f"  → 現在の {currency}/JPY: {rate:.2f}（自動取得）")
            raw = input(f"  為替レート（Enter でそのまま使用）[{round(rate, 2)}]: ").strip()
            return float(raw) if raw else round(rate, 2)
    except Exception as e:
        cli_print(f"  ⚠️  為替自動取得失敗: {e}")
    return _ask_float("為替レート（手動入力）", default=155.0)


def _run_demand_check(
    brand: str,
    product_name: str,
    *,
    display_name: Optional[str] = None,
) -> BUYMADemandSignal:
    """BUYMA 需要確認を実行する。失敗時はゼロ値シグナルを返す。"""
    label = display_name or f"{brand} {product_name}"
    cli_print(f"  BUYMAで「{label}」を確認中... ", end="", flush=True)
    try:
        scraper = BUYMADemandScraper(headless=True, page_wait_ms=3000)
        signal = scraper.get_demand(brand, product_name)
        cli_print("完了")
        return signal
    except Exception as e:
        cli_print(f"スキップ（{e}）")
        return BUYMADemandSignal(
            brand=brand, product_name=product_name,
            favorites_count=0, listing_count=0,
            min_price=None, max_price=None,
            order_count=0, has_cart=False,
            search_url="",
        )


def _collect_source_urls(brand: str, product_name: str) -> list[str]:
    """検索URLを表示し、ユーザーから商品URLを収集する。"""
    url_set = build_search_urls(brand, product_name)
    cli_print(url_set.display())

    cli_print("  上記URLをブラウザで開き、商品ページのURLを貼り付けてください。")
    cli_print("  複数サイトで見つけた場合は全て入力（カンマ区切り）。")
    cli_print("  → システムが並列スクレイプして最安値・在庫ありを自動選択します。")
    cli_print("  → 1件だけでも可能です。\n")

    raw = input("  商品URL（なければEnterでスキップ）: ").strip()
    if not raw:
        return []

    urls = [u.strip() for u in raw.split(",") if u.strip().startswith("http")]
    invalid = [u.strip() for u in raw.split(",") if u.strip() and not u.strip().startswith("http")]
    if invalid:
        cli_print(f"  ⚠️  無効なURL（httpで始まらない）をスキップ: {invalid}")
    return urls


def _collect_buyma_style_id() -> str:
    """型番を手入力するか、BUYMA商品URLから自動取得する。"""
    cli_print("  型番（Style ID / SKU）を入力すると、仕入先ページの ID と照合して別商品を弾きます。")
    style_id = input("  型番 [Enterでスキップ]: ").strip()
    if style_id:
        return style_id

    buyma_url = input(
        "  BUYMA商品URL（型番を自動取得、Enterでスキップ）: "
    ).strip()
    if not buyma_url:
        return ""

    if not buyma_url.startswith("http"):
        cli_print("  ⚠️  URLの形式ではありません。型番なしで続行します。")
        return ""

    try:
        from lib.buyma_style_id import fetch_buyma_style_id_from_url_sync

        cli_print("  BUYMAページから型番を取得中（10〜30秒）...")
        fetched = fetch_buyma_style_id_from_url_sync(buyma_url)
        if fetched:
            cli_print(f"  → 取得した型番: {fetched}")
            return fetched
        cli_print("  ⚠️  型番を取得できませんでした。手動入力かシート追記で対応してください。")
    except Exception as e:
        cli_print(f"  ⚠️  型番取得エラー: {e}")
    return ""


def _print_style_id_report(result: "BestSourceResult", buyma_style_id: str) -> None:
    """スクレイプ各候補の style_id と BUYMA 型番の一致状況を表示する。"""
    if not (buyma_style_id or "").strip():
        return

    from lib.style_id_utils import scraped_matches_buyma_style

    ref = buyma_style_id.strip()
    cli_print(f"\n  【型番照合】 BUYMA側: {ref}")
    for c in result.all_candidates:
        sid = c.style_id or "（未取得）"
        if scraped_matches_buyma_style(c.style_id, ref):
            mark = "✅ 一致"
        elif c.style_id:
            mark = "❌ 不一致（選定対象外）"
        else:
            mark = "❓ 仕入先ID未取得（選定対象外）"
        cli_print(f"    {mark}  {c.url[:58]}")
        cli_print(f"           style_id={sid}")


def _scrape_and_select(
    candidate_urls: list[str],
    buyma_price: float,
    exchange_rate: float,
    buyma_style_id: str = "",
    brand: str = "",
    variant: Optional["VariantKey"] = None,
) -> tuple[str, float, Optional["MatchScore"], str, str]:
    """複数候補URLをスクレイプして最安値・在庫ありを選択する。
    buyma_style_id がある場合、型番一致した候補のみ最優良選定の対象とする。
    失敗時は空URLと価格0を返す。MatchScore は product_identity で付与。
    """
    from lib.multi_source import BestSourceFinder
    from lib.product_identity import VariantKey, score_when_no_supply
    from lib.supply_search_utils import filter_scrape_candidate_urls

    if variant is None:
        variant = VariantKey.resolve(sheet_style_id=buyma_style_id or "")

    try:
        heavy_ms = int(os.environ.get("SCRAPER_HEAVY_TIMEOUT_MS", "60000"))
    except ValueError:
        heavy_ms = 60_000

    valid_urls, rejected = filter_scrape_candidate_urls(
        brand, candidate_urls, style_id=buyma_style_id,
    )
    if rejected:
        for u in rejected:
            cli_print(f"  ⚠️  不正な仕入先URLを除外: {u[:85]}")
        if not valid_urls:
            cli_print(
                "  ❌ スクレイプ可能な URL がありません。"
                " 「最新_仕入れ自動化を取得.bat」実行後に再試行するか、"
                "手動で py intake.py に新品 URL を貼ってください。"
            )
            return "", 0.0, score_when_no_supply(variant, reason="URL検証失敗"), "", "unknown"
        candidate_urls = valid_urls

    try:
        finder = BestSourceFinder(
            headless=True, max_retries=2, timeout_ms=heavy_ms,
        )
        result = finder.find_best(
            candidate_urls=candidate_urls,
            buyma_price=buyma_price,
            exchange_rate=exchange_rate,
            buyma_style_id=buyma_style_id or None,
        )
        cli_print(f"\n  {result.summary()}")
        _print_style_id_report(result, buyma_style_id)
        if result.match_score:
            cli_print(result.match_score.format_console())

        if result.best:
            b = result.best
            return (
                b.url,
                b.price or 0.0,
                result.match_score,
                b.style_id or "",
                b.stock_status,
            )

        return _select_fallback_candidate(
            result, buyma_style_id, buyma_price, exchange_rate,
        )

    except Exception as e:
        cli_print(f"  ❌ スクレイプエラー: {e}")
        return (
            "",
            0.0,
            score_when_no_supply(variant, reason=str(e)[:80]),
            "",
            "unknown",
        )


def _select_fallback_candidate(
    result: "BestSourceResult",
    buyma_style_id: str,
    buyma_price: float,
    exchange_rate: float,
) -> tuple[str, float, Optional["MatchScore"], str, str]:
    """best が無い場合に在庫なし候補から型番一致・妥当価格のものを選ぶ。"""
    from lib.scraper.price_sanity import is_plausible_supply_price
    from lib.style_id_utils import scraped_matches_buyma_style

    style_ref = (buyma_style_id or "").strip()
    if style_ref and "型番「" in result.reason:
        cli_print(
            "  ⚠️  型番が一致する仕入先が無いため、"
            "誤った商品の価格フォールバックは行いません。"
        )
        return "", 0.0, result.match_score, "", "unknown"

    for c in result.all_candidates:
        if not c.price:
            continue
        if style_ref and not scraped_matches_buyma_style(c.style_id, style_ref):
            cli_print(f"  ⚠️  型番不一致のため除外: style_id={c.style_id or '未取得'}")
            continue
        if c.profit is not None and c.profit <= 0:
            cli_print(
                f"  ⚠️  利益がマイナスの候補は除外: "
                f"{c.currency} {c.price:,.0f} 利益¥{c.profit:,.0f}"
            )
            continue
        if not is_plausible_supply_price(
            c.price, c.currency, c.url, buyma_price, exchange_rate,
            raw_price="",
        ):
            cli_print(
                f"  ⚠️  価格が妥当範囲外のため除外: "
                f"{c.currency} {c.price:,.0f} ({c.url[:70]}...)"
            )
            continue
        cli_print(f"  → 在庫なしですが価格取得済みの候補を使用: {c.url[:85]}")
        return (c.url, c.price, result.match_score, c.style_id or "", c.stock_status)

    return "", 0.0, result.match_score, "", "unknown"


def _evaluate(
    brand: str, product_name: str, category: str,
    model_year: int, source_url: str, source_price: float,
    currency: str, exchange_rate: float, buyma_price: float,
    demand_signal: Optional["BUYMADemandSignal"] = None,
) -> PurchaseScore:
    """保守的なデフォルト値で PurchaseEvaluator を実行する。

    BUYMA需要シグナルが取得できている場合はその値を使用する。
    """

    favorites = demand_signal.favorites_count if demand_signal else 0
    has_cart  = demand_signal.has_cart        if demand_signal else False

    inp = EvaluationInput(
        product_name=product_name,
        brand=brand,
        model_year=model_year,
        source_url=source_url or "https://example.com",
        source_price=max(source_price, 0.01),
        currency=currency,
        exchange_rate=exchange_rate,
        buyma_price=max(buyma_price, 0.01),
        japan_retail_price=0.0,
        dispatch_days=5,            # 保守的デフォルト
        japan_arrival_days=10,      # 保守的デフォルト
        is_realtime_stock=True,
        packaging_quality="good",
        buyma_rank=None,
        sns_trending=False,
        japan_soldout=False,
        japan_exclusive=False,
        favorites_count=favorites,
        has_cart_addition=has_cart,
        source_type="select",       # 保守的デフォルト（実際はauthorized/official が多い）
        is_volume_zone=True,
        customs_rate=0.10,
        shipping_cost_jpy=2000.0,
        buyma_fee_rate=0.077,
        fx_buffer_rate=0.03,
        target_profit_rate=0.15,
        product_category=category,
    )
    return PurchaseEvaluator().evaluate(inp)


def _build_record(
    brand: str, product_name: str,
    source_url: str, source_price: float,
    exchange_rate: float, buyma_price: float,
    candidate_urls: list[str],
    score: "PurchaseScore",
    buyma_style_id: str = "",
    match_score: Optional["MatchScore"] = None,
) -> ProductRecord:
    """ProductRecord を構築する。"""
    profit_str = str(round(score.profit_breakdown.profit)) if score.profit_breakdown else ""
    identity_grade = (match_score.grade if match_score else "")
    price_basis = (match_score.price_note if match_score else "")
    return ProductRecord(
        商品名=f"{brand} {product_name}",
        ブランド=brand,
        型番=(buyma_style_id or "").strip(),
        仕入れURL=source_url,
        現地価格=str(round(source_price, 2)) if source_price > 0 else "",
        為替=str(round(exchange_rate, 2)),
        BUYMA販売価格=str(int(buyma_price)) if buyma_price > 0 else "",
        在庫ステータス="出品前",
        利益額=profit_str,
        候補URLs=",".join(candidate_urls) if len(candidate_urls) > 1 else "",
        同一性スコア=identity_grade,
        価格根拠=price_basis[:200],
    )


def _write_to_sheet(record: ProductRecord) -> None:
    """シートに書き込む。設定がない場合はスキップ。"""
    try:
        from lib.config import Config
        config = Config.from_env()
        errors = config.validate()
        if errors:
            cli_print("  ⚠️  シート設定が未完了のため書き込みをスキップします。")
            cli_print(f"     商品情報: {record.商品名}")
            for e in errors:
                cli_print(f"       - {e}")
            return

        manager = SheetManager(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_path=config.credentials_path,
        )
        manager.ensure_header()
        action = manager.upsert_record(record)
        verb = "追加" if action == "appended" else "更新"
        cli_print(f"  ✅ シートに{verb}しました: {record.商品名}")

    except Exception as e:
        cli_print(f"  ❌ シートへの書き込み失敗: {e}")
        cli_print("  商品情報（手動でシートに追加してください）:")
        for col, val in zip(["商品名", "ブランド", "型番", "仕入れURL", "現地価格",
                              "為替", "BUYMA販売価格", "在庫ステータス", "利益額"],
                             record.to_row()):
            if val:
                cli_print(f"    {col}: {val}")


def _write_to_sheet_quiet(record: ProductRecord) -> bool:
    """シートに書き込み、成功可否を bool で返す（自動モード用）。"""
    try:
        from lib.config import Config
        config = Config.from_env()
        errors = config.validate()
        if errors:
            cli_print("  ⚠️  シート設定が未完了のため書き込みをスキップします。")
            return False
        manager = SheetManager(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_path=config.credentials_path,
        )
        manager.ensure_header()
        action = manager.upsert_record(record)
        verb = "追加" if action == "appended" else "更新"
        cli_print(f"  ✅ シートに{verb}しました: {record.商品名}")
        return True
    except Exception as e:
        cli_print(f"  ❌ シートへの書き込み失敗: {e}")
        return False


# UI helpers are imported from lib.intake_cli at the top of the file.



# ============================================================================
# エントリーポイント
# ============================================================================

def main() -> int:
    from lib.logging_config import setup_logging

    setup_logging(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="BUYMA 商品取り込みツール")
    parser.add_argument("--batch", metavar="FILE.csv",
                        help="CSV を一括評価する（スクレイプなし）")
    parser.add_argument("--auto-buyma", metavar="URL",
                        help="BUYMA 商品 URL から仕入先を自動探索してシートに追加")
    parser.add_argument("--auto-sheet", action="store_true",
                        help="シートの BUYMA候補 行を一括で自動処理")
    parser.add_argument("--limit", type=int, default=0,
                        help="--auto-sheet 時の最大件数（0=漏斗の週次上限、既定40）")
    parser.add_argument("--no-funnel", action="store_true",
                        help="漏斗フィルタ・自動見送り・型番site検索を無効化")
    parser.add_argument("--include-low-grades", action="store_true",
                        help="D/E グレードもシートに反映する")
    args = parser.parse_args()

    skip_low = not args.include_low_grades
    use_funnel = not args.no_funnel

    if args.batch:
        batch_intake(args.batch)
    elif args.auto_buyma:
        ok = auto_intake_from_buyma(args.auto_buyma, skip_low_grades=skip_low)
        return 0 if ok else 1
    elif args.auto_sheet:
        auto_intake_from_sheet(
            limit=args.limit, skip_low_grades=skip_low, use_funnel=use_funnel,
        )
    else:
        interactive_intake()
    return 0


if __name__ == "__main__":
    sys.exit(main())
