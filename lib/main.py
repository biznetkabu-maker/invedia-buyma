"""
メインロジック: SheetManager と PriceScraper を統合した自動巡回スクリプト。

動作フロー:
  1. スプレッドシートから全商品情報を読み込む
  2. 各商品の「仕入れURL」を PriceScraper で巡回し価格・在庫を取得
  3. 現地価格・為替・BUYMA手数料・関税・国際送料から現在の利益を計算
  4. 在庫・利益率に基づき在庫ステータスを自動判定
     - 在庫切れ              → "停止中"
     - 利益率 < 目標値       → "要確認 (利益率 XX.X%)"
     - 在庫あり & 利益率 OK  → "出品中"
  5. 型番列がある場合は仕入先 style_id と照合（不一致は要確認 + LINE）
  6. 結果をスプレッドシートに書き戻す
  7. サマリーをコンソール出力（GitHub Actions のログに残る）
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.async_compat import run_sync
from lib.config import Config
from lib.forex import get_rates_for_sheet, update_sheet_exchange_rates
from lib.multi_source import BestSourceFinder, BestSourceResult, style_id_consistent_with_buyma
from lib.notification_manager import NotificationManager
from lib.profit_calculator import ProfitBreakdown, try_calculate_profit
from lib.scraper import PriceScraper, ScrapedResult
from lib.scraper.proxy import ProxyRotator
from lib.sheet_manager import ProductRecord, SheetManager

logger = logging.getLogger(__name__)


# ── ステータス定数 ──────────────────────────────────────────────────────────
STATUS_ACTIVE = "出品中"
STATUS_STOPPED = "停止中"
STATUS_WARNING_PREFIX = "要確認"


# ── 商品1件の処理結果 ────────────────────────────────────────────────────────

class ProductResult:
    """1商品の処理結果をまとめるクラス。"""

    def __init__(
        self,
        original: ProductRecord,
        updated: ProductRecord,
        scrape: Optional[ScrapedResult],
        breakdown: Optional[ProfitBreakdown],
        error: Optional[str] = None,
    ) -> None:
        self.original = original
        self.updated = updated
        self.scrape = scrape
        self.breakdown = breakdown
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None and (self.scrape is None or self.scrape.success)


# ── コアビジネスロジック ──────────────────────────────────────────────────────

def is_scrapable_source_url(url: str) -> bool:
    """仕入れ先スクレイプ対象か。BUYMA 商品URLは候補メモ用のため巡回しない。"""
    u = url.strip().lower()
    if not u:
        return False
    if "buyma.com" in u:
        return False
    return True


def determine_status(
    scrape: Optional[ScrapedResult],
    breakdown: Optional[ProfitBreakdown],
    target_profit_rate: float,
) -> str:
    """在庫・利益情報からステータス文字列を決定する。"""
    # スクレイピング失敗 or URL未設定 → ステータス変更しない
    if scrape is None or not scrape.success:
        return ""

    if scrape.stock_status == "out_of_stock":
        return STATUS_STOPPED

    if breakdown is None:
        # 価格情報不足でも在庫はある → 変更なし
        return ""

    if breakdown.profit_rate < target_profit_rate:
        return f"{STATUS_WARNING_PREFIX} (利益率 {breakdown.profit_rate:.1%})"

    if scrape.stock_status == "in_stock":
        return STATUS_ACTIVE

    # unknown の場合はそのまま維持
    return ""



STYLE_ID_WARNING = f"{STATUS_WARNING_PREFIX} (型番不一致)"


def style_id_status_override(
    record: ProductRecord,
    scrape: Optional[ScrapedResult],
    current_status: str,
) -> str:
    """シートの型番と仕入先 style_id が食い違う場合、要確認ステータスを返す。"""
    buyma_sid = (record.型番 or "").strip()
    if not buyma_sid or scrape is None or not scrape.success:
        return current_status
    if style_id_consistent_with_buyma(scrape, buyma_sid):
        return current_status
    # 在庫切れは型番警告より停止を優先
    if current_status == STATUS_STOPPED:
        return current_status
    return STYLE_ID_WARNING


def _check_style_id_mismatches(results: list[ProductResult]) -> None:
    """型番不一致の商品をログ出力し、LINE に通知する。"""
    alerts: list[str] = []
    for result in results:
        buyma_sid = (result.original.型番 or "").strip()
        if not buyma_sid or result.scrape is None or not result.scrape.success:
            continue
        if style_id_consistent_with_buyma(result.scrape, buyma_sid):
            continue
        scraped_sid = result.scrape.style_id or "（未取得）"
        alerts.append(
            f"{result.original.商品名}: シート型番={buyma_sid} / "
            f"仕入先={scraped_sid} (URL: {result.original.仕入れURL[:50]})"
        )

    if not alerts:
        return

    alert_text = (
        f"⚠️ 型番不一致を検出しました ({len(alerts)}件)\n"
        "仕入先ページが別商品の可能性があります。URL・型番を確認してください。\n"
        + "\n".join(f"  - {a}" for a in alerts)
    )
    logger.warning(alert_text)
    try:
        from lib.line_notifier import LINENotifier
        notifier = LINENotifier()
        if notifier.is_configured:
            notifier.send_text(alert_text)
    except Exception:
        logger.debug("LINE通知送信失敗", exc_info=True)

def process_product(
    record: ProductRecord,
    scrape: Optional[ScrapedResult],
    config: Config,
) -> ProductResult:
    """1商品の価格取得 → 利益計算 → ステータス判定 → ProductRecord 更新。

    実際のシート書き込みは行わない（副作用フリー）。
    """
    updated = replace(record)  # shallow copy

    breakdown: Optional[ProfitBreakdown] = None

    if scrape and scrape.success and scrape.price is not None:
        # 現地価格をスクレイピング結果で上書き
        updated.現地価格 = str(scrape.price)

    # 利益計算（価格文字列が揃っている場合のみ）
    breakdown = try_calculate_profit(
        local_price_str=updated.現地価格,
        exchange_rate_str=updated.為替,
        buyma_price_str=updated.BUYMA販売価格,
        customs_rate=config.customs_rate,
        shipping_cost=config.shipping_cost_jpy,
        buyma_fee_rate=config.buyma_fee_rate,
    )
    if breakdown is not None:
        updated.利益額 = str(round(breakdown.profit))

    # ステータス自動判定
    new_status = determine_status(scrape, breakdown, config.target_profit_rate)
    if new_status:
        updated.在庫ステータス = new_status
    updated.在庫ステータス = style_id_status_override(
        record, scrape, updated.在庫ステータス,
    )

    return ProductResult(
        original=record,
        updated=updated,
        scrape=scrape,
        breakdown=breakdown,
    )


# ── サマリー出力 ─────────────────────────────────────────────────────────────

_UNKNOWN_HISTORY_FILE = Path("scraper_unknown_history.json")


def _load_unknown_history() -> dict[str, int]:
    """商品名→連続 unknown 回数のキャッシュを読む。"""
    from lib.file_lock import atomic_json_read
    data = atomic_json_read(_UNKNOWN_HISTORY_FILE, default={})
    return {str(k): int(v) for k, v in data.items()}


def _save_unknown_history(history: dict[str, int]) -> None:
    from lib.file_lock import atomic_json_write
    atomic_json_write(_UNKNOWN_HISTORY_FILE, history)


def _check_scraper_health(results: list[ProductResult], config: Config) -> None:
    """スクレイピング結果を分析し、異常（連続 unknown）を検出して LINE 通知する。

    unknown が `config.unknown_alert_threshold` 回連続した商品は
    「スクレイパー異常の可能性」としてアラートを上げる。
    """
    history = _load_unknown_history()
    alerts: list[str] = []

    for result in results:
        name = result.original.商品名
        if result.scrape is None:
            continue

        if result.scrape.stock_status == "unknown" and not result.scrape.success:
            history[name] = history.get(name, 0) + 1
        elif result.scrape.success and result.scrape.stock_status != "unknown":
            history[name] = 0  # 正常取得でリセット

        if history.get(name, 0) >= config.unknown_alert_threshold:
            alerts.append(
                f"{name}: {history[name]}回連続でステータス不明 (URL: {result.original.仕入れURL[:50]})"
            )

    _save_unknown_history(history)

    if alerts:
        alert_text = (
            f"⚠️ スクレイパー異常を検出しました ({len(alerts)}件)\n"
            + "\n".join(f"  - {a}" for a in alerts)
        )
        logger.warning(alert_text)
        # LINE 通知
        try:
            from lib.line_notifier import LINENotifier
            notifier = LINENotifier()
            if notifier.is_configured:
                notifier.send_text(alert_text)
        except Exception:
            logger.debug("LINE通知送信失敗", exc_info=True)


def print_summary(results: list[ProductResult], config: Config) -> None:
    """処理結果のサマリーをコンソールに出力する。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    active = sum(1 for r in results if r.updated.在庫ステータス == STATUS_ACTIVE)
    stopped = sum(1 for r in results if r.updated.在庫ステータス == STATUS_STOPPED)
    warning = sum(1 for r in results if r.updated.在庫ステータス.startswith(STATUS_WARNING_PREFIX))
    errors = sum(1 for r in results if not r.ok)

    separator = "=" * 60
    logger.info("巡回完了: %s | 対象:%d 出品中:%d 停止:%d 要確認:%d エラー:%d",
                now, len(results), active, stopped, warning, errors)
    print(f"\n{separator}")
    print(f"  巡回完了: {now}")
    print(f"  対象商品: {len(results)} 件")
    print(f"  出品中  : {active} 件")
    print(f"  停止中  : {stopped} 件")
    print(f"  要確認  : {warning} 件")
    print(f"  エラー  : {errors} 件")
    print(separator)
    print(f"  設定 — BUYMA手数料: {config.buyma_fee_rate:.0%} | "
          f"関税: {config.customs_rate:.0%} | "
          f"送料: ¥{config.shipping_cost_jpy:,.0f} | "
          f"目標利益率: {config.target_profit_rate:.0%}")
    print(separator)

    for r in results:
        status_icon = {
            STATUS_ACTIVE: "✅",
            STATUS_STOPPED: "⛔",
        }.get(r.updated.在庫ステータス, "⚠️ " if r.updated.在庫ステータス.startswith(STATUS_WARNING_PREFIX) else "ℹ️ ")

        profit_str = (
            f"¥{r.breakdown.profit:,.0f} ({r.breakdown.profit_rate:.1%})"
            if r.breakdown else "計算不可"
        )
        scrape_price = (
            f"{r.scrape.currency} {r.scrape.price:,.2f}"
            if r.scrape and r.scrape.success and r.scrape.price
            else ("取得失敗" if r.scrape and not r.scrape.success else "URLなし")
        )

        print(
            f"  {status_icon} {r.updated.商品名[:20]:<20} | "
            f"現地価格: {scrape_price:<18} | "
            f"利益: {profit_str:<22} | {r.updated.在庫ステータス}"
        )

    print(separator + "\n")


