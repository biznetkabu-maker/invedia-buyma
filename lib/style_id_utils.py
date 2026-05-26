"""
型番 / Style ID / SKU などの表記ゆれを吸収して比較するユーティリティ。

BUYMA 詳細HTMLから抜いた文字列と、仕入先 JSON-LD の sku 等を突き合わせるときに使う。
"""

from __future__ import annotations

import re
from typing import Optional

# 正規化後に空になる文字だけのコードは無視
_MIN_NORMALIZED_LEN = 3


def normalize_style_id(value: Optional[str]) -> str:
    """比較用に Style ID 文字列を正規化する。

    - 前後空白除去
    - 大文字化
    - 連続空白・一般的な区切り（-/. 空白）を単一ハイフンに潰す
    """
    if not value:
        return ""
    s = value.strip().upper()
    s = re.sub(r"[\s/]+", "-", s)
    s = s.replace(".", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def style_ids_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    """2つの Style ID が同一商品を指す可能性が高いか（緩い一致）。"""
    na, nb = normalize_style_id(a), normalize_style_id(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 片方がもう一方のサフィックス（サイトによりプレフィックスが抜ける場合）
    if len(na) >= _MIN_NORMALIZED_LEN and len(nb) >= _MIN_NORMALIZED_LEN:
        if na.endswith(nb) or nb.endswith(na):
            return True
    return False


def scraped_matches_buyma_style(
    scraped_style_id: Optional[str],
    buyma_style_id: Optional[str],
) -> bool:
    """供給側スクレイプ結果の style_id と BUYMA 側の型番が一致するか。

    両方 None のときは「検証なし」として True（呼び出し側で要件を決める）。
    """
    if not buyma_style_id and not scraped_style_id:
        return True
    if not buyma_style_id or not scraped_style_id:
        return False
    return style_ids_equivalent(buyma_style_id, scraped_style_id)
