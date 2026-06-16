"""商品取り込みの非対話パイプライン処理。

評価（PurchaseEvaluator 実行）・ProductRecord 構築・シート書き込みなど、
ユーザー入力を伴わない処理を intake.py から分離したもの。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from lib.intake_cli import cli_print
from lib.purchase_evaluator import (
    EvaluationInput,
    PurchaseEvaluator,
    PurchaseScore,
)
from lib.sheet_manager import ProductRecord, SheetManager

if TYPE_CHECKING:
    from lib.buyma_demand import BUYMADemandSignal
    from lib.product_identity import MatchScore

logger = logging.getLogger(__name__)


def evaluate(
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


def build_record(
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


def _build_manager() -> tuple[Optional[SheetManager], list[str]]:
    """設定を検証して SheetManager を生成する。未設定なら (None, エラー一覧)。"""
    from lib.config import Config
    config = Config.from_env()
    errors = config.validate()
    if errors:
        cli_print("  ⚠️  シート設定が未完了のため書き込みをスキップします。")
        return None, errors
    manager = SheetManager(
        spreadsheet_id=config.spreadsheet_id,
        worksheet_name=config.worksheet_name,
        credentials_path=config.credentials_path,
    )
    return manager, []


def write_to_sheet(record: ProductRecord) -> None:
    """シートに書き込む。設定がない場合はスキップ。"""
    try:
        manager, errors = _build_manager()
        if manager is None:
            cli_print(f"     商品情報: {record.商品名}")
            for e in errors:
                cli_print(f"       - {e}")
            return
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


def write_to_sheet_quiet(record: ProductRecord) -> bool:
    """シートに書き込み、成功可否を bool で返す（自動モード用）。"""
    try:
        manager, _errors = _build_manager()
        if manager is None:
            return False
        manager.ensure_header()
        action = manager.upsert_record(record)
        verb = "追加" if action == "appended" else "更新"
        cli_print(f"  ✅ シートに{verb}しました: {record.商品名}")
        return True
    except Exception as e:
        cli_print(f"  ❌ シートへの書き込み失敗: {e}")
        return False
