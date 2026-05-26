"""
LINE Messaging API Webhook ハンドラー。

BUYMAバイヤーが LINE からコマンドを送信して、
リアルタイムで商品情報・利益計算・お宝検索を実行できる。

対応コマンド:
  「リスト」       — スプレッドシートの商品一覧を返信
  「お宝」         — 利益 ≥ しきい値の商品を返信
  「巡回」         — スクレイピングを実行（管理者のみ）
  「利益 <価格>円」 — 簡易利益計算
  「ヘルプ」       — コマンド一覧

セットアップ:
  1. LINE Developers Console でWebhook URLを設定
     例: https://your-server.example.com/webhook
  2. 下記の環境変数を設定（実際の値は .env に書かず GitHub Secrets で管理）:
     LINE_CHANNEL_SECRET       ← 署名検証用（必須）
     LINE_CHANNEL_ACCESS_TOKEN ← メッセージ送信用（必須）
     LINE_USER_ID              ← 管理者のユーザーID

起動方法:
  pip install flask
  python3 line_webhook.py

本番環境:
  gunicorn -w 1 line_webhook:app
  または GitHub Actions の代わりに常時起動サーバーに配置

⚠️  Channel Secret / Access Token は環境変数で管理する。
    絶対にソースコードに直接書かない。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from base64 import b64encode

logger = logging.getLogger(__name__)

# ── 環境変数から読み込む（ハードコード禁止）──────────────────────────────
_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
_ACCESS_TOKEN   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
_ADMIN_IDS      = set(filter(None, os.getenv("LINE_ADMIN_USER_IDS", "").split(",")))

# .env ファイルがある場合は python-dotenv で読み込む（オプション）
try:
    from dotenv import load_dotenv
    load_dotenv()
    _CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", _CHANNEL_SECRET)
    _ACCESS_TOKEN   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", _ACCESS_TOKEN)
    _ADMIN_IDS      = set(filter(None, os.getenv("LINE_ADMIN_USER_IDS", "").split(",")))
except ImportError:
    pass  # python-dotenv 未インストールでも動作する


import requests

_REPLY_API  = "https://api.line.me/v2/bot/message/reply"
_PUSH_API   = "https://api.line.me/v2/bot/message/push"


# ============================================================================
# 署名検証
# ============================================================================

def verify_signature(body: bytes, x_line_signature: str) -> bool:
    """LINE から送られてきたWebhookリクエストの署名を検証する。

    Channel Secret を使って HMAC-SHA256 署名を計算し、
    ヘッダーの値と比較する。

    Returns:
        正当なリクエストなら True、そうでなければ False。
    """
    if not _CHANNEL_SECRET:
        logger.error("LINE_CHANNEL_SECRET が設定されていません")
        return False

    hash_value = hmac.new(
        _CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, x_line_signature)


# ============================================================================
# メッセージ送信
# ============================================================================

def reply_text(reply_token: str, text: str) -> bool:
    """テキストメッセージを返信する。"""
    return _send_reply(reply_token, [{"type": "text", "text": text[:5000]}])


def reply_flex(reply_token: str, flex_content: dict, alt_text: str) -> bool:
    """Flex Message を返信する。"""
    return _send_reply(reply_token, [{
        "type": "flex",
        "altText": alt_text,
        "contents": flex_content,
    }])


def push_text(user_id: str, text: str) -> bool:
    """特定ユーザーへプッシュ通知する。"""
    return _send_push(user_id, [{"type": "text", "text": text[:5000]}])


def _send_reply(reply_token: str, messages: list) -> bool:
    if not _ACCESS_TOKEN:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False
    try:
        resp = requests.post(
            _REPLY_API,
            headers={
                "Authorization": f"Bearer {_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps({"replyToken": reply_token, "messages": messages},
                            ensure_ascii=False),
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("LINE reply 失敗: %s", e)
        return False


def _send_push(to: str, messages: list) -> bool:
    if not _ACCESS_TOKEN:
        return False
    try:
        resp = requests.post(
            _PUSH_API,
            headers={
                "Authorization": f"Bearer {_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps({"to": to, "messages": messages}, ensure_ascii=False),
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("LINE push 失敗: %s", e)
        return False


# ============================================================================
# コマンド処理
# ============================================================================

def handle_message(event: dict) -> None:
    """受信したメッセージイベントを処理する。"""
    reply_token = event.get("replyToken", "")
    source      = event.get("source", {})
    user_id     = source.get("userId", "")
    msg         = event.get("message", {})
    text        = msg.get("text", "").strip()

    if msg.get("type") != "text":
        return  # テキスト以外は無視

    logger.info("受信 [user=%s]: %s", user_id[:8] + "...", text[:50])

    # ── コマンド分岐 ──────────────────────────────────────────────────────
    if text in ("ヘルプ", "help", "/help"):
        reply_text(reply_token, _HELP_TEXT)

    elif text in ("リスト", "list", "/list"):
        _cmd_list(reply_token)

    elif text in ("お宝", "treasure", "/treasure"):
        _cmd_treasure(reply_token)

    elif text.startswith("利益") or text.startswith("/profit"):
        _cmd_profit(reply_token, text)

    elif text in ("巡回", "scrape", "/scrape"):
        if user_id in _ADMIN_IDS:
            _cmd_scrape(reply_token)
        else:
            reply_text(reply_token, "⛔ このコマンドは管理者のみ実行できます。")

    else:
        reply_text(reply_token, "コマンドが認識できません。「ヘルプ」と送ってください。")


_HELP_TEXT = """🤖 BUYMAアシスタント コマンド一覧

