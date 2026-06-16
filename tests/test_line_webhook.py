"""line_webhook.py のテスト。

外部 API（LINE Messaging API）へのリクエストは全て mock で遮断。
Flask テストクライアントで Webhook エンドポイントを検証する。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from base64 import b64encode
from unittest.mock import MagicMock, patch

import pytest

# ── テスト用にモジュールレベル変数を上書きしてからインポート ──────────────
os.environ.setdefault("LINE_CHANNEL_SECRET", "test_secret_for_ci")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test_token_for_ci")

import lib.line_webhook as lw

# ── ヘルパー ──────────────────────────────────────────────────────────────


def _sign(body: bytes, secret: str = "test_secret_for_ci") -> str:
    """LINE 署名を生成する。"""
    h = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return b64encode(h).decode()


def _make_event(text: str, *, user_id: str = "U1234567890") -> dict:
    return {
        "type": "message",
        "replyToken": "dummy_reply_token",
        "source": {"userId": user_id, "type": "user"},
        "message": {"type": "text", "text": text, "id": "1"},
    }


# ============================================================================
# verify_signature テスト
# ============================================================================


class TestVerifySignature:
    def test_valid_signature(self):
        body = b'{"events":[]}'
        sig = _sign(body)
        with patch.object(lw, "_CHANNEL_SECRET", "test_secret_for_ci"):
            assert lw.verify_signature(body, sig) is True

    def test_invalid_signature(self):
        body = b'{"events":[]}'
        with patch.object(lw, "_CHANNEL_SECRET", "test_secret_for_ci"):
            assert lw.verify_signature(body, "bad_signature") is False

    def test_empty_secret(self):
        with patch.object(lw, "_CHANNEL_SECRET", ""):
            assert lw.verify_signature(b"body", "sig") is False


# ============================================================================
# reply / push テスト
# ============================================================================


class TestReplyText:
    @patch("lib.line_webhook.requests")
    def test_reply_text_success(self, mock_requests):
        mock_requests.post.return_value = MagicMock(status_code=200)
        mock_requests.post.return_value.raise_for_status = MagicMock()
        with patch.object(lw, "_ACCESS_TOKEN", "test_token"):
            result = lw.reply_text("token", "hello")
        assert result is True

    @patch("lib.line_webhook.requests")
    def test_reply_text_truncates(self, mock_requests):
        mock_requests.post.return_value = MagicMock(status_code=200)
        mock_requests.post.return_value.raise_for_status = MagicMock()
        with patch.object(lw, "_ACCESS_TOKEN", "test_token"):
            lw.reply_text("token", "x" * 10000)
        call_data = json.loads(mock_requests.post.call_args[1]["data"])
        assert len(call_data["messages"][0]["text"]) <= 5000

    def test_reply_text_no_token(self):
        with patch.object(lw, "_ACCESS_TOKEN", ""):
            result = lw.reply_text("token", "hello")
        assert result is False

    @patch("lib.line_webhook.requests")
    def test_push_text_success(self, mock_requests):
        mock_requests.post.return_value = MagicMock(status_code=200)
        mock_requests.post.return_value.raise_for_status = MagicMock()
        with patch.object(lw, "_ACCESS_TOKEN", "test_token"):
            result = lw.push_text("user_id", "hello")
        assert result is True

    def test_push_text_no_token(self):
        with patch.object(lw, "_ACCESS_TOKEN", ""):
            result = lw.push_text("user_id", "hello")
        assert result is False

    @patch("lib.line_webhook.requests")
    def test_reply_flex_success(self, mock_requests):
        mock_requests.post.return_value = MagicMock(status_code=200)
        mock_requests.post.return_value.raise_for_status = MagicMock()
        with patch.object(lw, "_ACCESS_TOKEN", "test_token"):
            result = lw.reply_flex("token", {"type": "bubble"}, "alt")
        assert result is True


# ============================================================================
# handle_message テスト
# ============================================================================


class TestHandleMessage:
    @patch("lib.line_webhook.reply_text")
    def test_help_command(self, mock_reply):
        lw.handle_message(_make_event("ヘルプ"))
        mock_reply.assert_called_once()
        args = mock_reply.call_args[0]
        assert "コマンド一覧" in args[1]

    @patch("lib.line_webhook.reply_text")
    def test_help_english(self, mock_reply):
        lw.handle_message(_make_event("help"))
        mock_reply.assert_called_once()

    @patch("lib.line_webhook.reply_text")
    def test_unknown_command(self, mock_reply):
        lw.handle_message(_make_event("こんにちは"))
        mock_reply.assert_called_once()
        assert "認識できません" in mock_reply.call_args[0][1]

    def test_non_text_message_ignored(self):
        event = {
            "type": "message",
            "replyToken": "token",
            "source": {"userId": "U1", "type": "user"},
            "message": {"type": "image", "id": "1"},
        }
        lw.handle_message(event)

    @patch("lib.line_webhook.reply_text")
    def test_scrape_denied_non_admin(self, mock_reply):
        with patch.object(lw, "_ADMIN_IDS", {"ADMIN_ONLY"}):
            lw.handle_message(_make_event("巡回", user_id="NON_ADMIN"))
        assert "管理者のみ" in mock_reply.call_args[0][1]

    @patch("lib.line_webhook.reply_text")
    @patch("subprocess.Popen")
    def test_scrape_allowed_admin(self, mock_popen, mock_reply):
        with patch.object(lw, "_ADMIN_IDS", {"ADMIN_USER"}):
            lw.handle_message(_make_event("巡回", user_id="ADMIN_USER"))
        assert "巡回を開始" in mock_reply.call_args[0][1]


# ============================================================================
# _cmd_profit テスト
# ============================================================================


class TestCmdProfit:
    @patch("lib.line_webhook.reply_text")
    def test_profit_bad_format(self, mock_reply):
        lw.handle_message(_make_event("利益 abc"))
        assert "書式" in mock_reply.call_args[0][1]

    @patch("lib.line_webhook.reply_text")
    def test_profit_insufficient_numbers(self, mock_reply):
        lw.handle_message(_make_event("利益 800"))
        assert "書式" in mock_reply.call_args[0][1]

    @patch("lib.line_webhook.reply_text")
    def test_profit_success(self, mock_reply):
        with patch("lib.profit_calculator.calculate_profit") as mock_calc:
            mock_result = MagicMock()
            mock_result.jpy_cost = 124000
            mock_result.customs_cost = 12400
            mock_result.shipping_cost = 2000
            mock_result.buyma_fee = 15015
            mock_result.profit = 41585
            mock_result.profit_rate = 0.213
            mock_calc.return_value = mock_result
            lw._cmd_profit("dummy_token", "利益 800 155 195000")
        assert "利益計算結果" in mock_reply.call_args[0][1]


# ============================================================================
# _to_float テスト
# ============================================================================


def _make_record(**kwargs):
    from lib.sheet_manager import ProductRecord
    return ProductRecord(**kwargs)


def _patch_sheet(records):
    """Config.from_env と SheetManager をモックして records を返すコンテキスト。"""
    cfg = MagicMock()
    cfg.spreadsheet_id = "sid"
    cfg.worksheet_name = "ws"
    cfg.credentials_path = "creds"
    manager = MagicMock()
    manager.get_all_records.return_value = records
    return (
        patch("lib.config.Config.from_env", return_value=cfg),
        patch("lib.sheet_manager.SheetManager", return_value=manager),
    )


class TestCmdList:
    @patch("lib.line_webhook.reply_text")
    def test_list_empty(self, mock_reply):
        p_cfg, p_mgr = _patch_sheet([])
        with p_cfg, p_mgr:
            lw._cmd_list("token")
        assert "登録されていません" in mock_reply.call_args[0][1]

    @patch("lib.line_webhook.reply_text")
    def test_list_with_records(self, mock_reply):
        recs = [
            _make_record(商品名="バッグA", ブランド="PRADA", BUYMA販売価格="50000",
                         利益額="35000", 在庫ステータス="出品中")
            for _ in range(3)
        ]
        p_cfg, p_mgr = _patch_sheet(recs)
        with p_cfg, p_mgr:
            lw._cmd_list("token")
        out = mock_reply.call_args[0][1]
        assert "登録商品" in out
        assert "バッグA" in out

    @patch("lib.line_webhook.reply_text")
    def test_list_error(self, mock_reply):
        with patch("lib.config.Config.from_env", side_effect=RuntimeError("boom")):
            lw._cmd_list("token")
        assert "エラー" in mock_reply.call_args[0][1]


class TestCmdTreasure:
    @patch("lib.line_webhook.reply_text")
    def test_treasure_none_found(self, mock_reply):
        recs = [_make_record(利益額="1000", 在庫ステータス="出品中")]
        p_cfg, p_mgr = _patch_sheet(recs)
        with p_cfg, p_mgr:
            lw._cmd_treasure("token")
        assert "ありません" in mock_reply.call_args[0][1]

    @patch("lib.line_webhook.reply_text")
    def test_treasure_found(self, mock_reply):
        recs = [
            _make_record(商品名="お宝バッグ", ブランド="GUCCI", 利益額="50000",
                         在庫ステータス="出品中", 仕入れURL="https://example.com/x"),
            _make_record(商品名="安物", 利益額="500", 在庫ステータス="出品中"),
        ]
        p_cfg, p_mgr = _patch_sheet(recs)
        with p_cfg, p_mgr:
            lw._cmd_treasure("token")
        out = mock_reply.call_args[0][1]
        assert "お宝バッグ" in out
        assert "安物" not in out


class TestCmdScrape:
    @patch("subprocess.Popen")
    @patch("lib.line_webhook.reply_text")
    def test_scrape_launches(self, mock_reply, mock_popen):
        lw._cmd_scrape("token")
        mock_popen.assert_called_once()
        assert "巡回" in mock_reply.call_args[0][1]


class TestDispatchListTreasure:
    @patch("lib.line_webhook._cmd_list")
    def test_dispatch_list(self, mock_cmd):
        lw.handle_message(_make_event("リスト"))
        mock_cmd.assert_called_once()

    @patch("lib.line_webhook._cmd_treasure")
    def test_dispatch_treasure(self, mock_cmd):
        lw.handle_message(_make_event("お宝"))
        mock_cmd.assert_called_once()


class TestToFloat:
    def test_normal_number(self):
        assert lw._to_float("12345") == 12345.0

    def test_with_commas(self):
        assert lw._to_float("12,345") == 12345.0

    def test_empty_string(self):
        assert lw._to_float("") == 0.0

    def test_none_value(self):
        assert lw._to_float(None) == 0.0

    def test_invalid_string(self):
        assert lw._to_float("abc") == 0.0


# ============================================================================
# Flask App テスト
# ============================================================================


class TestFlaskApp:
    @pytest.fixture
    def client(self):
        pytest.importorskip("flask")
        app = lw.create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_webhook_invalid_signature(self, client):
        with patch.object(lw, "_CHANNEL_SECRET", "test_secret_for_ci"):
            resp = client.post(
                "/webhook",
                data=b'{"events":[]}',
                headers={"X-Line-Signature": "invalid"},
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_webhook_valid_signature_empty_events(self, client):
        body = b'{"events":[]}'
        sig = _sign(body)
        with patch.object(lw, "_CHANNEL_SECRET", "test_secret_for_ci"):
            resp = client.post(
                "/webhook",
                data=body,
                headers={"X-Line-Signature": sig},
                content_type="application/json",
            )
        assert resp.status_code == 200

    @patch("lib.line_webhook.handle_message")
    def test_webhook_dispatches_message_event(self, mock_handle, client):
        event = _make_event("ヘルプ")
        payload = {"events": [event]}
        body = json.dumps(payload).encode()
        sig = _sign(body)
        with patch.object(lw, "_CHANNEL_SECRET", "test_secret_for_ci"):
            resp = client.post(
                "/webhook",
                data=body,
                headers={"X-Line-Signature": sig},
                content_type="application/json",
            )
        assert resp.status_code == 200
        mock_handle.assert_called_once()
