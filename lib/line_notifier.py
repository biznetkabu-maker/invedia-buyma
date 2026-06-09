"""
LINE 通知モジュール。

お宝商品（利益 ≥ 指定額）が見つかった際に LINE へ通知する。

送信方式:
  - LINE Messaging API: チャンネルBot経由の通知（推奨）
  - LINE Notify       : 非推奨（2025年3月末廃止済み、フォールバックのみ）

環境変数:
  LINE_CHANNEL_ACCESS_TOKEN : LINE Messaging API チャンネルアクセストークン
  LINE_USER_ID              : 送信先ユーザーID または グループID
  LINE_PROFIT_THRESHOLD     : 通知する利益額のしきい値（default: 30000）
  LINE_NOTIFY_TOKEN         : (非推奨) LINE Notify アクセストークン
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

from lib import http_client

logger = logging.getLogger(__name__)

_LINE_NOTIFY_ENDPOINT = "https://notify-api.line.me/api/notify"
_LINE_MESSAGING_API = "https://api.line.me/v2/bot/message/push"


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class TreasureAlert:
    """通知する「お宝商品」の情報。"""

    product_name: str
    brand: str
    buyma_price: float
    profit: float
    profit_rate: float
    source_url: str
    stock_status: str
    image_url: Optional[str] = None
    grade: Optional[str] = None   # PurchaseEvaluator のグレード

    @property
    def profit_jpy_str(self) -> str:
        return f"¥{self.profit:,.0f}"

    @property
    def profit_rate_str(self) -> str:
        return f"{self.profit_rate:.1%}"


@dataclass
class NotificationResult:
    success: bool
    method: str
    error: Optional[str] = None


# ============================================================================
# LINE Notify 送信クラス
# ============================================================================

class LINENotifyClient:
    """LINE Notify API クライアント（非推奨: 2025年3月末廃止済み）。

    LINE Messaging API への移行を推奨します。
    このクライアントは Messaging API が利用不可な場合の
    フォールバックとしてのみ残されています。
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.getenv("LINE_NOTIFY_TOKEN", "")
        if self._token:
            import warnings
            warnings.warn(
                "LINE Notify API は 2025年3月末に廃止されました。"
                "LINE Messaging API (LINE_CHANNEL_ACCESS_TOKEN) への移行を推奨します。",
                DeprecationWarning,
                stacklevel=2,
            )

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def send(
        self,
        message: str,
        image_url: Optional[str] = None,
        image_thumbnail: Optional[str] = None,
        sticker_package_id: Optional[int] = None,
        sticker_id: Optional[int] = None,
    ) -> NotificationResult:
        """LINE Notify でメッセージを送信する。

        Args:
            message: 通知テキスト（最大1000文字）
            image_url: 添付画像URL（フルサイズ）
            image_thumbnail: 添付画像URL（サムネイル）
        """
        if not self.is_configured:
            return NotificationResult(
                success=False, method="LINE Notify",
                error="LINE_NOTIFY_TOKEN が設定されていません"
            )

        headers = {"Authorization": f"Bearer {self._token}"}
        data: dict = {"message": message[:1000]}
        if image_url:
            data["imageFullsize"] = image_url
            data["imageThumbnail"] = image_thumbnail or image_url
        if sticker_package_id and sticker_id:
            data["stickerPackageId"] = sticker_package_id
            data["stickerId"] = sticker_id

        try:
            resp = http_client.post(
                _LINE_NOTIFY_ENDPOINT, headers=headers, data=data, timeout=15
            )
            resp.raise_for_status()
            logger.info("LINE Notify 送信成功")
            return NotificationResult(success=True, method="LINE Notify")
        except requests.HTTPError:
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("LINE Notify 送信失敗: %s", err)
            return NotificationResult(success=False, method="LINE Notify", error=err)
        except Exception as e:
            logger.error("LINE Notify 送信例外: %s", e)
            return NotificationResult(success=False, method="LINE Notify", error=str(e))


# ============================================================================
# LINE Messaging API クライアント
# ============================================================================