# ── メインフロー ─────────────────────────────────────────────────────────────

def _get_priority_products(
    records: list[ProductRecord],
    tier: str,
    high_threshold: float,
    medium_threshold: float,
) -> list[tuple[int, ProductRecord]]:
    """優先度ティアに応じた商品インデックス・レコードのペアリストを返す。

    "all"    → 全商品
    "medium" → 利益率 >= medium_threshold
    "high"   → 利益率 >= high_threshold
    """
    if tier == "all":
        return [(i, r) for i, r in enumerate(records)]

    result = []
    for i, r in enumerate(records):
        try:
            profit = float(r.利益額 or 0)
            buyma = float(r.BUYMA販売価格 or 1)
            rate = profit / buyma if buyma > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            rate = 0.0

        if tier == "high" and rate >= high_threshold:
            result.append((i, r))
        elif tier == "medium" and rate >= medium_threshold:
            result.append((i, r))

    return result


async def _load_sheet_data(
    config: Config,
) -> tuple[SheetManager, list[ProductRecord], list[tuple[int, ProductRecord]]]:
    """シートから全商品を読み込み、優先度フィルタリングして返す。"""
    tier = config.effective_priority_tier()
    logger.info(
        "スプレッドシートから商品情報を読み込み中... (優先度ティア: %s, モード: %s)",
        tier, config.operation_mode,
    )
    manager = SheetManager(
        spreadsheet_id=config.spreadsheet_id,
        worksheet_name=config.worksheet_name,
        credentials_path=config.credentials_path,
    )
    manager.ensure_header()

    if config.auto_forex:
        logger.info("  為替レート自動取得中...")
        live_rates = get_rates_for_sheet(["USD", "EUR", "GBP", "CAD", "AUD"])
        logger.info("  為替レート取得: %s", {k: v for k, v in live_rates.items() if v})
        if config.forex_update_sheet:
            update_sheet_exchange_rates(manager)

    all_records = manager.get_all_records()
    logger.info("  %d 件の商品を読み込みました", len(all_records))

    target_indexed = _get_priority_products(
        all_records, tier,
        config.high_profit_threshold,
        config.medium_profit_threshold,
    )
    logger.info(
        "  優先度フィルタ後: %d 件 / 全 %d 件",
        len(target_indexed), len(all_records),
    )
    return manager, all_records, target_indexed


