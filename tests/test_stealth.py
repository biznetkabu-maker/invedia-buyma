"""stealth モジュールのテスト。"""

from __future__ import annotations

from lib.scraper.stealth import (
    LAUNCH_ARGS,
    STEALTH_INIT_SCRIPT,
    random_user_agent,
    random_viewport,
    random_wait_ms,
    stealth_context_options,
)


class TestRandomUserAgent:
    def test_returns_string(self):
        ua = random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 50

    def test_contains_browser_token(self):
        ua = random_user_agent()
        assert any(b in ua for b in ("Chrome", "Firefox", "Safari"))


class TestRandomViewport:
    def test_returns_dict(self):
        vp = random_viewport()
        assert "width" in vp
        assert "height" in vp

    def test_reasonable_size(self):
        vp = random_viewport()
        assert 1000 <= vp["width"] <= 3000
        assert 600 <= vp["height"] <= 2000


class TestRandomWaitMs:
    def test_within_range(self):
        for _ in range(50):
            val = random_wait_ms(500, 2000)
            assert 500 <= val <= 2000

    def test_default_range(self):
        val = random_wait_ms()
        assert 800 <= val <= 3000


class TestStealthContextOptions:
    def test_keys(self):
        opts = stealth_context_options()
        assert "user_agent" in opts
        assert "viewport" in opts
        assert "locale" in opts
        assert "extra_http_headers" in opts

    def test_custom_ua(self):
        opts = stealth_context_options(user_agent="CustomUA/1.0")
        assert opts["user_agent"] == "CustomUA/1.0"


class TestConstants:
    def test_launch_args(self):
        assert isinstance(LAUNCH_ARGS, list)
        assert len(LAUNCH_ARGS) > 5
        assert "--no-sandbox" in LAUNCH_ARGS

    def test_stealth_script(self):
        assert "webdriver" in STEALTH_INIT_SCRIPT
        assert "navigator" in STEALTH_INIT_SCRIPT
