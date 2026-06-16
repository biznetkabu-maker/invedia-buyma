"""
仕入先 URL の妥当性判定・優先順位付けルール。

商品名・型番に対して候補 URL が新品仕入れ対象として妥当かを判定する。
後方互換のため ``supply_search_utils`` から re-export される。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from lib.brand_utils import url_matches_brand
from lib.style_id_utils import is_plausible_model_code
from lib.supply_search_utils import (
    infer_supply_category_hints,
    is_footwear_product_name,
    line_name_search_tokens,
)

_DISALLOWED_SUPPLY_PATH = re.compile(
    r"pre-?owned|vintage|second-hand|used-wear|outlet|archive-sale",
    re.I,
)


def url_is_retail_supply_candidate(url: str) -> bool:
    """中古・アウトレット系の商品URLを除外（新品仕入れ向け）。"""
    return not _DISALLOWED_SUPPLY_PATH.search(url or "")


_FARFETCH_ITEM_PATH = re.compile(
    r"(?:/[a-z]{2})?/shopping/(?:women|men)/(.+)-item-(\d+)\.aspx$",
    re.I,
)


def is_valid_farfetch_product_url(url: str) -> bool:
    """FARFETCH 商品 URL の形式チェック（検索結果の壊れた slug を除外）。"""
    path = urlparse(url).path
    if not path.lower().endswith(".aspx"):
        return False
    if "--" in path:
        return False
    m = _FARFETCH_ITEM_PATH.search(path)
    if not m:
        return False
    slug, item_id = m.group(1), m.group(2)
    if len(item_id) < 5:
        return False
    if any(not p for p in slug.split("-")):
        return False
    parts = [p for p in slug.split("-") if p]
    return not (len(parts) < 2 or len(slug) < 8)


def url_matches_style_hint(style_id: str, url: str) -> bool:
    """型番が分かっているとき、URL に型番らしき文字列が無い候補を除外。

    ページ内 JSON-LD のみに型番がある商品もあるため、妥当な型番のみ検査する。
    """
    sid = (style_id or "").strip()
    if not sid or not is_plausible_model_code(sid):
        return True
    compact = re.sub(r"[^a-z0-9]", "", sid.lower())
    if len(compact) < 5:
        return True
    path_compact = re.sub(r"[^a-z0-9]", "", urlparse(url).path.lower())
    return compact in path_compact


def style_id_for_matching(sheet_style_id: str, buyma_style_id: str = "") -> str:
    """型番照合・選定用。BUYMA 商品 ID（数字のみ）や空は使わない。"""
    sid = (sheet_style_id or "").strip()
    if sid and is_plausible_model_code(sid):
        return sid
    legacy = (buyma_style_id or "").strip()
    if legacy and is_plausible_model_code(legacy):
        return legacy
    return ""


def filter_scrape_candidate_urls(
    brand: str,
    urls: list[str],
    *,
    style_id: str = "",
) -> tuple[list[str], list[str]]:
    """スクレイプ前に仕入先 URL を検証し、(有効, 除外) を返す。"""
    ok: list[str] = []
    rejected: list[str] = []
    for u in urls:
        if url_is_valid_supply_candidate(brand, u, style_id=style_id):
            ok.append(u)
        else:
            rejected.append(u)
    return ok, rejected


def rank_supply_urls_for_discovery(
    urls: list[str],
    *,
    style_id: str = "",
    product_name: str = "",
) -> list[str]:
    """探索用 URL の優先順位付け（型番スラッグ一致 > カテゴリ語 > その他）。"""
    sid = (style_id or "").strip()
    category_hints, mismatch_hints = infer_supply_category_hints(product_name)

    def score(url: str) -> int:
        s = 0
        path = urlparse(url).path.lower()
        if sid and url_matches_style_hint(sid, url):
            s += 200
        for i, hint in enumerate(category_hints):
            if hint in path:
                s += 50 - i
        for bad in mismatch_hints:
            if bad in path:
                s -= 150
        if "pre-owned" in path or "vintage" in path:
            s -= 100
        return s

    return sorted(urls, key=score, reverse=True)


_GENERIC_BAG_HINTS = frozenset({"bag", "shoulder", "tote"})


def _requires_specific_path_match(product_name: str, positive: list[str]) -> bool:
    """バケット/ウィッカー等 — URL にカテゴリ語が無い候補を拒否する。"""
    name_l = (product_name or "").lower()
    if is_footwear_product_name(product_name):
        return False
    if any(
        k in name_l
        for k in (
            "バケット", "bucket", "ウィッカー", "wicker", "ラタン", "rattan",
            "ハンドバッグ", "handbag", "hand bag", "hand-bag",
            "ベルトバッグ", "ボディバッグ", "belt bag", "body bag", "bum bag",
            "フラグメント", "fragment", "カードケース", "card-case", "card-holder",
            "名刺",
        )
    ):
        return True
    return len([h for h in positive if h not in _GENERIC_BAG_HINTS]) >= 2


def url_has_line_or_style_slug_match(
    product_name: str, style_id: str, url: str,
) -> bool:
    """Step3 用 — URL スラッグが型番・ライン名・（非フットウェアは）カテゴリ語と一致。"""
    sid = (style_id or "").strip()
    if sid and url_matches_style_hint(sid, url):
        return True
    path = urlparse(url).path.lower()
    path_norm = path.replace("-", " ")

    def path_has(token: str) -> bool:
        t = token.lower().replace("-", " ")
        return t in path or t in path_norm

    for token in line_name_search_tokens(product_name):
        if token in path:
            return True
    if is_footwear_product_name(product_name):
        return False
    positive, _ = infer_supply_category_hints(product_name)
    return any(path_has(hint) for hint in positive)


def url_requires_line_or_style_slug(product_name: str, style_id: str) -> bool:
    """Step3 で汎用カテゴリ URL（別 SKU の sandal 等）を拾わない。"""
    sid = (style_id or "").strip()
    if not sid or not is_plausible_model_code(sid):
        return False
    if is_footwear_product_name(product_name):
        return True
    return _requires_specific_path_match(
        product_name, infer_supply_category_hints(product_name)[0]
    )


def url_has_category_path_mismatch(product_name: str, url: str) -> bool:
    """URL パスが商品カテゴリと明らかに矛盾するか（eyewear vs bag 等）。"""
    if not (product_name or "").strip() or not url:
        return False
    positive, negative = infer_supply_category_hints(product_name)
    path = urlparse(url).path.lower()
    path_norm = path.replace("-", " ")

    def path_has(token: str) -> bool:
        t = token.lower().replace("-", " ")
        return t in path or t in path_norm

    if _requires_specific_path_match(product_name, positive) and not any(path_has(hint) for hint in positive):
        return True

    if not negative:
        return False

    mismatches = [bad for bad in negative if path_has(bad)]
    if not mismatches:
        return False
    return not any(path_has(hint) for hint in positive)


def url_is_valid_supply_candidate(
    brand: str, url: str, *, style_id: str = "", require_style_in_url: bool = False,
    product_name: str = "",
) -> bool:
    """仕入先 URL が探索・スクレイプ候補として妥当か。

    require_style_in_url=False（既定）では型番が URL に無くても通す。
    別 SKU の除外はスクレイプ後の JSON-LD 型番照合（BestSourceFinder）に任せる。
    """
    if not url_matches_brand(brand, url):
        return False
    if not url_is_retail_supply_candidate(url):
        return False
    if product_name and url_has_category_path_mismatch(product_name, url):
        return False
    if (
        product_name
        and style_id
        and url_requires_line_or_style_slug(product_name, style_id)
        and not url_has_line_or_style_slug_match(product_name, style_id, url)
    ):
        return False
    if "farfetch.com" in (url or "").lower():
        if not is_valid_farfetch_product_url(url):
            return False
        return not (require_style_in_url and style_id and not url_matches_style_hint(style_id, url))
    return not (require_style_in_url and style_id and not url_matches_style_hint(style_id, url))
