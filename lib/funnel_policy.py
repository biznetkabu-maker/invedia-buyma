"""
漏斗（ファネル）運用方針 — コードとドキュメントの単一ソース。

方針A（デフォルト）:
  - 週次 auto-sheet は上限件数まで（型番あり候補を優先）
  - 自動で通らない行は削除せず 自動見送り_* にする
  - 人は「候補URLs を貼って再実行」で救済（層3以降）
  - 香水・Re-Nylon ポーチのみ探索前に対象外
"""

from __future__ import annotations

import os
import re

POLICY_ID = "A"
POLICY_LABEL = "半自動（失敗は候補URLsで救済）"

# 環境変数（FUNNEL_OPS / .env.example と同期）
ENV_WEEKLY_LIMIT = "INTAKE_WEEKLY_LIMIT"
ENV_FUNNEL = "INTAKE_FUNNEL"
ENV_REQUIRE_STYLE = "INTAKE_REQUIRE_STYLE"
ENV_OFFICIAL_PRADA = "INTAKE_OFFICIAL_PRADA"

DEFAULT_WEEKLY_LIMIT = 40

# 在庫ステータス
STATUS_BUYMA_CANDIDATE = "BUYMA候補"
STATUS_AUTO_SKIP_PREFIX = "自動見送り"
SKIP_OUT_OF_SCOPE = f"{STATUS_AUTO_SKIP_PREFIX}_対象外"
SKIP_NO_STYLE = f"{STATUS_AUTO_SKIP_PREFIX}_型番なし"
SKIP_BUYMA_FETCH = f"{STATUS_AUTO_SKIP_PREFIX}_BUYMA取得失敗"
SKIP_NO_SELL_PRICE = f"{STATUS_AUTO_SKIP_PREFIX}_売価不明"
SKIP_NO_SUPPLY = f"{STATUS_AUTO_SKIP_PREFIX}_仕入先なし"
SKIP_NO_PRICE = f"{STATUS_AUTO_SKIP_PREFIX}_価格不明"
SKIP_LOW_GRADE = f"{STATUS_AUTO_SKIP_PREFIX}_利益不足"

_RE_NYLON_POUCH = re.compile(
    r"re[-\s]?nylon.*(?:ポーチ|pouch)|(?:ポーチ|pouch).*re[-\s]?nylon",
    re.I,
)
# 探索しても意味が薄いカテゴリ（方針Aでも自動探索しない）
_HARD_EXCLUDE_AUTO = re.compile(
    r"オード|パルファム|香水|フレグランス|perfume|fragrance|"
    r"コスメ|化粧|ネイル|リップ|ファンデ|"
    r"(?:\d+\s*ml|\d+ml)(?:\s|$|　)",
    re.I,
)

_NUMERIC_BUYMA_ID = re.compile(r"^\d{7,}$")


def weekly_auto_limit() -> int:
    try:
        return max(1, int(os.environ.get(ENV_WEEKLY_LIMIT, str(DEFAULT_WEEKLY_LIMIT))))
    except ValueError:
        return DEFAULT_WEEKLY_LIMIT


def funnel_enabled() -> bool:
    return os.environ.get(ENV_FUNNEL, "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def require_style_id() -> bool:
    return os.environ.get(ENV_REQUIRE_STYLE, "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def official_prada_enabled() -> bool:
    return os.environ.get(ENV_OFFICIAL_PRADA, "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def is_hard_excluded_product_name(name: str) -> bool:
    """香水・コスメ・Re-Nylon ポーチ等（候補URLs があっても自動探索しない）。"""
    text = name or ""
    if _HARD_EXCLUDE_AUTO.search(text):
        return True
    if _RE_NYLON_POUCH.search(text):
        return True
    return False


def is_eyewear_product_name(name: str) -> bool:
    """サングラス・眼鏡（方針A: 自動探索は試す。失敗時は候補URLs）。"""
    return bool(
        re.search(r"サングラス|メガネ|眼鏡|eyewear|sunglasses?", name or "", re.I)
    )


def rescue_hint() -> str:
    return (
        "シートの「候補URLs」に仕入先の新品 URL を貼り、"
        "py intake.py --auto-sheet --limit 1 で再実行"
    )
