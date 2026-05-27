"""
複数仕入先URL比較モジュール。

同一商品に対して複数の仕入先候補URLを並列スクレイプし、
「在庫あり × 最安値（= 最高利益率）」の仕入先を自動選択する。

使い方:
    from lib.multi_source import BestSourceFinder

    finder = BestSourceFinder()
    result = finder.find_best(
        candidate_urls=[
            "https://www.ssense.com/en-us/women/product/celine/xxx",
            "https://www.net-a-porter.com/en-us/shop/product/celine/yyy",
            "https://www.24s.com/en-us/celine-zzz",
        ],
        buyma_price=210_000,
        exchange_rate=155.0,
    )
    if result.best:
        print(f"最安値: {result.best.url}")
        print(f"現地価格: {result.best.currency} {result.best.price}")
        print(f"実質利益率: {result.best.profit_rate:.1%}")

選定ロジック:
    1. 全候補URLを並列スクレイプ
    2. stock_status == "in_stock" の候補に絞り込む
    3. FXバッファ込みの実質利益率が最大のものを選択
    4. 在庫ありが1件もない場合は best=None を返す
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from lib.profit_calculator import ProfitBreakdown, calculate_profit
from lib.scraper import PriceScraper
from lib.scraper.models import ScrapedResult
from lib.scraper.proxy import ProxyRotator
from lib.style_id_utils import scraped_matches_buyma_style

if TYPE_CHECKING:
    from lib.product_identity import MatchScore

logger = logging.getLogger(__name__)


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class SourceCandidate:
    """1つの仕入先URLのスクレイピング結果と利益計算の組み合わせ。"""

    url: str
    price: Optional[float]
    currency: Optional[str]
    stock_status: str           # "in_stock" / "out_of_stock" / "unknown"
    jpy_cost: Optional[float]   # 現地価格 × 為替（FXバッファ込み）
    profit: Optional[float]
    profit_rate: Optional[float]
    breakdown: Optional[ProfitBreakdown]
    style_id: Optional[str] = None   # 仕入先ページ由来（JSON-LD sku 等）
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """在庫あり かつ 価格取得済み かつ 利益がプラス。"""
        return (
            self.stock_status == "in_stock"
            and self.price is not None
            and self.profit is not None
            and self.profit > 0
        )

    def summary(self) -> str:
        if self.price:
            cur = self.currency or "?"
            price_str = f"{cur} {self.price:,.2f}"
        else:
            price_str = "取得失敗"
        profit_str = (
            f"¥{self.profit:,.0f} ({self.profit_rate:.1%})"
            if self.profit is not None else "計算不可"
        )
        status_icon = {"in_stock": "✅", "out_of_stock": "⛔", "unknown": "❓"}.get(
            self.stock_status, "❓"
        )
        sid_str = f" | ID: {self.style_id}" if self.style_id else ""
        err_str = f" | {self.error}" if self.error else ""
        shown = self.url if len(self.url) <= 88 else f"{self.url[:85]}..."
        return (
            f"{status_icon} [{self.stock_status}] {shown} | "
            f"価格: {price_str} | 利益: {profit_str}{sid_str}{err_str}"
        )


@dataclass
class BestSourceResult:
    """複数候補URLを比較した結果。"""

    best: Optional[SourceCandidate]         # 最優良候補（None = 在庫あり候補なし）
    all_candidates: list[SourceCandidate]
    reason: str                             # 選定理由または不選定理由
    match_score: Optional["MatchScore"] = None  # product_identity（選定後に付与）

    @property
    def in_stock_count(self) -> int:
        return sum(1 for c in self.all_candidates if c.stock_status == "in_stock")

    @property
    def cheapest_available(self) -> Optional[SourceCandidate]:
        """在庫ありの中で最安値（現地価格が最小）の候補を返す。"""
        avail = [c for c in self.all_candidates if c.is_available]
        if not avail:
            return None
        return min(avail, key=lambda c: c.price or float("inf"))

    def summary(self) -> str:
        lines = [
            f"比較結果: {len(self.all_candidates)}件中 在庫あり{self.in_stock_count}件",
            f"選定理由: {self.reason}",
        ]
        if self.best:
            lines.append(f"  → 選定: {self.best.summary()}")
        else:
            lines.append("  → 在庫ありの仕入先が見つかりませんでした")
        lines.append("  全候補:")
        for c in self.all_candidates:
            lines.append(f"    {c.summary()}")
        return "\n".join(lines)


# ============================================================================
# BestSourceFinder
# ============================================================================

class BestSourceFinder:
    """複数の仕入先候補URLを並列スクレイプし、最優良ソースを返すクラス。

    選定基準:
        1. stock_status == "in_stock" を必須条件とする
        2. FXバッファ込みの実質利益率が最高の候補を選ぶ
           （利益率が同じ場合は現地価格が低い方を優先）

    Args:
        headless: ヘッドレスモードで実行するか（default: True）
        timeout_ms: 1サイトあたりのタイムアウト ms（default: 30000）
        max_retries: 失敗時のリトライ回数（default: 1）
        proxy_rotator: プロキシローテーター（None で直接接続）
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30_000,
        max_retries: int = 1,
        proxy_rotator: Optional[ProxyRotator] = None,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._max_retries = max_retries
        self._proxy_rotator = proxy_rotator

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------

    def find_best(
        self,
        candidate_urls: list[str],
        buyma_price: float,
        exchange_rate: float,
        *,
        buyma_style_id: Optional[str] = None,
        customs_rate: float = 0.10,
        shipping_cost_jpy: float = 2000.0,
        buyma_fee_rate: float = 0.077,
        fx_buffer_rate: float = 0.03,
    ) -> BestSourceResult:
        """候補URLリストを並列スクレイプし、最優良仕入先を返す（同期版）。"""
        return asyncio.run(
            self.find_best_async(
                candidate_urls=candidate_urls,
                buyma_price=buyma_price,
                exchange_rate=exchange_rate,
                buyma_style_id=buyma_style_id,
                customs_rate=customs_rate,
                shipping_cost_jpy=shipping_cost_jpy,
                buyma_fee_rate=buyma_fee_rate,
                fx_buffer_rate=fx_buffer_rate,
            )
        )

    async def find_best_async(
        self,
        candidate_urls: list[str],
        buyma_price: float,
        exchange_rate: float,
        *,
        buyma_style_id: Optional[str] = None,
        customs_rate: float = 0.10,
        shipping_cost_jpy: float = 2000.0,
        buyma_fee_rate: float = 0.077,
        fx_buffer_rate: float = 0.03,
    ) -> BestSourceResult:
        """候補URLリストを並列スクレイプし、最優良仕入先を返す（非同期版）。"""
        if not candidate_urls:
            return BestSourceResult(
                best=None, all_candidates=[], reason="候補URLが指定されていません"
            )

        from lib.supply_search_utils import is_valid_farfetch_product_url

        scrape_urls: list[str] = []
        for u in candidate_urls:
            if "farfetch.com" in u.lower() and not is_valid_farfetch_product_url(u):
                logger.warning("skip invalid FARFETCH URL: %s", u)
                continue
            scrape_urls.append(u)
        if not scrape_urls:
            return BestSourceResult(
                best=None,
                all_candidates=[],
                reason="有効な仕入先URLがありません（FARFETCH slug 不正等）",
            )
        candidate_urls = scrape_urls

        logger.info(
            "BestSourceFinder: %d件の候補URLを並列スクレイプ開始", len(candidate_urls)
        )

        # 並列スクレイピング
        scraper = PriceScraper(
            headless=self._headless,
            timeout_ms=min(self._timeout_ms, 35_000),
            heavy_site_timeout_ms=self._timeout_ms,
            max_retries=self._max_retries,
            proxy_rotator=self._proxy_rotator or ProxyRotator.from_env(),
        )
        scrape_results: list[ScrapedResult] = await scraper.scrape_many_async(
            candidate_urls, concurrency=min(len(candidate_urls), 5)
        )

        # 利益計算
        effective_rate = exchange_rate * (1 + fx_buffer_rate)
        candidates: list[SourceCandidate] = []

        for url, scrape in zip(candidate_urls, scrape_results):
            candidate = self._build_candidate(
                url=url,
                scrape=scrape,
                buyma_price=buyma_price,
                effective_rate=effective_rate,
                customs_rate=customs_rate,
                shipping_cost_jpy=shipping_cost_jpy,
                buyma_fee_rate=buyma_fee_rate,
            )
            candidates.append(candidate)
            logger.info("  %s", candidate.summary())

        # 最優良候補を選択（buyma_style_id 指定時は型番一致のみ）
        best, reason = self._select_best(candidates, buyma_style_id=buyma_style_id)
        logger.info(
            "BestSourceFinder: 選定結果 → %s | %s",
            best.url[:60] if best else "なし",
            reason,
        )

        match_score = _compute_match_score(best, buyma_style_id, reason)

        return BestSourceResult(
            best=best,
            all_candidates=candidates,
            reason=reason,
            match_score=match_score,
        )

    # ------------------------------------------------------------------
    # 内部ロジック
    # ------------------------------------------------------------------

    @staticmethod
    def _build_candidate(
        url: str,
        scrape: ScrapedResult,
        buyma_price: float,
        effective_rate: float,
        customs_rate: float,
        shipping_cost_jpy: float,
        buyma_fee_rate: float,
    ) -> SourceCandidate:
        """ScrapedResult と利益計算を組み合わせて SourceCandidate を生成する。"""
        from lib.scraper.price_sanity import explain_price_rejection, is_plausible_supply_price

        if not scrape.success or scrape.price is None:
            err = (scrape.error or "価格をページから取得できませんでした")[:160]
            if scrape.raw_price:
                err = f"{err}（raw: {scrape.raw_price[:40]}）"
            return SourceCandidate(
                url=url,
                price=None,
                currency=scrape.currency,
                stock_status=scrape.stock_status,
                jpy_cost=None,
                profit=None,
                profit_rate=None,
                breakdown=None,
                style_id=scrape.style_id,
                error=err,
            )

        currency = scrape.currency
        if not is_plausible_supply_price(
            scrape.price,
            currency,
            url,
            buyma_price,
            effective_rate,
            raw_price=scrape.raw_price or "",
        ):
            return SourceCandidate(
                url=url,
                price=None,
                currency=currency,
                stock_status=scrape.stock_status,
                jpy_cost=None,
                profit=None,
                profit_rate=None,
                breakdown=None,
                style_id=scrape.style_id,
                error=explain_price_rejection(
                    scrape.price,
                    currency,
                    url,
                    buyma_price,
                    effective_rate,
                    raw_price=scrape.raw_price or "",
                )[:200],
            )

        try:
            breakdown = calculate_profit(
                local_price=scrape.price,
                exchange_rate=effective_rate,
                buyma_price=buyma_price,
                customs_rate=customs_rate,
                shipping_cost=shipping_cost_jpy,
                buyma_fee_rate=buyma_fee_rate,
            )
            return SourceCandidate(
                url=url,
                price=scrape.price,
                currency=scrape.currency,
                stock_status=scrape.stock_status,
                jpy_cost=breakdown.jpy_cost,
                profit=breakdown.profit,
                profit_rate=breakdown.profit_rate,
                breakdown=breakdown,
                style_id=scrape.style_id,
            )
        except Exception as e:
            return SourceCandidate(
                url=url,
                price=scrape.price,
                currency=scrape.currency,
                stock_status=scrape.stock_status,
                jpy_cost=None,
                profit=None,
                profit_rate=None,
                breakdown=None,
                style_id=scrape.style_id,
                error=str(e),
            )

    @staticmethod
    def _select_best(
        candidates: list[SourceCandidate],
        buyma_style_id: Optional[str] = None,
    ) -> tuple[Optional[SourceCandidate], str]:
        """利用可能な候補から最優良を選ぶ。

        buyma_style_id が指定されている場合、型番が一致する候補のみ選定対象とする。

        Returns:
            (best_candidate_or_None, reason_string)
        """
        from lib.supply_search_utils import style_id_for_matching

        buyma_sid = style_id_for_matching(buyma_style_id or "", "") or None
        available = [c for c in candidates if c.is_available]

        if buyma_sid:
            style_ok = [
                c for c in available
                if scraped_matches_buyma_style(c.style_id, buyma_sid)
            ]
            style_rejected = len(available) - len(style_ok)
            available = style_ok
            if not available:
                out_of_stock = sum(1 for c in candidates if c.stock_status == "out_of_stock")
                unknown = sum(1 for c in candidates if c.stock_status == "unknown")
                errors = sum(1 for c in candidates if c.error)
                return None, (
                    f"型番「{buyma_sid}」と一致する在庫あり候補なし "
                    f"（利益OKだが型番不一致: {style_rejected}件 / "
                    f"在庫切れ: {out_of_stock}件 / 不明: {unknown}件 / エラー: {errors}件）"
                )

        if not available:
            out_of_stock = sum(1 for c in candidates if c.stock_status == "out_of_stock")
            unknown = sum(1 for c in candidates if c.stock_status == "unknown")
            errors = sum(1 for c in candidates if c.error)
            return None, (
                f"在庫ありの仕入先なし "
                f"（在庫切れ: {out_of_stock}件 / 不明: {unknown}件 / エラー: {errors}件）"
            )

        # 利益率最大 → 同率なら現地価格最小
        best = max(available, key=lambda c: (c.profit_rate or 0, -(c.price or float("inf"))))
        reason = (
            f"{len(available)}件の在庫あり候補中 利益率最大 "
            f"({best.profit_rate:.1%}) — {best.currency} {best.price:,.2f}"
        )
        if buyma_sid:
            reason += f" / 型番「{buyma_sid}」一致"
        return best, reason

