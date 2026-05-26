"""構造化ログ設定 + スクレイプメトリクス収集。

使い方:
    from lib.logging_config import setup_logging, get_metrics, reset_metrics

    setup_logging(json_format=True)  # JSON 形式のログ出力
    setup_logging(json_format=False) # 従来のテキスト形式

メトリクス:
    from lib.logging_config import record_scrape, get_metrics

    record_scrape("farfetch.com", success=True, response_time=1.23)
    metrics = get_metrics()
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """JSON 形式のログフォーマッター。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "_extra", None)
        if extra:
            entry["extra"] = extra
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(
    *,
    json_format: bool = False,
    level: int = logging.INFO,
) -> None:
    """ルートロガーを設定する。

    Args:
        json_format: True で JSON 形式、False で従来のテキスト形式。
        level: ログレベル。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 既存ハンドラを削除して二重出力を防ぐ
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)


@dataclass
class SiteMetrics:
    """サイト別スクレイプメトリクス。"""

    site: str
    total: int = 0
    success: int = 0
    failure: int = 0
    total_response_time: float = 0.0
    min_response_time: float = float("inf")
    max_response_time: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0

    @property
    def avg_response_time(self) -> float:
        return self.total_response_time / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "total": self.total,
            "success": self.success,
            "failure": self.failure,
            "success_rate": round(self.success_rate, 3),
            "avg_response_time": round(self.avg_response_time, 3),
            "min_response_time": round(self.min_response_time, 3) if self.min_response_time != float("inf") else 0.0,
            "max_response_time": round(self.max_response_time, 3),
        }


@dataclass
class ScrapeMetrics:
    """全体スクレイプメトリクスの集約。"""

    sites: dict[str, SiteMetrics] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)

    def record(
        self, site: str, *, success: bool, response_time: float = 0.0
    ) -> None:
        if site not in self.sites:
            self.sites[site] = SiteMetrics(site=site)
        m = self.sites[site]
        m.total += 1
        if success:
            m.success += 1
        else:
            m.failure += 1
        m.total_response_time += response_time
        if response_time > 0:
            m.min_response_time = min(m.min_response_time, response_time)
            m.max_response_time = max(m.max_response_time, response_time)

    def summary(self) -> dict:
        elapsed = time.time() - self.start_time
        total = sum(m.total for m in self.sites.values())
        success = sum(m.success for m in self.sites.values())
        return {
            "elapsed_seconds": round(elapsed, 1),
            "total_scrapes": total,
            "total_success": success,
            "total_failure": total - success,
            "overall_success_rate": round(success / total, 3) if total > 0 else 0.0,
            "sites": [m.to_dict() for m in sorted(self.sites.values(), key=lambda x: x.site)],
        }

    def log_summary(self) -> None:
        s = self.summary()
        logger = logging.getLogger("scrape_metrics")
        logger.info(
            "Scrape summary: %d/%d success (%.0f%%) in %.1fs",
            s["total_success"],
            s["total_scrapes"],
            s["overall_success_rate"] * 100,
            s["elapsed_seconds"],
        )
        for site in s["sites"]:
            logger.info(
                "  %s: %d/%d (%.0f%%) avg=%.1fs",
                site["site"],
                site["success"],
                site["total"],
                site["success_rate"] * 100,
                site["avg_response_time"],
            )


# グローバルメトリクスインスタンス
_metrics = ScrapeMetrics()


def record_scrape(
    site: str, *, success: bool, response_time: float = 0.0
) -> None:
    """スクレイプ結果を記録する。"""
    _metrics.record(site, success=success, response_time=response_time)


def get_metrics() -> ScrapeMetrics:
    """現在のメトリクスインスタンスを返す。"""
    return _metrics


def reset_metrics() -> None:
    """メトリクスをリセットする。"""
    global _metrics
    _metrics = ScrapeMetrics()
