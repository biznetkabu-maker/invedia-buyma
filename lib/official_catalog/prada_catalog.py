"""PRADA 公式 (prada.com) のカタログ定義（データ部）。

F12 で確認した XHR / JSON-LD / HTML から抽出するためのサイト固有データを集約。
解析ロジックは prada.py 側に置き、ここにはデータのみを置く。
docs/PRADA_OFFICIAL_F12.md と同期。
"""

from __future__ import annotations

import re

from lib.official_catalog.catalog_base import BrandCatalogData

_BASE = "https://www.prada.com"
_LOCALE_PATH = "/jp/ja"

# F12 でよく見られる API パス断片（docs/PRADA_OFFICIAL_F12.md と同期）
_XHR_URL_HINTS = (
    "/api/",
    "/yTos/api/",
    "search",
    "Search",
    "product",
    "catalog",
)

_SKU_KEYS = frozenset({
    "partnumber", "part_number", "mpn", "sku", "code", "productcode",
    "productid", "styleid", "modelcode",
})
_URL_KEYS = frozenset({"url", "producturl", "seourl", "link", "canonicalurl", "pdpurl"})
_NAME_KEYS = frozenset({"name", "productname", "title", "displayname", "shortdescription"})
_PRICE_KEYS = frozenset({"price", "saleprice", "fullprice", "formattedprice", "value"})

_PRODUCT_PATH = re.compile(
    r"/(?:jp/ja|us/en|gb/en)?/p/[^?\s\"']+\.html",
    re.I,
)
_MPN_IN_TEXT = re.compile(r"\b([A-Z]{2}\d{2}[A-Z]{2,})\b", re.I)
_PRADA_PDP_URL = re.compile(
    r"https?://(?:www\.)?prada\.com(?:/[a-z]{2}/[a-z]{2})?/p/[^\s\"'<>]+\.html",
    re.I,
)

PRADA = BrandCatalogData(
    base_url=_BASE,
    locale_path=_LOCALE_PATH,
    xhr_url_hints=_XHR_URL_HINTS,
    sku_keys=_SKU_KEYS,
    url_keys=_URL_KEYS,
    name_keys=_NAME_KEYS,
    price_keys=_PRICE_KEYS,
    product_path=_PRODUCT_PATH,
    mpn_in_text=_MPN_IN_TEXT,
    pdp_url=_PRADA_PDP_URL,
)