def _compute_match_score(
    best: Optional[SourceCandidate],
    buyma_style_id: Optional[str],
    reason: str,
) -> "MatchScore":
    """最優良候補の有無に応じて MatchScore を生成する。"""
    from lib.product_identity import (
        VariantKey,
        score_when_no_supply,
        summarize_best_source_result,
    )

    variant = VariantKey.resolve(sheet_style_id=buyma_style_id or "")
    if best and best.price is not None and not best.error:
        price_note = f"{best.currency or '?'} {best.price:,.2f}"
        if best.profit_rate is not None:
            price_note += f" 利益率{best.profit_rate:.1%}"
        return summarize_best_source_result(
            variant,
            best_url=best.url,
            best_style_id=best.style_id,
            best_stock=best.stock_status,
            best_price_ok=True,
            best_price_note=price_note[:160],
        )
    if best:
        return summarize_best_source_result(
            variant,
            best_url=best.url,
            best_style_id=best.style_id,
            best_stock=best.stock_status,
            best_price_ok=False,
            best_price_note=(best.error or "価格未取得")[:160],
        )
    return score_when_no_supply(variant, reason=reason[:120])


# ============================================================================
# P3: 価格マルチソース投票
# ============================================================================

@dataclass
class PriceVote:
    """1つの仕入先が報告した価格票。"""

    url: str
    price: float
    currency: str
    source_site: str  # e.g. "ssense", "farfetch"

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.url).hostname or self.source_site


