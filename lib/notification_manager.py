"""
通知マネージャー — お宝商品の検出と各種通知・出品の統合オーケストレーター。

役割:
  1. スプレッドシートの全商品を確認し「お宝（利益 ≥ しきい値）」を抽出
  2. 新規発見のお宝のみ LINE に通知（重複通知を防ぐ）
  3. オプションで画像処理 → BUYMA 自動出品まで実行

環境変数:
  LINE_NOTIFY_TOKEN         : LINE Notify トークン
  LINE_CHANNEL_ACCESS_TOKEN : LINE Messaging API トークン
  LINE_USER_ID              : 送信先 LINE ユーザーID
  LINE_PROFIT_THRESHOLD     : 利益しきい値（default: 30000）
  BUYMA_EMAIL               : BUYMA ログインメール
  BUYMA_PASSWORD            : BUYMA ログインパスワード
  AUTO_LIST_GRADE           : 自動出品するグレード閾値（default: A）
  BG_REMOVAL_BACKEND        : rembg / removebg / nanobanana2 (default: rembg)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.line_notifier import LINENotifier, TreasureAlert
from lib.sheet_manager import ProductRecord

logger = logging.getLogger(__name__)

# 通知済みアイテムを記録するキャッシュファイル
_NOTIFIED_CACHE_FILE = Path(".notified_treasures.json")


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class NotificationEvent:
    """1回の通知処理の結果。"""

    detected_count: int       # お宝として検出した件数
    new_count: int            # 新規（未通知）お宝の件数
    notified: bool            # 実際に通知を送ったか
    listed_count: int = 0     # 自動出品した件数
    images_processed: int = 0 # 画像処理した件数
    errors: list[str] = field(default_factory=list)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 通知マネージャー
# ============================================================================

class NotificationManager:
    """お宝検出・LINE通知・画像処理・BUYMA出品を一元管理するクラス。

    Args:
        profit_threshold: 通知する最低利益額（default: 環境変数 LINE_PROFIT_THRESHOLD）
        auto_list_grade: この グレード以上の商品を自動出品する（None で無効）
        enable_image_processing: 画像処理を実行するか
    """

    def __init__(
        self,
        profit_threshold: float | None = None,
        auto_list_grade: str | None = None,
        enable_image_processing: bool = False,
    ) -> None:
        self._threshold = profit_threshold or float(
            os.getenv("LINE_PROFIT_THRESHOLD", "30000")
        )
        self._auto_list_grade = (
            auto_list_grade or os.getenv("AUTO_LIST_GRADE", "")
        ) or None
        self._enable_image = enable_image_processing
        self._notifier = LINENotifier(profit_threshold=self._threshold)

    def process(self, results: list) -> NotificationEvent:
        """メイン処理エントリーポイント。

        Args:
            results: main.py の ProductResult オブジェクトのリスト。

        Returns:
            NotificationEvent
        """
        # 1. お宝商品の抽出
        treasures = self._extract_treasures(results)
        logger.info(
            "お宝検出: %d 件 (しきい値: ¥%,.0f)",
            len(treasures), self._threshold,
        )

        if not treasures:
            return NotificationEvent(
                detected_count=0, new_count=0, notified=False
            )

        # 2. 重複フィルタ（前回通知済みを除外）
        cache = _load_notified_cache()
        new_treasures = [
            t for t in treasures
            if _cache_key(t) not in cache
        ]
        logger.info(
            "うち新規お宝: %d 件（既通知を除外）", len(new_treasures)
        )

        event = NotificationEvent(
            detected_count=len(treasures),
            new_count=len(new_treasures),
            notified=False,
        )

        if not new_treasures:
            return event

        # 3. 画像処理（オプション）
        if self._enable_image:
            img_count = self._process_images(new_treasures, results)
            event.images_processed = img_count

        # 4. LINE 通知
        if self._notifier.is_configured:
            line_result = self._notifier.notify_treasures(new_treasures)
            event.notified = line_result.success
            if not line_result.success:
                event.errors.append(f"LINE通知失敗: {line_result.error}")
        else:
            logger.info(
                "LINE通知未設定。お宝 %d 件:\n%s",
                len(new_treasures),
                "\n".join(
                    f"  [{t.grade or '?'}] {t.brand} {t.product_name} — {t.profit_jpy_str}"
                    for t in new_treasures
                ),
            )

        # 5. BUYMA 自動出品（オプション）
        if self._auto_list_grade:
            list_count = self._auto_list(new_treasures, results)
            event.listed_count = list_count

        # 6. 通知済みキャッシュを更新
        for t in new_treasures:
            cache[_cache_key(t)] = datetime.now(timezone.utc).isoformat()
        _save_notified_cache(cache)

        return event

    # ------------------------------------------------------------------
    # お宝抽出
    # ------------------------------------------------------------------

    def _extract_treasures(self, results: list) -> list[TreasureAlert]:
        """ProductResult リストからお宝商品を抽出する。"""
        alerts = []
        for r in results:
            try:
                breakdown = r.breakdown
                if breakdown is None:
                    continue
                profit = breakdown.profit
                if profit < self._threshold:
                    continue
                if r.scrape and r.scrape.stock_status == "out_of_stock":
                    continue

                alerts.append(TreasureAlert(
                    product_name=r.updated.商品名,
                    brand=r.updated.ブランド,
                    buyma_price=float(r.updated.BUYMA販売価格 or 0),
                    profit=profit,
                    profit_rate=breakdown.profit_rate,
                    source_url=r.updated.仕入れURL,
                    stock_status=r.scrape.stock_status if r.scrape else "unknown",
                    grade=None,  # PurchaseEvaluator を統合した場合はここでセット
                ))
            except Exception as e:
                logger.debug("お宝抽出スキップ [%s]: %s", getattr(r, 'product_name', '?'), e)

        return sorted(alerts, key=lambda a: a.profit, reverse=True)

    # ------------------------------------------------------------------
    # 画像処理
    # ------------------------------------------------------------------

    def _process_images(self, alerts: list[TreasureAlert], results: list) -> int:
        """お宝商品の画像を処理する。"""
        try:
            from lib.image_processor import BUYMAImageProcessor
        except ImportError:
            logger.warning("image_processor が利用できません。画像処理をスキップします。")
            return 0

        processor = BUYMAImageProcessor()
        processed = 0

        for alert in alerts:
            # 仕入れ元URLから画像を取得するため、対応する scrape 結果から画像URLを探す
            # (実際の商品画像URLは scraper で取得する必要がある)
            image_url = alert.image_url
            if not image_url:
                logger.debug("画像URL不明のためスキップ: %s", alert.product_name)
                continue

            filename = f"{alert.brand}_{alert.product_name}"[:50]
            result = processor.process_url(image_url, filename)
            if result.success:
                alert.image_url = result.output_path  # 処理済み画像パスで上書き
                processed += 1
                logger.info("画像処理完了: %s → %s", alert.product_name, result)
            else:
                logger.warning("画像処理失敗: %s — %s", alert.product_name, result.error)

        return processed

    # ------------------------------------------------------------------
    # 自動出品
    # ------------------------------------------------------------------

    def _auto_list(self, alerts: list[TreasureAlert], results: list) -> int:
        """グレード条件を満たすお宝商品を BUYMA に自動出品する。"""
        try:
            from lib.buyma_automator import BUYMAAutomator, record_to_listing
        except ImportError:
            logger.warning("buyma_automator が利用できません。自動出品をスキップします。")
            return 0

        automator = BUYMAAutomator()
        if not automator.is_configured:
            logger.info("BUYMA_EMAIL / BUYMA_PASSWORD 未設定。自動出品をスキップします。")
            return 0

        grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        threshold_order = grade_order.get(self._auto_list_grade, 1)

        target_alerts = [
            a for a in alerts
            if grade_order.get(a.grade or "E", 4) <= threshold_order
        ]
        if not target_alerts:
            logger.info("自動出品対象のグレードに達する商品がありません。")
            return 0

        # ProductRecord を引いて ListingData を構築
        record_map = {r.updated.商品名: r.updated for r in results}
        listings = []
        for alert in target_alerts:
            record = record_map.get(alert.product_name)
            if record:
                img_paths = [alert.image_url] if alert.image_url and Path(alert.image_url).exists() else []
                listings.append(record_to_listing(record, image_paths=img_paths))

        if not listings:
            return 0

        import asyncio
        listing_results = asyncio.run(
            automator.post_batch_async(listings, interval_sec=8.0)
        )
        success_count = sum(1 for r in listing_results if r.success)
        logger.info("自動出品完了: %d / %d 件成功", success_count, len(listings))
        return success_count


# ============================================================================
# キャッシュ管理
# ============================================================================

def _cache_key(alert: TreasureAlert) -> str:
    return f"{alert.brand}::{alert.product_name}::{alert.source_url}"


def _load_notified_cache() -> dict:
    from lib.file_lock import atomic_json_read
    return atomic_json_read(_NOTIFIED_CACHE_FILE, default={})


def _save_notified_cache(cache: dict) -> None:
    from lib.file_lock import atomic_json_write
    atomic_json_write(_NOTIFIED_CACHE_FILE, cache)
