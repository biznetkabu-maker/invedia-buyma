"""
PRADA 公式 (prada.com) による型番照合・英語名取得。

F12 で確認した XHR / JSON-LD / HTML から MPN・SKU・商品 URL を抽出する。
クラウド環境では Playwright が失敗することがある → DuckDuckGo site:prada.com にフォールバック。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

from lib.async_compat import run_sync
from lib.official_catalog.prada_catalog import (
    _BASE,
    _LOCALE_PATH,
    _NAME_KEYS,
    _PRADA_PDP_URL,
    _PRICE_KEYS,
    _PRODUCT_PATH,
    _SKU_KEYS,
    _URL_KEYS,
    _XHR_URL_HINTS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PradaOfficialMatch:
    """公式照合結果（仕入先 URL ではない）。"""

    mpn_query: str
    product_url: str
    sku: str
    english_name: str
    price_note: str
    source: str
    identity_note: str

    def matches_mpn(self, mpn: str) -> bool:
        q = (mpn or "").strip().upper()
        if not q:
            return False
        sku_u = (self.sku or "").upper()
        return sku_u == q or sku_u.startswith(q + "-") or q in sku_u


def _normalize_mpn(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _mpn_matches(query: str, candidate: str) -> bool:
    q = _normalize_mpn(query)
    c = _normalize_mpn(candidate)
    if not q or not c:
        return False
    if c == q:
        return True
    return c.startswith(q) and len(q) >= 5


@dataclass
class _Candidate:
    sku: str = ""
    url: str = ""
    name: str = ""
    price_note: str = ""
    source: str = ""
    score: int = 0


def _score_candidate(c: _Candidate, mpn: str) -> int:
    s = c.score
    if c.sku and _mpn_matches(mpn, c.sku):
        s += 100
    if c.url and "prada.com" in c.url and "/p/" in c.url:
        s += 40
    if c.name:
        s += 10
    if mpn.upper() in (c.url or "").upper():
        s += 30
    return s


def _walk_json(obj: Any, mpn: str, out: list[_Candidate], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        sku_val = ""
        url_val = ""
        name_val = ""
        price_val = ""
        for k, v in obj.items():
            kl = k.lower().replace("-", "").replace("_", "")
            if kl in _SKU_KEYS and isinstance(v, (str, int)):
                sku_val = str(v).strip()
            elif kl in _URL_KEYS and isinstance(v, str) and v.startswith("http"):
                url_val = v.strip()
            elif kl in _NAME_KEYS and isinstance(v, str) and len(v) > 3:
                name_val = v.strip()[:200]
            elif kl in _PRICE_KEYS and v is not None:
                price_val = str(v)[:40]
        if sku_val and _mpn_matches(mpn, sku_val):
            out.append(
                _Candidate(
                    sku=sku_val,
                    url=url_val,
                    name=name_val,
                    price_note=price_val,
                    source="xhr_json",
                    score=80,
                )
            )
        for v in obj.values():
            _walk_json(v, mpn, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:80]:
            _walk_json(item, mpn, out, depth + 1)


def _parse_html_product(html: str, mpn: str, page_url: str) -> list[_Candidate]:
    out: list[_Candidate] = []
    if not html:
        return out

    for m in _PRODUCT_PATH.finditer(html):
        path = m.group(0)
        if _normalize_mpn(mpn) not in _normalize_mpn(path) and mpn.upper() not in path.upper():
            continue
        url = urljoin(_BASE, path)
        out.append(_Candidate(url=url, sku=mpn, source="html_path", score=50))

    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>([^<]+)</script>',
        html,
        re.I,
    ):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            sku = str(root.get("sku") or root.get("mpn") or "").strip()
            if sku and _mpn_matches(mpn, sku):
                offers = root.get("offers") or {}
                if isinstance(offers, list) and offers:
                    offers = offers[0]
                price = ""
                if isinstance(offers, dict):
                    price = str(offers.get("price") or "")
                out.append(
                    _Candidate(
                        sku=sku,
                        url=page_url or str(root.get("url") or ""),
                        name=str(root.get("name") or "")[:200],
                        price_note=price,
                        source="json_ld",
                        score=90,
                    )
                )

    for m in re.finditer(
        r'"(?:partNumber|sku|mpn|productCode)"\s*:\s*"([^"]+)"',
        html,
        re.I,
    ):
        code = m.group(1).strip()
        if _mpn_matches(mpn, code):
            out.append(_Candidate(sku=code, url=page_url, source="html_embedded", score=70))

    return out


def _pick_best(candidates: list[_Candidate], mpn: str) -> Optional[_Candidate]:
    if not candidates:
        return None
    for c in candidates:
        c.score = _score_candidate(c, mpn)
    candidates.sort(key=lambda x: x.score, reverse=True)
    best = candidates[0]
    if _mpn_matches(mpn, best.sku):
        return best
    if best.score >= 50:
        return best
    # site:prada.com 由来で商品 PDP らしき URL
    if (
        best.url
        and "prada.com" in best.url
        and "/p/" in best.url
        and mpn.upper() in best.url.upper()
    ):
        if not best.sku:
            best.sku = mpn
        return best
    return None


def _search_urls(mpn: str) -> list[str]:
    from urllib.parse import quote_plus

    q = quote_plus(mpn)
    return [
        f"{_BASE}{_LOCALE_PATH}/search?q={q}",
        f"{_BASE}{_LOCALE_PATH}/search.html?query={q}",
        f"{_BASE}/jp/ja/search.html?q={q}",
        f"{_BASE}{_LOCALE_PATH}/search?text={q}",
    ]


def _ddg_queries(mpn: str, *, product_name: str = "") -> list[str]:
    extra = "sunglasses" if re.search(
        r"sunglass|eyewear|サングラス|メガネ", product_name or "", re.I
    ) else ""
    return [
        f"site:prada.com PRADA {mpn} {extra}".strip(),
        f"site:prada.com {mpn}",
        f"site:prada.com PRADA {mpn} symbole",
    ]


def _ddg_prada_urls(mpn: str, *, product_name: str = "") -> list[str]:
    try:
        from lib.supply_site_search import search_product_urls_on_domain
    except ImportError:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for q in _ddg_queries(mpn, product_name=product_name):
        for u in search_product_urls_on_domain(q, "prada.com", max_urls=5):
            key = u.split("?")[0]
            if key not in seen:
                seen.add(key)
                out.append(u)
        if out:
            break
    return out


def _extract_prada_pdp_urls(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in _PRADA_PDP_URL.finditer(html or ""):
        u = m.group(0).split("?")[0]
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _ddg_urls_playwright(page, mpn: str, *, product_name: str = "") -> list[str]:
    """urllib DDG が 0 件のとき Playwright で HTML DDG を取得。"""
    from urllib.parse import urlencode

    from lib.supply_site_search import extract_urls_from_ddg_html

    seen: set[str] = set()
    out: list[str] = []
    for q in _ddg_queries(mpn, product_name=product_name):
        ddg_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": q})
        try:
            await page.goto(ddg_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2500)
            for u in extract_urls_from_ddg_html(
                await page.content(), domain_hint="prada.com",
            ):
                key = u.split("?")[0]
                if key not in seen:
                    seen.add(key)
                    out.append(u)
            if out:
                break
        except Exception as e:
            logger.debug("ddg playwright %s: %s", q[:40], e)
    return out


async def _visit_pdps_for_sku(
    page,
    urls: list[str],
    mpn: str,
    collected: list[_Candidate],
    *,
    limit: int = 4,
) -> None:
    seen_pdp: set[str] = set()
    for u in urls:
        key = u.split("?")[0]
        if key in seen_pdp:
            continue
        seen_pdp.add(key)
        try:
            await page.goto(key, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)
            collected.extend(
                _parse_html_product(await page.content(), mpn, page.url)
            )
        except Exception as e:
            logger.debug("prada pdp %s: %s", key[:50], e)
        if len(seen_pdp) >= limit:
            break


async def _search_prada_pages(
    page: Any, mpn: str, debug: dict[str, object],
) -> tuple[list[_Candidate], list[str], str]:
    """Prada 公式サイトの検索ページを巡回して候補を収集する。"""
    collected: list[_Candidate] = []
    json_blobs: list[str] = []
    last_html = ""

    async def on_response(resp: Any) -> None:
        u = resp.url
        if "prada.com" not in u:
            return
        if not any(h in u for h in _XHR_URL_HINTS):
            return
        try:
            ct = resp.headers.get("content-type") or ""
            if resp.status != 200 or "json" not in ct:
                return
            text = await resp.text()
            if mpn.upper() in text.upper():
                json_blobs.append(text)
        except Exception as exc:
            logger.debug("prada: %s", exc)

    page.on("response", on_response)

    for search_url in _search_urls(mpn):
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(4000)
            html = await page.content()
            last_html = html
            debug["final_url"] = page.url
            if mpn.upper() in html.upper():
                debug["mpn_in_search_html"] = True
            pdp_in_html = _extract_prada_pdp_urls(html)
            debug["prada_pdp_links_in_html"] = len(pdp_in_html)
            collected.extend(_parse_html_product(html, mpn, page.url))
            for u in pdp_in_html:
                collected.append(_Candidate(url=u, sku=mpn, source="html_regex", score=42))
            if debug["mpn_in_search_html"] or pdp_in_html:
                break
        except Exception as e:
            logger.debug("prada search goto %s: %s", search_url[:60], e)

    return collected, json_blobs, last_html


async def _collect_dom_links(
    page: Any, mpn: str,
) -> list[_Candidate]:
    """DOM 内の PDP リンクから候補を収集する。"""
    collected: list[_Candidate] = []
    try:
        links = await page.locator('a[href*="/p/"]').evaluate_all(
            "elements => elements.map(e => e.href)"
        )
    except Exception:
        links = []
    for link in (links or [])[:12]:
        u = link.split("?")[0]
        if "prada.com" not in u or "/p/" not in u:
            continue
        score = 48 if mpn.upper() in u.upper() else 35
        collected.append(_Candidate(url=u, sku=mpn, source="dom_link", score=score))
    return collected


async def _collect_ddg_candidates(
    page: Any, mpn: str, product_name: str, debug: dict[str, object],
) -> list[_Candidate]:
    """DuckDuckGo フォールバックで候補URLを収集する。"""
    ddg_urllib = _ddg_prada_urls(mpn, product_name=product_name)
    debug["ddg_urllib"] = len(ddg_urllib)
    ddg_urls = list(ddg_urllib)
    if not ddg_urls:
        ddg_pw = await _ddg_urls_playwright(page, mpn, product_name=product_name)
        debug["ddg_playwright"] = len(ddg_pw)
        ddg_urls = ddg_pw
    return [_Candidate(url=u, sku=mpn, source="ddg_fallback", score=40) for u in ddg_urls]


async def _lookup_playwright(
    mpn: str, *, product_name: str = "",
) -> tuple[list[_Candidate], dict[str, object]]:
    from lib.supply_search.base_search import launch_stealth_page

    mpn = (mpn or "").strip()
    debug: dict[str, object] = {
        "mpn_in_search_html": False,
        "prada_pdp_links_in_html": 0,
        "ddg_urllib": 0,
        "ddg_playwright": 0,
        "final_url": "",
    }
    if not mpn:
        return [], debug

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser, ctx, page = await launch_stealth_page(pw)
        try:
            # 1. Prada 公式検索ページを巡回
            collected, json_blobs, _ = await _search_prada_pages(page, mpn, debug)

            # 2. XHR JSON データを解析
            for blob in json_blobs:
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                _walk_json(data, mpn, collected)

            # 3. DOM 内 PDP リンク収集
            collected.extend(await _collect_dom_links(page, mpn))

            # 4. DuckDuckGo フォールバック
            collected.extend(await _collect_ddg_candidates(page, mpn, product_name, debug))

            # 5. PDP ページを訪問して JSON-LD から完全 SKU を取得
            pdp_to_visit: list[str] = []
            for c in collected:
                if c.url and "/p/" in c.url:
                    pdp_to_visit.append(c.url.split("?")[0])
            pdp_to_visit = list(dict.fromkeys(pdp_to_visit))[:6]
            await _visit_pdps_for_sku(page, pdp_to_visit, mpn, collected)
        finally:
            await browser.close()

    return collected, debug


@dataclass
class PradaLookupDiagnostics:
    """診断用（capture_prada_f12 --verbose）。"""

    mpn: str
    playwright_ok: bool
    playwright_error: str = ""
    ddg_urls: list[str] = field(default_factory=list)
    candidate_count: int = 0
    top_candidates: list[dict] = field(default_factory=list)
    mpn_in_search_html: bool = False
    prada_pdp_links_in_html: int = 0
    ddg_urllib: int = 0
    ddg_playwright: int = 0
    search_final_url: str = ""


def lookup_prada_official_diagnose(
    mpn: str,
    *,
    product_name: str = "",
    use_playwright: bool = True,
) -> tuple[Optional[PradaOfficialMatch], PradaLookupDiagnostics]:
    mpn = (mpn or "").strip()
    diag = PradaLookupDiagnostics(mpn=mpn, playwright_ok=False)
    candidates: list[_Candidate] = []
    pw_err = ""

    pw_debug: dict[str, object] = {}
    if use_playwright:
        try:
            candidates, pw_debug = run_sync(
                _lookup_playwright(mpn, product_name=product_name)
            )
            diag.playwright_ok = True
            diag.mpn_in_search_html = bool(pw_debug.get("mpn_in_search_html"))
            diag.prada_pdp_links_in_html = int(
                pw_debug.get("prada_pdp_links_in_html") or 0
            )
            diag.ddg_urllib = int(pw_debug.get("ddg_urllib") or 0)
            diag.ddg_playwright = int(pw_debug.get("ddg_playwright") or 0)
            diag.search_final_url = str(pw_debug.get("final_url") or "")[:120]
        except Exception as e:
            pw_err = str(e)
            diag.playwright_error = pw_err

    diag.ddg_urls = _ddg_prada_urls(mpn, product_name=product_name)
    if not candidates:
        for u in diag.ddg_urls:
            candidates.append(
                _Candidate(url=u, sku=mpn, source="ddg_only", score=35)
            )

    diag.candidate_count = len(candidates)
    for c in sorted(candidates, key=lambda x: _score_candidate(x, mpn), reverse=True)[:5]:
        diag.top_candidates.append({
            "sku": c.sku,
            "url": (c.url or "")[:120],
            "source": c.source,
            "score": _score_candidate(c, mpn),
        })

    best = _pick_best(candidates, mpn)
    if not best:
        return None, diag

    url = (best.url or "").strip()
    if url and not url.startswith("http"):
        url = urljoin(_BASE, url)
    note = (
        f"公式SKU={best.sku or mpn}; source={best.source}; "
        f"MPN照合={'OK' if _mpn_matches(mpn, best.sku or mpn) else '部分'}"
    )
    return (
        PradaOfficialMatch(
            mpn_query=mpn,
            product_url=url,
            sku=best.sku or mpn,
            english_name=best.name or "",
            price_note=best.price_note or "",
            source=best.source,
            identity_note=note,
        ),
        diag,
    )


def lookup_prada_official_sync(
    mpn: str,
    *,
    product_name: str = "",
    use_playwright: bool = True,
) -> Optional[PradaOfficialMatch]:
    """MPN で prada.com を照合。ローカル Playwright 推奨。"""
    mpn = (mpn or "").strip()
    if not mpn:
        return None

    match, _diag = lookup_prada_official_diagnose(
        mpn, product_name=product_name, use_playwright=use_playwright,
    )
    return match