async def _compare_candidate_urls(
    target_indexed: list[tuple[int, ProductRecord]],
    config: Config,
    proxy_rotator: Optional[ProxyRotator],
) -> list[tuple[int, ProductRecord]]:
    """候補URLを比較し、最安値の仕入先URLで target_indexed を更新する。"""
    indexed_with_candidates = [
        (i, r) for i, r in target_indexed
        if r.candidate_url_list() and r.在庫ステータス.strip() != "BUYMA候補"
    ]
    if not indexed_with_candidates:
        return target_indexed

    logger.info("  候補URL比較対象: %d 件", len(indexed_with_candidates))
    finder = BestSourceFinder(
        headless=config.scraper_headless,
        timeout_ms=config.scraper_timeout_ms,
        max_retries=config.scraper_max_retries,
        proxy_rotator=proxy_rotator,
    )
    for idx, record in indexed_with_candidates:
        try:
            buyma_price = float(record.BUYMA販売価格 or 0)
            exchange_rate = float(record.為替 or 0)
            if buyma_price <= 0 or exchange_rate <= 0:
                logger.warning("    [%d] 価格/為替が未設定のため候補URL比較をスキップ", idx)
                continue

            buyma_sid = (record.型番 or "").strip() or None
            best_result: BestSourceResult = await finder.find_best_async(
                candidate_urls=record.candidate_url_list(),
                buyma_price=buyma_price,
                exchange_rate=exchange_rate,
                buyma_style_id=buyma_sid,
                customs_rate=config.customs_rate,
                shipping_cost_jpy=config.shipping_cost_jpy,
                buyma_fee_rate=config.buyma_fee_rate,
            )
            if best_result.best:
                for j, (k, r) in enumerate(target_indexed):
                    if k == idx:
                        new_r = replace(r, 仕入れURL=best_result.best.url)
                        target_indexed[j] = (k, new_r)
                        logger.info(
                            "    [%d] 仕入先自動選択: %s → 利益率 %s",
                            idx, best_result.best.url[:60],
                            f"{best_result.best.profit_rate:.1%}" if best_result.best.profit_rate else "不明",
                        )
                        break
            else:
                logger.info("    [%d] 在庫ありの仕入先なし: %s", idx, best_result.reason)
        except Exception as e:
            logger.warning("    [%d] 候補URL比較エラー: %s", idx, e)
    return target_indexed


