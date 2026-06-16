"""
全 Strategy の接続テスト + 成功/失敗レポート。

使い方:
  # 接続テストのみ（価格抽出なし、高速）
  python3 test_all_strategies.py

  # 価格・在庫の完全抽出テスト（実ブラウザ + ネットワーク必要）
  python3 test_all_strategies.py --full

  # プロキシ使用
  PROXY_SERVER=http://proxy.example.com:8080 python3 test_all_strategies.py

  # 並列数を指定
  python3 test_all_strategies.py --concurrency 3

このスクリプトは GitHub Actions の手動トリガーからも実行できます。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from lib.scraper.engine import PriceScraper
from lib.scraper.proxy import ProxyRotator
from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, random_user_agent, stealth_context_options

logging.basicConfig(
    level=logging.WARNING,  # テスト中は WARNING 以上のみ表示
    format="%(levelname)s: %(message)s",
)


# ---------------------------------------------------------------------------
# テスト対象 URL リスト（各サイトのトップまたは代表的な商品ページ）
# ---------------------------------------------------------------------------

TEST_SITES: list[dict] = [
    # ── 既存 ──────────────────────────────────────────────────────────────
    {
        "site": "SSENSE",
        "category": "既存",
        "url": "https://www.ssense.com/en-us/women/product/bottega-veneta/dark-green-intrecciato-mini-pouch/14965161",
        "domain": "ssense.com",
        "expected_currency": "USD",
    },
    {
        "site": "TESSABIT",
        "category": "既存",
        "url": "https://www.tessabit.com/en/women/bags",
        "domain": "tessabit.com",
        "expected_currency": "EUR",
    },
    # ── 定番 ──────────────────────────────────────────────────────────────
    {
        "site": "FARFETCH",
        "category": "定番",
        "url": "https://www.farfetch.com/shopping/women/gucci-horsebit-1955-shoulder-bag-item-18025673.aspx",
        "domain": "farfetch.com",
        "expected_currency": "USD",
    },
    {
        "site": "MATCHESFASHION",
        "category": "定番",
        "url": "https://www.matchesfashion.com/products/Bottega-Veneta-Intrecciato-leather-coin-purse-1482302",
        "domain": "matchesfashion.com",
        "expected_currency": "GBP",
    },
    {
        "site": "MYTHERESA",
        "category": "定番",
        "url": "https://www.mytheresa.com/en-us/women/handbags",
        "domain": "mytheresa.com",
        "expected_currency": "USD",
    },
    # ── デパート ──────────────────────────────────────────────────────────
    {
        "site": "Selfridges",
        "category": "デパート",
        "url": "https://www.selfridges.com/GB/en/cat/",
        "domain": "selfridges.com",
        "expected_currency": "GBP",
        "heavy": True,
    },
    {
        "site": "Saks Fifth Avenue",
        "category": "デパート",
        "url": "https://www.saksfifthavenue.com/category/handbags.html",
        "domain": "saksfifthavenue.com",
        "expected_currency": "USD",
        "heavy": True,
    },
    {
        "site": "Harrods",
        "category": "デパート",
        "url": "https://www.harrods.com/en-gb/",
        "domain": "harrods.com",
        "expected_currency": "GBP",
        "heavy": True,
    },
    # ── 欧州セレクト ──────────────────────────────────────────────────────
    {
        "site": "LUISAVIAROMA",
        "category": "欧州セレクト",
        "url": "https://www.luisaviaroma.com/en-us/shop/women/bags",
        "domain": "luisaviaroma.com",
        "expected_currency": "USD",
        "heavy": True,
    },
    {
        "site": "GIGLIO",
        "category": "欧州セレクト",
        "url": "https://www.giglio.com/en/women/bags.html",
        "domain": "giglio.com",
        "expected_currency": "EUR",
    },
    {
        "site": "Biffi",
        "category": "欧州セレクト",
        "url": "https://www.biffi.com/en/",
        "domain": "biffi.com",
        "expected_currency": "EUR",
    },
    # ── アウトレット ──────────────────────────────────────────────────────
    {
        "site": "YOOX",
        "category": "アウトレット",
        "url": "https://www.yoox.com/us/women/shoponline/bags_d#/dept=bags&gender=D",
        "domain": "yoox.com",
        "expected_currency": "USD",
    },
    {
        "site": "THE OUTNET",
        "category": "アウトレット",
        "url": "https://www.theoutnet.com/en-us/shop/bags",
        "domain": "theoutnet.com",
        "expected_currency": "USD",
    },
]


# ---------------------------------------------------------------------------
# テスト結果データクラス
# ---------------------------------------------------------------------------

@dataclass
class SiteTestResult:
    site: str
    category: str
    url: str
    success: bool
    elapsed_ms: int
    status_code: int | None = None
    price: float | None = None
    currency: str | None = None
    stock_status: str | None = None
    error: str | None = None

    @property
    def icon(self) -> str:
        return "✅" if self.success else "❌"


# ---------------------------------------------------------------------------
# 接続テスト（価格抽出なし）
# ---------------------------------------------------------------------------

async def _connection_test(
    site: dict,
    timeout_ms: int,
    use_proxy: bool,
    proxy_rotator: ProxyRotator,
) -> SiteTestResult:
    """単一サイトへの接続テストを実行する。"""
    url = site["url"]
    start = time.monotonic()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=LAUNCH_ARGS,
            )
            try:
                ctx_opts = stealth_context_options(user_agent=random_user_agent())
                if use_proxy:
                    proxy = proxy_rotator.next()
                    if proxy:
                        ctx_opts["proxy"] = proxy.to_playwright_proxy()

                context = await browser.new_context(**ctx_opts)
                await context.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2}", lambda r: r.abort())

                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                await apply_stealth_scripts(page)

                response = await page.goto(url, wait_until="domcontentloaded")
                elapsed = int((time.monotonic() - start) * 1000)

                return SiteTestResult(
                    site=site["site"],
                    category=site["category"],
                    url=url,
                    success=response is not None and response.status < 400,
                    elapsed_ms=elapsed,
                    status_code=response.status if response else None,
                )
            finally:
                await browser.close()

    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return SiteTestResult(
            site=site["site"],
            category=site["category"],
            url=url,
            success=False,
            elapsed_ms=elapsed,
            error=str(e)[:120],
        )


# ---------------------------------------------------------------------------
# 完全抽出テスト（価格・在庫まで取得）
# ---------------------------------------------------------------------------

async def _full_extraction_test(
    site: dict,
    scraper: PriceScraper,
) -> SiteTestResult:
    """価格・在庫まで含めた完全抽出テストを実行する。"""
    url = site["url"]
    start = time.monotonic()

    try:
        result = await scraper.scrape_async(url)
        elapsed = int((time.monotonic() - start) * 1000)

        return SiteTestResult(
            site=site["site"],
            category=site["category"],
            url=url,
            success=result.success and result.price is not None,
            elapsed_ms=elapsed,
            price=result.price,
            currency=result.currency,
            stock_status=result.stock_status,
            error=result.error,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return SiteTestResult(
            site=site["site"],
            category=site["category"],
            url=url,
            success=False,
            elapsed_ms=elapsed,
            error=str(e)[:120],
        )


# ---------------------------------------------------------------------------
# レポート表示
# ---------------------------------------------------------------------------

def _print_report(results: list[SiteTestResult], full_mode: bool) -> None:
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sep = "=" * 80
    print(f"\n{sep}")
    print(f"  PriceScraper 接続テストレポート  {'（完全抽出モード）' if full_mode else ''}")
    print(f"  実行日時: {now}")
    print(f"  結果: {passed} / {len(results)} 成功  ({failed} 件失敗)")
    print(sep)

    current_category = ""
    for r in sorted(results, key=lambda x: (x.category, x.site)):
        if r.category != current_category:
            current_category = r.category
            print(f"\n  ── {current_category} ──")

        extra = ""
        if full_mode and r.success:
            price_str = f"{r.currency} {r.price:,.2f}" if r.price else "価格取得不可"
            extra = f" | {price_str} | {r.stock_status}"
        elif r.error:
            extra = f" | ❗ {r.error[:60]}"

        print(
            f"  {r.icon} {r.site:<25} {r.elapsed_ms:>5}ms"
            f"  {('HTTP ' + str(r.status_code)) if r.status_code else '':<10}"
            f"{extra}"
        )

    print(f"\n{sep}")

    # 失敗サイトのサマリー
    failed_sites = [r for r in results if not r.success]
    if failed_sites:
        print("\n  ❌ 失敗サイト一覧:")
        for r in failed_sites:
            print(f"    - {r.site}: {r.error or 'unknown error'}")
    else:
        print("\n  🎉 全サイト接続成功！")

    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> int:
    proxy_rotator = ProxyRotator.from_env()
    timeout_ms = 30_000 if args.full else 15_000

    if args.full:
        scraper = PriceScraper(
            headless=True,
            use_stealth=True,
            max_retries=1,
            proxy_rotator=proxy_rotator,
        )

    semaphore = asyncio.Semaphore(args.concurrency)

    async def _run_one(site: dict) -> SiteTestResult:
        async with semaphore:
            if args.full:
                return await _full_extraction_test(site, scraper)
            return await _connection_test(site, timeout_ms, bool(proxy_rotator), proxy_rotator)

    # 対象サイトのフィルタリング
    sites = TEST_SITES
    if args.site:
        sites = [s for s in sites if args.site.lower() in s["site"].lower()]
        if not sites:
            print(f"❌ サイト '{args.site}' が見つかりません。")
            return 1

    print(f"  {len(sites)} サイトをテスト中... (並列数: {args.concurrency})")

    results = await asyncio.gather(*[_run_one(s) for s in sites])
    _print_report(list(results), full_mode=args.full)

    failed = sum(1 for r in results if not r.success)
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PriceScraper 全Strategy 接続テスト & レポート",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="価格・在庫まで含む完全抽出テストを実行する（時間がかかります）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="同時実行数 (default: 3)",
    )
    parser.add_argument(
        "--site",
        type=str,
        default="",
        help="特定サイトのみテスト (例: --site FARFETCH)",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
