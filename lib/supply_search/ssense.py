"""
SSENSE 検索ページの F12 相当解析（Step3 URL 探索）。

SSENSE 検索 URL（2026-05）:
  https://www.ssense.com/en-us/women?q={query}
  ※ 旧 /en-us/search?q= は 404。product_finder も women パスに更新済み。

主ソース: HTML 内 JSON-LD Product（name / brand / offers.url / sku）
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
from lib.supply_search_utils import infer_supply_category_hints, normalize_brand_name

logger = logging.getLogger(__name__)

_BASE = "https://www.ssense.com"
_SEARCH_PATH = "/en-us/women"
_LOCALE = "en-us"

_XHR_URL_HINTS = (
    "/api/",
    "search",
    "catalog",
    "product",
    "listing",
    "graphql",
)

_JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)
_PRODUCT_HREF_RE = re.compile(
    r'https?://(?:www\.)?ssense\.com/(?:en-[a-z]{2}/)?(?:women|men)/product/[^"\s?#]+/\d+',
    re.I,
)
_PRODUCT_PATH_RE = re.compile(
    r'"(/(?:en-[a-z]{2}/)?(?:women|men)/product/[^"\s?#]+/\d+)"',
    re.I,
)
_NO_MATCH_RE = re.compile(
    r"there are no (?:\w+ )*products that match",
    re.I,
)
_SSENSE_PRODUCT = re.compile(
    r"/(?:en-[a-z]{2}/)?(?:women|men)/product/[^/?#]+/[^/?#]+/\d+$",
    re.I,
)


@dataclass
class SsenseCatalogItem:
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


def is_valid_ssense_product_url(url: str) -> bool:
    from urllib.parse import urlparse

    if not url or "ssense.com" not in url.lower():
        return False
    path = urlparse(url).path.rstrip("/")
    if not _SSENSE_PRODUCT.match(path):
        return False
    if re.search(r"/(?:search|cart|login|account)(?:/|$)", path, re.I):
        return False
    return True


def build_ssense_search_url(query: str, *, department: str = "women") -> str:
    q = quote_plus((query or "").strip())
    dept = "men" if department.lower().startswith("men") else "women"
    return f"{_BASE}/{_LOCALE}/{dept}?q={q}"


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


def _parse_json_ld_products(html: str) -> list[SsenseCatalogItem]:
    out: list[SsenseCatalogItem] = []
    seen: set[str] = set()
    for m in _JSON_LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            if root.get("@type") != "Product":
                continue
            name = str(root.get("name") or "").strip()
            brand_raw = root.get("brand") or {}
            if isinstance(brand_raw, dict):
                brand = str(brand_raw.get("name") or "").strip()
            else:
                brand = str(brand_raw or "").strip()
            sku = str(root.get("sku") or root.get("mpn") or "").strip()
            offers = root.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            url = str((offers or {}).get("url") or root.get("url") or "").strip()
            if not url:
                continue
            from urllib.parse import urlparse
            path = urlparse(url).path if url.startswith("http") else url
            key = path.rstrip("/")
            if key in seen:
                continue
            if not is_valid_ssense_product_url(
                url if url.startswith("http") else f"{_BASE}{path}"
            ):
                continue
            seen.add(key)
            out.append(
                SsenseCatalogItem(
                    name=name,
                    brand=brand,
                    path=path,
                    sku=sku,
                    source="json_ld_product",
                )
            )
    return out


def _parse_embedded_links(html: str) -> list[SsenseCatalogItem]:
    out: list[SsenseCatalogItem] = []
    seen: set[str] = set()
    for m in _PRODUCT_HREF_RE.finditer(html or ""):
        url = m.group(0).split("?")[0]
        if not is_valid_ssense_product_url(url):
            continue
        from urllib.parse import urlparse
        path = urlparse(url).path
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 2)[-2] if "/" in path else path
        out.append(
            SsenseCatalogItem(
                name=slug.replace("-", " ")[:120],
                brand="",
                path=path,
                sku="",
                source="html_link",
            )
        )
    return out


def parse_ssense_search_html(
    html: str,
    *,
    brand: str = "",
    require_brand_match: bool = True,
) -> list[SsenseCatalogItem]:
    """検索 HTML から商品候補を抽出。"""
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
    item: SsenseCatalogItem,
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
    category_intent = _has_category_intent(product_name)
    pos, neg = infer_supply_category_hints(product_name)
    if category_intent:
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
            if hint in ("sunglasses", "eyewear") and any(
                k in blob for k in ("sunglass", "eyewear", "サングラス", "glasses")
            ):
                score += 25
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
    if not is_valid_ssense_product_url(item.url):
        score -= 100
    if item.source == "json_ld_product":
        score += 5
    return score


def style_id_matches_loose(query: str, candidate: str) -> bool:
    q = normalize_style_token(query)
    c = normalize_style_token(candidate)
    if not q or not c:
        return False
    return q in c or c.startswith(q)


def rank_ssense_catalog_items(
    items: list[SsenseCatalogItem],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
) -> list[tuple[SsenseCatalogItem, int]]:
    scored = [
        (item, _score_item(item, style_id=style_id, product_name=product_name, brand=brand))
        for item in items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def merge_search_hits(
    catalog: list[SsenseCatalogItem],
    xhr_hits: list[SearchHit],
    *,
    style_id: str,
    product_name: str,
    brand: str,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    ranked = rank_ssense_catalog_items(
        catalog, style_id=style_id, product_name=product_name, brand=brand, limit=8,
    )
    for item, score in ranked:
        if score < 0:
            continue
        u = item.url.split("?")[0]
        if u not in seen and is_valid_ssense_product_url(u):
            seen.add(u)
            urls.append(u)

    for hit in sorted(xhr_hits, key=lambda h: h.score, reverse=True):
        u = (hit.url or "").split("?")[0]
        if not u or u in seen:
            continue
        if not u.startswith("http"):
            u = urljoin(_BASE, u)
        if not is_valid_ssense_product_url(u):
            continue
        seen.add(u)
        urls.append(u)

    return urls


async def search_ssense_product_urls(
    page,
    query: str,
    *,
    brand: str = "",
    style_id: str = "",
    product_name: str = "",
    wait_ms: int = 5000,
    xhr_blobs: Optional[list[str]] = None,
    department: str = "women",
) -> tuple[list[str], dict[str, Any]]:
    search_url = build_ssense_search_url(query, department=department)
    debug: dict[str, Any] = {
        "search_url": search_url,
        "no_results": False,
        "json_ld_items": 0,
        "html_link_items": 0,
        "xhr_blobs": 0,
        "top_scores": [],
    }
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(wait_ms)
    html = await page.content()
    debug["no_results"] = is_no_results_html(html)

    catalog = parse_ssense_search_html(html, brand=brand)
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
    ranked = rank_ssense_catalog_items(
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


@dataclass
class SsenseSearchDiagnostics:
    query: str
    style_id: str
    playwright_ok: bool
    playwright_error: str = ""
    search_url: str = ""
    no_results: bool = False
    json_ld_items: int = 0
    html_link_items: int = 0
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
    department: str = "women",
) -> tuple[list[str], SsenseSearchDiagnostics]:
    from playwright.async_api import async_playwright
    from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

    diag = SsenseSearchDiagnostics(
        query=query,
        style_id=style_id,
        playwright_ok=False,
        search_url=build_ssense_search_url(query, department=department),
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
                    if "ssense.com" not in u.lower():
                        return
                    if not any(h in u.lower() for h in _XHR_URL_HINTS):
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct:
                            return
                    try:
                        if resp.status != 200:
                            return
                        ct = resp.headers.get("content-type") or ""
                        if "json" not in ct:
                            return
                        text = await resp.text()
                        if len(text) < 80:
                            return
                        xhr_blobs.append(text)
                    except Exception:
                        pass

                page.on("response", on_response)
                urls, dbg = await search_ssense_product_urls(
                    page,
                    query,
                    brand=brand,
                    style_id=style_id,
                    product_name=product_name or query,
                    xhr_blobs=xhr_blobs,
                    department=department,
                )
                diag.playwright_ok = True
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
        logger.debug("ssense search playwright failed: %s", e)
        return [], diag


def lookup_ssense_search_diagnose(
    query: str,
    *,
    brand: str = "PRADA",
    style_id: str = "",
    product_name: str = "",
    department: str = "women",
) -> tuple[list[str], SsenseSearchDiagnostics]:
    return asyncio.run(
        _lookup_playwright(
            query,
            brand=brand,
            style_id=style_id,
            product_name=product_name,
            department=department,
        )
    )
