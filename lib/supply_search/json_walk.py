"""XHR / 埋め込み JSON から SKU・URL を再帰収集（official_catalog/prada.py と同型）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_SKU_KEYS = frozenset({
    "partnumber", "part_number", "mpn", "sku", "code", "productcode",
    "productid", "styleid", "modelcode", "brandstyleid",
})
_URL_KEYS = frozenset({
    "url", "producturl", "seourl", "link", "canonicalurl", "pdpurl", "path",
})
_NAME_KEYS = frozenset({"name", "productname", "title", "displayname", "shortdescription"})


def normalize_style_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def style_id_matches(query: str, candidate: str) -> bool:
    q = normalize_style_token(query)
    c = normalize_style_token(candidate)
    if not q or not c:
        return False
    if c == q:
        return True
    return c.startswith(q) and len(q) >= 5


@dataclass
class SearchHit:
    url: str = ""
    name: str = ""
    style_id: str = ""
    source: str = ""
    score: int = 0


def _is_product_path(url_val: str) -> bool:
    u = url_val.lower().rstrip("/")
    if "item-" in u and ".aspx" in u:
        return True
    if ("/women/" in u or "/men/" in u) and u.endswith(".html"):
        return True
    if "/product/" in u and re.search(r"/\d+$", u):
        return True
    if "/shop/product/" in u and re.search(r"/\d+$", u):
        return True
    return bool(re.search(r"/(?:en-[a-z]{2}/)?[a-z0-9-]+_[a-z0-9]+$", u, re.I))


def _extract_dict_fields(obj: dict, base_url: str) -> tuple[str, str, str]:
    """dict から (sku, url, name) を抽出する。"""
    sku_val = ""
    url_val = ""
    name_val = ""
    for k, v in obj.items():
        kl = k.lower().replace("-", "").replace("_", "")
        if kl in _SKU_KEYS and isinstance(v, (str, int)):
            sku_val = str(v).strip()
        elif kl in _URL_KEYS and isinstance(v, str) and v.strip():
            raw = v.strip()
            if raw.startswith("http"):
                url_val = raw
            elif raw.startswith("/") and _is_product_path(raw):
                url_val = base_url.rstrip("/") + raw
        elif kl in _NAME_KEYS and isinstance(v, str) and len(v) > 2:
            name_val = v.strip()[:200]
    return sku_val, url_val, name_val


def _score_hit(style_id: str, sku_val: str, name_val: str, url_val: str) -> int:
    """商品ヒットのスコアを計算する。"""
    score = 40
    if style_id and style_id_matches(style_id, sku_val or name_val or url_val):
        score += 80
    if style_id and normalize_style_token(style_id) in normalize_style_token(url_val):
        score += 50
    return score


def walk_json_for_hits(
    obj: Any,
    style_id: str,
    out: list[SearchHit],
    *,
    depth: int = 0,
    base_url: str = "https://www.farfetch.com",
) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        sku_val, url_val, name_val = _extract_dict_fields(obj, base_url)
        if url_val and _is_product_path(url_val):
            out.append(
                SearchHit(
                    url=url_val.split("?")[0],
                    name=name_val,
                    style_id=sku_val,
                    source="xhr_json",
                    score=_score_hit(style_id, sku_val, name_val, url_val),
                )
            )
        for v in obj.values():
            walk_json_for_hits(v, style_id, out, depth=depth + 1, base_url=base_url)
    elif isinstance(obj, list):
        for item in obj[:120]:
            walk_json_for_hits(item, style_id, out, depth=depth + 1, base_url=base_url)


def collect_hits_from_json_text(
    text: str,
    style_id: str,
    *,
    source: str,
    base_url: str = "https://www.farfetch.com",
) -> list[SearchHit]:
    out: list[SearchHit] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return out
    walk_json_for_hits(data, style_id, out, base_url=base_url)
    for h in out:
        if not h.source:
            h.source = source
    return out
