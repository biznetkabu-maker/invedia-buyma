"""
為替レート自動取得モジュール。

frankfurter.app（無料・認証不要・無制限）を使用して最新レートを取得する。
フォールバックとして exchangerate-api.com も対応。

使い方:
    from lib.forex import get_rate, get_rates_for_sheet

    # USD/JPY を1件取得
    rate = get_rate("USD", "JPY")      # → 155.43

    # シートに必要な通貨を一括取得
    rates = get_rates_for_sheet(["USD", "EUR", "GBP"])
    # → {"USD": 155.43, "EUR": 168.21, "GBP": 196.87}

エラーハンドリング:
    - API 失敗時はキャッシュ値を返す（キャッシュなければ None）
    - キャッシュは .forex_cache.json に保存（TTL: 1時間）
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ── 設定 ──────────────────────────────────────────────────────────────────────

_PRIMARY_API = "https://api.frankfurter.app/latest"   # 無料・認証不要・ECB公式レート
_FALLBACK_API = "https://open.er-api.com/v6/latest"   # 1500 req/month 無料枠
_CACHE_FILE = Path(".forex_cache.json")
_CACHE_TTL_SECONDS = 3600   # 1 時間キャッシュ
_REQUEST_TIMEOUT = 10       # タイムアウト秒

# 対応通貨（ISO 4217）
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "CNY", "KRW"}


# ── 公開 API ─────────────────────────────────────────────────────────────────

def get_rate(from_currency: str, to_currency: str = "JPY") -> Optional[float]:
    """指定通貨の最新レートを取得する。

    Args:
        from_currency: 取得元通貨（例: "USD"）
        to_currency: 変換先通貨（default: "JPY"）

    Returns:
        1 from_currency = X to_currency のレート。
        取得失敗時はキャッシュ値、キャッシュもなければ None。
    """
    if from_currency == to_currency:
        return 1.0

    rates = get_all_rates(base=from_currency)
    if rates is None:
        return None
    return rates.get(to_currency)


def get_rates_for_sheet(currencies: list[str], to_currency: str = "JPY") -> dict[str, Optional[float]]:
    """複数通貨の JPY レートを一括取得する。

    シートに登録されている為替欄を自動更新する際に使用する。

    Args:
        currencies: 取得する通貨コードのリスト（例: ["USD", "EUR", "GBP"]）
        to_currency: 変換先通貨（default: "JPY"）

    Returns:
        {"USD": 155.43, "EUR": 168.21, ...}。取得失敗した通貨は None。
    """
    result: dict[str, Optional[float]] = {}

    # JPY ベースで一括取得（1 API コール）
    rates = get_all_rates(base=to_currency)
    if rates:
        for cur in currencies:
            if cur == to_currency:
                result[cur] = 1.0
            elif cur in rates:
                # rates は "JPY → X" の形式なので逆数に変換
                x_per_jpy = rates[cur]
                result[cur] = round(1.0 / x_per_jpy, 4) if x_per_jpy else None
            else:
                result[cur] = None
        return result

    # JPY ベース取得失敗 → 個別に取得
    for cur in currencies:
        result[cur] = get_rate(cur, to_currency)

    return result


def get_all_rates(base: str = "JPY") -> Optional[dict[str, float]]:
    """ベース通貨に対する全通貨レートを取得する。

    Returns:
        {"USD": 0.0064, "EUR": 0.0059, ...} 形式の辞書。
        取得失敗時はキャッシュを返す。キャッシュもなければ None。
    """
    cache = _load_cache()
    cache_key = f"rates_{base}"

    # キャッシュが有効ならそのまま返す
    if _is_cache_valid(cache, cache_key):
        logger.debug("為替レート: キャッシュ使用 (base=%s)", base)
        raw_rates = cache[cache_key].get("rates", {})
        if isinstance(raw_rates, dict):
            return {str(k): float(v) for k, v in raw_rates.items()}
        return None

    # API から取得
    rates = _fetch_from_primary(base) or _fetch_from_fallback(base)

    if rates:
        cache[cache_key] = {
            "rates": rates,
            "fetched_at": time.time(),
            "base": base,
        }
        _save_cache(cache)
        logger.info(
            "為替レート更新: base=%s, %d 通貨取得 (時刻: %s UTC)",
            base, len(rates),
            datetime.now(timezone.utc).strftime("%H:%M"),
        )
        return rates

    # フォールバック: 古いキャッシュを返す
    if cache_key in cache:
        logger.warning(
            "為替API取得失敗。古いキャッシュを使用: base=%s "
            "(%.0f 分前のデータ)",
            base,
            (time.time() - float(str(cache[cache_key].get("fetched_at", 0)))) / 60,
        )
        raw_rates = cache[cache_key].get("rates", {})
        if isinstance(raw_rates, dict):
            return {str(k): float(v) for k, v in raw_rates.items()}
        return None

    logger.error("為替レート取得失敗・キャッシュなし: base=%s", base)
    return None


# ── 内部実装 ─────────────────────────────────────────────────────────────────

def _fetch_from_primary(base: str) -> Optional[dict[str, float]]:
    """Frankfurter API からレートを取得する。"""
    url = f"{_PRIMARY_API}?from={base}"
    try:
        req = Request(url, headers={"User-Agent": "invedia-automation/1.0"})
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            rates: dict[str, float] = data.get("rates", {})
            if rates:
                return rates
    except (URLError, json.JSONDecodeError, KeyError) as e:
        logger.debug("Frankfurter API 失敗: %s", e)
    return None


def _fetch_from_fallback(base: str) -> Optional[dict[str, float]]:
    """open.er-api.com からレートを取得する（フォールバック）。"""
    url = f"{_FALLBACK_API}/{base}"
    try:
        req = Request(url, headers={"User-Agent": "invedia-automation/1.0"})
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            if data.get("result") == "success":
                rates_raw: dict[str, float] = data.get("rates", {})
                return rates_raw
    except (URLError, json.JSONDecodeError, KeyError) as e:
        logger.debug("open.er-api フォールバック失敗: %s", e)
    return None


_CacheDict = dict[str, dict[str, object]]


def _load_cache() -> _CacheDict:
    from lib.file_lock import atomic_json_read
    raw = atomic_json_read(_CACHE_FILE, default={})
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _save_cache(cache: dict) -> None:
    from lib.file_lock import atomic_json_write
    atomic_json_write(_CACHE_FILE, cache)


def _is_cache_valid(cache: _CacheDict, key: str) -> bool:
    if key not in cache:
        return False
    fetched_at = float(str(cache[key].get("fetched_at", 0)))
    return (time.time() - fetched_at) < _CACHE_TTL_SECONDS


# ── シート自動更新ヘルパー ────────────────────────────────────────────────────

# 仕入先ドメイン → 通貨コードの対応表
_DOMAIN_CURRENCY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("USD", ("saksfifthavenue.com", "ssense.com", "neimanmarcus.com")),
    ("GBP", ("harrods.com", "matchesfashion.com", "net-a-porter.com",
             "selfridges.com", "mrporter.com", "harveynichols.com")),
    ("EUR", ("luisaviaroma.com", "farfetch.com", "mytheresa.com",
             "tessabit.com", "giglio.com", "biffi.com", "yoox.com",
             "theoutnet.com", "24s.com")),
)


def _currency_from_url(url: str) -> Optional[str]:
    """仕入れURLのドメインから通貨コードを推定する（不明なら None）。"""
    u = (url or "").lower()
    for currency, domains in _DOMAIN_CURRENCY:
        if any(d in u for d in domains):
            return currency
    return None


def update_sheet_exchange_rates(
    manager,
    currencies: list[str] | None = None,
) -> dict[str, Optional[float]]:
    """シートの全レコードの為替欄をライブレートで更新する。

    Args:
        manager: SheetManager インスタンス
        currencies: 更新対象の通貨コードリスト（None で自動検出）

    Returns:
        更新に使用したレート辞書。
    """

    records = manager.get_all_records()
    if not records:
        return {}

    # シートに存在する通貨を自動検出
    if currencies is None:
        # 為替欄の値から通貨コードを推定する（簡易: 数値なら USD/EUR/GBP から検索）
        currencies = ["USD", "EUR", "GBP", "CAD", "AUD"]

    rates = get_rates_for_sheet(currencies)
    logger.info("為替レート取得: %s", {k: v for k, v in rates.items() if v})

    updated = 0
    for record in records:
        # 各レコードの為替欄を更新（仕入れURLから通貨を推定）
        cur = _currency_from_url(record.仕入れURL)
        if cur is None:
            continue  # 判定できない場合はスキップ

        new_rate = rates.get(cur)
        if new_rate and str(round(new_rate, 2)) != record.為替:
            from dataclasses import replace
            updated_record = replace(record, 為替=str(round(new_rate, 2)))
            manager.update_record(record.商品名, updated_record)
            updated += 1

    logger.info("為替レート更新: %d 件", updated)
    return rates
