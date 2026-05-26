"""
プロキシ・優先度ティアのユニットテスト。

- TestProxyConfig      : ProxyConfig の生成・変換
- TestProxyRotator     : ProxyRotator のローテーション動作
- TestProxyFromEnv     : 環境変数からのプロキシ読み込み
- TestHeavySiteTimeout : エンジンの重サイト判定
- TestPriorityTier     : Config.effective_priority_tier / _get_priority_products
"""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lib.scraper.proxy import ProxyConfig, ProxyRotator
from lib.scraper.engine import PriceScraper


# ---------------------------------------------------------------------------
# ProxyConfig
# ---------------------------------------------------------------------------

class TestProxyConfig(unittest.TestCase):

    def test_to_playwright_proxy_with_auth(self):
        p = ProxyConfig(server="http://proxy.example.com:8080", username="user", password="pass")
        d = p.to_playwright_proxy()
        self.assertEqual(d["server"], "http://proxy.example.com:8080")
        self.assertEqual(d["username"], "user")
        self.assertEqual(d["password"], "pass")

    def test_to_playwright_proxy_without_auth(self):
        p = ProxyConfig(server="http://proxy.example.com:8080")
        d = p.to_playwright_proxy()
        self.assertNotIn("username", d)
        self.assertNotIn("password", d)

    def test_from_url(self):
        p = ProxyConfig.from_url("http://myuser:mypass@proxy.example.com:3128")
        self.assertEqual(p.server, "http://proxy.example.com:3128")
        self.assertEqual(p.username, "myuser")
        self.assertEqual(p.password, "mypass")

    def test_from_url_no_auth(self):
        p = ProxyConfig.from_url("http://proxy.example.com:3128")
        self.assertEqual(p.server, "http://proxy.example.com:3128")
        self.assertEqual(p.username, "")
        self.assertEqual(p.password, "")

    def test_brightdata_factory(self):
        p = ProxyConfig.brightdata(
            customer="lum-customer-12345",
            zone="residential",
            password="secret",
            country="jp",
        )
        self.assertIn("lum-customer-12345", p.username)
        self.assertIn("zone-residential", p.username)
        self.assertIn("country-jp", p.username)
        self.assertEqual(p.password, "secret")
        self.assertIn("zproxy.lum-superproxy.io", p.server)

    def test_brightdata_no_country(self):
        p = ProxyConfig.brightdata(
            customer="lum-customer-x", zone="datacenter", password="pw"
        )
        self.assertNotIn("country", p.username)

    def test_smartproxy_factory(self):
        p = ProxyConfig.smartproxy(user="sp_user", password="sp_pass")
        self.assertEqual(p.username, "sp_user")
        self.assertEqual(p.password, "sp_pass")
        self.assertIn("gate.smartproxy.com", p.server)

    def test_smartproxy_custom_host_port(self):
        p = ProxyConfig.smartproxy(
            user="u", password="p",
            host="us.smartproxy.com", port=10000,
        )
        self.assertIn("10000", p.server)
        self.assertIn("us.smartproxy.com", p.server)

    def test_repr_hides_password(self):
        p = ProxyConfig(server="http://proxy.example.com:8080", username="u", password="secret")
        r = repr(p)
        self.assertIn("proxy.example.com", r)
        self.assertNotIn("secret", r)


# ---------------------------------------------------------------------------
# ProxyRotator
# ---------------------------------------------------------------------------

