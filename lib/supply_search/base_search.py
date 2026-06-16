"""仕入先検索の共通基盤。

各サイト検索モジュール（ssense, mytheresa, netaporter, farfetch, 24s）が
共通で使用する Playwright セットアップ、XHR 収集、JSON-LD パース、
診断データクラスを提供する。

新しいサイトを追加する際はこのモジュールの関数を使うことで
ボイラープレートを削減できる。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.I | re.S,
)


@dataclass
class SearchDiagnostics:
    """サイト検索の診断情報（共通フィールド）。"""

    query: str
    style_id: str
    playwright_ok: bool
    playwright_error: str = ""
    search_url: str = ""
    no_results: bool = False
    access_denied: bool = False
    json_ld_items: int = 0
    html_link_items: int = 0
    xhr_blobs: int = 0
    candidate_count: int = 0
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    product_urls: list[str] = field(default_factory=list)


def make_xhr_collector(
    domain: str,
    xhr_url_hints: tuple[str, ...],
    blobs: list[str],
    min_length: int = 80,
) -> Any:
    """Playwright の page.on("response") に渡す XHR 収集コールバックを生成する。

    Args:
        domain: 収集対象のドメイン（例: "ssense.com"）
        xhr_url_hints: XHR URL に含まれるヒント文字列のタプル
        blobs: 収集した JSON テキストを追加するリスト
        min_length: 最小 JSON テキスト長
    """

    async def _on_response(resp: Any) -> None:
        u = resp.url
        if domain not in u.lower():
            return
        if not any(h in u.lower() for h in xhr_url_hints):
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
            if len(text) < min_length:
                return
            blobs.append(text)
        except Exception as exc:
            logger.debug("base_search: %s", exc)

    return _on_response


async def launch_stealth_page(pw: Any) -> tuple[Any, Any, Any]:
    """ステルス設定済みの Playwright ブラウザ・コンテキスト・ページを起動する。

    Returns:
        (browser, context, page)
    """
    from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

    browser = await pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
    ctx = await browser.new_context(**stealth_context_options())
    page = await ctx.new_page()
    await apply_stealth_scripts(page)
    return browser, ctx, page


def extract_json_ld_blocks(html: str) -> list[Any]:
    """HTML から JSON-LD ブロックを抽出してパース済みオブジェクトのリストを返す。"""
    results: list[Any] = []
    for m in JSON_LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
            results.append(data)
        except (json.JSONDecodeError, ValueError):
            continue
    return results


def _json_ld_brand_name(raw: Any) -> str:
    """JSON-LD の brand フィールド（dict / 文字列）から名称を取り出す。"""
    if isinstance(raw, dict):
        return str(raw.get("name", ""))
    return str(raw or "")


def _json_ld_offer_url(offers: Any) -> str:
    """JSON-LD の offers（dict / list）から URL を取り出す。"""
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict):
        return str(offers.get("url") or "")
    return ""


def iter_json_ld_products(html: str) -> list[dict[str, str]]:
    """JSON-LD の ItemList / Product から正規化済み商品レコードを返す。

    各レコードは ``{"name", "brand", "url", "sku", "source"}`` の dict。
    サイト個別の検証・データクラス変換は呼び出し側で行う。
    """
    records: list[dict[str, str]] = []

    def _from_product(node: dict[str, Any], source: str, fallback: dict[str, Any]) -> None:
        records.append(
            {
                "name": str(node.get("name") or fallback.get("name") or ""),
                "brand": _json_ld_brand_name(node.get("brand")),
                "url": str(
                    _json_ld_offer_url(node.get("offers") or {})
                    or node.get("url")
                    or fallback.get("url")
                    or ""
                ),
                "sku": str(node.get("sku") or node.get("mpn") or ""),
                "source": source,
            }
        )

    for data in extract_json_ld_blocks(html):
        roots = data if isinstance(data, list) else [data]
        for root in roots:
            if not isinstance(root, dict):
                continue
            type_ = root.get("@type")
            if type_ == "ItemList":
                for el in root.get("itemListElement") or []:
                    if not isinstance(el, dict):
                        continue
                    item = el.get("item") if isinstance(el.get("item"), dict) else el
                    if isinstance(item, dict):
                        _from_product(item, "json_ld_itemlist", el)
            elif type_ == "Product":
                _from_product(root, "json_ld_product", {})
    return records


def extract_product_urls_from_html(
    html: str,
    href_re: re.Pattern[str],
    path_re: re.Pattern[str],
    base_url: str,
    *,
    exclude_re: re.Pattern[str] | None = None,
) -> list[str]:
    """HTML から正規表現にマッチする商品 URL を抽出する。

    Args:
        html: ページの HTML
        href_re: 完全 URL にマッチする正規表現
        path_re: パスにマッチする正規表現（グループ 1 がパス）
        base_url: 相対パスのベース URL
        exclude_re: 除外する URL パターン
    """
    seen: set[str] = set()
    urls: list[str] = []

    for m in href_re.finditer(html or ""):
        u = m.group(0).split("?")[0].split("#")[0]
        if u in seen:
            continue
        if exclude_re and exclude_re.search(u):
            continue
        seen.add(u)
        urls.append(u)

    for m in path_re.finditer(html or ""):
        path = m.group(1).split("?")[0]
        u = urljoin(base_url, path)
        if u in seen:
            continue
        if exclude_re and exclude_re.search(u):
            continue
        seen.add(u)
        urls.append(u)

    return urls


def merge_ranked_urls(
    ranked: list[tuple[Any, int]],
    xhr_hits: list[Any],
    *,
    base_url: str,
    url_validator: Any,
    min_score: int = 0,
) -> list[str]:
    """ランキング済みカタログアイテムと XHR ヒットから URL リストをマージする。

    Args:
        ranked: (item, score) タプルのリスト
        xhr_hits: SearchHit のリスト
        base_url: 相対 URL のベース
        url_validator: URL の妥当性を検証する関数
        min_score: カタログアイテムに必要な最低スコア
    """
    urls: list[str] = []
    seen: set[str] = set()

    for item, score in ranked:
        if score < min_score:
            continue
        u = item.url.split("?")[0]
        if u not in seen and url_validator(u):
            seen.add(u)
            urls.append(u)

    for hit in sorted(xhr_hits, key=lambda h: h.score, reverse=True):
        u = (hit.url or "").split("?")[0]
        if not u or u in seen:
            continue
        if not u.startswith("http"):
            u = urljoin(base_url, u)
        if not url_validator(u):
            continue
        seen.add(u)
        urls.append(u)

    return urls


async def run_playwright_search(
    domain: str,
    xhr_url_hints: tuple[str, ...],
    search_func: Any,
    search_url: str,
    diag: SearchDiagnostics,
    **search_kwargs: Any,
) -> tuple[list[str], SearchDiagnostics]:
    """Playwright で検索を実行する共通パターン。

    Args:
        domain: XHR 収集対象ドメイン
        xhr_url_hints: XHR URL ヒント
        search_func: async def search_func(page, query, *, xhr_blobs, **kwargs) -> (urls, debug)
        search_url: 検索 URL（diag 用）
        diag: SearchDiagnostics インスタンス
        **search_kwargs: search_func に渡す追加引数
    """
    from playwright.async_api import async_playwright

    xhr_blobs: list[str] = []
    try:
        async with async_playwright() as pw:
            browser, _ctx, page = await launch_stealth_page(pw)
            try:
                page.on("response", make_xhr_collector(domain, xhr_url_hints, xhr_blobs))
                urls, dbg = await search_func(page, xhr_blobs=xhr_blobs, **search_kwargs)
                diag.playwright_ok = True
                diag.json_ld_items = dbg.get("json_ld_items", 0)
                diag.html_link_items = dbg.get("html_link_items", 0)
                diag.xhr_blobs = len(xhr_blobs)
                diag.top_candidates = dbg.get("top_scores", [])
                diag.product_urls = urls
                diag.candidate_count = len(urls)
                for key in ("no_results", "access_denied"):
                    if key in dbg:
                        setattr(diag, key, dbg[key])
                return urls, diag
            finally:
                await browser.close()
    except Exception as e:
        diag.playwright_error = str(e)
        logger.debug("%s search playwright failed: %s", domain, e)
        return [], diag


def build_top_scores_debug(
    ranked: list[tuple[Any, int]],
    *,
    has_brand: bool = True,
    has_sku: bool = True,
) -> list[dict[str, Any]]:
    """ランキング結果をデバッグ用辞書リストに変換する。"""
    out: list[dict[str, Any]] = []
    for item, score in ranked:
        entry: dict[str, Any] = {
            "score": score,
            "name": item.name[:60],
            "url": item.url,
            "source": item.source,
        }
        if has_brand and hasattr(item, "brand"):
            entry["brand"] = item.brand[:30]
        if has_sku and hasattr(item, "sku"):
            entry["sku"] = item.sku
        out.append(entry)
    return out


# ============================================================================
# 共通スコアリング
# ============================================================================

def score_catalog_item_base(
    item: Any,
    *,
    style_id: str,
    product_name: str,
    brand: str,
    preowned_re: re.Pattern[str] | None = None,
    url_validator: Any | None = None,
) -> int:
    """カタログアイテムの共通スコアリングロジック。

    各サイトの ``_score_item`` で共有するベーススコアを算出する。
    サイト固有のボーナス/ペナルティは呼び出し側で加減すること。
    """
    from lib.supply_search.json_walk import normalize_style_token
    from lib.supply_search_utils import infer_supply_category_hints

    score = 30

    name = getattr(item, "name", "")
    path = getattr(item, "path", "")
    sku = getattr(item, "sku", "")
    item_brand = getattr(item, "brand", "")
    blob = f"{name} {item_brand} {path} {sku}".lower()

    sid = (style_id or "").strip()
    if sid:
        compact = normalize_style_token(sid)
        if compact and compact in normalize_style_token(blob):
            score += 100

    pos, neg = infer_supply_category_hints(product_name)
    for hint in pos:
        h = hint.lower().replace("-", " ")
        if h in blob or h.replace(" ", "-") in path.lower():
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
        score -= 20

    if preowned_re and (preowned_re.search(path) or preowned_re.search(name)):
        score -= 35

    url = getattr(item, "url", "")
    if url_validator and not url_validator(url):
        score -= 100

    source = getattr(item, "source", "")
    if source == "json_ld_itemlist":
        score += 5

    return score


def rank_catalog_items(
    items: list[Any],
    *,
    style_id: str = "",
    product_name: str = "",
    brand: str = "",
    limit: int = 5,
    scorer: Any | None = None,
    preowned_re: re.Pattern[str] | None = None,
    url_validator: Any | None = None,
) -> list[tuple[Any, int]]:
    """カタログアイテムをスコアでランキングする共通関数。"""
    if scorer:
        scored = [(it, scorer(it, style_id=style_id, product_name=product_name, brand=brand)) for it in items]
    else:
        scored = [
            (it, score_catalog_item_base(
                it, style_id=style_id, product_name=product_name,
                brand=brand, preowned_re=preowned_re, url_validator=url_validator,
            ))
            for it in items
        ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def rank_merge_and_debug(
    catalog: list[Any],
    xhr_hits: list[Any],
    *,
    style_id: str,
    product_name: str,
    brand: str,
    base_url: str,
    url_validator: Any,
    scorer: Any | None = None,
    preowned_re: re.Pattern[str] | None = None,
    limit: int = 8,
) -> tuple[list[str], list[dict[str, Any]]]:
    """ランキング→マージ→デバッグ情報を一括で返す共通関数。"""
    ranked = rank_catalog_items(
        catalog, style_id=style_id, product_name=product_name,
        brand=brand, limit=limit, scorer=scorer,
        preowned_re=preowned_re, url_validator=url_validator,
    )
    urls = merge_ranked_urls(
        ranked, xhr_hits, base_url=base_url, url_validator=url_validator,
    )
    top_scores = build_top_scores_debug(ranked)
    return urls, top_scores
