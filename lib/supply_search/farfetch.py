"""
FARFETCH 検索ページの F12 相当解析（Step3 URL 探索）。

FARFETCH は検索結果を次の形式で返す（2026-05 時点）:
1. HTML 内 JSON-LD ItemList（主ソース）
2. HTML 内 Apollo GraphQL キャッシュ（ProductCatalogItem）
3. 追加 XHR（ページネーション等 — 環境により 0 件のこともある）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote_plus

from lib.supply_search.json_walk import (
    SearchHit,
    collect_hits_from_json_text,
    normalize_style_token,
)
from lib.supply_search_utils import (
    infer_supply_category_hints,
    infer_supply_department,
    is_footwear_product_name,
    is_valid_farfetch_product_url,
    line_name_search_tokens,
)

logger = logging.getLogger(__name__)

_BASE = "https://www.farfetch.com"
_SEARCH_PATH_WOMEN = "/jp/shopping/women/search/items.aspx"
_SEARCH_PATH_MEN = "/jp/shopping/men/search/items.aspx"
_XHR_URL_HINTS = (
    "/api/",
    "graphql",
    "experience",
    "catalog",
    "listing",
    "search",
    "productcatalog",
)

_ITEMLIST_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)
_APOLLO_PATH_RE = re.compile(
    r'\\"path\\":\\"(/shopping/[^\\"]+-item-\d+\.aspx)\\"',
    re.I,
)
_APOLLO_DESC_RE = re.compile(
    r'\\"shortDescription\\":\\"([^\\"]*)\\"',
    re.I,
)
_PREOWNED_PATH = re.compile(r"pre-owned|preowned", re.I)


@dataclass
class FarfetchCatalogItem:
    name: str
    path: str
    source: str

    @property
    def url(self) -> str:
        path = self.path if self.path.startswith("/") else f"/{self.path.lstrip('/')}"
        if path.startswith("/jp/"):
            return f"{_BASE}{path.split('?')[0]}"
        return f"{_BASE}/jp{path.split('?')[0]}"


def build_farfetch_search_url(query: str, *, department: str = "women") -> str:
    q = quote_plus((query or "").strip())
    path = _SEARCH_PATH_MEN if (department or "").lower().startswith("men") else _SEARCH_PATH_WOMEN
    return f"{_BASE}{path}?q={q}"


def _parse_json_ld_itemlist(html: str) -> list[FarfetchCatalogItem]:
    out: list[FarfetchCatalogItem] = []
    seen: set[str] = set()
    for m in _ITEMLIST_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        for el in data.get("itemListElement") or []:
            if not isinstance(el, dict):
                continue
            prod = el
            if prod.get("@type") != "Product" and isinstance(el.get("item"), dict):
                prod = el["item"]
            if prod.get("@type") != "Product":
                continue
            name = str(prod.get("name") or "").strip()
            offers = prod.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            path = str((offers or {}).get("url") or "").strip()
            if not path or "item-" not in path.lower():
                continue
            key = path.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            out.append(FarfetchCatalogItem(name=name, path=path, source="json_ld_itemlist"))
    return out


def _parse_apollo_catalog(html: str) -> list[FarfetchCatalogItem]:
    paths = _APOLLO_PATH_RE.findall(html or "")
    descs = _APOLLO_DESC_RE.findall(html or "")
    if not paths:
        return []
    if len(descs) == len(paths):
        pairs = zip(descs, paths)
    else:
        pairs = (( "", p) for p in paths)
    out: list[FarfetchCatalogItem] = []
    seen: set[str] = set()
    for desc, path in pairs:
        key = path.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(FarfetchCatalogItem(name=desc, path=path, source="apollo_catalog"))
    return out


def parse_farfetch_search_html(html: str) -> list[FarfetchCatalogItem]:
    """検索 HTML から商品候補を抽出（JSON-LD 優先、Apollo フォールバック）。"""
    items = _parse_json_ld_itemlist(html)
    if items:
        return items
    return _parse_apollo_catalog(html)


def _score_item(
    item: FarfetchCatalogItem,
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> int:
    score = 30
    blob = f"{item.name} {item.path}".lower()
    sid = (style_id or "").strip()
    if sid:
        compact = normalize_style_token(sid)
        if compact and compact in normalize_style_token(blob):
            score += 100
    pos, neg = infer_supply_category_hints(product_name)
    dept = infer_supply_department(product_name)
    if dept == "men" and "/men/" in item.path.lower():
        score += 25
    elif dept == "men" and "/women/" in item.path.lower():
        score -= 35
    for hint in pos:
        h = hint.lower().replace("-", " ")
        if h in blob or h.replace(" ", "-") in item.path.lower():
            score += 25
        if hint == "bag" and any(k in blob for k in ("バッグ", "handbag", "hand bag")):
            score += 25
    for hint in neg:
        h = hint.lower()
        if h in blob:
            score -= 50 if h == "wallet" else 40
    if brand and brand.lower().replace(" ", "") not in blob.replace("-", ""):
        if "prada" in brand.lower() and "prada" not in blob:
            score -= 30
    if _PREOWNED_PATH.search(item.path) or _PREOWNED_PATH.search(item.name):
        score -= 35
    if "eyewear" in blob and not any(
        x in (product_name or "").lower() for x in ("sunglass", "eyewear", "サングラス", "メガネ")
    ):
        score -= 30
    if is_footwear_product_name(product_name):
        if not any(
            k in blob
            for k in ("sandal", "mule", "slide", "shoe", "sneaker", "boot", "trainer", "platform")
        ):
            score -= 55
        for bad in ("wish", "re-nylon", "wallet", "pouch", "handbag", "tote"):
            if bad in blob and not any(k in blob for k in ("sandal", "mule", "slide", "shoe")):
                score -= 45
        for token in line_name_search_tokens(product_name):
            if token in blob:
                score += 35
    if not is_valid_farfetch_product_url(item.url):
        score -= 100
    if item.source == "json_ld_itemlist":
        score += 5
    return score


def rank_farfetch_catalog_items(
    items: list[FarfetchCatalogItem],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
) -> list[tuple[FarfetchCatalogItem, int]]:
    scored = [
        (item, _score_item(item, style_id=style_id, product_name=product_name, brand=brand))
        for item in items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def merge_search_hits(
    catalog: list[FarfetchCatalogItem],
    xhr_hits: list[SearchHit],
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> list[str]:
    """カタログ + XHR を統合し URL リストを返す。"""
    urls: list[str] = []
    seen: set[str] = set()

    ranked = rank_farfetch_catalog_items(
        catalog, style_id=style_id, product_name=product_name, brand=brand, limit=8,
    )
    for item, score in ranked:
        if score < 0:
            continue
        u = item.url.split("?")[0]
        if u not in seen and is_valid_farfetch_product_url(u):
            seen.add(u)
            urls.append(u)

    xhr_ranked = sorted(xhr_hits, key=lambda h: h.score, reverse=True)
    for hit in xhr_ranked:
        u = (hit.url or "").split("?")[0]
        if not u or u in seen:
            continue
        if not is_valid_farfetch_product_url(u):
            continue
        seen.add(u)
        urls.append(u)

    return urls


async def search_farfetch_product_urls(
    page,
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    wait_ms: int = 4500,
    xhr_blobs: Optional[list[str]] = None,
) -> tuple[list[str], dict[str, Any]]:
    """Playwright page で FARFETCH 検索し URL 候補を返す。"""
    search_url = build_farfetch_search_url(query)
    debug: dict[str, Any] = {
        "search_url": search_url,
        "json_ld_items": 0,
        "apollo_items": 0,
        "xhr_blobs": 0,
        "top_scores": [],
    }
    await page.goto(search_url, wait_until="commit", timeout=60_000)
    await page.wait_for_timeout(wait_ms)
    html = await page.content()

    json_ld = _parse_json_ld_itemlist(html)
    apollo = _parse_apollo_catalog(html)
    catalog = json_ld or apollo
    debug["json_ld_items"] = len(json_ld)
    debug["apollo_items"] = len(apollo)

    xhr_hits: list[SearchHit] = []
    for blob in xhr_blobs or []:
        xhr_hits.extend(collect_hits_from_json_text(blob, style_id, source="xhr"))
    debug["xhr_blobs"] = len(xhr_blobs or [])

    pname = product_name or query
    ranked = rank_farfetch_catalog_items(
        catalog, style_id=style_id, product_name=pname, brand=brand, limit=5,
    )
    debug["top_scores"] = [
        {"score": s, "name": it.name[:60], "url": it.url, "source": it.source}
        for it, s in ranked
    ]

    urls = merge_search_hits(
        catalog, xhr_hits, style_id=style_id, product_name=pname, brand=brand,
    )
    return urls, debug


@dataclass
class FarfetchSearchDiagnostics:
    query: str
    style_id: str
    playwright_ok: bool
    playwright_error: str = ""
    search_url: str = ""
    json_ld_items: int = 0
    apollo_items: int = 0
    xhr_blobs: int = 0
    candidate_count: int = 0
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    product_urls: list[str] = field(default_factory=list)


async def _lookup_playwright(
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
) -> tuple[list[str], FarfetchSearchDiagnostics]:
    from playwright.async_api import async_playwright

    from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

    diag = FarfetchSearchDiagnostics(
        query=query,
        style_id=style_id,
        playwright_ok=False,
        search_url=build_farfetch_search_url(query),
    )
    xhr_blobs: list[str] = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
            try:
                ctx = await browser.new_context(**stealth_context_options())
                page = await ctx.new_page()
                await apply_stealth_scripts(page)

                async def on_response(resp) -> None:
                    u = resp.url
                    if "farfetch" not in u.lower():
                        return
                    if not any(h in u.lower() for h in _XHR_URL_HINTS):
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct:
                            return
                    try:
                        if resp.status != 200:
                            return
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct and "graphql" not in ct:
                            return
                        text = await resp.text()
                        if len(text) < 80:
                            return
                        if style_id and style_id.upper() not in text.upper():
                            if "item-" not in text.lower() and "ProductCatalog" not in text:
                                return
                        xhr_blobs.append(text)
                    except Exception:
                        pass

                page.on("response", on_response)
                urls, dbg = await search_farfetch_product_urls(
                    page,
                    query,
                    brand=brand,
                    style_id=style_id,
                    product_name=product_name or query,
                    xhr_blobs=xhr_blobs,
                )
                diag.playwright_ok = True
                diag.json_ld_items = dbg["json_ld_items"]
                diag.apollo_items = dbg["apollo_items"]
                diag.xhr_blobs = len(xhr_blobs)
                diag.top_candidates = dbg["top_scores"]
                diag.product_urls = urls
                diag.candidate_count = len(urls)
                return urls, diag
            finally:
                await browser.close()
    except Exception as e:
        diag.playwright_error = str(e)
        logger.debug("farfetch search playwright failed: %s", e)
        return [], diag


def lookup_farfetch_search_sync(
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
) -> list[str]:
    urls, _ = asyncio.run(
        _lookup_playwright(
            query, brand=brand, style_id=style_id, product_name=product_name,
        )
    )
    return urls


def lookup_farfetch_search_diagnose(
    query: str,
    *,
    brand: str = "PRADA",
    style_id: str = "",
    product_name: str = "",
) -> tuple[list[str], FarfetchSearchDiagnostics]:
    return asyncio.run(
        _lookup_playwright(
            query, brand=brand, style_id=style_id, product_name=product_name,
        )
    )
