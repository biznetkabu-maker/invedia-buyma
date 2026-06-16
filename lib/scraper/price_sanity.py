"""仕入先価格の妥当性チェック・通貨推定。"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def infer_currency_from_url(url: str, raw_price: str = "") -> str:
    """仕入先 URL と価格文字列から通貨を推定する。"""
    u = (url or "").lower()
    raw = raw_price or ""

    if "¥" in raw or "円" in raw or "jpy" in raw.lower():
        return "JPY"
    if "€" in raw or "eur" in raw.lower():
        return "EUR"
    if "£" in raw or "gbp" in raw.lower():
        return "GBP"
    if "$" in raw and "hk$" not in raw.lower():
        return "USD"

    if "farfetch.com/jp" in u or (
        "farfetch.com" in u and "/jp/" in urlparse(url).path.lower()
    ):
        return "JPY"
    if any(d in u for d in (
        "saksfifthavenue.com", "ssense.com", "neimanmarcus.com",
    )):
        return "USD"
    if any(d in u for d in (
        "harrods.com", "matchesfashion.com", "net-a-porter.com",
        "selfridges.com", "mrporter.com", "harveynichols.com",
    )):
        return "GBP"
    return "EUR"


def normalize_raw_price_string(raw: str) -> str:
    """'None473000' など JSON 由来のゴミを除去。"""
    s = (raw or "").strip()
    s = re.sub(r"^none\s*", "", s, flags=re.I)
    return s.strip()


_ITEM_ID_IN_URL = re.compile(r"item-(\d+)", re.I)


def price_matches_url_item_id(url: str, local_price: float) -> bool:
    """URL の item-12345 と同じ数値を価格と誤認していないか。"""
    m = _ITEM_ID_IN_URL.search(url or "")
    if not m:
        return False
    item_id = int(m.group(1))
    p = int(local_price) if local_price == int(local_price) else int(local_price)
    if p == item_id:
        return True
    return bool(len(str(item_id)) >= 6 and str(item_id) in str(p))


def estimate_jpy_cost(
    local_price: float,
    currency: str | None,
    url: str,
    exchange_rate: float,
) -> float:
    """現地価格をおおよそ JPY に換算（簡易）。"""
    cur = (currency or infer_currency_from_url(url)).upper()
    if cur == "JPY":
        return local_price
    if cur == "EUR":
        return local_price * exchange_rate
    if cur == "GBP":
        return local_price * exchange_rate * 1.15
    if cur == "USD":
        return local_price * exchange_rate * 0.92
    return local_price * exchange_rate


def is_plausible_supply_price(
    local_price: float | None,
    currency: str | None,
    url: str,
    buyma_price_jpy: float,
    exchange_rate: float,
    *,
    raw_price: str = "",
) -> bool:
    """利益計算前に明らかな誤取得を弾く。"""
    if local_price is None or local_price <= 0:
        return False
    if price_matches_url_item_id(url, local_price):
        return False
    cur = (currency or infer_currency_from_url(url, raw_price)).upper()
    if cur == "JPY" and (local_price < 2_000 or local_price > 2_500_000):
        return False
    if local_price >= 10_000_000:
        return False
    if raw_price and re.match(r"^none\s*\d", raw_price.strip(), re.I):
        return False
    if (currency or "").upper() == "NONE":
        return False
    if buyma_price_jpy <= 0:
        return True
    jpy = estimate_jpy_cost(local_price, currency, url, exchange_rate)
    ratio = jpy / buyma_price_jpy
    # BUYMA 転売価格は定価よりかなり安いことが多い（JPY 直販は 4 倍超はほぼ誤取得）
    max_ratio = 4.0 if cur == "JPY" else 5.0
    if ratio > max_ratio or ratio < 0.03:
        return False
    # FARFETCH JP で NEXT_DATA 由来の ¥473,000 等（実売価格の数倍）
    return not (cur == "JPY" and buyma_price_jpy < 250000 and jpy >= 350000)


def explain_price_rejection(
    local_price: float,
    currency: str | None,
    url: str,
    buyma_price_jpy: float,
    exchange_rate: float,
    *,
    raw_price: str = "",
) -> str:
    """妥当性チェック失敗時の説明文。"""
    cur = currency or infer_currency_from_url(url, raw_price)
    jpy = estimate_jpy_cost(local_price, currency, url, exchange_rate)
    parts = [f"{cur} {local_price:,.0f}", f"≈¥{jpy:,.0f}"]
    if buyma_price_jpy > 0:
        parts.append(f"売価比{jpy / buyma_price_jpy:.1f}倍")
    if price_matches_url_item_id(url, local_price):
        parts.append("URLの商品IDと一致（誤取得）")
    if raw_price:
        parts.append(f"raw={raw_price[:30]}")
    return "価格が妥当範囲外: " + ", ".join(parts)