@dataclass
class PriceConsensus:
    """P3 投票の集計結果。"""

    consensus_price: float
    currency: str
    votes: list[PriceVote]
    outliers: list[PriceVote]
    confidence: float  # 0.0 ~ 1.0
    method: str  # "median", "single", "unanimous"

    @property
    def vote_count(self) -> int:
        return len(self.votes)

    @property
    def outlier_count(self) -> int:
        return len(self.outliers)

    def summary(self) -> str:
        return (
            f"P3: {self.currency} {self.consensus_price:,.2f} "
            f"(信頼度 {self.confidence:.0%}, {self.vote_count}票, "
            f"外れ値{self.outlier_count}件, 方式: {self.method})"
        )


def compute_price_consensus(
    candidates: list[SourceCandidate],
    *,
    outlier_threshold: float = 0.15,
) -> Optional[PriceConsensus]:
    """複数の SourceCandidate から価格コンセンサスを計算する。

    同一通貨で価格取得済み・在庫ありの候補から投票を集め、
    中央値を基準として外れ値（±threshold 以上の乖離）を除外し、
    合意価格と信頼度を返す。

    Args:
        candidates: SourceCandidate のリスト
        outlier_threshold: 外れ値の閾値（中央値からの乖離率、デフォルト 15%）

    Returns:
        PriceConsensus or None（有効な投票が 0 件の場合）
    """
    import statistics

    votes: list[PriceVote] = []
    for c in candidates:
        if c.price is not None and c.currency and c.stock_status == "in_stock":
            site = _extract_site_name(c.url)
            votes.append(PriceVote(
                url=c.url,
                price=c.price,
                currency=c.currency,
                source_site=site,
            ))

    if not votes:
        return None

    # 通貨別にグループ化し、最多通貨を採用
    currency_groups: dict[str, list[PriceVote]] = {}
    for v in votes:
        currency_groups.setdefault(v.currency, []).append(v)
    primary_currency = max(currency_groups, key=lambda k: len(currency_groups[k]))
    primary_votes = currency_groups[primary_currency]

    if len(primary_votes) == 1:
        return PriceConsensus(
            consensus_price=primary_votes[0].price,
            currency=primary_currency,
            votes=primary_votes,
            outliers=[],
            confidence=0.5,
            method="single",
        )

    prices = [v.price for v in primary_votes]
    median_price = statistics.median(prices)

    inliers, outliers = _split_outliers(primary_votes, median_price, outlier_threshold)
    consensus_price = statistics.median([v.price for v in inliers])
    method, confidence = _consensus_confidence(inliers, outliers, consensus_price)

    return PriceConsensus(
        consensus_price=consensus_price,
        currency=primary_currency,
        votes=inliers,
        outliers=outliers,
        confidence=round(confidence, 3),
        method=method,
    )


