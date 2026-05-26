"""
MYTHERESA 検索ページの F12 相当解析（Step3 URL 探索）。

MYTHERESA は Bot 検知が強く、クラウド headless では HTML が空になることがある。
ローカル Chrome + Playwright で F12 キャプチャすること（docs/MYTHERESA_SEARCH_F12.md）。

想定ソース（2026-05）:
1. JSON-LD ItemList / ListItem
2. HTML 内 product リンク（/women/...-{id}.html）
3. __NEXT_DATA__ / 埋め込み JSON
4. GraphQL XHR（/graphql 等 — F12 で確認）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin

from lib.supply_search.json_walk import (
    SearchHit,
    collect_hits_from_json_text,
    normalize_style_token,
)
from lib.supply_search_utils import infer_supply_category_hints

logger = logging.getLogger(__name__)

_BASE = "https://www.mytheresa.com"
_SEARCH_PATH = "/en-us/search/"
_LOCALE_PREFIX = "/en-us"

_XHR_URL_HINTS = (
    "/graphql",
    "/api/",
    "search",
    "catalog",
    "product",
    "listing",
)

_ITEMLIST_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)
_PRODUCT_HREF_RE = re.compile(
    r'https?://(?:www\.)?mytheresa\.com'
    r'/(?:en-[a-z]{2}/)?(?:women|men)/(?:[^"\s?#]+/)*[^"\s?#]+-[a-z0-9]+\.html',
    re.I,
)
_PRODUCT_PATH_RE = re.compile(
    r'"(/(?:en-[a-z]{2}/)?(?:women|men)/(?:[^"\s?#]+/)*[^"\s?#]+-[a-z0-9]+\.html)"',
    re.I,
)
_BOT_PAGE_RE = re.compile(r"something went wrong|report issue|reference bot:", re.I)
_PREOWNED_PATH = re.compile(r"pre-owned|preowned|archive", re.I)

_MYTHERESA_PRODUCT = re.compile(
    r"/(?:en-[a-z]{2}/)?(?:women|men)/(?:[^?#]+/)*[^/?#]+-[a-z0-9]+\.html$",
    re.I,
)


@dataclass
class MytheresaCatalogItem:
    name: str
    path: str
    source: str

    @property
    def url(self) -> str:
        path = self.path if self.path.startswith("/") else f"/{self.path.lstrip('/')}"
        if path.startswith("http"):
            return path.split("?")[0]
        return f"{_BASE}{path.split('?')[0]}"


def is_valid_mytheresa_product_url(url: str) -> bool:
    from urllib.parse import urlparse

    if not url or "mytheresa.com" not in url.lower():
        return False
    path = urlparse(url).path
    if not _MYTHERESA_PRODUCT.search(path):
        return False
    if _PREOWNED_PATH.search(path):
        return False
    if re.search(r"/(?:search|cart|login|account|wishlist)(?:/|$)", path, re.I):
        return False
    slug = path.rsplit("/", 1)[-1]
    if slug.count("-") < 1:
        return False
    return True


def build_mytheresa_search_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"{_BASE}{_SEARCH_PATH}?q={q}"


def is_bot_blocked_html(html: str) -> bool:
    return bool(_BOT_PAGE_RE.search(html or ""))


def _normalize_product_path(path_or_url: str) -> str:
    raw = (path_or_url or "").strip().split("?")[0]
    if raw.startswith("http"):
        from urllib.parse import urlparse
        return urlparse(raw).path
    return raw if raw.startswith("/") else f"/{raw}"


def _parse_json_ld_itemlist(html: str) -> list[MytheresaCatalogItem]:
    out: list[MytheresaCatalogItem] = []
    seen: set[str] = set()
    for m in _ITEMLIST_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            if root.get("@type") != "ItemList":
                continue
            for el in root.get("itemListElement") or []:
                if not isinstance(el, dict):
                    continue
                name = str(el.get("name") or "").strip()
                path = ""
                if el.get("@type") == "ListItem":
                    path = str(el.get("url") or el.get("item") or "").strip()
                    if isinstance(el.get("item"), dict):
                        item = el["item"]
                        name = name or str(item.get("name") or "").strip()
                        path = path or str(item.get("url") or "").strip()
                elif el.get("@type") == "Product":
                    name = str(el.get("name") or "").strip()
                    offers = el.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    path = str((offers or {}).get("url") or el.get("url") or "").strip()
                if not path:
                    continue
                path = _normalize_product_path(path)
                if not is_valid_mytheresa_product_url(f"{_BASE}{path}"):
                    continue
                if path in seen:
                    continue
                seen.add(path)
                out.append(
                    MytheresaCatalogItem(name=name, path=path, source="json_ld_itemlist")
                )
    return out


def _parse_embedded_links(html: str) -> list[MytheresaCatalogItem]:
    out: list[MytheresaCatalogItem] = []
    seen: set[str] = set()
    for m in _PRODUCT_HREF_RE.finditer(html or ""):
        url = m.group(0).split("?")[0]
        if not is_valid_mytheresa_product_url(url):
            continue
        path = _normalize_product_path(url)
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1].replace(".html", "").replace("-", " ")
        out.append(
            MytheresaCatalogItem(name=slug[:120], path=path, source="html_link")
        )
    for m in _PRODUCT_PATH_RE.finditer(html or ""):
        path = m.group(1).split("?")[0]
        if path in seen:
            continue
        url = f"{_BASE}{path}"
        if not is_valid_mytheresa_product_url(url):
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1].replace(".html", "").replace("-", " ")
        out.append(
            MytheresaCatalogItem(name=slug[:120], path=path, source="html_path")
        )
    return out


def _parse_next_data(html: str) -> list[MytheresaCatalogItem]:
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html or "",
        re.I | re.S,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    hits: list[SearchHit] = []
    from lib.supply_search.json_walk import walk_json_for_hits

    walk_json_for_hits(data, "", hits, base_url=_BASE)
    out: list[MytheresaCatalogItem] = []
    seen: set[str] = set()
    for h in hits:
        path = _normalize_product_path(h.url)
        if path in seen:
            continue
        url = h.url if h.url.startswith("http") else f"{_BASE}{path}"
        if not is_valid_mytheresa_product_url(url):
            continue
        seen.add(path)
        out.append(
            MytheresaCatalogItem(
                name=h.name or path.rsplit("/", 1)[-1],
                path=path,
                source="next_data",
            )
        )
    return out


def parse_mytheresa_search_html(html: str) -> list[MytheresaCatalogItem]:
    """検索 HTML から商品候補を抽出。"""
    if is_bot_blocked_html(html):
        return []
    for parser in (_parse_json_ld_itemlist, _parse_next_data, _parse_embedded_links):
        items = parser(html)
        if items:
            return items
    return []


def _score_item(
    item: MytheresaCatalogItem,
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
    for hint in pos:
        h = hint.lower().replace("-", " ")
        if h in blob or h.replace(" ", "-") in item.path.lower():
            score += 25
        if hint == "bag" and any(k in blob for k in ("バッグ", "handbag", "hand bag")):
            score += 25
        if hint == "wallet" and "wallet" in blob:
            score += 25
        if hint == "shoulder" and any(k in blob for k in ("ショルダー", "shoulder")):
            score += 20
    for hint in neg:
        if hint.lower() in blob:
            score -= 40
    if brand and brand.lower().replace(" ", "") not in blob.replace("-", ""):
        if "prada" in brand.lower() and "prada" not in blob:
            score -= 20
    if _PREOWNED_PATH.search(item.path) or _PREOWNED_PATH.search(item.name):
        score -= 35
    if not is_valid_mytheresa_product_url(item.url):
        score -= 100
    if item.source == "json_ld_itemlist":
        score += 5
    return score


def rank_mytheresa_catalog_items(
    items: list[MytheresaCatalogItem],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
) -> list[tuple[MytheresaCatalogItem, int]]:
    scored = [
        (item, _score_item(item, style_id=style_id, product_name=product_name, brand=brand))
        for item in items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def merge_search_hits(
    catalog: list[MytheresaCatalogItem],
    xhr_hits: list[SearchHit],
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    ranked = rank_mytheresa_catalog_items(
        catalog, style_id=style_id, product_name=product_name, brand=brand, limit=8,
    )
    for item, score in ranked:
        if score < 0:
            continue
        u = item.url.split("?")[0]
        if u not in seen and is_valid_mytheresa_product_url(u):
            seen.add(u)
            urls.append(u)

    for hit in sorted(xhr_hits, key=lambda h: h.score, reverse=True):
        u = (hit.url or "").split("?")[0]
        if not u or u in seen:
            continue
        if not u.startswith("http"):
            u = urljoin(_BASE, u)
        if not is_valid_mytheresa_product_url(u):
            continue
        seen.add(u)
        urls.append(u)

    return urls


async def search_mytheresa_product_urls(
    page,
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    wait_ms: int = 5000,
    xhr_blobs: Optional[list[str]] = None,
) -> tuple[list[str], dict[str, Any]]:
    search_url = build_mytheresa_search_url(query)
    debug: dict[str, Any] = {
        "search_url": search_url,
        "bot_blocked": False,
        "json_ld_items": 0,
        "html_link_items": 0,
        "next_data_items": 0,
        "xhr_blobs": 0,
        "top_scores": [],
    }
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(wait_ms)
    html = await page.content()
    debug["bot_blocked"] = is_bot_blocked_html(html)

    json_ld = _parse_json_ld_itemlist(html)
    next_data = _parse_next_data(html)
    embedded = _parse_embedded_links(html)
    catalog = json_ld or next_data or embedded
    debug["json_ld_items"] = len(json_ld)
    debug["next_data_items"] = len(next_data)
    debug["html_link_items"] = len(embedded)

    xhr_hits: list[SearchHit] = []
    for blob in xhr_blobs or []:
        xhr_hits.extend(
            collect_hits_from_json_text(
                blob, style_id, source="xhr", base_url=_BASE,
            )
        )
    for h in xhr_hits:
        if h.url and not h.url.startswith("http") and h.url.startswith("/"):
            h.url = urljoin(_BASE, h.url)
    debug["xhr_blobs"] = len(xhr_blobs or [])

    pname = product_name or query
    ranked = rank_mytheresa_catalog_items(
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
class MytheresaSearchDiagnostics:
    query: str
    style_id: str
    playwright_ok: bool
    playwright_error: str = ""
    search_url: str = ""
    bot_blocked: bool = False
    json_ld_items: int = 0
    html_link_items: int = 0
    next_data_items: int = 0
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
) -> tuple[list[str], MytheresaSearchDiagnostics]:
    from playwright.async_api import async_playwright
    from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

    diag = MytheresaSearchDiagnostics(
        query=query,
        style_id=style_id,
        playwright_ok=False,
        search_url=build_mytheresa_search_url(query),
    )
    xhr_blobs: list[str] = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
            try:
                ctx_opts = stealth_context_options()
                ctx_opts["locale"] = "en-US"
                ctx = await browser.new_context(**ctx_opts)
                page = await ctx.new_page()
                await apply_stealth_scripts(page)

                async def on_response(resp) -> None:
                    u = resp.url
                    if "mytheresa" not in u.lower():
                        return
                    if not any(h in u.lower() for h in _XHR_URL_HINTS):
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct:
                            return
                    try:
                        if resp.status != 200:
                            return
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct and "graphql" not in u.lower():
                            return
                        text = await resp.text()
                        if len(text) < 80:
                            return
                        xhr_blobs.append(text)
                    except Exception:
                        pass

                page.on("response", on_response)
                urls, dbg = await search_mytheresa_product_urls(
                    page,
                    query,
                    brand=brand,
                    style_id=style_id,
                    product_name=product_name or query,
                    xhr_blobs=xhr_blobs,
                )
                diag.playwright_ok = True
                diag.bot_blocked = dbg["bot_blocked"]
                diag.json_ld_items = dbg["json_ld_items"]
                diag.html_link_items = dbg["html_link_items"]
                diag.next_data_items = dbg["next_data_items"]
                diag.xhr_blobs = len(xhr_blobs)
                diag.top_candidates = dbg["top_scores"]
                diag.product_urls = urls
                diag.candidate_count = len(urls)
                return urls, diag
            finally:
                await browser.close()
    except Exception as e:
        diag.playwright_error = str(e)
        logger.debug("mytheresa search playwright failed: %s", e)
        return [], diag


def lookup_mytheresa_search_diagnose(
    query: str,
    *,
    brand: str = "PRADA",
    style_id: str = "",
    product_name: str = "",
) -> tuple[list[str], MytheresaSearchDiagnostics]:
    return asyncio.run(
        _lookup_playwright(
            query, brand=brand, style_id=style_id, product_name=product_name,
        )
    )
