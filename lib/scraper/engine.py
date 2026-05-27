"""PriceScraper: URLを受け取り、適切なStrategyで価格・在庫を取得するコンテキストクラス。"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, async_playwright

from lib.async_compat import run_sync

from .base import ScraperStrategy
from .models import ScrapedResult
from .proxy import ProxyRotator
from .stealth import (
    LAUNCH_ARGS,
    apply_stealth_scripts,
    random_user_agent,
    random_wait_ms,
    stealth_context_options,
)
from .strategies.biffi import BIFFIStrategy
from .strategies.farfetch import FARFETCHStrategy
from .strategies.generic import GenericStrategy
from .strategies.giglio import GIGLIOStrategy
from .strategies.harrods import HARRODSStrategy
from .strategies.harveynichols import HARVEYNICHOLSStrategy
from .strategies.luisaviaroma import LUISAVIAROMAStrategy
from .strategies.matchesfashion import MATCHESFASHIONStrategy
from .strategies.mrporter import MRPORTERStrategy
from .strategies.mytheresa import MYTHERESAStrategy
from .strategies.neimanmarcus import NEIMANMARCUSStrategy
from .strategies.netaporter import NETAPORTERStrategy
from .strategies.saks import SAKSStrategy
from .strategies.selfridges import SELFRIDGESStrategy
from .strategies.ssense import SSENSEStrategy
from .strategies.tessabit import TESSABITStrategy
from .strategies.theoutnet import THEOUTNETStrategy
from .strategies.twentyfoursevens import TWENTYFOURSStrategy
from .strategies.yoox import YOOXStrategy
from .utils import parse_price_string

logger = logging.getLogger(__name__)

# 重いサイト（価格表示まで最大30秒待機）
_HEAVY_SITE_DOMAINS: frozenset[str] = frozenset([
    "selfridges.com",
    "harrods.com",
    "saksfifthavenue.com",
    "luisaviaroma.com",
    "net-a-porter.com",
    "mrporter.com",
    "neimanmarcus.com",
    "farfetch.com",
    "mytheresa.com",
])

_DEFAULT_HEAVY_TIMEOUT_MS = int(os.environ.get("SCRAPER_HEAVY_TIMEOUT_MS", "45000"))

# デフォルトで登録する全Strategyのリスト
_DEFAULT_STRATEGIES: list[ScraperStrategy] = [
    SSENSEStrategy(),
    TESSABITStrategy(),
    FARFETCHStrategy(),
    MATCHESFASHIONStrategy(),
    MYTHERESAStrategy(),
    SELFRIDGESStrategy(),
    SAKSStrategy(),
    HARRODSStrategy(),
    HARVEYNICHOLSStrategy(),
    NEIMANMARCUSStrategy(),
    LUISAVIAROMAStrategy(),
    GIGLIOStrategy(),
    BIFFIStrategy(),
    NETAPORTERStrategy(),
    MRPORTERStrategy(),
    YOOXStrategy(),
    THEOUTNETStrategy(),
    TWENTYFOURSStrategy(),
]


class PriceScraper:
    """URL を受け取り、ドメインに応じた Strategy でスクレイピングを実行するクラス。

    新しいショップを追加したい場合::

        scraper = PriceScraper()
        scraper.register(MyNewShopStrategy())

    Args:
        headless: ブラウザをヘッドレスモードで起動する（デフォルト True）。
        timeout_ms: ページロードのタイムアウト（ミリ秒、デフォルト 30000）。
        heavy_site_timeout_ms: 重いサイト向け最大待機時間（デフォルト 30000）。
        user_agent: User-Agent 文字列。None の場合はランダムに選択する。
        max_retries: 失敗時のリトライ回数（デフォルト 2）。
        extra_wait_ms: ページロード後の追加待機時間の最大値（ms）。0 で無効。
        use_stealth: ステルス設定（UA偽装・フィンガープリント）を有効にする。
        proxy_rotator: プロキシローテーター。None の場合は直接接続。
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30_000,
        heavy_site_timeout_ms: int = _DEFAULT_HEAVY_TIMEOUT_MS,
        user_agent: Optional[str] = None,
        max_retries: int = 2,
        extra_wait_ms: int = 2_000,
        use_stealth: bool = True,
        proxy_rotator: Optional[ProxyRotator] = None,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._heavy_site_timeout_ms = heavy_site_timeout_ms
        self._user_agent = user_agent
        self._max_retries = max_retries
        self._extra_wait_ms = extra_wait_ms
        self._use_stealth = use_stealth
        self._proxy_rotator = proxy_rotator or ProxyRotator()

        self._strategies: dict[str, ScraperStrategy] = {}
        self._generic = GenericStrategy()

        for strategy in _DEFAULT_STRATEGIES:
            self.register(strategy)

    # ------------------------------------------------------------------
    # Strategy 管理
    # ------------------------------------------------------------------

    def register(self, strategy: ScraperStrategy) -> None:
        """Strategyを登録する。既存ドメインは上書きされる。"""
        self._strategies[strategy.domain] = strategy
        logger.debug("Registered strategy: %s → %s", strategy.domain, type(strategy).__name__)

    def get_strategy(self, url: str) -> ScraperStrategy:
        """URLのドメインに対応するStrategyを返す。なければGenericStrategyを返す。"""
        netloc = urlparse(url).netloc.lower()
        for domain, strategy in self._strategies.items():
            if domain in netloc:
                return strategy
        logger.debug("No specific strategy for %s, using GenericStrategy", netloc)
        return self._generic

    def is_heavy_site(self, url: str) -> bool:
        """重いサイト（長いタイムアウトが必要）かどうかを返す。"""
        netloc = urlparse(url).netloc.lower()
        return any(d in netloc for d in _HEAVY_SITE_DOMAINS)

    def navigation_wait_chain(self, url: str) -> list[str]:
        """page.goto の wait_until を試す順序（先頭から順にリトライ）。"""
        if not self.is_heavy_site(url):
            return ["networkidle"]
        netloc = urlparse(url).netloc.lower()
        if "farfetch.com" in netloc:
            return ["domcontentloaded", "commit"]
        return ["domcontentloaded"]

    async def _goto_with_fallback(self, page, url: str) -> None:
        """重いサイトは domcontentloaded → commit の順でナビゲーションを試す。"""
        waits = self.navigation_wait_chain(url)
        last_error: Optional[Exception] = None
        for i, wait_until in enumerate(waits):
            try:
                await page.goto(url, wait_until=wait_until)
                return
            except Exception as e:
                last_error = e
                if i < len(waits) - 1:
                    logger.debug(
                        "goto %s wait_until=%s failed (%s), retrying",
                        url, wait_until, e,
                    )
                else:
                    raise
        if last_error:
            raise last_error

    # ------------------------------------------------------------------
    # 通貨・価格ユーティリティ（外部からも利用可能）
    # ------------------------------------------------------------------

    @staticmethod
    def parse_price(raw: str) -> tuple[Optional[float], Optional[str]]:
        """価格文字列から (数値, 通貨コード) を抽出する。

        Examples:
            >>> PriceScraper.parse_price("$1,550")
            (1550.0, 'USD')
            >>> PriceScraper.parse_price("€ 2.450,00")
            (2450.0, 'EUR')
            >>> PriceScraper.parse_price("£899")
            (899.0, 'GBP')
            >>> PriceScraper.parse_price("¥15,000")
            (15000.0, 'JPY')

        Returns:
            (price_float, currency_code) タプル。変換失敗時は (None, None) または
            (None, currency_code) を返す。
        """
        return parse_price_string(raw)

    # ------------------------------------------------------------------
    # 非同期スクレイピング
    # ------------------------------------------------------------------

    async def scrape_async(self, url: str) -> ScrapedResult:
        """1件のURLを非同期でスクレイピングする。"""
        import time as _time

        from lib.logging_config import record_scrape

        strategy = self.get_strategy(url)
        last_error: Optional[Exception] = None
        launch_args = LAUNCH_ARGS if self._use_stealth else []
        site = urlparse(url).netloc.lower()
        t0 = _time.monotonic()

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=self._headless,
                args=launch_args,
            )
            try:
                for attempt in range(1, self._max_retries + 1):
                    try:
                        result = await self._scrape_with_browser(url, browser, strategy)
                        if result.success:
                            record_scrape(site, success=True, response_time=_time.monotonic() - t0)
                            return result
                        last_error = Exception(result.error or "unknown error")
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s",
                            attempt, self._max_retries, url, e,
                        )
                        if attempt < self._max_retries:
                            await asyncio.sleep(
                                attempt * 2 + random_wait_ms(0, 1000) / 1000
                            )
            finally:
                await browser.close()

        record_scrape(site, success=False, response_time=_time.monotonic() - t0)
        return self._make_error_result(url, last_error)

    def _build_context_options(self, url: str) -> dict[str, Any]:
        ua = self._user_agent or (random_user_agent() if self._use_stealth else None)
        ctx_opts: dict[str, Any] = (
            stealth_context_options(user_agent=ua)
            if self._use_stealth
            else {"user_agent": ua or "", "locale": "en-US"}
        )
        if "farfetch.com/jp" in url.lower():
            ctx_opts = {**ctx_opts, "locale": "ja-JP"}
        proxy = self._proxy_rotator.next() if self._proxy_rotator else None
        if proxy:
            ctx_opts["proxy"] = proxy.to_playwright_proxy()
            logger.debug("Using proxy: %r for %s", proxy, url)
        return ctx_opts

    @staticmethod
    def _build_result_from_extracted(
        url: str, extracted: dict[str, Any],
    ) -> ScrapedResult:
        from .price_sanity import infer_currency_from_url, normalize_raw_price_string

        style_id = extracted.get("style_id")
        raw_price = normalize_raw_price_string(extracted.get("price") or "")
        price_val, currency = parse_price_string(raw_price)
        if currency is None:
            currency = extracted.get("currency")
        if currency is None or str(currency).lower() == "none":
            currency = infer_currency_from_url(url, raw_price)
        return ScrapedResult(
            url=url, price=price_val, currency=currency,
            stock_status=extracted.get("stock_status", "unknown"),
            raw_price=raw_price or None, style_id=style_id,
            scraped_at=datetime.now(timezone.utc), success=True,
        )

    async def _scrape_with_browser(
        self,
        url: str,
        browser: Browser,
        strategy: ScraperStrategy,
    ) -> ScrapedResult:
        ctx_opts = self._build_context_options(url)
        context: BrowserContext = await browser.new_context(**ctx_opts)
        await context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf,eot}",
            lambda route: route.abort(),
        )
        effective_timeout = (
            self._heavy_site_timeout_ms
            if self.is_heavy_site(url)
            else self._timeout_ms
        )

        try:
            page = await context.new_page()
            page.set_default_timeout(effective_timeout)
            if self._use_stealth:
                await apply_stealth_scripts(page)
            await self._goto_with_fallback(page, url)

            extra_ms = self._extra_wait_ms
            if "farfetch.com" in urlparse(url).netloc.lower():
                extra_ms = max(extra_ms, 5_000)
            if extra_ms > 0:
                wait = (
                    random_wait_ms(500, extra_ms)
                    if self._use_stealth
                    else extra_ms
                )
                await page.wait_for_timeout(wait)

            extracted = await strategy.extract(page)
            if not extracted.get("style_id"):
                from .json_ld_style_id import extract_primary_style_id_from_json_ld
                extracted["style_id"] = await extract_primary_style_id_from_json_ld(page)
            return self._build_result_from_extracted(url, extracted)
        except Exception as e:
            logger.error("Extraction error for %s: %s", url, e, exc_info=True)
            return self._make_error_result(url, e)
        finally:
            await context.close()

    # ------------------------------------------------------------------
    # 複数URL並列スクレイピング
    # ------------------------------------------------------------------

    async def scrape_many_async(
        self,
        urls: list[str],
        concurrency: int = 3,
    ) -> list[ScrapedResult]:
        """複数URLを指定並列数でスクレイピングする。"""
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded(url: str) -> ScrapedResult:
            async with semaphore:
                return await self.scrape_async(url)

        return list(await asyncio.gather(*[_bounded(u) for u in urls]))

    # ------------------------------------------------------------------
    # 同期インターフェース
    # ------------------------------------------------------------------

    def scrape(self, url: str) -> ScrapedResult:
        return run_sync(self.scrape_async(url))

    def scrape_many(self, urls: list[str], concurrency: int = 3) -> list[ScrapedResult]:
        return run_sync(self.scrape_many_async(urls, concurrency=concurrency))

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    @staticmethod
    def _make_error_result(url: str, exc: Optional[Exception]) -> ScrapedResult:
        return ScrapedResult(
            url=url,
            price=None,
            currency=None,
            stock_status="unknown",
            raw_price=None,
            style_id=None,
            scraped_at=datetime.now(timezone.utc),
            success=False,
            error=str(exc) if exc else "unknown error",
        )
