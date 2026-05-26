"""ボット検知回避モジュール。

提供する対策:
  - User-Agent ローテーション（実機ブラウザと同等の UA プール）
  - navigator.webdriver フラグ除去
  - Chrome プラグイン・言語・パーミッション偽装
  - ランダムなビューポートサイズ
  - ページロード後のランダム待機
  - 画像・フォントブロック（速度向上 + トラッキングピクセル回避）
  - 余分なリクエストヘッダー付与（実ブラウザと同等）
"""

from __future__ import annotations

import random
from typing import Any

from playwright.async_api import BrowserContext, Page


# ── User-Agent プール（2026年時点の主要ブラウザ） ─────────────────────────────
_USER_AGENTS: list[str] = [
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ── ブラウザ起動引数（自動化検知フラグを無効化） ──────────────────────────────
LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
]

# ── WebDriver フラグ除去・ブラウザ偽装 JavaScript ─────────────────────────────
STEALTH_INIT_SCRIPT = """
// webdriver フラグを除去
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// Chrome オブジェクトを注入（headless では存在しないため）
if (!window.chrome) {
    window.chrome = {
        runtime: {
            connect: () => { throw new Error(); },
            sendMessage: () => { throw new Error(); },
        },
        loadTimes: () => ({}),
        csi: () => ({}),
        app: {},
    };
}

// プラグインを偽装（0個だと headless バレる）
const _plugins = [
    { name: 'Chrome PDF Plugin',  filename: 'internal-pdf-viewer',  description: 'Portable Document Format', length: 1 },
    { name: 'Chrome PDF Viewer',  filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
    { name: 'Native Client',      filename: 'internal-nacl-plugin',  description: '', length: 2 },
];
Object.defineProperty(navigator, 'plugins', {
    get: () => Object.assign(_plugins, {
        item:       (i) => _plugins[i],
        namedItem:  (n) => _plugins.find(p => p.name === n) || null,
        refresh:    () => {},
        [Symbol.iterator]: _plugins[Symbol.iterator].bind(_plugins),
    }),
    configurable: true,
});

// 言語設定
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'ja'],
    configurable: true,
});

// permissions.query を notifications 以外に対して通常動作させる
const _origPermQuery = window.navigator.permissions.query.bind(navigator.permissions);
Object.defineProperty(navigator.permissions, 'query', {
    value: (params) => params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _origPermQuery(params),
    configurable: true,
});

// hardware concurrency / memory を実機に近い値に設定
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
"""

# ── リアルなビューポートサイズプール ─────────────────────────────────────────
_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]


def random_user_agent() -> str:
    """ランダムな User-Agent を返す。"""
    return random.choice(_USER_AGENTS)


def random_viewport() -> dict[str, int]:
    """ランダムなビューポートサイズ（わずかなノイズを加える）を返す。"""
    base = random.choice(_VIEWPORTS)
    noise_w = random.randint(-20, 20)
    noise_h = random.randint(-10, 10)
    return {
        "width": base["width"] + noise_w,
        "height": base["height"] + noise_h,
    }


def random_wait_ms(min_ms: int = 800, max_ms: int = 3000) -> int:
    """ランダムな待機時間 (ms) を返す（正規分布に近い分布で自然に見せる）。"""
    mu = (min_ms + max_ms) / 2
    sigma = (max_ms - min_ms) / 6
    val = int(random.gauss(mu, sigma))
    return max(min_ms, min(max_ms, val))


def stealth_context_options(user_agent: str | None = None) -> dict[str, Any]:
    """ステルスブラウザコンテキストの設定辞書を返す。"""
    ua = user_agent or random_user_agent()
    vp = random_viewport()
    return {
        "user_agent": ua,
        "viewport": vp,
        "screen": {"width": vp["width"], "height": vp["height"]},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "extra_http_headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        },
    }


async def apply_stealth_scripts(page: Page) -> None:
    """ページにステルス初期化スクリプトを追加する。
    page.goto() の前に呼ぶこと（add_init_script はリロードにも適用される）。
    """
    await page.add_init_script(STEALTH_INIT_SCRIPT)
