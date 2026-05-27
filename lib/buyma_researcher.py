"""
BUYMAリサーチャー — 人気ランキングから出品候補を自動収集するモジュール。

⚠️  利用前に BUYMA 利用規約を確認してください。
    本モジュールは BUYMA の公開ページのみを対象とし、
    過度なリクエストを避けるためリクエスト間隔を設けています。

動作概要:
    1. BUYMA 人気ブランドランキング・人気商品ランキングページを巡回
    2. 各商品の「ブランド / 商品名 / カテゴリ / お気に入り数 / 出品数」を抽出
    3. 推奨ブランド・定番カテゴリ・最低お気に入り数でフィルタリング
    4. 各商品に対して仕入先候補URLを生成（SSENSE / NAP / 24S 等で商品検索）
    5. fetch_style_ids=True 時は商品詳細URLに寄り、buyma_style_id モジュールで型番を ResearchCandidate.style_id に格納
    6. SheetManager 経由でスプレッドシートに候補を追加

使い方:
    from lib.buyma_researcher import BUYMAResearcher

    researcher = BUYMAResearcher()
    candidates = researcher.research(
        min_favorites=10,
        max_items=20,
    )
    for c in candidates:
        print(c)
"""

from __future__ import annotations

import asyncio

from lib.async_compat import run_sync
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

from lib.purchase_evaluator import RECOMMENDED_BRANDS, STABLE_CATEGORIES

logger = logging.getLogger(__name__)


# ============================================================================
# BUYMA ページ定義
# ============================================================================

# 公開ランキングURL（ログイン不要）
_BUYMA_RANKING_URLS: list[str] = [
    "https://www.buyma.com/buy/ranking/",                   # 総合人気ランキング
    "https://www.buyma.com/buy/brand/ranking/",             # ブランドランキング
]

# カテゴリ別ランキング（定番カテゴリのみ）
_BUYMA_CATEGORY_URLS: list[str] = [
    "https://www.buyma.com/buy/-A3/",    # バッグ
    "https://www.buyma.com/buy/-A21/",   # 財布
    "https://www.buyma.com/buy/-A82/",   # スニーカー
]


# ============================================================================
# 仕入先サイト別 検索URL ビルダー
# ============================================================================

def _build_search_urls(brand: str, product_name: str) -> list[str]:
    """ブランド名・商品名から各仕入先の検索URLを生成する。

    生成されるURLは検索結果ページ。BestSourceFinder に渡す前に
    実際の商品ページURLに変換する必要がある場合がある。
    """
    q = quote_plus(f"{brand} {product_name}")
    return [
        f"https://www.ssense.com/en-us/women?q={q}",
        f"https://www.net-a-porter.com/en-us/search?q={q}",
        f"https://www.mytheresa.com/en-us/search/?q={q}",
        f"https://www.farfetch.com/shopping/women/search/items.aspx?q={q}",
        f"https://www.24s.com/en-us/search?q={q}",
        f"https://www.luisaviaroma.com/en-us/shop/?lvrid=_search&q={q}",
    ]


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class ResearchCandidate:
    """BUYMAリサーチで発見した出品候補商品。"""

    brand: str
    product_name: str
    category: str
    favorites_count: int
    listing_count: int          # BUYMA上の競合出品数
    buyma_url: str              # BUYMAの商品/検索ページURL
    candidate_source_urls: list[str] = field(default_factory=list)
    style_id: Optional[str] = None  # 詳細ページから抽出した型番（fetch_style_ids 時）

    @property
    def is_recommended_brand(self) -> bool:
        b = self.brand.lower()
        return any(kw in b for kw in RECOMMENDED_BRANDS)

    @property
    def is_stable_category(self) -> bool:
        c = (self.product_name + " " + self.category).lower()
        return any(kw in c for kw in STABLE_CATEGORIES)

    def __str__(self) -> str:
        rec = "⭐" if self.is_recommended_brand else "  "
        cat = "📦" if self.is_stable_category else "  "
        return (
            f"{rec}{cat} [{self.brand}] {self.product_name} "
            f"| お気に入り: {self.favorites_count}件 / 競合: {self.listing_count}件"
        )


# ============================================================================
# BUYMAResearcher
# ============================================================================