async def _execute_scraping(
    target_indexed: list[tuple[int, ProductRecord]],
    config: Config,
    proxy_rotator: Optional[ProxyRotator],
) -> dict[int, ScrapedResult]:
    """スクレイピング可能なURLを持つ商品を並列スクレイピングする。"""
    indexed_with_url = [
        (i, r) for i, r in target_indexed
        if is_scrapable_source_url(r.仕入れURL)
    ]
    indexed_without_url = [(i, r) for i, r in target_indexed if not r.仕入れURL.strip()]
    logger.info(
        "  スクレイピング対象: %d 件 / URLなし: %d 件",
        len(indexed_with_url), len(indexed_without_url),
    )

    scrape_map: dict[int, ScrapedResult] = {}
    if not indexed_with_url:
        return scrape_map

    scraper = PriceScraper(
        headless=config.scraper_headless,
        timeout_ms=config.scraper_timeout_ms,
        max_retries=config.scraper_max_retries,
        proxy_rotator=proxy_rotator,
    )
    urls = [r.仕入れURL for _, r in indexed_with_url]
    logger.info("  巡回開始 (並列数: %d)...", config.scraper_concurrency)
    scrape_results = await scraper.scrape_many_async(urls, concurrency=config.scraper_concurrency)

    for (idx, _), result in zip(indexed_with_url, scrape_results):
        scrape_map[idx] = result
        if not result.success:
            logger.warning("    [%d] スクレイピング失敗: %s", idx, result.error)
        else:
            sid_note = f" | ID={result.style_id}" if result.style_id else ""
            logger.info(
                "    [%d] 取得OK — %s %s | %s%s",
                idx, result.currency or "", result.price or "N/A",
                result.stock_status, sid_note,
            )
    return scrape_map


