"""ブランド公式カタログ共通基盤。

各ブランドのサイト固有データ（URL・JSON フィールドキー・正規表現）を
`BrandCatalogData` にまとめ、解析ロジック（prada.py 等）から分離する。
新ブランドを追加する際はこのデータ構造に沿って定義する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BrandCatalogData:
    """ブランド公式サイトのカタログ定義（データのみ）。"""

    base_url: str
    locale_path: str
    xhr_url_hints: tuple[str, ...]
    sku_keys: frozenset[str]
    url_keys: frozenset[str]
    name_keys: frozenset[str]
    price_keys: frozenset[str]
    product_path: re.Pattern[str]
    mpn_in_text: re.Pattern[str]
    pdp_url: re.Pattern[str]