class TestProxyRotator(unittest.TestCase):

    def _make_proxies(self, n: int) -> list[ProxyConfig]:
        return [
            ProxyConfig(server=f"http://proxy{i}.example.com:8080", username=f"u{i}")
            for i in range(n)
        ]

    def test_empty_rotator_returns_none(self):
        r = ProxyRotator()
        self.assertIsNone(r.next())
        self.assertFalse(bool(r))

    def test_single_proxy_always_returns_same(self):
        proxies = self._make_proxies(1)
        r = ProxyRotator(proxies, strategy="roundrobin")
        for _ in range(5):
            self.assertEqual(r.next().username, "u0")

    def test_roundrobin_cycles(self):
        proxies = self._make_proxies(3)
        r = ProxyRotator(proxies, strategy="roundrobin")
        users = [r.next().username for _ in range(6)]
        self.assertEqual(users, ["u0", "u1", "u2", "u0", "u1", "u2"])

    def test_random_returns_from_pool(self):
        proxies = self._make_proxies(5)
        r = ProxyRotator(proxies, strategy="random")
        for _ in range(20):
            p = r.next()
            self.assertIn(p.username, [f"u{i}" for i in range(5)])

    def test_bool_true_with_proxies(self):
        r = ProxyRotator(self._make_proxies(2))
        self.assertTrue(bool(r))

    def test_len(self):
        r = ProxyRotator(self._make_proxies(4))
        self.assertEqual(len(r), 4)


# ---------------------------------------------------------------------------
# ProxyRotator — ヘルスチェック & フォールバック
# ---------------------------------------------------------------------------

class TestProxyHealthCheck(unittest.TestCase):

    def _make_proxies(self, n: int) -> list[ProxyConfig]:
        return [
            ProxyConfig(server=f"http://proxy{i}.example.com:8080", username=f"u{i}")
            for i in range(n)
        ]

    def test_mark_failed_makes_proxy_unhealthy(self):
        proxies = self._make_proxies(2)
        r = ProxyRotator(proxies, strategy="roundrobin", cooldown_seconds=600)
        r.mark_failed(proxies[0])
        for _ in range(3):
            p = r.next()
            self.assertEqual(p.username, "u1")

    def test_mark_healthy_restores_proxy(self):
        proxies = self._make_proxies(2)
        r = ProxyRotator(proxies, strategy="roundrobin", cooldown_seconds=600)
        r.mark_failed(proxies[0])
        r.mark_healthy(proxies[0])
        users = {r.next().username for _ in range(4)}
        self.assertIn("u0", users)

    def test_fallback_direct_when_all_unhealthy(self):
        proxies = self._make_proxies(2)
        r = ProxyRotator(proxies, strategy="roundrobin", fallback_direct=True, cooldown_seconds=600)
        r.mark_failed(proxies[0])
        r.mark_failed(proxies[1])
        self.assertIsNone(r.next())

    def test_no_fallback_uses_unhealthy_proxies(self):
        proxies = self._make_proxies(2)
        r = ProxyRotator(proxies, strategy="roundrobin", fallback_direct=False, cooldown_seconds=600)
        r.mark_failed(proxies[0])
        r.mark_failed(proxies[1])
        p = r.next()
        self.assertIsNotNone(p)

    def test_cooldown_expires(self):
        import time
        proxies = self._make_proxies(1)
        r = ProxyRotator(proxies, strategy="roundrobin", fallback_direct=True, cooldown_seconds=0.1)
        r.mark_failed(proxies[0])
        self.assertIsNone(r.next())
        time.sleep(0.15)
        p = r.next()
        self.assertIsNotNone(p)
        self.assertEqual(p.username, "u0")

    def test_health_check_with_mock(self):
        proxies = self._make_proxies(2)
        r = ProxyRotator(proxies)

        mock_resp = unittest.mock.MagicMock()
        mock_resp.status_code = 200

        with patch("requests.get", return_value=mock_resp) as mock_get:
            results = r.health_check(timeout=1.0)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(results.values()))

    def test_health_check_marks_failed_on_error(self):
        proxies = self._make_proxies(1)
        r = ProxyRotator(proxies, fallback_direct=True, cooldown_seconds=600)

        with patch("requests.get", side_effect=ConnectionError("proxy down")):
            results = r.health_check(timeout=1.0)

        self.assertFalse(results[proxies[0].server])
        self.assertIsNone(r.next())


# ---------------------------------------------------------------------------
# ProxyRotator.from_env
# ---------------------------------------------------------------------------