class BUYMAResearcher:
    """BUYMA人気ランキングをスクレイプして出品候補を自動収集するクラス。

    Args:
        headless: ヘッドレスモードで実行するか（default: True）
        page_wait_ms: ページ読み込み後の追加待機時間 ms（default: 2000）
        request_interval_sec: ページ間のリクエスト間隔 秒（default: 3.0）
        max_pages: 各ランキングページから取得するページ数（default: 1）
    """

    def __init__(
        self,
        headless: bool = True,
        page_wait_ms: int = 2_000,
        request_interval_sec: float = 3.0,
        max_pages: int = 1,
    ) -> None:
        self._headless = headless
        self._page_wait_ms = page_wait_ms
        self._request_interval_sec = request_interval_sec
        self._max_pages = max_pages

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------

    def research(
        self,
        min_favorites: int = 10,
        max_items: int = 30,
        recommended_only: bool = True,
        stable_category_only: bool = True,
        build_source_urls: bool = True,
        fetch_style_ids: bool = False,
    ) -> list[ResearchCandidate]:
        """BUYMAランキングから出品候補を収集して返す（同期版）。

        Args:
            min_favorites: 最低お気に入り登録数のフィルタ
            max_items: 返す最大件数
            recommended_only: 推奨ブランドのみに絞るか
            stable_category_only: 定番カテゴリのみに絞るか
            build_source_urls: 仕入先候補URLを生成するか
            fetch_style_ids: True のとき個別商品URLに遷移し style_id を埋める（要約:追加アクセス）

        Returns:
            ResearchCandidate のリスト（お気に入り数降順）
        """
        return run_sync(
            self.research_async(
                min_favorites=min_favorites,
                max_items=max_items,
                recommended_only=recommended_only,
                stable_category_only=stable_category_only,
                build_source_urls=build_source_urls,
                fetch_style_ids=fetch_style_ids,
            )
        )

    async def research_async(
        self,
        min_favorites: int = 10,
        max_items: int = 30,
        recommended_only: bool = True,
        stable_category_only: bool = True,
        build_source_urls: bool = True,
        fetch_style_ids: bool = False,
    ) -> list[ResearchCandidate]:
        """BUYMAランキングから出品候補を収集して返す（非同期版）。

        fetch_style_ids:
            True の場合、結果各行の buyma_url が商品詳細URLと判定できるときのみ
            追加でページを開き、HTML から型番候補を style_id に格納する。
        """
        from playwright.async_api import async_playwright

        from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

        all_candidates: list[ResearchCandidate] = []
        target_urls = _BUYMA_RANKING_URLS + _BUYMA_CATEGORY_URLS

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless, args=LAUNCH_ARGS
            )
            try:
                ctx = await browser.new_context(**stealth_context_options())
                page = await ctx.new_page()
                await apply_stealth_scripts(page)

                for url in target_urls:
                    try:
                        logger.info("BUYMAリサーチ: %s", url)
                        await page.goto(url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(self._page_wait_ms)

                        items = await self._extract_items(page, url)
                        logger.info("  → %d件抽出", len(items))
                        all_candidates.extend(items)

                        # リクエスト間隔
                        await asyncio.sleep(self._request_interval_sec)

                    except Exception as e:
                        logger.warning("ページ取得失敗 [%s]: %s", url, e)
                        continue

            finally:
                await browser.close()

        # 重複除去（ブランド + 商品名でユニーク）
        seen: set[str] = set()
        unique: list[ResearchCandidate] = []
        for c in all_candidates:
            key = f"{c.brand.lower()}::{c.product_name.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(c)

        # フィルタリング
        filtered = self._filter(
            unique,
            min_favorites=min_favorites,
            recommended_only=recommended_only,
            stable_category_only=stable_category_only,
        )

        # お気に入り数降順でソート
        filtered.sort(key=lambda c: c.favorites_count, reverse=True)
        result = filtered[:max_items]

        # 仕入先候補URL生成
        if build_source_urls:
            for c in result:
                c.candidate_source_urls = _build_search_urls(c.brand, c.product_name)

        if fetch_style_ids:
            await self._enrich_style_ids_on_detail_pages(result)

        logger.info(
            "BUYMAリサーチ完了: 合計 %d件 → フィルタ後 %d件",
            len(unique), len(result),
        )
        return result

    async def _enrich_style_ids_on_detail_pages(
        self,
        candidates: list[ResearchCandidate],
    ) -> None:
        """buyma_url が商品詳細のとき、ページ HTML から style_id を抽出する。"""
        from playwright.async_api import async_playwright

        from lib.buyma_style_id import extract_primary_style_id_from_buyma_html, is_buyma_item_url
        from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

        to_fetch = [
            c for c in candidates
            if is_buyma_item_url(c.buyma_url) and not c.style_id
        ]
        if not to_fetch:
            return

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless, args=LAUNCH_ARGS,
            )
            try:
                ctx = await browser.new_context(**stealth_context_options())
                page = await ctx.new_page()
                await apply_stealth_scripts(page)
                page.set_default_timeout(25_000)
                for i, c in enumerate(to_fetch):
                    try:
                        logger.info(
                            "BUYMA型番取得 (%d/%d): %s",
                            i + 1, len(to_fetch), c.buyma_url,
                        )
                        await page.goto(c.buyma_url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(self._page_wait_ms)
                        html = await page.content()
                        sid = extract_primary_style_id_from_buyma_html(html)
                        if sid:
                            c.style_id = sid
                    except Exception as e:
                        logger.warning(
                            "BUYMA型番取得失敗 [%s]: %s", c.buyma_url, e,
                        )
                    await asyncio.sleep(self._request_interval_sec)
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # ページパース
    # ------------------------------------------------------------------

    async def _extract_items(self, page, source_url: str) -> list[ResearchCandidate]:
        """ページから商品候補を抽出する。

        BUYMA のページ構造は変更されることがあるため、
        複数のセレクタパターンを試みる。
        """
        candidates: list[ResearchCandidate] = []

        # ── アプローチ1: 商品カードセレクタ ────────────────────────────
        item_selectors = [
            ".item-card",
            "[class*='item-list'] li",
            "[class*='product-list'] li",
            "[class*='ranking'] li",
            "article[class*='item']",
        ]

        for sel in item_selectors:
            try:
                elements = await page.query_selector_all(sel)
                if not elements:
                    continue

                for el in elements[:50]:  # 1ページあたり最大50件
                    try:
                        c = await self._parse_item_element(el, source_url)
                        if c:
                            candidates.append(c)
                    except Exception:
                        continue

                if candidates:
                    return candidates
            except Exception:
                continue

        # ── アプローチ2: JSON-LD / microdata ────────────────────────────
        try:
            ld_items = await page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                    try {
                        const d = JSON.parse(s.textContent);
                        const items = d['@graph'] || (Array.isArray(d) ? d : [d]);
                        items.forEach(item => {
                            if (item['@type'] === 'Product' && item.name && item.brand) {
                                results.push({
                                    name: item.name,
                                    brand: (item.brand.name || item.brand),
                                    url: item.url || '',
                                });
                            }
                        });
                    } catch {}
                });
                return results;
            }""")

            for item in (ld_items or []):
                brand = str(item.get("brand", "")).strip()
                name = str(item.get("name", "")).strip()
                if brand and name:
                    candidates.append(ResearchCandidate(
                        brand=brand,
                        product_name=name,
                        category="",
                        favorites_count=0,
                        listing_count=0,
                        buyma_url=item.get("url", source_url),
                    ))

        except Exception:
            logger.debug("BUYMA検索結果パース失敗", exc_info=True)

        return candidates

    async def _parse_item_element(self, el, source_url: str) -> Optional[ResearchCandidate]:
        """DOM 要素1つから ResearchCandidate を生成する。"""
        # テキスト全体を取得してパース
        text = (await el.inner_text()).strip()
        if not text:
            return None

        # href（商品URL）
        link = await el.query_selector("a")
        buyma_url = source_url
        if link:
            href = await link.get_attribute("href")
            if href:
                buyma_url = href if href.startswith("http") else f"https://www.buyma.com{href}"

        # ブランド名抽出（実際のHTML構造に合わせて調整）
        brand = await self._extract_text(el, [
            "[class*='brand']", "[class*='maker']", ".item-brand",
        ])

        # 商品名抽出
        product_name = await self._extract_text(el, [
            "[class*='item-name']", "[class*='product-name']", "h3", "h4", ".name",
        ])

        # お気に入り数
        favorites_str = await self._extract_text(el, [
            "[class*='favorite']", "[class*='like']", "[class*='wish']",
        ])
        favorites_count = _parse_int(favorites_str)

        # 出品数
        listing_str = await self._extract_text(el, [
            "[class*='listing']", "[class*='item-count']", "[class*='seller']",
        ])
        listing_count = _parse_int(listing_str)

        if not brand or not product_name:
            return None

        return ResearchCandidate(
            brand=brand.strip(),
            product_name=product_name.strip(),
            category="",
            favorites_count=favorites_count,
            listing_count=listing_count,
            buyma_url=buyma_url,
        )

    @staticmethod
    async def _extract_text(el, selectors: list[str]) -> str:
        """複数セレクタを試してテキストを取得する。見つからなければ空文字。"""
        for sel in selectors:
            try:
                child = await el.query_selector(sel)
                if child:
                    text = (await child.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    # ------------------------------------------------------------------
    # フィルタリング
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(
        candidates: list[ResearchCandidate],
        min_favorites: int,
        recommended_only: bool,
        stable_category_only: bool,
    ) -> list[ResearchCandidate]:
        result = []
        for c in candidates:
            if c.favorites_count < min_favorites:
                continue
            if recommended_only and not c.is_recommended_brand:
                continue
            if stable_category_only and not c.is_stable_category:
                # 推奨ブランドかつお気に入り多数なら定番カテゴリ外でも許容
                if not (c.is_recommended_brand and c.favorites_count >= 20):
                    continue
            result.append(c)
        return result


# ============================================================================
# ユーティリティ
# ============================================================================

def _parse_int(text: str) -> int:
    """テキストから数値を抽出する（例: "お気に入り 23件" → 23）。"""
    if not text:
        return 0
    m = re.search(r"[\d,]+", text.replace("，", ","))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return 0
