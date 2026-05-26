"""
SheetManager: Google Sheets APIを使用したスプレッドシートの読み書きクラス

カラム構成:
  [商品名, ブランド, 型番, 仕入れURL, 現地価格, 為替, BUYMA販売価格,
   在庫ステータス, 利益額, 候補URLs, 同一性スコア, 価格根拠]
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, fields, asdict
from typing import TYPE_CHECKING, Optional

import gspread

if TYPE_CHECKING:
    from lib.sheet_analysis import SheetAnalysisReport
from gspread.exceptions import APIError, WorksheetNotFound, SpreadsheetNotFound
from oauth2client.service_account import ServiceAccountCredentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNS = [
    "商品名",
    "ブランド",
    "型番",
    "仕入れURL",
    "現地価格",
    "為替",
    "BUYMA販売価格",
    "在庫ステータス",
    "利益額",
    "候補URLs",          # カンマ区切りの複数仕入先候補URL。空の場合は仕入れURLを使用。
    "同一性スコア",      # S/A/B/C/F（product_identity.MatchScore）
    "価格根拠",          # 価格・型番照合の短い根拠ログ
]


@dataclass
class ProductRecord:
    """スプレッドシートの1行に対応するデータクラス。

    候補URLs:
        複数の仕入先URLをカンマ区切りで入力する任意フィールド。
        設定されている場合、main.py は全候補を並列スクレイプして
        「在庫あり × 最安値」の URL を仕入れURL に自動更新する。
        空の場合は既存の仕入れURL のみを使用する。
    """

    商品名: str = ""
    ブランド: str = ""
    型番: str = ""
    仕入れURL: str = ""
    現地価格: str = ""
    為替: str = ""
    BUYMA販売価格: str = ""
    在庫ステータス: str = ""
    利益額: str = ""
    候補URLs: str = ""
    同一性スコア: str = ""
    価格根拠: str = ""

    def candidate_url_list(self) -> list[str]:
        """候補URLs フィールドをパースして URL リストを返す。"""
        if not self.候補URLs.strip():
            return []
        return [u.strip() for u in self.候補URLs.split(",") if u.strip()]

    @classmethod
    def from_row(cls, row: list[str]) -> "ProductRecord":
        """シートの1行リストから ProductRecord を生成する。
        行が列数より短い場合は空文字で補完する。
        """
        padded = (list(row) + [""] * len(COLUMNS))[: len(COLUMNS)]
        return cls(**dict(zip(COLUMNS, padded)))

    def to_row(self) -> list[str]:
        """ProductRecord を列順のリストに変換する。"""
        return [str(getattr(self, col)) for col in COLUMNS]


class SheetManager:
    """Google Sheets API を通じてスプレッドシートのCRUD操作を提供するクラス。

    Args:
        spreadsheet_id: スプレッドシートのID（URLの /d/<ID>/ 部分）。
        worksheet_name: 操作対象のシート名。
        credentials_path: サービスアカウントのJSONファイルパス。
                          省略時は "credentials.json" を使用する。
    """

    HEADER_ROW = 1

    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_path: str = "credentials.json",
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self._credentials_path = credentials_path
        self._client: Optional[gspread.Client] = None
        self._worksheet: Optional[gspread.Worksheet] = None

    # ------------------------------------------------------------------
    # 認証・接続
    # ------------------------------------------------------------------

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            if not os.path.exists(self._credentials_path):
                raise FileNotFoundError(
                    f"認証情報ファイルが見つかりません: {self._credentials_path}"
                )
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self._credentials_path, SCOPES
            )
            self._client = gspread.authorize(creds)
        return self._client

    def list_worksheet_titles(self) -> list[str]:
        """スプレッドシート内のタブ名一覧を返す（接続確認・設定ミス診断用）。"""
        client = self._get_client()
        try:
            spreadsheet = client.open_by_key(self.spreadsheet_id)
        except SpreadsheetNotFound:
            raise SpreadsheetNotFound(
                f"スプレッドシートが見つかりません: {self.spreadsheet_id}"
            ) from None
        return [ws.title for ws in spreadsheet.worksheets()]

    def get_worksheet(self) -> gspread.Worksheet:
        """ワークシートオブジェクトを返す（キャッシュ済み）。"""
        if self._worksheet is None:
            client = self._get_client()
            try:
                spreadsheet = client.open_by_key(self.spreadsheet_id)
            except SpreadsheetNotFound:
                raise SpreadsheetNotFound(
                    f"スプレッドシートが見つかりません: {self.spreadsheet_id}"
                )
            try:
                self._worksheet = spreadsheet.worksheet(self.worksheet_name)
            except WorksheetNotFound:
                available = [ws.title for ws in spreadsheet.worksheets()]
                hint = ", ".join(available[:12])
                if len(available) > 12:
                    hint += f", …（他 {len(available) - 12} 件）"
                raise WorksheetNotFound(
                    f"シートが見つかりません: {self.worksheet_name}"
                    f"（設定: worksheet_name.txt または WORKSHEET_NAME）\n"
                    f"  スプレッドシートにあるタブ: {hint or '（取得できず）'}\n"
                    f"  → タブ名を1文字ずつ合わせて worksheet_name.txt を修正するか、"
                    f"初回だけ設定.bat を再実行してください。"
                ) from None
        return self._worksheet

    def ensure_header(self) -> None:
        """シートが空の場合にヘッダー行を書き込む。"""
        ws = self.get_worksheet()
        first_row = ws.row_values(self.HEADER_ROW)
        if not first_row:
            ws.append_row(COLUMNS)

    # ------------------------------------------------------------------
    # 読み取り
    # ------------------------------------------------------------------

    def get_all_records(self) -> list[ProductRecord]:
        """全レコードを取得して ProductRecord のリストで返す。

        Returns:
            ヘッダー行を除いた全データ行のリスト。
        """
        ws = self.get_worksheet()
        rows = ws.get_all_values()
        if len(rows) <= self.HEADER_ROW:
            return []
        return [ProductRecord.from_row(row) for row in rows[self.HEADER_ROW :]]

    def get_record_by_product_name(self, product_name: str) -> Optional[ProductRecord]:
        """商品名でレコードを1件取得する。

        Args:
            product_name: 検索する商品名。

        Returns:
            一致したレコード。見つからなければ None。
        """
        row_index = self._find_row_index(product_name)
        if row_index is None:
            return None
        ws = self.get_worksheet()
        row = ws.row_values(row_index)
        return ProductRecord.from_row(row)

    def get_records_by_status(self, status: str) -> list[ProductRecord]:
        """在庫ステータスでレコードを絞り込んで返す。

        Args:
            status: 検索する在庫ステータス文字列。

        Returns:
            一致したレコードのリスト。
        """
        return [r for r in self.get_all_records() if r.在庫ステータス == status]

    def search_records(
        self,
        query: str,
        *,
        field: str = "商品名",
        limit: Optional[int] = None,
    ) -> list[ProductRecord]:
        """指定列に query を含むレコードを返す（大文字小文字は区別しない）。

        Args:
            query: 部分一致する検索文字列。
            field: COLUMNS に含まれる列名。
            limit: 最大件数。None なら全件。
        """
        if field not in COLUMNS:
            raise ValueError(f"未知の列名: {field}. 利用可能: {COLUMNS}")
        q = query.strip().lower()
        if not q:
            return []
        matched: list[ProductRecord] = []
        for record in self.get_all_records():
            value = str(getattr(record, field, "")).lower()
            if q in value:
                matched.append(record)
                if limit is not None and len(matched) >= limit:
                    break
        return matched

    def analyze(
        self,
        *,
        buyma_fee_rate: float = 0.077,
        customs_rate: float = 0.10,
        shipping_cost_jpy: float = 2000.0,
        target_profit_rate: float = 0.10,
        top_n: int = 10,
    ) -> "SheetAnalysisReport":
        """全レコードを分析して SheetAnalysisReport を返す（シートは変更しない）。"""
        from lib.sheet_analysis import analyze_records

        return analyze_records(
            self.get_all_records(),
            buyma_fee_rate=buyma_fee_rate,
            customs_rate=customs_rate,
            shipping_cost_jpy=shipping_cost_jpy,
            target_profit_rate=target_profit_rate,
            top_n=top_n,
        )

    # ------------------------------------------------------------------
    # 書き込み
    # ------------------------------------------------------------------

    def append_record(self, record: ProductRecord) -> None:
        """シートの末尾に新しいレコードを追加する。

        Args:
            record: 追加する ProductRecord。
        """
        self.append_records([record])

    def append_records(self, records: list[ProductRecord], *, chunk_size: int = 100) -> None:
        """複数レコードをまとめて追加する（API 書き込み回数を抑える）。

        Google Sheets の「1分あたりの書き込み」制限対策のため、
        1行ずつ append せず append_rows で一括送信する。
        """
        if not records:
            return
        ws = self.get_worksheet()
        rows = [r.to_row() for r in records]
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            self._append_rows_with_retry(ws, chunk)

    @staticmethod
    def _append_rows_with_retry(ws: gspread.Worksheet, rows: list[list[str]]) -> None:
        """429（書き込み制限）のときは待ってから再試行する。"""
        for attempt in range(6):
            try:
                ws.append_rows(rows, value_input_option="USER_ENTERED")
                return
            except APIError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                is_quota = status == 429 or "429" in str(exc)
                if is_quota and attempt < 5:
                    wait_sec = 20 * (attempt + 1)
                    time.sleep(wait_sec)
                    continue
                raise

    def update_status(self, product_name: str, status: str) -> bool:
        """在庫ステータス列のみを更新する。

        Returns:
            更新できた場合は True、対象行が見つからなければ False。
        """
        row_index = self._find_row_index(product_name)
        if row_index is None:
            return False
        status_col = COLUMNS.index("在庫ステータス") + 1
        ws = self.get_worksheet()
        ws.update_cell(row_index, status_col, status)
        return True

    def update_record(self, product_name: str, record: ProductRecord) -> bool:
        """商品名が一致する行を新しいレコードで上書きする。

        Args:
            product_name: 更新対象を特定するための商品名。
            record: 新しい値を持つ ProductRecord。

        Returns:
            更新できた場合は True、対象行が見つからなければ False。
        """
        row_index = self._find_row_index(product_name)
        if row_index is None:
            return False
        ws = self.get_worksheet()
        col_count = len(COLUMNS)
        range_notation = f"A{row_index}:{self._col_letter(col_count)}{row_index}"
        ws.update(range_notation, [record.to_row()], value_input_option="USER_ENTERED")
        return True

    def upsert_record(self, record: ProductRecord) -> str:
        """商品名が存在すれば更新、存在しなければ追加する。

        Returns:
            "updated" または "appended"。
        """
        if self._find_row_index(record.商品名) is not None:
            self.update_record(record.商品名, record)
            return "updated"
        self.append_record(record)
        return "appended"

    def delete_record(self, product_name: str) -> bool:
        """商品名が一致する行を削除する。

        Args:
            product_name: 削除対象の商品名。

        Returns:
            削除できた場合は True、見つからなければ False。
        """
        row_index = self._find_row_index(product_name)
        if row_index is None:
            return False
        ws = self.get_worksheet()
        ws.delete_rows(row_index)
        return True

    # ------------------------------------------------------------------
    # 利益額・価格の一括再計算
    # ------------------------------------------------------------------

    def recalculate_profit(
        self,
        exchange_rate: Optional[float] = None,
        fee_rate: float = 0.077,
        customs_rate: float = 0.10,
        shipping_cost_jpy: float = 2000.0,
    ) -> int:
        """全レコードの利益額を再計算してシートに書き戻す。

        利益額 = BUYMA販売価格
                 - 現地価格 × 為替（JPY仕入原価）
                 - JPY仕入原価 × customs_rate（関税）
                 - shipping_cost_jpy（国際送料）
                 - BUYMA販売価格 × fee_rate（BUYMA手数料）

        Args:
            exchange_rate: 上書きする為替レート。None の場合は各行の値を使用。
            fee_rate: BUYMA手数料率（デフォルト 7.7%）。
            customs_rate: 関税率（デフォルト 10%）。
            shipping_cost_jpy: 国際送料固定費 JPY（デフォルト 2000）。

        Returns:
            更新した行数。
        """
        ws = self.get_worksheet()
        rows = ws.get_all_values()
        if len(rows) <= self.HEADER_ROW:
            return 0

        updated = 0
        for i, row in enumerate(rows[self.HEADER_ROW :], start=self.HEADER_ROW + 1):
            record = ProductRecord.from_row(row)
            try:
                local_price = float(record.現地価格 or 0)
                rate = float(exchange_rate if exchange_rate is not None else record.為替 or 0)
                buyma_price = float(record.BUYMA販売価格 or 0)
            except ValueError:
                continue

            jpy_cost = local_price * rate
            customs = jpy_cost * customs_rate
            buyma_fee = buyma_price * fee_rate
            profit = buyma_price - jpy_cost - customs - shipping_cost_jpy - buyma_fee
            record.利益額 = str(round(profit, 2))

            profit_col = COLUMNS.index("利益額") + 1
            ws.update_cell(i, profit_col, record.利益額)
            updated += 1

        return updated

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    def _find_row_index(self, product_name: str) -> Optional[int]:
        """商品名列を走査して1-indexed の行番号を返す。ヘッダーは除外する。"""
        ws = self.get_worksheet()
        col_values = ws.col_values(1)
        for idx, value in enumerate(col_values[self.HEADER_ROW :], start=self.HEADER_ROW + 1):
            if value == product_name:
                return idx
        return None

    @staticmethod
    def _col_letter(n: int) -> str:
        """1-indexed の列番号をアルファベット表記に変換する（例: 1→A, 27→AA）。"""
        result = ""
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            result = chr(65 + remainder) + result
        return result
