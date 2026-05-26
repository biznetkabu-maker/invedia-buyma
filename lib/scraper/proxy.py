"""プロキシ管理モジュール。

Bright Data・Smartproxy・カスタムプロキシをサポートし、
複数プロキシのローテーション（ランダム / ラウンドロビン）を提供する。

環境変数による設定:
  単一プロキシ:
    PROXY_SERVER   = http://proxy.example.com:22225
    PROXY_USERNAME = username
    PROXY_PASSWORD = password

  複数プロキシ（カンマ区切り URL リスト）:
    PROXY_LIST     = http://user1:pass1@host1:port,http://user2:pass2@host2:port
    PROXY_ROTATION = random  # または roundrobin

  Bright Data 専用:
    BRIGHTDATA_CUSTOMER  = lum-customer-XXXXX
    BRIGHTDATA_ZONE      = residential
    BRIGHTDATA_PASSWORD  = YOUR_PASSWORD
    # → http://lum-customer-XXXXX-zone-residential:PASSWORD@zproxy.lum-superproxy.io:22225

  Smartproxy 専用:
    SMARTPROXY_USER     = user.proxy
    SMARTPROXY_PASSWORD = password
    SMARTPROXY_HOST     = gate.smartproxy.com
    SMARTPROXY_PORT     = 7000
    # → http://user.proxy:password@gate.smartproxy.com:7000
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """1つのプロキシサーバーの設定を保持するデータクラス。"""

    server: str                  # 例: "http://proxy.example.com:22225"
    username: str = ""
    password: str = ""

    def to_playwright_proxy(self) -> dict:
        """Playwright の `browser.new_context(proxy=...)` に渡す辞書を返す。"""
        config: dict = {"server": self.server}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config

    @classmethod
    def from_url(cls, url: str) -> "ProxyConfig":
        """'http://user:pass@host:port' 形式の URL から ProxyConfig を生成する。"""
        parsed = urlparse(url)
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return cls(
            server=server,
            username=parsed.username or "",
            password=parsed.password or "",
        )

    @classmethod
    def brightdata(
        cls,
        customer: str,
        zone: str,
        password: str,
        country: str = "",
        host: str = "zproxy.lum-superproxy.io",
        port: int = 22225,
    ) -> "ProxyConfig":
        """Bright Data (旧 Luminati) 形式の ProxyConfig を生成する。

        Args:
            customer: lum-customer-XXXXX 形式の顧客ID。
            zone: ゾーン名（例: "residential", "datacenter"）。
            password: Bright Data のパスワード。
            country: 国コード（例: "jp", "us"）。省略で指定なし。
            host: プロキシホスト名。
            port: ポート番号。
        """
        country_suffix = f"-country-{country}" if country else ""
        username = f"{customer}-zone-{zone}{country_suffix}"
        return cls(
            server=f"http://{host}:{port}",
            username=username,
            password=password,
        )

    @classmethod
    def smartproxy(
        cls,
        user: str,
        password: str,
        host: str = "gate.smartproxy.com",
        port: int = 7000,
    ) -> "ProxyConfig":
        """Smartproxy 形式の ProxyConfig を生成する。"""
        return cls(
            server=f"http://{host}:{port}",
            username=user,
            password=password,
        )

    def __repr__(self) -> str:
        parsed = urlparse(self.server)
        return f"ProxyConfig(server={parsed.hostname}:{parsed.port}, user={self.username or '(none)'})"


class ProxyRotator:
    """複数の ProxyConfig をローテーションして返すクラス。

    Args:
        proxies: ProxyConfig のリスト。空の場合はプロキシなし動作。
        strategy: "random"（デフォルト）または "roundrobin"。
    """

    def __init__(
        self,
        proxies: list[ProxyConfig] | None = None,
        strategy: str = "random",
        *,
        fallback_direct: bool = True,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self._proxies: list[ProxyConfig] = proxies or []
        self._strategy = strategy
        self._index = 0
        self._fallback_direct = fallback_direct
        self._cooldown_seconds = cooldown_seconds
        self._fail_times: dict[str, float] = {}
        self._fail_counts: dict[str, int] = {}

    def next(self) -> Optional[ProxyConfig]:
        """次のプロキシを返す。プロキシ未設定の場合は None を返す。

        ヘルスチェック結果を考慮し、不健全なプロキシをスキップする。
        全プロキシが不健全でフォールバックが有効な場合は None（直接接続）を返す。
        """
        if not self._proxies:
            return None

        healthy = [p for p in self._proxies if self._is_proxy_healthy(p)]
        if not healthy:
            if self._fallback_direct:
                logger.warning("全プロキシが不健全 → 直接接続にフォールバック")
                return None
            healthy = self._proxies

        if self._strategy == "roundrobin":
            proxy = healthy[self._index % len(healthy)]
            self._index += 1
            return proxy
        return random.choice(healthy)

    def _is_proxy_healthy(self, proxy: ProxyConfig) -> bool:
        """プロキシが現在健全（クールダウン期間外）かどうかを返す。"""
        key = proxy.server
        last_fail = self._fail_times.get(key, 0.0)
        if last_fail == 0.0:
            return True
        return (time.monotonic() - last_fail) >= self._cooldown_seconds

    def mark_failed(self, proxy: ProxyConfig) -> None:
        """プロキシを不健全としてマークする。"""
        self._fail_times[proxy.server] = time.monotonic()
        self._fail_counts[proxy.server] = self._fail_counts.get(proxy.server, 0) + 1
        logger.info(
            "プロキシ不健全マーク: %r (通算 %d 回)", proxy, self._fail_counts[proxy.server]
        )

    def mark_healthy(self, proxy: ProxyConfig) -> None:
        """プロキシを健全としてマークする（失敗状態をリセット）。"""
        self._fail_times.pop(proxy.server, None)

    def health_check(self, timeout: float = 5.0) -> dict[str, bool]:
        """全プロキシに対して HTTP ヘルスチェックを実行する。

        各プロキシを通じて httpbin.org/ip に GET リクエストを送り、
        応答があれば健全、タイムアウトまたはエラーなら不健全とする。

        Returns:
            {proxy_server: is_healthy} の辞書。
        """
        import requests

        results: dict[str, bool] = {}
        for proxy in self._proxies:
            try:
                proxies_dict = {
                    "http": f"http://{proxy.username}:{proxy.password}@{urlparse(proxy.server).hostname}:{urlparse(proxy.server).port}" if proxy.username else proxy.server,
                    "https": f"http://{proxy.username}:{proxy.password}@{urlparse(proxy.server).hostname}:{urlparse(proxy.server).port}" if proxy.username else proxy.server,
                }
                resp = requests.get(
                    "https://httpbin.org/ip",
                    proxies=proxies_dict,
                    timeout=timeout,
                )
                healthy = resp.status_code == 200
            except Exception:
                healthy = False

            results[proxy.server] = healthy
            if healthy:
                self.mark_healthy(proxy)
            else:
                self.mark_failed(proxy)

        alive = sum(1 for v in results.values() if v)
        logger.info("ヘルスチェック完了: %d/%d 健全", alive, len(results))
        return results

    def __bool__(self) -> bool:
        return len(self._proxies) > 0

    def __len__(self) -> int:
        return len(self._proxies)

    @classmethod
    def from_env(cls) -> "ProxyRotator":
        """環境変数からプロキシ設定を読み込む。

        優先順位:
          1. BRIGHTDATA_* 環境変数（Bright Data 専用）
          2. SMARTPROXY_* 環境変数（Smartproxy 専用）
          3. PROXY_LIST 環境変数（カンマ区切り URL リスト）
          4. PROXY_SERVER + PROXY_USERNAME + PROXY_PASSWORD 環境変数
        """
        proxies: list[ProxyConfig] = []
        strategy = os.getenv("PROXY_ROTATION", "random")

        # 1. Bright Data
        bd_customer = os.getenv("BRIGHTDATA_CUSTOMER", "")
        bd_zone = os.getenv("BRIGHTDATA_ZONE", "residential")
        bd_password = os.getenv("BRIGHTDATA_PASSWORD", "")
        if bd_customer and bd_password:
            country = os.getenv("BRIGHTDATA_COUNTRY", "")
            proxy = ProxyConfig.brightdata(
                customer=bd_customer,
                zone=bd_zone,
                password=bd_password,
                country=country,
            )
            proxies.append(proxy)
            logger.info("Bright Data プロキシを登録: %r", proxy)

        # 2. Smartproxy
        sp_user = os.getenv("SMARTPROXY_USER", "")
        sp_password = os.getenv("SMARTPROXY_PASSWORD", "")
        sp_host = os.getenv("SMARTPROXY_HOST", "gate.smartproxy.com")
        sp_port = int(os.getenv("SMARTPROXY_PORT", "7000"))
        if sp_user and sp_password:
            proxy = ProxyConfig.smartproxy(
                user=sp_user, password=sp_password,
                host=sp_host, port=sp_port,
            )
            proxies.append(proxy)
            logger.info("Smartproxy プロキシを登録: %r", proxy)

        # 3. PROXY_LIST（カンマ区切り URL リスト）
        proxy_list_str = os.getenv("PROXY_LIST", "")
        for entry in proxy_list_str.split(","):
            entry = entry.strip()
            if entry:
                try:
                    proxy = ProxyConfig.from_url(entry)
                    proxies.append(proxy)
                    logger.info("カスタムプロキシを登録: %r", proxy)
                except Exception as e:
                    logger.warning("プロキシURL のパース失敗 [%s]: %s", entry, e)

        # 4. 単一プロキシ
        if not proxies:
            server = os.getenv("PROXY_SERVER", "")
            if server:
                proxy = ProxyConfig(
                    server=server,
                    username=os.getenv("PROXY_USERNAME", ""),
                    password=os.getenv("PROXY_PASSWORD", ""),
                )
                proxies.append(proxy)
                logger.info("単一プロキシを登録: %r", proxy)

        if proxies:
            logger.info(
                "ProxyRotator 初期化完了: %d プロキシ / strategy=%s", len(proxies), strategy
            )
        else:
            logger.debug("プロキシ未設定。直接接続で実行します。")

        return cls(proxies=proxies, strategy=strategy)