class TestProxyFromEnv(unittest.TestCase):

    def test_no_env_returns_empty(self):
        env_clear = {k: "" for k in [
            "PROXY_SERVER", "PROXY_LIST",
            "BRIGHTDATA_CUSTOMER", "BRIGHTDATA_PASSWORD",
            "SMARTPROXY_USER", "SMARTPROXY_PASSWORD",
        ]}
        with patch.dict(os.environ, env_clear):
            r = ProxyRotator.from_env()
        self.assertFalse(bool(r))

    def test_single_proxy_server(self):
        env = {
            "PROXY_SERVER": "http://proxy.example.com:8080",
            "PROXY_USERNAME": "user1",
            "PROXY_PASSWORD": "pass1",
        }
        with patch.dict(os.environ, env):
            r = ProxyRotator.from_env()
        self.assertTrue(bool(r))
        p = r.next()
        self.assertIn("proxy.example.com", p.server)
        self.assertEqual(p.username, "user1")

    def test_proxy_list_comma_separated(self):
        env = {
            "PROXY_LIST": "http://u1:p1@host1.com:3128,http://u2:p2@host2.com:3128",
            "PROXY_ROTATION": "roundrobin",
        }
        with patch.dict(os.environ, env):
            r = ProxyRotator.from_env()
        self.assertEqual(len(r), 2)

    def test_brightdata_env(self):
        env = {
            "BRIGHTDATA_CUSTOMER": "lum-customer-TEST",
            "BRIGHTDATA_ZONE": "residential",
            "BRIGHTDATA_PASSWORD": "bd_pass",
            "BRIGHTDATA_COUNTRY": "jp",
        }
        with patch.dict(os.environ, env):
            r = ProxyRotator.from_env()
        self.assertTrue(bool(r))
        p = r.next()
        self.assertIn("lum-customer-TEST", p.username)
        self.assertIn("country-jp", p.username)

    def test_smartproxy_env(self):
        env = {
            "SMARTPROXY_USER": "sp_user",
            "SMARTPROXY_PASSWORD": "sp_pass",
        }
        with patch.dict(os.environ, env):
            r = ProxyRotator.from_env()
        self.assertTrue(bool(r))
        p = r.next()
        self.assertEqual(p.username, "sp_user")

    def test_rotation_strategy_roundrobin(self):
        env = {
            "PROXY_LIST": "http://u1:p1@h1.com:3128,http://u2:p2@h2.com:3128",
            "PROXY_ROTATION": "roundrobin",
        }
        with patch.dict(os.environ, env):
            r = ProxyRotator.from_env()
        users = [r.next().username for _ in range(4)]
        self.assertEqual(users, ["u1", "u2", "u1", "u2"])


# ---------------------------------------------------------------------------
# エンジン: 重サイト判定 / proxy integration
# ---------------------------------------------------------------------------

