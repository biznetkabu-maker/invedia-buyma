"""
仕入れ判断 CLI ツール。

使い方:

  # 対話モード（プロンプトで入力）
  python3 evaluate.py

  # スプレッドシートの全商品を一括評価（既存のシートデータを使用）
  python3 evaluate.py --sheet

  # サンプル評価（デモ）
  python3 evaluate.py --demo

  # CSV 出力
  python3 evaluate.py --sheet --csv results.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Optional

from lib.config import Config
from lib.intake_cli import cli_print
from lib.purchase_evaluator import EvaluationInput, PurchaseEvaluator, PurchaseScore
from lib.sheet_manager import ProductRecord, SheetManager


def _prompt(label: str, default=None, type_fn=str, choices: list | None = None):
    """ユーザーに入力を促す汎用プロンプト。"""
    hint = f" [{default}]" if default is not None else ""
    if choices:
        hint += f" ({'/'.join(str(c) for c in choices)})"
    while True:
        raw = input(f"  {label}{hint}: ").strip()
        if not raw and default is not None:
            return default
        if not raw:
            cli_print("    ⚠️  必須項目です。")
            continue
        try:
            val = type_fn(raw)
            if choices and val not in choices:
                cli_print(f"    ⚠️  {choices} から選択してください。")
                continue
            return val
        except (ValueError, TypeError):
            cli_print("    ⚠️  入力形式が正しくありません。")


def _prompt_bool(label: str, default: bool = False) -> bool:
    hint = "y/N" if not default else "Y/n"
    raw = input(f"  {label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "はい", "1", "true")


def interactive_mode() -> PurchaseScore:
    """対話モードで入力を受け付けて評価する。"""
    cli_print("\n" + "=" * 60)
    cli_print("  BUYMA 仕入れ判断シミュレーター — 対話モード")
    cli_print("=" * 60)
    cli_print("  各項目を入力してください（[] 内はデフォルト値）\n")

    cli_print("── 基本情報 ─────────────────────────────────")
    product_name   = _prompt("商品名")
    brand          = _prompt("ブランド名")
    model_year     = _prompt("モデル年（例: 2024）", 2025, int)
    source_url     = _prompt("仕入れURL")
    source_price   = _prompt("現地価格（数値）", type_fn=float)
    currency       = _prompt("通貨コード", "USD", choices=["USD", "EUR", "GBP", "JPY", "CAD", "AUD"])
    exchange_rate  = _prompt("為替レート（1外貨=X円）", 155.0, float)
    buyma_price    = _prompt("BUYMA予定販売価格（JPY）", type_fn=float)
    japan_retail   = _prompt("日本公式定価（JPY、不明は 0）", 0, float)

    cli_print("\n── 物流情報 ─────────────────────────────────")
    dispatch_days       = _prompt("注文から現地発送までの日数", 3, int)
    japan_arrival_days  = _prompt("現地発送から日本着までの日数", 7, int)
    is_realtime_stock   = _prompt_bool("在庫はリアルタイム表示か", True)
    packaging_quality   = _prompt("梱包品質", "excellent", choices=["excellent", "good", "unknown"])

    cli_print("\n── 市場需要 ─────────────────────────────────")
    buyma_rank_str = input("  BUYMAランキング順位（不明は Enter）: ").strip()
    buyma_rank: Optional[int] = int(buyma_rank_str) if buyma_rank_str else None
    sns_trending        = _prompt_bool("SNSでトレンド中か", False)
    japan_soldout       = _prompt_bool("国内完売か", False)
    japan_exclusive     = _prompt_bool("日本未入荷カラー/サイズか", False)
    favorites_count     = _prompt("直近1週間のお気に入り登録数", 0, int)
    has_cart_addition   = _prompt_bool("カート投入（購入意思）があるか", False)

    cli_print("\n── リスク管理 ───────────────────────────────")
    source_type   = _prompt(
        "仕入れ先種別", "authorized",
        choices=["official", "authorized", "select", "unknown"]
    )
    is_volume_zone = _prompt_bool("日本ボリュームゾーン（Mサイズ・定番色）か", True)

    cli_print("\n── 計算パラメータ（任意、Enter でデフォルト使用）──")
    customs_rate        = _prompt("関税率（例: 0.10）", 0.10, float)
    shipping_cost_jpy   = _prompt("国際送料固定（JPY）", 2000.0, float)
    buyma_fee_rate      = _prompt("BUYMA手数料率（例: 0.077）", 0.077, float)
    fx_buffer_rate      = _prompt("為替バッファ率（例: 0.03）", 0.03, float)
    target_profit_rate  = _prompt("目標利益率（例: 0.15）", 0.15, float)

    inp = EvaluationInput(
        product_name=product_name,
        brand=brand,
        model_year=model_year,
        source_url=source_url,
        source_price=source_price,
        currency=currency,
        exchange_rate=exchange_rate,
        buyma_price=buyma_price,
        japan_retail_price=japan_retail,
        dispatch_days=dispatch_days,
        japan_arrival_days=japan_arrival_days,
        is_realtime_stock=is_realtime_stock,
        packaging_quality=packaging_quality,
        buyma_rank=buyma_rank,
        sns_trending=sns_trending,
        japan_soldout=japan_soldout,
        japan_exclusive=japan_exclusive,
        favorites_count=favorites_count,
        has_cart_addition=has_cart_addition,
        source_type=source_type,
        is_volume_zone=is_volume_zone,
        customs_rate=customs_rate,
        shipping_cost_jpy=shipping_cost_jpy,
        buyma_fee_rate=buyma_fee_rate,
        fx_buffer_rate=fx_buffer_rate,
        target_profit_rate=target_profit_rate,
    )

    evaluator = PurchaseEvaluator()
    return evaluator.evaluate(inp)


def _record_to_input(record: ProductRecord, config: Config) -> Optional[EvaluationInput]:
    """ProductRecord から EvaluationInput を生成する（物流・需要は不明値で補完）。"""
    try:
        source_price   = float(record.現地価格 or 0)
        exchange_rate  = float(record.為替 or 0)
        buyma_price    = float(record.BUYMA販売価格 or 0)
    except ValueError:
        return None

    if source_price <= 0 or exchange_rate <= 0 or buyma_price <= 0:
        return None

    return EvaluationInput(
        product_name=record.商品名,
        brand=record.ブランド,
        model_year=2024,           # 不明 → 保守的に2024年と仮定
        source_url=record.仕入れURL,
        source_price=source_price,
        currency="USD",            # デフォルトUSD（実際はスクレイプ時に判明）
        exchange_rate=exchange_rate,
        buyma_price=buyma_price,
        japan_retail_price=0.0,    # 不明
        dispatch_days=5,           # 保守的なデフォルト
        japan_arrival_days=10,     # 保守的なデフォルト
        is_realtime_stock=True,    # 大手セレクトは基本リアルタイム
        packaging_quality="good",
        buyma_rank=None,
        sns_trending=False,
        japan_soldout=False,
        japan_exclusive=False,
        favorites_count=0,
        has_cart_addition=False,
        source_type="select",      # セレクト想定（保守的）
        is_volume_zone=True,
        customs_rate=config.customs_rate,
        shipping_cost_jpy=config.shipping_cost_jpy,
        buyma_fee_rate=config.buyma_fee_rate,
        fx_buffer_rate=0.03,
        target_profit_rate=config.target_profit_rate,
    )


def sheet_mode(config: Config, csv_path: str = "") -> list[PurchaseScore]:
    """スプレッドシートから全商品を読み込んで一括評価する。"""
    cli_print("\n  スプレッドシートから商品を読み込み中...")
    manager = SheetManager(
        spreadsheet_id=config.spreadsheet_id,
        worksheet_name=config.worksheet_name,
        credentials_path=config.credentials_path,
    )
    records = manager.get_all_records()
    cli_print(f"  {len(records)} 件の商品を読み込みました。\n")

    evaluator = PurchaseEvaluator()
    scores: list[PurchaseScore] = []

    for record in records:
        inp = _record_to_input(record, config)
        if inp is None:
            cli_print(f"  ⚠️  スキップ: {record.商品名}（価格データ不足）")
            continue
        score = evaluator.evaluate(inp)
        scores.append(score)
        grade_icon = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "⛔"}.get(score.grade, "❓")
        cli_print(
            f"  {grade_icon} [{score.grade}] {score.product_name:<25}"
            f" | スコア {score.overall_score:5.1f}"
            f" | 実質利益率 {score.effective_profit_rate:5.1%}"
        )

    if csv_path:
        _export_csv(scores, csv_path)
        cli_print(f"\n  📄 CSV に書き出しました: {csv_path}")

    return scores


def demo_mode() -> list[PurchaseScore]:
    """デモ用サンプル評価を実行して出力する。"""
    samples = [
        EvaluationInput(
            product_name="GG マーモント ミニバッグ (黒)",
            brand="GUCCI",
            model_year=2024,
            source_url="https://www.ssense.com/en-us/women/product/gucci/gg-marmont/example",
            source_price=750.0, currency="USD", exchange_rate=155.0,
            buyma_price=175_000, japan_retail_price=198_000,
            dispatch_days=3, japan_arrival_days=7, is_realtime_stock=True,
            packaging_quality="excellent", buyma_rank=5, sns_trending=True,
            japan_soldout=True, japan_exclusive=False,
            favorites_count=35, has_cart_addition=True,
            source_type="authorized", is_volume_zone=True,
            customs_rate=0.10, shipping_cost_jpy=2000, buyma_fee_rate=0.077,
            fx_buffer_rate=0.03, target_profit_rate=0.15,
        ),
        EvaluationInput(
            product_name="レザーショルダーバッグ (ピンク・XS)",
            brand="PRADA",
            model_year=2021,  # 3年前
            source_url="https://www.farfetch.com/shopping/women/prada/example",
            source_price=1200.0, currency="USD", exchange_rate=155.0,
            buyma_price=160_000, japan_retail_price=180_000,
            dispatch_days=8, japan_arrival_days=12, is_realtime_stock=False,
            packaging_quality="unknown", buyma_rank=120, sns_trending=False,
            japan_soldout=False, japan_exclusive=False,
            favorites_count=3, has_cart_addition=False,
            source_type="select", is_volume_zone=False,
            customs_rate=0.10, shipping_cost_jpy=2000, buyma_fee_rate=0.077,
            fx_buffer_rate=0.01, target_profit_rate=0.15,
        ),
        EvaluationInput(
            product_name="バーキン 30 (エトゥープ)",
            brand="HERMÈS",
            model_year=2025,
            source_url="https://www.harrods.com/en-gb/shopping/hermes-birkin",
            source_price=8_500.0, currency="GBP", exchange_rate=196.0,
            buyma_price=3_200_000, japan_retail_price=2_800_000,
            dispatch_days=2, japan_arrival_days=5, is_realtime_stock=True,
            packaging_quality="excellent", buyma_rank=1, sns_trending=True,
            japan_soldout=True, japan_exclusive=True,
            favorites_count=89, has_cart_addition=True,
            source_type="official", is_volume_zone=True,
            customs_rate=0.10, shipping_cost_jpy=5000, buyma_fee_rate=0.055,
            fx_buffer_rate=0.03, target_profit_rate=0.15,
        ),
    ]

    evaluator = PurchaseEvaluator()
    scores = [evaluator.evaluate(s) for s in samples]

    cli_print("\n" + "=" * 60)
    cli_print("  BUYMA 仕入れ判断シミュレーター — デモ結果")
    cli_print("=" * 60)
    for score in scores:
        cli_print(score.summary())
        cli_print()

    return scores


def _export_csv(scores: list[PurchaseScore], path: str) -> None:
    """評価結果を CSV に書き出す。"""
    rows = []
    for s in scores:
        rows.append({
            "商品名": s.product_name,
            "ブランド": s.brand,
            "グレード": s.grade,
            "総合スコア": s.overall_score,
            "物流スコア": s.logistics.aggregate_score,
            "需要スコア": s.demand.aggregate_score,
            "経済性スコア": s.economics.aggregate_score,
            "リスクスコア": s.risk.aggregate_score,
            "実質利益率": f"{s.effective_profit_rate:.2%}",
            "推奨": "推奨" if s.is_recommended else "非推奨",
            "致命的問題": " / ".join(s.critical_issues),
            "URL": s.source_url,
        })
    if rows:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BUYMA 仕入れ判断シミュレーター",
    )
    parser.add_argument("--demo",  action="store_true", help="デモ評価を実行")
    parser.add_argument("--sheet", action="store_true", help="スプレッドシートの全商品を一括評価")
    parser.add_argument("--csv",   type=str, default="", help="結果をCSVに書き出す（パスを指定）")
    args = parser.parse_args()

    if args.demo:
        demo_mode()
        return 0

    if args.sheet:
        config = Config.from_env()
        errors = config.validate()
        if errors:
            for e in errors:
                cli_print(f"❌ 設定エラー: {e}")
            return 1
        scores = sheet_mode(config, csv_path=args.csv)
        cli_print(f"\n  評価完了: {len(scores)} 件")
        recommended = [s for s in scores if s.is_recommended]
        cli_print(f"  推奨（A/B）: {len(recommended)} 件")
        if recommended:
            cli_print("\n  🟢 仕入れ推奨商品一覧:")
            for s in recommended:
                cli_print(f"    [{s.grade}] {s.product_name} — スコア {s.overall_score:.1f}")
        return 0

    # デフォルト: 対話モード
    score = interactive_mode()
    cli_print("\n" + score.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
