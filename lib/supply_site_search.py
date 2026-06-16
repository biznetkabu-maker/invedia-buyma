"""
型番 + site:ドメイン 検索で仕入先商品 URL を取得（層2・漏斗用）。

DuckDuckGo HTML を利用（API キー不要）。失敗時は呼び出し側が Playwright 検索にフォールバック。
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; invedia-automation/1.0; +supply-site-search)"
)

# 成功率・実装済み Strategy を優先
_DEFAULT_DOMAINS = (
    "farfetch.com",
    "mytheresa.com",
    "ssense.com",
    "net-a-porter.com",
    "24s.com",
)

_RESULT_HREF = re.compile(
    r'class="result__a"[^>]+href="([^"]+)"',
    re.I,
)
_UDDG_REDIRECT = re.compile(r"uddg=([^&\"]+)")


def build_site_queries(brand: str, style_id: str, domains: tuple[str, ...] = _DEFAULT_DOMAINS) -> list[str]:
    b = (brand or "").strip()
    s = (style_id or "").strip()
    if not s:
        return []
    queries: list[str] = []
    for dom in domains:
        q = f"site:{dom} {b} {s}".strip() if b else f"site:{dom} {s}"
        queries.append(q)
    return queries


def _fetch_ddg_html(query: str, timeout: float = 20.0) -> str:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _unwrap_ddg_href(href: str) -> str:
    if "uddg=" in href:
        m = _UDDG_REDIRECT.search(href)
        if m:
            return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def extract_urls_from_ddg_html(html: str, *, domain_hint: str = "") -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    dom = (domain_hint or "").lower().replace("www.", "")

    def _add(raw_href: str) -> None:
        raw = _unwrap_ddg_href(raw_href)
        if not raw.startswith("http"):
            return
        if dom and dom not in raw.lower():
            return
        key = raw.split("?")[0]
        if key in seen:
            return
        seen.add(key)
        out.append(raw)

    for m in _RESULT_HREF.finditer(html):
        _add(m.group(1))

    # DDG HTML レイアウト変更時: すべての uddg= リダイレクトを走査
    for m in _UDDG_REDIRECT.finditer(html):
        try:
            _add(urllib.parse.unquote(m.group(1)))
        except Exception:
            continue

    return out


def search_product_urls_on_domain(
    query: str,
    domain: str,
    *,
    max_urls: int = 3,
    timeout: float = 20.0,
) -> list[str]:
    try:
        html = _fetch_ddg_html(query, timeout=timeout)
        urls = extract_urls_from_ddg_html(html, domain_hint=domain)
        return urls[:max_urls]
    except Exception as e:
        logger.debug("DDG search failed %s: %s", query, e)
        return []


def _style_site_queries(
    brand: str,
    style_id: str,
    *,
    product_name: str = "",
    domains: tuple[str, ...] = _DEFAULT_DOMAINS,
) -> list[str]:
    """site: 検索クエリ（財布・バッグ向けに英語キーワードを追加）。"""
    from lib.supply_search_utils import category_site_search_extras

    queries = build_site_queries(brand, style_id, domains)
    extras = category_site_search_extras(product_name)
    category_queries: list[str] = []
    if style_id:
        for extra in extras:
            for dom in domains:
                q = f"site:{dom} {brand} {style_id} {extra}".strip()
                category_queries.append(q)
    combined: list[str] = []
    seen_q: set[str] = set()
    for q in category_queries + queries:
        if q not in seen_q:
            seen_q.add(q)
            combined.append(q)
    return combined


def discover_urls_by_style_id(
    brand: str,
    style_id: str,
    *,
    product_name: str = "",
    domains: tuple[str, ...] = _DEFAULT_DOMAINS,
    log_lines: list[str] | None = None,
    max_per_domain: int = 1,
) -> list[str]:
    """型番ベースの site: 検索。有効な商品 URL のみ返す。"""
    from lib.supply_search_utils import (
        normalize_brand_name,
        rank_supply_urls_for_discovery,
        url_is_valid_supply_candidate,
        url_matches_style_hint,
    )

    norm_brand = normalize_brand_name(brand)
    lines = log_lines if log_lines is not None else []
    found: list[str] = []
    seen: set[str] = set()

    for q in _style_site_queries(
        norm_brand, style_id, product_name=product_name, domains=domains
    ):
        dom = ""
        if q.lower().startswith("site:"):
            dom = q.split()[0][5:].lower()
        lines.append(f"  型番検索: {q}")
        raw = search_product_urls_on_domain(q, dom, max_urls=5)
        candidates = [
            u for u in rank_supply_urls_for_discovery(
                raw, style_id=style_id, product_name=product_name
            )
            if url_is_valid_supply_candidate(
                norm_brand, u, style_id=style_id, product_name=product_name,
            )
        ]
        if not candidates:
            if raw:
                lines.append(
                    f"    -- {dom}: 候補{len(raw)}件はブランド/形式不一致で除外"
                )
            continue
        url = candidates[0]
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
        hint = (
            "型番URL一致"
            if url_matches_style_hint(style_id, url)
            else "型番はページ照合"
        )
        lines.append(f"    OK {dom} ({hint}): {url[:80]}")
    if not found:
        return []
    return rank_supply_urls_for_discovery(
        found, style_id=style_id, product_name=product_name,
    )
