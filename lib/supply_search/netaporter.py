"""
NET-A-PORTER 検索ページの F12 相当解析（Step3 URL 探索）。

YNAP グループ（MR PORTER / YOOX と同系列）。
クラウド headless では Akamai 403（Access Denied）になることが多い → ローカル F12 必須。

想定ソース（2026-05）:
1. JSON-LD Product / ItemList
2. HTML 内 /shop/product/.../{id} リンク
3. 検索 XHR / GraphQL（F12 で確認）
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote_plus

from lib.async_compat import run_sync
from lib.supply_search.json_walk import (
    SearchHit,
    collect_hits_from_json_text,
    normalize_style_token,
)
from lib.supply_search_utils import infer_supply_category_hints, normalize_brand_name

logger = logging.getLogger(__name__)

_BASE = "https://www.net-a-porter.com"
_SEARCH_PATH = "/en-us/search"
_LOCALE = "en-us"

_XHR_URL_HINTS = (
    "/api/",
    "graphql",
    "search",
    "catalog",
    "product",
    "listing",
    "ynap",
)

_JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)
_PRODUCT_HREF_RE = re.compile(
    r'https?://(?:www\.)?net-a-porter\.com/(?:en-[a-z]{2}/)?shop/product/[^"\s?#]+/\d+',
    re.I,
)
_PRODUCT_PATH_RE = re.compile(
    r'"(/(?:en-[a-z]{2}/)?shop/product/[^"\s?#]+/\d+)"',
    re.I,
)
_ACCESS_DENIED_RE = re.compile(
    r"access denied|don't have permission to access|errors\.edgesuite\.net",
    re.I,
)
_NO_MATCH_RE = re.compile(
    r"no results|0 products|we couldn't find|we could not find|did not match",
    re.I,
)
_NAP_PRODUCT = re.compile(
    r"/(?:en-[a-z]{2}/)?shop/product/(?:[^/?#]+/)*\d+$",
    re.I,
)
_PREOWNED_PATH = re.compile(r"pre-owned|preowned|archive", re.I)


@dataclass
class NetaporterCatalogItem:
    name: str
    brand: str
    path: str
    sku: str
    source: str

    @property
    def url(self) -> str:
        if self.path.startswith("http"):
            return self.path.split("?")[0]
        path = self.path if self.path.startswith("/") else f"/{self.path.lstrip('/')}"
        return f"{_BASE}{path.split('?')[0]}"


def is_valid_netaporter_product_url(url: str) -> bool:
    from urllib.parse import urlparse

    if not url or "net-a-porter.com" not in url.lower():
        return False
    path = urlparse(url).path.rstrip("/")
    if not _NAP_PRODUCT.match(path):
        return False
    if _PREOWNED_PATH.search(path):
        return False
    if re.search(r"/(?:search|cart|login|account|wishlist)(?:/|$)", path, re.I):
        return False
    return True


def build_netaporter_search_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"{_BASE}{_SEARCH_PATH}?q={q}"


def is_access_denied_html(html: str) -> bool:
    return bool(_ACCESS_DENIED_RE.search(html or ""))


def is_no_results_html(html: str) -> bool:
    return bool(_NO_MATCH_RE.search(html or ""))


def _brand_matches(brand: str, item_brand: str, item_name: str, path: str) -> bool:
    b = normalize_brand_name(brand).lower()
    if not b:
        return True
    blob = f"{item_brand} {item_name} {path}".lower()
    token = b.split()[0] if b else ""
    if token and token in blob:
        return True
    if "prada" in b and "prada" in blob:
        return True
    return False


def _parse_json_ld_products(html: str) -> list[NetaporterCatalogItem]:
    out: list[NetaporterCatalogItem] = []
    seen: set[str] = set()

    def _add(name: str, brand: str, url: str, sku: str, source: str) -> None:
        from urllib.parse import urlparse

        if not url:
            return
        path = urlparse(url).path if url.startswith("http") else url
        full = url if url.startswith("http") else f"{_BASE}{path}"
        if not is_valid_netaporter_product_url(full):
            return
        key = path.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        out.append(
            NetaporterCatalogItem(
                name=name,
                brand=brand,
                path=path,
                sku=sku,
                source=source,
            )
        )

    for m in _JSON_LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            if root.get("@type") == "ItemList":
                for el in root.get("itemListElement") or []:
                    if not isinstance(el, dict):
                        continue
                    item = el.get("item") if isinstance(el.get("item"), dict) else el
                    if not isinstance(item, dict):
                        continue
                    brand_raw = item.get("brand") or {}
                    brand = (
                        brand_raw.get("name", "")
                        if isinstance(brand_raw, dict)
                        else str(brand_raw)
                    )
                    offers = item.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    _add(
                        str(item.get("name") or el.get("name") or ""),
                        str(brand),
                        str((offers or {}).get("url") or item.get("url") or el.get("url") or ""),
                        str(item.get("sku") or item.get("mpn") or ""),
                        "json_ld_itemlist",
                    )
            elif root.get("@type") == "Product":
                brand_raw = root.get("brand") or {}
                brand = (
                    brand_raw.get("name", "")
                    if isinstance(brand_raw, dict)
                    else str(brand_raw)
                )
                offers = root.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                _add(
                    str(root.get("name") or ""),
                    str(brand),
                    str((offers or {}).get("url") or root.get("url") or ""),
                    str(root.get("sku") or root.get("mpn") or ""),
                    "json_ld_product",
                )
    return out


def _parse_embedded_links(html: str) -> list[NetaporterCatalogItem]:
    out: list[NetaporterCatalogItem] = []
    seen: set[str] = set()
    for m in _PRODUCT_HREF_RE.finditer(html or ""):
        url = m.group(0).split("?")[0]
        if not is_valid_netaporter_product_url(url):
            continue
        from urllib.parse import urlparse
        path = urlparse(url).path
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 2)[-2] if "/" in path else path
        out.append(
            NetaporterCatalogItem(
                name=slug.replace("-", " ")[:120],
                brand="",
                path=path,
                sku="",
                source="html_link",
            )
        )
    for m in _PRODUCT_PATH_RE.finditer(html or ""):
        path = m.group(1).split("?")[0]
        if path in seen:
            continue
        url = f"{_BASE}{path}"
        if not is_valid_netaporter_product_url(url):
            continue
        seen.add(path)
        slug = path.rsplit("/", 2)[-2] if "/" in path else path
        out.append(
            NetaporterCatalogItem(
                name=slug.replace("-", " ")[:120],
                brand="",
                path=path,
                sku="",
                source="html_path",
            )
        )
    return out


def parse_netaporter_search_html(
    html: str,
    *,
    brand: str = "",
    require_brand_match: bool = True,
) -> list[NetaporterCatalogItem]:
    if is_access_denied_html(html):
        return []
    if is_no_results_html(html):
        return []
    items = _parse_json_ld_products(html)
    if not items:
        items = _parse_embedded_links(html)
    if brand and require_brand_match:
        items = [
            it for it in items
            if _brand_matches(brand, it.brand, it.name, it.path)
        ]
    return items


def _has_category_intent(product_name: str) -> bool:
    name_l = (product_name or "").lower()
    tokens = (
        "wallet", "bag", "shoulder", "sunglass", "eyewear", "glasses",
        "boot", "sandal", "t-shirt", "shirt", "pouch",
        "財布", "バッグ", "サングラス", "メガネ", "ショルダー", "ポーチ",
    )
    return any(t in name_l for t in tokens)


def _score_item(
    item: NetaporterCatalogItem,
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> int:
    score = 30
    blob = f"{item.name} {item.brand} {item.path} {item.sku}".lower()
    sid = (style_id or "").strip()
    if sid:
        compact = normalize_style_token(sid)
        if compact and compact in normalize_style_token(blob):
            score += 100
        if item.sku and style_id_matches_loose(sid, item.sku):
            score += 90
    if _has_category_intent(product_name):
        pos, neg = infer_supply_category_hints(product_name)
        for hint in pos:
            h = hint.lower().replace("-", " ")
            if h in blob or h.replace(" ", "-") in item.path.lower():
                score += 25
            if hint == "bag" and any(k in blob for k in ("バッグ", "handbag", "hand bag", "tote")):
                score += 25
            if hint == "wallet" and "wallet" in blob:
                score += 25
            if hint == "shoulder" and any(k in blob for k in ("ショルダー", "shoulder")):
                score += 20
        for hint in neg:
            if hint.lower() in blob:
                score -= 40
        if "eyewear" in blob and not any(
            x in (product_name or "").lower()
            for x in ("sunglass", "eyewear", "サングラス", "メガネ", "glasses")
        ):
            score -= 25
    if brand and not _brand_matches(brand, item.brand, item.name, item.path):
        score -= 50
    if _PREOWNED_PATH.search(item.path):
        score -= 35
    if not is_valid_netaporter_product_url(item.url):
        score -= 100
    if item.source.startswith("json_ld"):
        score += 5
    return score


def style_id_matches_loose(query: str, candidate: str) -> bool:
    q = normalize_style_token(query)
    c = normalize_style_token(candidate)
    if not q or not c:
        return False
    return q in c or c.startswith(q)


def rank_netaporter_catalog_items(
    items: list[NetaporterCatalogItem],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
) -> list[tuple[NetaporterCatalogItem, int]]:
    scored = [
        (item, _score_item(item, style_id=style_id, product_name=product_name, brand=brand))
        for item in items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def merge_search_hits(
    catalog: list[NetaporterCatalogItem],
    xhr_hits: list[SearchHit],
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> list[str]:
    from lib.supply_search.base_search import merge_ranked_urls

    ranked = rank_netaporter_catalog_items(
        catalog, style_id=style_id, product_name=product_name, brand=brand, limit=8,
    )
    return merge_ranked_urls(
        ranked, xhr_hits, base_url=_BASE, url_validator=is_valid_netaporter_product_url,
    )


async def search_netaporter_product_urls(
    page,
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    wait_ms: int = 5000,
    xhr_blobs: Optional[list[str]] = None,
) -> tuple[list[str], dict[str, Any]]:
    search_url = build_netaporter_search_url(query)
    debug: dict[str, Any] = {
        "search_url": search_url,
        "access_denied": False,
        "no_results": False,
        "json_ld_items": 0,
        "html_link_items": 0,
        "xhr_blobs": 0,
        "top_scores": [],
    }
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(wait_ms)
    html = await page.content()
    debug["access_denied"] = is_access_denied_html(html)
    debug["no_results"] = is_no_results_html(html)

    catalog = parse_netaporter_search_html(html, brand=brand)
    json_ld = _parse_json_ld_products(html)
    embedded = _parse_embedded_links(html)
    debug["json_ld_items"] = len(json_ld)
    debug["html_link_items"] = len(embedded)

    xhr_hits: list[SearchHit] = []
    for blob in xhr_blobs or []:
        xhr_hits.extend(
            collect_hits_from_json_text(
                blob, style_id, source="xhr", base_url=_BASE,
            )
        )

    pname = product_name or query
    ranked = rank_netaporter_catalog_items(
        catalog, style_id=style_id, product_name=pname, brand=brand, limit=5,
    )
    debug["top_scores"] = [
        {
            "score": s,
            "name": it.name[:60],
            "brand": it.brand[:30],
            "sku": it.sku,
            "url": it.url,
            "source": it.source,
        }
        for it, s in ranked
    ]

    urls = merge_search_hits(
        catalog, xhr_hits, style_id=style_id, product_name=pname, brand=brand,
    )
    return urls, debug


from lib.supply_search.base_search import (
    SearchDiagnostics as NetaporterSearchDiagnostics,
)
from lib.supply_search.base_search import (
    launch_stealth_page,
    make_xhr_collector,
)


async def _lookup_playwright(
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
) -> tuple[list[str], NetaporterSearchDiagnostics]:
    from playwright.async_api import async_playwright

    diag = NetaporterSearchDiagnostics(
        query=query,
        style_id=style_id,
        playwright_ok=False,
        search_url=build_netaporter_search_url(query),
    )
    xhr_blobs: list[str] = []

    try:
        async with async_playwright() as pw:
            browser, _ctx, page = await launch_stealth_page(pw)
            try:
                page.on("response", make_xhr_collector("net-a-porter", _XHR_URL_HINTS, xhr_blobs))
                urls, dbg = await search_netaporter_product_urls(
                    page,
                    query,
                    brand=brand,
                    style_id=style_id,
                    product_name=product_name or query,
                    xhr_blobs=xhr_blobs,
                )
                diag.playwright_ok = True
                diag.access_denied = dbg["access_denied"]
                diag.no_results = dbg["no_results"]
                diag.json_ld_items = dbg["json_ld_items"]
                diag.html_link_items = dbg["html_link_items"]
                diag.xhr_blobs = len(xhr_blobs)
                diag.top_candidates = dbg["top_scores"]
                diag.product_urls = urls
                diag.candidate_count = len(urls)
                return urls, diag
            finally:
                await browser.close()
    except Exception as e:
        diag.playwright_error = str(e)
        logger.debug("netaporter search playwright failed: %s", e)
        return [], diag


def lookup_netaporter_search_diagnose(
    query: str,
    *,
    brand: str = "PRADA",
    style_id: str = "",
    product_name: str = "",
) -> tuple[list[str], NetaporterSearchDiagnostics]:
    return run_sync(
        _lookup_playwright(
            query,
            brand=brand,
            style_id=style_id,
            product_name=product_name or query,
        )
    )