class TestHeavySiteTimeout(unittest.TestCase):

    def setUp(self):
        self.scraper = PriceScraper()

    def test_selfridges_is_heavy(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.selfridges.com/GB/en/cat/product"))

    def test_harrods_is_heavy(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.harrods.com/en-gb/product"))

    def test_saks_is_heavy(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.saksfifthavenue.com/product"))

    def test_luisaviaroma_is_heavy(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.luisaviaroma.com/en-us/product"))

    def test_ssense_is_not_heavy(self):
        self.assertFalse(self.scraper.is_heavy_site("https://www.ssense.com/en-us/product"))

    def test_farfetch_is_heavy(self):
        self.assertTrue(self.scraper.is_heavy_site("https://www.farfetch.com/shopping/item"))

    def test_farfetch_navigation_uses_domcontentloaded_then_commit(self):
        url = "https://www.farfetch.com/jp/shopping/women/prada-item-1.aspx"
        self.assertEqual(
            self.scraper.navigation_wait_chain(url),
            ["domcontentloaded", "commit"],
        )

    def test_proxy_passed_to_scraper(self):
        proxies = [ProxyConfig(server="http://proxy.example.com:8080", username="u")]
        rotator = ProxyRotator(proxies)
        scraper = PriceScraper(proxy_rotator=rotator)
        self.assertTrue(bool(scraper._proxy_rotator))

    def test_parse_price_static_method(self):
        val, cur = PriceScraper.parse_price("€2,450.00")
        self.assertAlmostEqual(val, 2450.0)
        self.assertEqual(cur, "EUR")

    def test_parse_price_jpy(self):
        val, cur = PriceScraper.parse_price("¥15,000")
        self.assertAlmostEqual(val, 15000.0)
        self.assertEqual(cur, "JPY")

    def test_parse_price_cad(self):
        val, cur = PriceScraper.parse_price("CA$1,550.00")
        self.assertAlmostEqual(val, 1550.0)
        self.assertEqual(cur, "CAD")


# ---------------------------------------------------------------------------
# 優先度ティア
# ---------------------------------------------------------------------------

class TestPriorityTier(unittest.TestCase):

    def _make_config(self, tier="auto", high=0.20, medium=0.10):
        from lib.config import Config
        return Config(
            spreadsheet_id="x", worksheet_name="s", credentials_path="c.json",
            buyma_fee_rate=0.11, customs_rate=0.10, shipping_cost_jpy=2000,
            target_profit_rate=0.10,
            scraper_concurrency=3, scraper_headless=True,
            scraper_timeout_ms=30000, scraper_max_retries=2,
            priority_tier=tier,
            high_profit_threshold=high,
            medium_profit_threshold=medium,
        )

    def test_explicit_high(self):
        self.assertEqual(self._make_config(tier="high").effective_priority_tier(), "high")

    def test_explicit_all(self):
        self.assertEqual(self._make_config(tier="all").effective_priority_tier(), "all")

    def test_explicit_medium(self):
        self.assertEqual(self._make_config(tier="medium").effective_priority_tier(), "medium")

    def test_auto_hour_0_returns_all(self):
        config = self._make_config(tier="auto")
        with patch("lib.config.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(config.effective_priority_tier(), "all")

    def test_auto_hour_3_returns_medium(self):
        config = self._make_config(tier="auto")
        with patch("lib.config.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 3, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(config.effective_priority_tier(), "medium")

    def test_auto_hour_1_returns_high(self):
        config = self._make_config(tier="auto")
        with patch("lib.config.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 1, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(config.effective_priority_tier(), "high")

    def test_get_priority_products_all(self):
        from lib.main import _get_priority_products
        from lib.sheet_manager import ProductRecord
        records = [
            ProductRecord(商品名="A", BUYMA販売価格="100000", 利益額="25000"),  # 25%
            ProductRecord(商品名="B", BUYMA販売価格="100000", 利益額="12000"),  # 12%
            ProductRecord(商品名="C", BUYMA販売価格="100000", 利益額="5000"),   # 5%
        ]
        result = _get_priority_products(records, "all", 0.20, 0.10)
        self.assertEqual(len(result), 3)

    def test_get_priority_products_high(self):
        from lib.main import _get_priority_products
        from lib.sheet_manager import ProductRecord
        records = [
            ProductRecord(商品名="A", BUYMA販売価格="100000", 利益額="25000"),
            ProductRecord(商品名="B", BUYMA販売価格="100000", 利益額="12000"),
            ProductRecord(商品名="C", BUYMA販売価格="100000", 利益額="5000"),
        ]
        result = _get_priority_products(records, "high", 0.20, 0.10)
        names = [r.商品名 for _, r in result]
        self.assertEqual(names, ["A"])

    def test_get_priority_products_medium(self):
        from lib.main import _get_priority_products
        from lib.sheet_manager import ProductRecord
        records = [
            ProductRecord(商品名="A", BUYMA販売価格="100000", 利益額="25000"),
            ProductRecord(商品名="B", BUYMA販売価格="100000", 利益額="12000"),
            ProductRecord(商品名="C", BUYMA販売価格="100000", 利益額="5000"),
        ]
        result = _get_priority_products(records, "medium", 0.20, 0.10)
        names = [r.商品名 for _, r in result]
        self.assertIn("A", names)
        self.assertIn("B", names)
        self.assertNotIn("C", names)

    def test_get_priority_products_invalid_data(self):
        from lib.main import _get_priority_products
        from lib.sheet_manager import ProductRecord
        records = [
            ProductRecord(商品名="X", BUYMA販売価格="", 利益額="N/A"),
        ]
        result = _get_priority_products(records, "high", 0.20, 0.10)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