📋 リスト — 現在の商品一覧を表示
🎯 お宝   — 利益¥30,000以上の商品を表示
💰 利益 <価格>円 — 簡易利益計算
   例: 利益 800ドル 155円 195000円

🔄 巡回（管理者のみ）— 価格・在庫を最新化

ヘルプ — このメッセージを表示"""


def _cmd_list(reply_token: str) -> None:
    """商品リストを返信する。"""
    try:
        from lib.config import Config
        from lib.sheet_manager import SheetManager
        config = Config.from_env()
        manager = SheetManager(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_path=config.credentials_path,
        )
        records = manager.get_all_records()

        if not records:
            reply_text(reply_token, "📋 商品が登録されていません。")
            return

        lines = [f"📋 登録商品 {len(records)} 件\n"]
        for r in records[:10]:
            status_icon = "✅" if r.在庫ステータス == "出品中" else "⛔"
            lines.append(
                f"{status_icon} {r.商品名[:15]} ({r.ブランド})\n"
                f"   ¥{r.BUYMA販売価格} | 利益: ¥{r.利益額}"
            )
        if len(records) > 10:
            lines.append(f"\n...他 {len(records) - 10} 件")

        reply_text(reply_token, "\n".join(lines))

    except Exception as e:
        logger.error("リストコマンドエラー: %s", e)
        reply_text(reply_token, f"❌ エラー: {str(e)[:100]}")


def _cmd_treasure(reply_token: str) -> None:
    """お宝商品を返信する。"""
    try:
        from lib.config import Config
        from lib.sheet_manager import SheetManager
        config = Config.from_env()
        threshold = float(os.getenv("LINE_PROFIT_THRESHOLD", "30000"))
        manager = SheetManager(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_path=config.credentials_path,
        )
        records = manager.get_all_records()
        treasures = [
            r for r in records
            if _to_float(r.利益額) >= threshold
            and r.在庫ステータス not in ("停止中", "out_of_stock")
        ]

        if not treasures:
            reply_text(reply_token, f"🔍 利益¥{threshold:,.0f}以上のお宝は現在ありません。")
            return

        lines = [f"🎯 お宝商品 {len(treasures)} 件（利益¥{threshold:,.0f}以上）\n"]
        for r in sorted(treasures, key=lambda x: _to_float(x.利益額), reverse=True)[:5]:
            lines.append(
                f"✨ {r.商品名[:15]} ({r.ブランド})\n"
                f"   利益: ¥{_to_float(r.利益額):,.0f} | {r.在庫ステータス}\n"
                f"   {r.仕入れURL[:40]}..."
            )

        reply_text(reply_token, "\n".join(lines))

    except Exception as e:
        logger.error("お宝コマンドエラー: %s", e)
        reply_text(reply_token, f"❌ エラー: {str(e)[:100]}")


def _cmd_profit(reply_token: str, text: str) -> None:
    """簡易利益計算を返信する。
    書式: 「利益 800ドル 155円 195000円」
    """
    import re
    nums = re.findall(r"[\d,\.]+", text.replace(",", ""))
    floats = [float(n) for n in nums if n]

    if len(floats) < 3:
        reply_text(
            reply_token,
            "書式: 利益 <現地価格> <為替レート> <BUYMA価格>\n"
            "例: 利益 800 155 195000"
        )
        return

    source_price, exchange, buyma_price = floats[0], floats[1], floats[2]
    try:
        from lib.profit_calculator import calculate_profit
        result = calculate_profit(
            local_price=source_price,
            exchange_rate=exchange,
            buyma_price=buyma_price,
        )
        msg = (
            f"💰 利益計算結果\n\n"
            f"現地価格: {source_price:,.0f}\n"
            f"為替レート: {exchange}\n"
            f"BUYMA販売価格: ¥{buyma_price:,.0f}\n"
            f"─────────────\n"
            f"仕入原価: ¥{result.jpy_cost:,.0f}\n"
            f"関税:     ¥{result.customs_cost:,.0f}\n"
            f"送料:     ¥{result.shipping_cost:,.0f}\n"
            f"手数料:   ¥{result.buyma_fee:,.0f}\n"
            f"─────────────\n"
            f"利益: ¥{result.profit:,.0f}\n"
            f"利益率: {result.profit_rate:.1%}\n"
            f"{'✅ 目標達成' if result.profit_rate >= 0.15 else '⚠️ 目標未達（15%以下）'}"
        )
        reply_text(reply_token, msg)
    except Exception as e:
        reply_text(reply_token, f"計算エラー: {e}")


def _cmd_scrape(reply_token: str) -> None:
    """スクレイピングを非同期でキックする（管理者専用）。"""
    reply_text(reply_token, "🔄 巡回を開始します。完了後に結果を通知します。")
    # 実際の実行はバックグラウンドタスクとして起動
    try:
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "main.py"], close_fds=True)
    except Exception as e:
        logger.error("巡回起動失敗: %s", e)


def _to_float(v: str) -> float:
    try:
        return float(str(v).replace(",", "") or 0)
    except (ValueError, TypeError):
        return 0.0


# ============================================================================
# Flask Webhook エンドポイント
# ============================================================================

def create_app():
    """Flask アプリを生成する。"""
    try:
        from flask import Flask, abort, request
    except ImportError:
        raise ImportError("Flask が未インストールです: pip install flask")

    app = Flask(__name__)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        signature = request.headers.get("X-Line-Signature", "")
        body = request.get_data()

        if not verify_signature(body, signature):
            logger.warning("署名検証失敗 — 不正なリクエストの可能性")
            abort(400)

        payload = request.get_json(force=True)

        for event in payload.get("events", []):
            if event.get("type") == "message":
                handle_message(event)

        return "OK", 200

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok", "line_configured": bool(_CHANNEL_SECRET and _ACCESS_TOKEN)}, 200

    return app


# ============================================================================
# 直接実行
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if not _CHANNEL_SECRET or not _ACCESS_TOKEN:
        print(
            "⚠️  LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN が未設定です。\n"
            "   .env ファイルを作成するか、環境変数を設定してください。\n"
            "   .env.example を参考にしてください。"
        )
    else:
        print("✅ LINE認証情報: 設定済み（環境変数から読み込み）")

    app = create_app()
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Webhook サーバー起動: http://localhost:{port}/webhook")
    app.run(host="0.0.0.0", port=port, debug=False)
