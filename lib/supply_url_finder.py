"""
仕入先サイトの検索結果ページから商品ページ URL を自動収集する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse

from lib.product_finder import ALL_SITES, SiteDefinition
from lib.supply_search_utils import (
    build_supply_search_queries,
    clean_product_name_for_search,
    is_valid_farfetch_product_url,
    normalize_brand_name,
    rank_supply_urls_for_discovery,
    sheet_style_id_value,
    url_is_valid_supply_candidate,
    url_matches_brand,
    url_matches_style_hint,
)

logger = logging.getLogger(__name__)

_AUTO_SITES = frozenset({
    "SSENSE", "MYTHERESA", "FARFETCH", "NET-A-PORTER", "24S（LVMHグループ）",
})

_PRODUCT_PATH_RES: dict[str, re.Pattern[str]] = {
    "ssense.com": re.compile(r"/(?:en-[a-z]{2}/)?(?:women|men)/product/", re.I),
    "mytheresa.com": re.compile(
        r"/(?:en-[a-z]{2}/)?(?:women|men)/[^/]+-\d+\.html$", re.I
    ),
    "farfetch.com": re.compile(
        r"(?:/[a-z]{2})?/shopping/(?:women|men)/"
        r"(?:[a-z0-9]+-){2,}[a-z0-9]*-item-\d+\.aspx$",
        re.I,
    ),
    "net-a-porter.com": re.compile(r"/shop/product/", re.I),
    "24s.com": re.compile(r"/(?:en-[a-z]{2}/)?[^/]+-[^/]+$", re.I),
}

_EXCLUDE_PATH = re.compile(
    r"/(?:search|cart|login|account|wishlist|help|privacy|terms)(?:/|$|\?)",
    re.I,
)

_COLLECT_LINKS_JS = """() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    let h = a.href;
    if (!h || seen.has(h)) continue;
    seen.add(h);
    out.push(h);
  }
  return out;
}"""


@dataclass
class SupplyUrlCandidate:
    site_name: str
    domain: str
    search_url: str
    product_url: str


def _domain(netloc: str) -> str:
    return netloc.lower().removeprefix("www.")


def _is_product_url(url: str, domain_key: str) -> bool:
    if _EXCLUDE_PATH.search(url):
        return False
    if "--" in urlparse(url).path:
        return False
    path = urlparse(url).path.lower()
    if "/search" in path or "items.aspx" in path:
        return False
    pat = _PRODUCT_PATH_RES.get(domain_key)
    if pat:
        if not pat.search(url):
            return False
        if domain_key == "farfetch.com":
            return is_valid_farfetch_product_url(url)
        return True
    return "/product" in path or "/shop/product" in path


def filter_product_urls(
    links: list[str],
    domain_key: str,
    limit: int = 3,
    *,
    brand: str = "",
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    brand_hits: list[str] = []
    for link in links:
        if domain_key not in _domain(urlparse(link).netloc):
            continue
        if not _is_product_url(link, domain_key):
            continue
        key = link.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        if brand and url_matches_brand(brand, link):
            brand_hits.append(link)
        else:
            out.append(link)
    merged = brand_hits + out
    return merged[:limit]


def _auto_site_defs() -> list[SiteDefinition]:
    return [s for s in ALL_SITES if s.name in _AUTO_SITES]


def build_style_search_urls(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
    *,
    search_query: Optional[str] = None,
) -> list[tuple[SiteDefinition, str]]:
    """検索クエリから各サイトの検索 URL を生成する。"""
    q = (search_query or "").strip()
    if not q:
        q = (style_id or "").strip() or f"{brand} {product_name}".strip()
    encoded = quote_plus(q)
    sites = _auto_site_defs()
    return [(site, site.search_url_template.replace("{q}", encoded)) for site in sites]


def _default_timeout_ms() -> int:
    try:
        return int(os.environ.get("SUPPLY_SEARCH_TIMEOUT_MS", "45000"))
    except ValueError:
        return 45000


async def _search_sites_for_query(
    page,
    search_query: str,
    *,
    brand: str,
    style_id_hint: str = "",
    rank_product_name: str = "",
    max_sites: int,
    timeout_ms: int,
    page_wait_ms: int,
    log_lines: list[str],
) -> list[SupplyUrlCandidate]:
    found: list[SupplyUrlCandidate] = []
    targets = build_style_search_urls("", "", search_query=search_query)[:max_sites]
    rank_name = (rank_product_name or search_query).strip()

    for site, search_url in targets:
        domain_key = site.domain
        wait_until = "commit" if domain_key == "farfetch.com" else "domcontentloaded"
        wait_ms = page_wait_ms + (1500 if domain_key == "farfetch.com" else 0)
        for attempt in range(2):
            try:
                await page.goto(
                    search_url,
                    wait_until=wait_until,
                    timeout=timeout_ms,
                )
                await page.wait_for_timeout(wait_ms)
                links = await page.evaluate(_COLLECT_LINKS_JS)
                product_urls = filter_product_urls(
                    list(links or []), domain_key, limit=3, brand=brand,
                )
                raw_hits = product_urls
                ranked = rank_supply_urls_for_discovery(
                    raw_hits,
                    style_id=style_id_hint,
                    product_name=rank_name,
                )
                product_urls = [
                    u for u in ranked
                    if url_is_valid_supply_candidate(
                        brand,
                        u,
                        style_id=style_id_hint,
                        product_name=rank_name,
                    )
                ][:1]
                if product_urls:
                    found.append(
                        SupplyUrlCandidate(
                            site_name=site.name,
                            domain=domain_key,
                            search_url=search_url,
                            product_url=product_urls[0],
                        )
                    )
                    shown = product_urls[0]
                    if len(shown) > 88:
                        shown = shown[:85] + "..."
                    hint = (
                        "型番URL一致"
                        if style_id_hint
                        and url_matches_style_hint(style_id_hint, shown)
                        else "型番はページ照合"
                    )
                    log_lines.append(f"    OK {site.name} ({hint}): {shown}")
                elif raw_hits:
                    log_lines.append(
                        f"    -- {site.name}: 候補{len(raw_hits)}件は"
                        "カテゴリ不一致・ブランド不一致・不正FARFETCH形式等で除外"
                    )
                else:
                    log_lines.append(f"    -- {site.name}: 商品URLなし（検索0件の可能性）")
                break
            except Exception as e:  # noqa: F841
                if attempt == 0:
                    log_lines.append(f"    .. {site.name}: 再試行（{type(e).__name__}）")
                    await asyncio.sleep(2)
                else:
                    log_lines.append(f"    NG {site.name}: {e}")

        await asyncio.sleep(1.0)

    return found


async def discover_supply_urls_async(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
    *,
    raw_product_name: Optional[str] = None,
    official_english_name: str = "",
    headless: bool = True,
    max_sites: int = 5,
    timeout_ms: Optional[int] = None,
    page_wait_ms: int = 3000,
    log_lines: Optional[list[str]] = None,
) -> list[SupplyUrlCandidate]:
    from playwright.async_api import async_playwright

    from lib.scraper.stealth import (
        LAUNCH_ARGS,
        apply_stealth_scripts,
        stealth_context_options,
    )

    lines: list[str] = log_lines if log_lines is not None else []
    timeout = timeout_ms if timeout_ms is not None else _default_timeout_ms()
    norm_brand = normalize_brand_name(brand)
    raw = (raw_product_name or product_name or "").strip()
    cleaned = clean_product_name_for_search(raw, norm_brand) or product_name
    style_id_hint = sheet_style_id_value(raw or product_name, style_id)
    queries = build_supply_search_queries(
        norm_brand,
        cleaned,
        style_id,
        raw_product_name=raw,
        official_english_name=official_english_name,
    )
    if not queries:
        queries = [f"{brand} {product_name}".strip()]

    all_found: list[SupplyUrlCandidate] = []
    seen_domains: set[str] = set()
    rank_context = raw or cleaned

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=LAUNCH_ARGS)
        try:
            ctx = await browser.new_context(**stealth_context_options())
            page = await ctx.new_page()
            await apply_stealth_scripts(page)
            page.set_default_timeout(timeout)

            for i, q in enumerate(queries, 1):
                lines.append(f"  検索 [{i}/{len(queries)}]: {q}")
                batch = await _search_sites_for_query(
                    page,
                    q,
                    brand=normalize_brand_name(brand),
                    style_id_hint=style_id_hint,
                    rank_product_name=rank_context,
                    max_sites=max_sites,
                    timeout_ms=timeout,
                    page_wait_ms=page_wait_ms,
                    log_lines=lines,
                )
                norm_brand = normalize_brand_name(brand)
                valid = [
                    c for c in batch
                    if url_is_valid_supply_candidate(
                        norm_brand,
                        c.product_url,
                        style_id=style_id_hint,
                        product_name=rank_context,
                    )
                ]
                if batch and not valid:
                    lines.append(
                        "    （ブランド不一致・中古pre-owned・不正FARFETCH URL等は除外）"
                    )
                for c in valid:
                    if c.domain in seen_domains:
                        continue
                    seen_domains.add(c.domain)
                    if style_id_hint and url_matches_style_hint(
                        style_id_hint, c.product_url
                    ):
                        all_found.insert(0, c)
                    else:
                        all_found.append(c)
                if style_id_hint and any(
                    url_matches_style_hint(style_id_hint, c.product_url)
                    for c in valid
                ):
                    break

        finally:
            await browser.close()

    return all_found


def _candidate_from_product_url(url: str) -> SupplyUrlCandidate:
    dom = _domain(urlparse(url).netloc)
    site_name = dom
    for s in ALL_SITES:
        if s.domain in dom:
            site_name = s.name
            break
    return SupplyUrlCandidate(
        site_name=site_name,
        domain=dom,
        search_url="",
        product_url=url,
    )


def discover_supply_urls_funnel(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
    *,
    preset_urls: Optional[list[str]] = None,
    raw_product_name: Optional[str] = None,
    official_english_name: str = "",
    use_site_search: bool = True,
    log_lines: Optional[list[str]] = None,
    **kwargs: object,
) -> list[SupplyUrlCandidate]:
    """漏斗用: 候補URLs → 型番 site: 検索 → Playwright サイト内検索の順。"""
    lines: list[str] = log_lines if log_lines is not None else []
    norm_brand = normalize_brand_name(brand)
    style_hint = sheet_style_id_value(
        (raw_product_name or product_name or "").strip(), style_id
    )

    if preset_urls:
        valid = [
            u for u in preset_urls
            if url_is_valid_supply_candidate(
                norm_brand, u, style_id=style_hint or ""
            )
        ]
        if valid:
            lines.append(
                f"  候補URLs 列から {len(valid)} 件を使用（サイト内検索スキップ）"
            )
            return [_candidate_from_product_url(u) for u in valid[:5]]

    if style_hint:
        from lib.supply_url_cache import lookup_supply_urls

        cached = lookup_supply_urls(norm_brand, style_hint, log_lines=lines)
        if cached:
            return [_candidate_from_product_url(u) for u in cached[:5]]

    search_name = (raw_product_name or product_name or "").strip()
    if official_english_name:
        search_name = f"{official_english_name} {search_name}".strip()

    if use_site_search and style_hint:
        lines.append("  型番 site: 検索（層2）…")
        from lib.supply_site_search import discover_urls_by_style_id

        urls = discover_urls_by_style_id(
            norm_brand,
            style_hint,
            product_name=search_name,
            log_lines=lines,
            max_per_domain=1,
        )
        if urls:
            return [_candidate_from_product_url(u) for u in urls[:5]]

    lines.append("  主要サイト内検索（Playwright）…")
    return discover_supply_urls_sync(
        brand,
        product_name,
        style_id,
        raw_product_name=search_name,
        official_english_name=official_english_name,
        log_lines=lines,
        **kwargs,
    )


def discover_supply_urls_sync(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
    **kwargs: object,
) -> list[SupplyUrlCandidate]:
    log = kwargs.pop("log_lines", None)
    return asyncio.run(
        discover_supply_urls_async(
            brand, product_name, style_id, log_lines=log, **kwargs  # type: ignore[arg-type]
        )
    )
