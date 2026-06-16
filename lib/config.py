"""実行設定の一元管理。

環境変数から値を読み込み、未設定の場合はデフォルト値を使用する。
GitHub Actions での運用では Secrets / Variables に以下を設定する:

  必須 Secrets:
    GOOGLE_CREDENTIALS_JSON  - サービスアカウントのJSONキー（文字列）
    SPREADSHEET_ID           - スプレッドシートID

  任意 Variables (デフォルト値あり):
    WORKSHEET_NAME           - シート名 (default: 02_Purchase_Control)
    BUYMA_FEE_RATE           - BUYMA手数料率 (default: 0.077 = 7.7%、小口取引の上限値)
    CUSTOMS_RATE             - 関税率 (default: 0.10 = 10%)
    SHIPPING_COST_JPY        - 国際送料固定費 JPY (default: 2000)
    TARGET_PROFIT_RATE       - 目標利益率 (default: 0.10 = 10%)
    SCRAPER_CONCURRENCY      - 並列スクレイピング数 (default: 3)
    SCRAPER_HEADLESS         - ヘッドレスモード (default: true)
    SCRAPER_TIMEOUT_MS       - タイムアウト ms (default: 30000)

  運用モード:
    OPERATION_MODE           - 実行モード (default: monitor)
      monitor   = 価格・在庫巡回のみ（最も安全）
      research  = monitor + 候補URLの最安値比較（BestSourceFinder）
      discovery = research + BUYMAランキング収集（ToS確認必須）

  為替自動更新:
    AUTO_FOREX               - "true" で為替レートを API から自動取得 (default: true)
    FOREX_UPDATE_SHEET       - "true" でシートの為替欄も自動更新 (default: false)

  スクレイパー異常検知:
    UNKNOWN_ALERT_THRESHOLD  - 連続 unknown 回数の閾値。超えたら LINE 通知 (default: 3)

  優先度ティア（監視頻度制御）:
    PRIORITY_TIER            - "high" / "medium" / "all" (default: 自動判定)
    HIGH_PROFIT_THRESHOLD    - 高優先度の利益率しきい値 (default: 0.20 = 20%)
    MEDIUM_PROFIT_THRESHOLD  - 中優先度の利益率しきい値 (default: 0.10 = 10%)

  プロキシ設定:
    PROXY_SERVER             - プロキシURL (例: http://proxy.example.com:22225)
    PROXY_USERNAME           - プロキシユーザー名
    PROXY_PASSWORD           - プロキシパスワード
    PROXY_LIST               - カンマ区切りプロキシURLリスト
    PROXY_ROTATION           - "random" / "roundrobin" (default: random)
    BRIGHTDATA_CUSTOMER      - Bright Data 顧客ID (lum-customer-XXXXX)
    BRIGHTDATA_ZONE          - Bright Data ゾーン (default: residential)
    BRIGHTDATA_PASSWORD      - Bright Data パスワード
    BRIGHTDATA_COUNTRY       - 国コード (例: jp, us)
    SMARTPROXY_USER          - Smartproxy ユーザー名
    SMARTPROXY_PASSWORD      - Smartproxy パスワード
    SMARTPROXY_HOST          - Smartproxy ホスト (default: gate.smartproxy.com)
    SMARTPROXY_PORT          - Smartproxy ポート (default: 7000)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass
class Config:
    """実行設定を保持するデータクラス。"""

    # Google Sheets
    spreadsheet_id: str
    worksheet_name: str
    credentials_path: str

    # 利益計算パラメータ
    buyma_fee_rate: float       # BUYMA販売手数料率 (例: 0.077 = 7.7%)
    customs_rate: float         # 関税率 (例: 0.10)
    shipping_cost_jpy: float    # 国際送料固定費 (JPY)
    target_profit_rate: float   # 目標利益率 (例: 0.10 = 10%)

    # スクレイパー設定
    scraper_concurrency: int
    scraper_headless: bool
    scraper_timeout_ms: int
    scraper_max_retries: int

    # 優先度ティア設定
    priority_tier: str          # "high" / "medium" / "all" / "auto"
    high_profit_threshold: float   # 高優先度の利益率しきい値
    medium_profit_threshold: float # 中優先度の利益率しきい値

    # 一時ファイルパス（credentials.json を環境変数から生成した場合に使用）
    _tmp_credentials: str | None = field(default=None, repr=False)

    # 運用モード（デフォルト値あり — 必ず非デフォルトフィールドの後に配置）
    operation_mode: str = "monitor"       # "monitor" / "research" / "discovery"
    auto_forex: bool = False              # True で為替レートを API から自動取得
    forex_update_sheet: bool = False      # True でシートの為替欄も自動更新
    unknown_alert_threshold: int = 3      # 連続 unknown の閾値（LINE アラート）

    @staticmethod
    def _bootstrap_env() -> None:
        """`.env` とローカル設定ファイルを環境変数へ読み込む。"""
        try:
            from dotenv import load_dotenv

            load_dotenv(_PROJECT_ROOT / ".env")
        except ImportError:
            pass

        sid_file = _PROJECT_ROOT / "spreadsheet_id.txt"
        if sid_file.is_file() and not os.environ.get("SPREADSHEET_ID", "").strip():
            value = sid_file.read_text(encoding="utf-8-sig").strip()
            if value:
                os.environ["SPREADSHEET_ID"] = value

        name_file = _PROJECT_ROOT / "worksheet_name.txt"
        if name_file.is_file() and not os.environ.get("WORKSHEET_NAME", "").strip():
            value = name_file.read_text(encoding="utf-8-sig").strip()
            if value:
                os.environ["WORKSHEET_NAME"] = value

    @classmethod
    def from_env(cls) -> Config:
        """環境変数から Config を生成する。

        GOOGLE_CREDENTIALS_JSON が設定されている場合は、
        その内容を一時ファイルに書き出して credentials_path に使用する。
        """
        cls._bootstrap_env()
        credentials_path, tmp_path = cls._resolve_credentials()

        return cls(
            spreadsheet_id=os.environ.get("SPREADSHEET_ID", ""),
            worksheet_name=os.environ.get("WORKSHEET_NAME", "02_Purchase_Control"),
            credentials_path=credentials_path,
            buyma_fee_rate=float(os.environ.get("BUYMA_FEE_RATE", "0.077")),
            customs_rate=float(os.environ.get("CUSTOMS_RATE", "0.10")),
            shipping_cost_jpy=float(os.environ.get("SHIPPING_COST_JPY", "2000")),
            target_profit_rate=float(os.environ.get("TARGET_PROFIT_RATE", "0.10")),
            operation_mode=os.environ.get("OPERATION_MODE", "monitor"),
            auto_forex=os.environ.get("AUTO_FOREX", "true").lower() == "true",
            forex_update_sheet=os.environ.get("FOREX_UPDATE_SHEET", "false").lower() == "true",
            unknown_alert_threshold=int(os.environ.get("UNKNOWN_ALERT_THRESHOLD", "3")),
            scraper_concurrency=int(os.environ.get("SCRAPER_CONCURRENCY", "3")),
            scraper_headless=os.environ.get("SCRAPER_HEADLESS", "true").lower() != "false",
            scraper_timeout_ms=int(os.environ.get("SCRAPER_TIMEOUT_MS", "30000")),
            scraper_max_retries=int(os.environ.get("SCRAPER_MAX_RETRIES", "2")),
            priority_tier=os.environ.get("PRIORITY_TIER", "auto"),
            high_profit_threshold=float(os.environ.get("HIGH_PROFIT_THRESHOLD", "0.20")),
            medium_profit_threshold=float(os.environ.get("MEDIUM_PROFIT_THRESHOLD", "0.10")),
            _tmp_credentials=tmp_path,
        )

    @staticmethod
    def _resolve_credentials() -> tuple[str, str | None]:
        """credentials のパスを解決する。

        Returns:
            (credentials_path, tmp_file_path_or_None)
        """
        json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        if json_str:
            # JSON文字列を一時ファイルに書き出す（GitHub Actions用）
            tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 永続化する一時ファイルのため明示クローズ
                mode="w", suffix=".json", delete=False
            )
            # 秘密鍵を含むため、所有者のみ読み書き可能に制限する。
            try:
                os.chmod(tmp.name, 0o600)
            except OSError:
                logger.debug("認証一時ファイルの権限設定に失敗: %s", tmp.name)
            json.dump(json.loads(json_str), tmp)
            tmp.flush()
            tmp.close()
            # 異常終了時にも一時ファイルを確実に削除
            def _cleanup_tmp(path: str = tmp.name) -> None:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.debug("認証一時ファイルの削除に失敗: %s", path)
            atexit.register(_cleanup_tmp)
            return tmp.name, tmp.name

        # ローカル開発用: ファイルパスを直接使用
        path = os.environ.get("CREDENTIALS_PATH", "credentials.json")
        return path, None

    def cleanup(self) -> None:
        """一時ファイルを削除する（終了時に呼ぶ）。"""
        if not self._tmp_credentials:
            return
        try:
            os.unlink(self._tmp_credentials)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("認証一時ファイルの削除に失敗: %s", self._tmp_credentials)

    def effective_priority_tier(self) -> str:
        """実行する優先度ティアを返す。

        "auto" の場合は現在の UTC 時刻から自動判定する:
          - 6の倍数時 (0, 6, 12, 18 UTC) → "all"
          - 3の倍数時 (3, 9, 15, 21 UTC) → "medium"
          - それ以外 (1, 2, 4, 5, 7, 8 ...) → "high"
        """
        if self.priority_tier != "auto":
            return self.priority_tier
        hour = datetime.now(timezone.utc).hour
        if hour % 6 == 0:
            return "all"
        if hour % 3 == 0:
            return "medium"
        return "high"

    def validate(self) -> list[str]:
        """設定値を検証し、問題点を文字列リストで返す。"""
        errors: list[str] = []
        if not self.spreadsheet_id:
            errors.append(
                "SPREADSHEET_ID が設定されていません"
                "（初回だけ設定.bat を実行するか、spreadsheet_id.txt に ID を1行で保存）"
            )
        if not os.path.exists(self.credentials_path):
            errors.append(f"認証情報ファイルが見つかりません: {self.credentials_path}")
        if not (0 < self.buyma_fee_rate < 1):
            errors.append(f"BUYMA_FEE_RATE の値が不正です: {self.buyma_fee_rate}")
        if not (0 <= self.customs_rate < 1):
            errors.append(f"CUSTOMS_RATE の値が不正です: {self.customs_rate}")
        if self.target_profit_rate <= 0:
            errors.append(f"TARGET_PROFIT_RATE の値が不正です: {self.target_profit_rate}")
        return errors