class LINEMessagingClient:
    """LINE Messaging API クライアント（Flex Message で見やすいカード通知）。

    セットアップ:
      1. LINE Developers でプロバイダー・チャンネルを作成
      2. Messaging API チャンネルのアクセストークンを発行
      3. LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID 環境変数に設定
    """

    def __init__(
        self,
        channel_token: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._token = channel_token or os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._user_id = user_id or os.getenv("LINE_USER_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._token and self._user_id)

    def send_text(self, message: str) -> NotificationResult:
        """テキストメッセージを送信する。"""
        if not self.is_configured:
            return NotificationResult(
                success=False, method="LINE Messaging API",
                error="LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定"
            )
        payload = {
            "to": self._user_id,
            "messages": [{"type": "text", "text": message[:5000]}],
        }
        try:
            resp = http_client.post(
                _LINE_MESSAGING_API,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False),
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("LINE Messaging API テキスト送信成功")
            return NotificationResult(success=True, method="LINE Messaging API")
        except requests.HTTPError:
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("LINE Messaging API テキスト送信失敗: %s", err)
            return NotificationResult(success=False, method="LINE Messaging API", error=err)
        except Exception as e:
            logger.error("LINE Messaging API 例外: %s", e)
            return NotificationResult(success=False, method="LINE Messaging API", error=str(e))

    def send_treasure_card(self, alerts: list[TreasureAlert]) -> NotificationResult:
        """Flex Message でお宝商品カードを送信する。"""
        if not self.is_configured:
            return NotificationResult(
                success=False, method="LINE Messaging API",
                error="LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定"
            )

        messages = [self._build_flex_message(a) for a in alerts[:5]]  # 最大5件/回

        payload = {
            "to": self._user_id,
            "messages": messages,
        }

        try:
            resp = http_client.post(
                _LINE_MESSAGING_API,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False),
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("LINE Messaging API 送信成功: %d 件", len(messages))
            return NotificationResult(success=True, method="LINE Messaging API")
        except requests.HTTPError:
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("LINE Messaging API 送信失敗: %s", err)
            return NotificationResult(success=False, method="LINE Messaging API", error=err)
        except Exception as e:
            logger.error("LINE Messaging API 例外: %s", e)
            return NotificationResult(success=False, method="LINE Messaging API", error=str(e))

    @staticmethod
    def _build_flex_message(alert: TreasureAlert) -> dict:
        """Flex Message カードを構築する。"""
        grade_color = {
            "A": "#22c55e",  # 緑
            "B": "#84cc16",  # 黄緑
            "C": "#f59e0b",  # オレンジ
        }.get(alert.grade or "", "#6b7280")

        header_text = f"🎯 お宝発見！ {alert.brand}"
        if alert.grade:
            header_text = f"[グレード{alert.grade}] " + header_text

        body_contents = [
            {"type": "text", "text": alert.product_name, "weight": "bold", "size": "md", "wrap": True},
            {"type": "separator", "margin": "md"},
            {
                "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                "contents": [
                    _flex_row("💴 利益", f"{alert.profit_jpy_str}（{alert.profit_rate_str}）", "#e74c3c"),
                    _flex_row("💴 BUYMA価格", f"¥{alert.buyma_price:,.0f}"),
                    _flex_row("📦 在庫", alert.stock_status),
                ],
            },
        ]

        footer_contents = [
            {
                "type": "button",
                "style": "primary",
                "color": grade_color,
                "action": {
                    "type": "uri",
                    "label": "仕入れページを開く",
                    "uri": alert.source_url,
                },
            }
        ]

        return {
            "type": "flex",
            "altText": f"お宝発見！{alert.brand} {alert.product_name} 利益{alert.profit_jpy_str}",
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": grade_color,
                    "contents": [
                        {"type": "text", "text": header_text,
                         "color": "#ffffff", "weight": "bold", "size": "sm"}
                    ],
                },
                "body": {
                    "type": "box", "layout": "vertical", "contents": body_contents
                },
                "footer": {
                    "type": "box", "layout": "vertical", "contents": footer_contents
                },
            },
        }


def _flex_row(label: str, value: str, value_color: str = "#333333") -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "color": "#888888", "size": "sm", "flex": 2},
            {"type": "text", "text": value, "color": value_color,
             "size": "sm", "flex": 3, "wrap": True, "weight": "bold"},
        ],
    }


# ============================================================================
# 通知マネージャー（ファサード）
# ============================================================================

