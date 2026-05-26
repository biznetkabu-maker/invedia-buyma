"""価格文字列のパースユーティリティ。"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 長いプレフィックスを先に照合するため降順に並べる
_CURRENCY_MAP: list[tuple[str, str]] = sorted(
    [
        ("CA$", "CAD"),
        ("AU$", "AUD"),
        ("HK$", "HKD"),
        ("NZ$", "NZD"),
        ("SGD", "SGD"),
        ("CHF", "CHF"),
        ("CNY", "CNY"),
        ("KRW", "KRW"),
        ("USD", "USD"),
        ("EUR", "EUR"),
        ("GBP", "GBP"),
        ("JPY", "JPY"),
        ("CAD", "CAD"),
        ("AUD", "AUD"),
        ("€", "EUR"),
        ("£", "GBP"),
        ("¥", "JPY"),
        ("$", "USD"),
    ],
    key=lambda x: -len(x[0]),
)


def parse_price_string(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """価格文字列から数値と通貨コードを抽出する。

    Examples:
        >>> parse_price_string("$1,550")
        (1550.0, 'USD')
        >>> parse_price_string("CA$1,550.00")
        (1550.0, 'CAD')
        >>> parse_price_string("€ 2.450,00")
        (2450.0, 'EUR')
        >>> parse_price_string("1,550 USD")
        (1550.0, 'USD')
        >>> parse_price_string("")
        (None, None)
    """
    if not raw:
        return None, None

    text = raw.strip()
    text = re.sub(r"^none\s*", "", text, flags=re.I)
    currency: Optional[str] = None

    # 先頭の通貨記号を除去
    for symbol, code in _CURRENCY_MAP:
        if text.upper().startswith(symbol.upper()):
            currency = code
            text = text[len(symbol):].strip()
            break

    # 末尾の通貨コードを除去（先頭で見つからなかった場合）
    if currency is None:
        for symbol, code in _CURRENCY_MAP:
            if len(symbol) >= 2 and text.upper().endswith(symbol.upper()):
                currency = code
                text = text[: -len(symbol)].strip()
                break

    # 数字・カンマ・ピリオド以外を除去
    numeric_str = re.sub(r"[^\d.,]", "", text)
    if not numeric_str:
        return None, currency

    # 小数点の形式を判定して正規化
    # 両方存在する → 後ろが小数点
    if "," in numeric_str and "." in numeric_str:
        if numeric_str.rindex(".") > numeric_str.rindex(","):
            # 形式: 1,234.56
            numeric_str = numeric_str.replace(",", "")
        else:
            # 形式: 1.234,56
            numeric_str = numeric_str.replace(".", "").replace(",", ".")
    elif "," in numeric_str:
        parts = numeric_str.split(",")
        # 末尾が2桁 → 小数 (1,55) / それ以外 → 千の区切り (1,550)
        if len(parts) == 2 and len(parts[-1]) <= 2:
            numeric_str = numeric_str.replace(",", ".")
        else:
            numeric_str = numeric_str.replace(",", "")

    try:
        return float(numeric_str), currency
    except ValueError:
        return None, currency