def _split_outliers(
    votes: list[PriceVote], median_price: float, threshold: float,
) -> tuple[list[PriceVote], list[PriceVote]]:
    """投票を中央値からの乖離率で inlier / outlier に分類する。"""
    inliers: list[PriceVote] = []
    outliers: list[PriceVote] = []
    for v in votes:
        deviation = abs(v.price - median_price) / median_price if median_price else 0
        if deviation <= threshold:
            inliers.append(v)
        else:
            outliers.append(v)
    if not inliers:
        return votes, []
    return inliers, outliers


def _consensus_confidence(
    inliers: list[PriceVote],
    outliers: list[PriceVote],
    consensus_price: float,
) -> tuple[str, float]:
    """合意方式と信頼度を算出する。"""
    if not outliers and len(set(round(v.price, 2) for v in inliers)) == 1:
        return "unanimous", 1.0

    inlier_prices = [v.price for v in inliers]
    if len(inlier_prices) >= 2:
        spread = max(inlier_prices) - min(inlier_prices)
        relative_spread = spread / consensus_price if consensus_price else 0
        confidence = max(0.5, min(1.0, 1.0 - relative_spread))
    else:
        confidence = 0.6
    if outliers:
        confidence *= max(0.7, 1.0 - 0.1 * len(outliers))
    return "median", confidence


def _extract_site_name(url: str) -> str:
    """URL からサイト名を抽出する。"""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    for name in ("ssense", "farfetch", "mytheresa", "net-a-porter", "24s",
                 "harrods", "selfridges", "saks", "neiman", "mr porter",
                 "yoox", "theoutnet", "biffi", "tessabit", "giglio",
                 "luisaviaroma", "matches", "harvey"):
        if name.replace("-", "") in host.replace("-", ""):
            return name
    return host


def style_id_consistent_with_buyma(
    scrape: ScrapedResult,
    buyma_style_id: Optional[str],
) -> bool:
    """供給側 ScrapedResult.style_id と BUYMA 側の型番が一致するか。

    buyma_style_id が空のときは検証せず True（シート未入力など）。
    """
    if not buyma_style_id or not buyma_style_id.strip():
        return True
    return scraped_matches_buyma_style(scrape.style_id, buyma_style_id.strip())

