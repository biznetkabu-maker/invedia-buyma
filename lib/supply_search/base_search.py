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
from typing import Any, Optional
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


def extract_product_urls_from_html(
    html: str,
    href_re: re.Pattern[str],
    path_re: re.Pattern[str],
    base_url: str,
    *,
    exclude_re: Optional[re.Pattern[str]] = None,
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