def _write_results_to_sheet(
    manager: SheetManager,
    results: list[ProductResult],
) -> None:
    """処理結果をスプレッドシートに書き戻す。"""
    logger.info("スプレッドシートに書き戻し中...")
    write_errors = 0
    for result in results:
        if result.updated == result.original:
            continue
        try:
            ok = manager.update_record(result.original.商品名, result.updated)
            if not ok:
                logger.warning("  更新対象が見つかりません: %s", result.original.商品名)
        except Exception as e:
            logger.error("  書き戻し失敗 [%s]: %s", result.original.商品名, e)
            write_errors += 1
    logger.info(
        "  書き戻し完了 (更新: %d 件 / エラー: %d 件)",
        sum(1 for r in results if r.updated != r.original),
        write_errors,
    )


def _send_notifications(results: list[ProductResult]) -> None:
    """お宝商品の通知（LINE + オプションで自動出品）。"""
    notification_mgr = NotificationManager(
        profit_threshold=float(os.environ.get("LINE_PROFIT_THRESHOLD", "30000")),
        auto_list_grade=os.environ.get("AUTO_LIST_GRADE", ""),
        enable_image_processing=os.environ.get("ENABLE_IMAGE_PROCESSING", "").lower() == "true",
    )
    event = notification_mgr.process(results)
    logger.info(
        "通知処理: 検出 %d 件 / 新規 %d 件 / 通知送信 %s / 自動出品 %d 件",
        event.detected_count, event.new_count,
        "OK" if event.notified else "（LINE未設定）",
        event.listed_count,
    )


async def run(config: Config) -> list[ProductResult]:
    """メイン処理を非同期で実行する。"""

    # 1. シートから全商品読み込み + 為替取得
    manager, all_records, target_indexed = await _load_sheet_data(config)
    if not all_records:
        logger.warning("商品データが空です。処理を終了します。")
        return []

    # 2. プロキシ設定 + 候補URL比較
    proxy_rotator = ProxyRotator.from_env()
    if proxy_rotator:
        logger.info("  プロキシ使用: %d 台", len(proxy_rotator))
    target_indexed = await _compare_candidate_urls(target_indexed, config, proxy_rotator)

    # 3. 並列スクレイピング
    scrape_map = await _execute_scraping(target_indexed, config, proxy_rotator)

    # 4. 利益計算 + ステータス判定
    logger.info("利益計算・ステータス判定中...")
    results: list[ProductResult] = []
    for idx, record in target_indexed:
        scrape = scrape_map.get(idx)
        result = process_product(record, scrape, config)
        results.append(result)

    # 5. スクレイパー異常検知
    _check_scraper_health(results, config)
    _check_style_id_mismatches(results)

    # 6. スプレッドシートに書き戻す
    _write_results_to_sheet(manager, results)

    # 7. お宝商品の通知
    _send_notifications(results)

    # 8. スクレイプメトリクスのサマリー出力
    from lib.logging_config import get_metrics
    metrics = get_metrics()
    if metrics.sites:
        metrics.log_summary()

    return results


def main() -> int:
    """エントリーポイント。終了コードを返す（0=正常, 1=エラー）。"""
    from lib.logging_config import setup_logging

    setup_logging(level=logging.INFO)
    config = Config.from_env()

    try:
        # 設定検証
        errors = config.validate()
        if errors:
            for e in errors:
                logger.error("設定エラー: %s", e)
            return 1

        logger.info(
            "設定確認 — スプレッドシートID: %s | シート: %s",
            config.spreadsheet_id,
            config.worksheet_name,
        )

        # メイン処理
        results = run_sync(run(config))

        # ── 6. サマリー出力 ──────────────────────────────────────────────────
        if results:
            print_summary(results, config)

        return 0

    except KeyboardInterrupt:
        logger.info("中断されました")
        return 0
    except Exception as e:
        logger.exception("予期しないエラーが発生しました: %s", e)
        return 1
    finally:
        config.cleanup()


if __name__ == "__main__":
    sys.exit(main())