class LINENotifier:
    """LINE Notify と Messaging API を統合した通知クライアント。

    利用可能な方式を自動選択し、フォールバックする。

    Args:
        notify_token: LINE Notify トークン（None で環境変数から読み込み）
        messaging_token: LINE Messaging API トークン（None で環境変数から読み込み）
        messaging_user_id: 送信先ユーザーID（None で環境変数から読み込み）
        profit_threshold: 通知する最低利益額（デフォルト 30,000 円）
    """

    def __init__(
        self,
        notify_token: str | None = None,
        messaging_token: str | None = None,
        messaging_user_id: str | None = None,
        profit_threshold: float | None = None,
    ) -> None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self._notify = LINENotifyClient(notify_token)
        self._messaging = LINEMessagingClient(messaging_token, messaging_user_id)
        self._threshold = profit_threshold or float(
            os.getenv("LINE_PROFIT_THRESHOLD", "30000")
        )

    @property
    def is_configured(self) -> bool:
        return self._notify.is_configured or self._messaging.is_configured

    def send_text(self, message: str) -> NotificationResult:
        """任意のテキストを通知する（Messaging API 優先、なければ Notify）。"""
        if self._messaging.is_configured:
            return self._messaging.send_text(message)
        return self._notify.send(message)

    def notify_treasure(self, alert: TreasureAlert) -> NotificationResult:
        """1件のお宝商品を通知する。"""
        return self.notify_treasures([alert])

    def notify_treasures(self, alerts: list[TreasureAlert]) -> NotificationResult:
        """複数のお宝商品をまとめて通知する。"""
        if not alerts:
            return NotificationResult(success=True, method="none (no alerts)")

        if not self.is_configured:
            logger.warning(
                "LINE通知が設定されていません。"
                "LINE_NOTIFY_TOKEN または LINE_CHANNEL_ACCESS_TOKEN を設定してください。"
            )
            return NotificationResult(
                success=False, method="none",
                error="LINE通知未設定"
            )

        # Messaging API を優先、次に Notify
        if self._messaging.is_configured:
            result = self._messaging.send_treasure_card(alerts)
            if result.success:
                return result
            logger.warning("Messaging API 失敗。LINE Notify にフォールバック")

        if self._notify.is_configured:
            return self._notify.send(self._build_notify_text(alerts))

        return NotificationResult(success=False, method="none", error="全送信方式が失敗")

    def notify_daily_summary(self, all_alerts: list[TreasureAlert]) -> NotificationResult:
        """日次サマリーを送信する（全お宝商品の一覧）。"""
        if not self.is_configured:
            return NotificationResult(success=False, method="none", error="LINE通知未設定")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        top_items = sorted(all_alerts, key=lambda a: a.profit, reverse=True)[:10]
        total_profit = sum(a.profit for a in all_alerts)

        summary_text = self._build_summary_text(all_alerts, top_items, total_profit, now)

        # Messaging API で Flex メッセージを形成できる場合はそちらを優先
        if self._messaging.is_configured:
            result = self._messaging.send_text(summary_text)
            if result.success:
                return result
            logger.warning("Messaging API サマリー送信失敗。LINE Notify にフォールバック")

        if self._notify.is_configured:
            return self._notify.send(summary_text)

        return NotificationResult(success=False, method="none", error="全送信方式が失敗")

    @staticmethod
    def _build_summary_text(
        all_alerts: list[TreasureAlert],
        top_items: list[TreasureAlert],
        total_profit: float,
        now: str,
    ) -> str:
        lines = [
            f"📊 BUYMA お宝サマリー — {now}",
            f"対象商品数: {len(all_alerts)} 件 / 合計利益: ¥{total_profit:,.0f}",
            "─" * 30,
        ]
        for i, a in enumerate(top_items, 1):
            lines.append(
                f"{i}. {a.brand} {a.product_name[:20]}"
                f"  利益: {a.profit_jpy_str}（{a.profit_rate_str}）"
            )
        return "\n".join(lines)

    def filter_treasures(self, records_with_profit: list[dict]) -> list[TreasureAlert]:
        """利益しきい値以上の商品をフィルタリングして TreasureAlert リストに変換する。

        Args:
            records_with_profit: {product_name, brand, buyma_price, profit,
                                   profit_rate, source_url, stock_status,
                                   grade (optional)} の辞書リスト。
        """
        alerts = []
        for r in records_with_profit:
            profit = float(r.get("profit", 0))
            if profit >= self._threshold and r.get("stock_status") != "out_of_stock":
                alerts.append(TreasureAlert(
                    product_name=r.get("product_name", ""),
                    brand=r.get("brand", ""),
                    buyma_price=float(r.get("buyma_price", 0)),
                    profit=profit,
                    profit_rate=float(r.get("profit_rate", 0)),
                    source_url=r.get("source_url", ""),
                    stock_status=r.get("stock_status", "unknown"),
                    image_url=r.get("image_url"),
                    grade=r.get("grade"),
                ))
        return sorted(alerts, key=lambda a: a.profit, reverse=True)

    @staticmethod
    def _build_notify_text(alerts: list[TreasureAlert]) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"\n🎯 お宝発見！ {now}"]
        for a in alerts[:5]:
            grade_tag = f"[{a.grade}] " if a.grade else ""
            lines += [
                "",
                "━━━━━━━━━━━━━━",
                f"🏷️  {grade_tag}{a.brand}",
                f"📦 {a.product_name}",
                f"💴 利益: {a.profit_jpy_str}（{a.profit_rate_str}）",
                f"💰 BUYMA価格: ¥{a.buyma_price:,.0f}",
                f"📊 在庫: {a.stock_status}",
                f"🔗 {a.source_url[:60]}",
            ]
        if len(alerts) > 5:
            lines.append(f"\n... 他 {len(alerts) - 5} 件のお宝があります")
        return "\n".join(lines)
