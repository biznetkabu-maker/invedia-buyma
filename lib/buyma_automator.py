"""
BUYMA 自動出品モジュール（Playwright ブラウザ自動操作）。

スプレッドシートの商品情報をもとに、BUYMA の出品フォームを
自動入力して出品または更新する。

⚠️  注意事項:
  - BUYMA の利用規約を必ず確認すること。
  - ログイン情報は環境変数（Secrets）で管理し、コードに直接書かないこと。
  - セレクターはBUYMAのサイト変更で動作しなくなる場合があります。
    動作しない場合は _SELECTORS を更新してください。

環境変数:
  BUYMA_EMAIL    : BUYMAログインメールアドレス
  BUYMA_PASSWORD : BUYMAログインパスワード
  BUYMA_HEADLESS : ブラウザをヘッドレスで起動するか (default: true)
  BUYMA_SLOW_MS  : 各操作間の待機時間 ms (default: 800)

出品ガイドラインの反映:
  - 商品タイトルは「ブランド名 ＋ アイテム名 ＋ 特徴」の形式を推奨。
  - 説明文は build_listing_description() で生成したテンプレートを使用する。
  - 在庫数は基本 1〜2 を設定（ListingData.stock_count のデフォルト = 1）。
  - 出品前に validate_listing() でブランド名誤表記・誇大表現を確認する。
  - 価格設定: 商品原価 + 国際送料 + 関税・消費税 + BUYMA手数料 + 利益
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.async_compat import run_sync

logger = logging.getLogger(__name__)

# ── BUYMA セレクター定義（変更があればここを更新する）──────────────────────────
_SELECTORS = {
    "login_email":     "input[name='session[email]'], input[type='email']",
    "login_password":  "input[name='session[password]'], input[type='password']",
    "login_submit":    "button[type='submit'], input[type='submit']",
    "my_page_link":    "a[href*='/my/'], .my-page-link",
    "new_item_btn":    "a[href*='/my/items/new'], .new-item-button",
    "brand_input":     "input[name*='brand'], input[placeholder*='ブランド']",
    "title_input":     "input[name*='title'], input[name*='name'], .item-name-input",
    "description":     "textarea[name*='description'], textarea[name*='detail']",
    "price_input":     "input[name*='price'], .price-input",
    "stock_input":     "input[name*='stock'], input[name*='quantity'], input[id*='stock']",
    "size_select":     "select[name*='size']",
    "color_input":     "input[name*='color']",
    "image_upload":    "input[type='file'][accept*='image']",
    "submit_btn":      "button[type='submit'], input[type='submit']",
    "success_marker":  ".success-message, .item-registered, [data-test='success']",
    "error_marker":    ".error-message, .alert-error",
}

# ── 認証セッションキャッシュ ──────────────────────────────────────────────────
_SESSION_COOKIE_FILE = Path(".buyma_session.json")


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class ListingData:
    """BUYMA 出品フォームに入力するデータ。

    Fields:
        product_name: 商品タイトル（推奨: ブランド名＋アイテム名＋特徴）
        brand: ブランド名
        model_number: 型番
        description: 商品説明文（build_listing_description() で生成推奨）
        buyma_price: BUYMA販売価格（JPY）
        size: サイズ（例: "S", "M", "37"）
        color: カラー（例: "ブラック"）
        image_paths: ローカル画像パスのリスト（最大5枚）
        category: BUYMAカテゴリ（例: "バッグ", "財布", "スニーカー"）
        condition: 商品状態（新品 / 中古）
        shipping_from: 発送元（例: "海外", "国内"）
        stock_count: 在庫数（ガイド推奨: 1〜2）
        source_shop: 買付先（例: "フランス正規取扱店"）
        shipping_method: 発送方法（例: "DHL国際宅配便（追跡番号付き）"）
    """

    product_name: str
    brand: str
    model_number: str
    description: str
    buyma_price: float
    size: str = ""
    color: str = ""
    image_paths: list[str] = field(default_factory=list)
    category: str = ""
    condition: str = "新品"
    shipping_from: str = "海外"
    stock_count: int = 1
    source_shop: str = ""
    shipping_method: str = "DHL国際宅配便（追跡番号付き）"

    def __post_init__(self):
        if self.image_paths is None:
            self.image_paths = []


@dataclass
class ListingResult:
    """出品操作の結果。"""

    product_name: str
    success: bool
    url: Optional[str] = None
    item_id: Optional[str] = None
    error: Optional[str] = None
    listed_at: Optional[datetime] = None

    def __post_init__(self):
        if self.listed_at is None:
            self.listed_at = datetime.now(timezone.utc)

    def __str__(self) -> str:
        if self.success:
            return f"[OK] {self.product_name} — {self.url or 'URL不明'}"
        return f"[FAILED] {self.product_name} — {self.error}"


# ============================================================================
# BUYMA 自動出品クラス
# ============================================================================

class BUYMAAutomator:
    """Playwright を使って BUYMA の出品フォームを自動操作するクラス。

    Args:
        email: BUYMA ログインメール
        password: BUYMA ログインパスワード
        headless: ヘッドレスモードで起動するか
        slow_ms: 各操作の間に入れる待機時間 (ms)
        max_retries: 失敗時のリトライ回数
    """

    BASE_URL = "https://www.buyma.com"
    LOGIN_URL = "https://www.buyma.com/login/"
    NEW_ITEM_URL = "https://www.buyma.com/my/items/new/"

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        headless: bool = True,
        slow_ms: int = 800,
        max_retries: int = 2,
    ) -> None:
        self._email = email or os.getenv("BUYMA_EMAIL", "")
        self._password = password or os.getenv("BUYMA_PASSWORD", "")
        self._headless = headless
        self._slow_ms = int(os.getenv("BUYMA_SLOW_MS", str(slow_ms)))
        self._max_retries = max_retries

        if not self._email or not self._password:
            logger.warning(
                "BUYMA_EMAIL / BUYMA_PASSWORD が設定されていません。"
                "出品操作は実行できません。"
            )

    @property
    def is_configured(self) -> bool:
        return bool(self._email and self._password)

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------

    async def post_listing_async(self, listing: ListingData) -> ListingResult:
        """1件の商品を BUYMA に出品する（非同期）。"""
        if not self.is_configured:
            return ListingResult(
                product_name=listing.product_name,
                success=False,
                error="BUYMA_EMAIL / BUYMA_PASSWORD が未設定"
            )

        from playwright.async_api import async_playwright

        from lib.scraper.stealth import LAUNCH_ARGS, apply_stealth_scripts, stealth_context_options

        last_error: Optional[Exception] = None

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless,
                args=LAUNCH_ARGS,
                slow_mo=self._slow_ms,
            )
            try:
                ctx_opts = stealth_context_options()
                context = await browser.new_context(**ctx_opts)

                # 保存済みセッションを読み込む
                if _SESSION_COOKIE_FILE.exists():
                    await context.add_cookies(
                        _load_session_cookies()
                    )

                page = await context.new_page()
                await apply_stealth_scripts(page)

                for attempt in range(1, self._max_retries + 1):
                    try:
                        # ログイン
                        await self._ensure_logged_in(page)

                        # 出品フォームを入力
                        result = await self._fill_and_submit(page, listing)

                        # セッションを保存
                        _save_session_cookies(await context.cookies())
                        return result

                    except Exception as e:
                        last_error = e
                        logger.warning(
                            "出品失敗 (attempt %d/%d) [%s]: %s",
                            attempt, self._max_retries, listing.product_name, e,
                        )
                        if attempt < self._max_retries:
                            await asyncio.sleep(attempt * 3 + _random_jitter())
                            # セッションをクリアして再ログイン
                            _SESSION_COOKIE_FILE.unlink(missing_ok=True)

            finally:
                await browser.close()

        return ListingResult(
            product_name=listing.product_name,
            success=False,
            error=str(last_error) if last_error else "unknown error",
        )

    def post_listing(self, listing: ListingData) -> ListingResult:
        """出品（同期版）。"""
        result: ListingResult = run_sync(self.post_listing_async(listing))
        return result

    async def post_batch_async(
        self, listings: list[ListingData], interval_sec: float = 5.0
    ) -> list[ListingResult]:
        """複数商品を順番に出品する（並列不可 — BUYMA の負荷軽減のため）。"""
        results = []
        for i, listing in enumerate(listings):
            result = await self.post_listing_async(listing)
            results.append(result)
            logger.info("  出品結果 %d/%d: %s", i + 1, len(listings), result)
            if i < len(listings) - 1:
                wait = interval_sec + _random_jitter()
                logger.debug("  次の出品まで %.1f 秒待機...", wait)
                await asyncio.sleep(wait)
        return results

    def post_batch(
        self, listings: list[ListingData], interval_sec: float = 5.0
    ) -> list[ListingResult]:
        """出品バッチ処理（同期版）。"""
        results: list[ListingResult] = run_sync(self.post_batch_async(listings, interval_sec))
        return results

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    async def _ensure_logged_in(self, page) -> None:
        """ログイン済みでなければログインを実行する。"""
        # マイページへのリダイレクトでログイン状態を確認
        await page.goto(f"{self.BASE_URL}/my/", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        if "/login" in page.url or "/session" in page.url:
            logger.info("BUYMA ログイン中...")
            await self._login(page)
        else:
            logger.debug("既にログイン済みです")

    async def _login(self, page) -> None:
        """ログインフォームを入力して送信する。"""
        await page.goto(self.LOGIN_URL, wait_until="networkidle")
        await page.wait_for_timeout(1000)

        # メールアドレス
        email_input = await page.wait_for_selector(
            _SELECTORS["login_email"], timeout=10_000
        )
        await email_input.fill(self._email)
        await page.wait_for_timeout(_random_type_delay())

        # パスワード
        pw_input = await page.wait_for_selector(
            _SELECTORS["login_password"], timeout=5_000
        )
        await pw_input.fill(self._password)
        await page.wait_for_timeout(_random_type_delay())

        # 送信
        submit = await page.wait_for_selector(_SELECTORS["login_submit"], timeout=5_000)
        await submit.click()
        await page.wait_for_timeout(3000)

        # ログイン失敗チェック
        if "/login" in page.url:
            error_el = await page.query_selector(_SELECTORS["error_marker"])
            error_text = (await error_el.inner_text()).strip() if error_el else "ログインに失敗しました"
            raise RuntimeError(f"BUYMAログイン失敗: {error_text}")

        logger.info("BUYMA ログイン成功")

    async def _fill_and_submit(self, page, listing: ListingData) -> ListingResult:
        """出品フォームに入力して送信する。"""
        await page.goto(self.NEW_ITEM_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # フォームが読み込まれるまで待機
        try:
            await page.wait_for_selector(_SELECTORS["title_input"], timeout=15_000)
        except Exception:
            logger.warning("出品フォームが見つかりません。ページ構造が変更された可能性があります。")
            raise

        # ── 各フィールドを入力 ──────────────────────────────────────────

        await _safe_fill(page, _SELECTORS["title_input"], listing.product_name)
        await _safe_fill(page, _SELECTORS["brand_input"], listing.brand)
        await _safe_fill(page, _SELECTORS["description"], listing.description)
        await _safe_fill(page, _SELECTORS["price_input"], str(int(listing.buyma_price)))

        if listing.size:
            await _safe_select(page, _SELECTORS["size_select"], listing.size)
        if listing.color:
            await _safe_fill(page, _SELECTORS["color_input"], listing.color)

        # 在庫数（ガイド推奨: 1〜2）
        await _safe_fill(page, _SELECTORS["stock_input"], str(listing.stock_count))

        # 画像アップロード
        for img_path in listing.image_paths[:5]:  # 最大5枚
            if Path(img_path).exists():
                try:
                    file_input = await page.query_selector(_SELECTORS["image_upload"])
                    if file_input:
                        await file_input.set_input_files(img_path)
                        await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning("画像アップロード失敗 [%s]: %s", img_path, e)

        await page.wait_for_timeout(1000)

        # ── 確認・送信 ─────────────────────────────────────────────────
        submit_btn = await page.wait_for_selector(_SELECTORS["submit_btn"], timeout=5_000)
        await submit_btn.click()
        await page.wait_for_timeout(3000)

        # 成功確認
        success_el = await page.query_selector(_SELECTORS["success_marker"])
        if success_el:
            current_url = page.url
            item_id = _extract_item_id(current_url)
            logger.info("出品成功: %s (id=%s)", listing.product_name, item_id)
            return ListingResult(
                product_name=listing.product_name,
                success=True,
                url=current_url,
                item_id=item_id,
            )

        # エラー確認
        error_el = await page.query_selector(_SELECTORS["error_marker"])
        if error_el:
            error_text = (await error_el.inner_text()).strip()
            raise RuntimeError(f"出品エラー: {error_text}")

        # どちらも見つからない場合はURLで判断
        if "/items/" in page.url and "/new" not in page.url:
            return ListingResult(
                product_name=listing.product_name,
                success=True,
                url=page.url,
                item_id=_extract_item_id(page.url),
            )

        raise RuntimeError(f"出品結果が不明です (URL: {page.url})")


# ============================================================================
# 商品説明文テンプレート生成
# ============================================================================

def build_listing_description(
    brand: str,
    product_name: str,
    *,
    color: str = "",
    size: str = "",
    source_shop: str = "",
    shipping_method: str = "DHL国際宅配便（追跡番号付き）",
    body: str = "",
) -> str:
    """ガイドのテンプレートに基づいた商品説明文を生成する。

    生成フォーマット:
        【ブランド】〇〇
        【商品名】〇〇
        【カラー】〇〇（color が指定された場合のみ）
        【サイズ】〇〇（size が指定された場合のみ）
        【買付先】〇〇（source_shop が指定された場合のみ）
        【発送方法】〇〇

        ■ 正規品のみ取り扱い。海外正規取扱店から直接お買い付けします。
        ■ BUYMAあんしんプラス適用対象です。

        （body テキスト）

    Args:
        brand: ブランド名
        product_name: 商品名
        color: カラー（省略可）
        size: サイズ（省略可）
        source_shop: 買付先（例: "フランス正規取扱店"）
        shipping_method: 発送方法
        body: 説明文本文（自由記述）

    Returns:
        フォーマット済みの商品説明文。
    """
    lines = [
        f"【ブランド】{brand}",
        f"【商品名】{product_name}",
    ]
    if color:
        lines.append(f"【カラー】{color}")
    if size:
        lines.append(f"【サイズ】{size}")
    if source_shop:
        lines.append(f"【買付先】{source_shop}")
    lines.append(f"【発送方法】{shipping_method}")
    lines.append("")
    lines.append("■ 正規品のみ取り扱い。海外正規取扱店から直接お買い付けします。")
    lines.append("■ BUYMAあんしんプラス適用対象です。")
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines)


# ============================================================================
# 出品バリデーション
# ============================================================================

# BUYMA規約で問題となる誇大表現・虚偽記載に相当するフレーズ
_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "100%本物",
    "100%正規品",
    "絶対に正規品",
    "絶対本物",
    "最安値保証",
    "完全保証",
    "保証書付き",     # 保証書は通常バイヤーでは提供できない
)


@dataclass
class ListingValidationResult:
    """出品データのバリデーション結果。"""

    is_valid: bool
    errors: list[str]       # 出品不可レベルの問題
    warnings: list[str]     # 改善推奨レベルの問題

    def summary(self) -> str:
        status = "✅ OK" if self.is_valid else "❌ エラーあり"
        lines = [f"バリデーション結果: {status}"]
        if self.errors:
            lines.append("【エラー（要修正）】")
            lines.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            lines.append("【警告（推奨改善）】")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


def validate_listing(listing: "ListingData") -> ListingValidationResult:
    """出品データをバリデートし、エラー・警告を返す。

    チェック内容:
      エラー（出品不可）:
        - ブランド名が空
        - 商品名が空
        - 販売価格が 0 以下

      警告（改善推奨）:
        - 商品名にブランド名が含まれていない（SEO低下）
        - 説明文が空
        - 説明文にブランド名が含まれていない（SEO低下）
        - 在庫数が 3 以上（ガイド推奨は 1〜2）
        - 誇大表現・禁止フレーズが説明文に含まれる
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── エラーチェック ────────────────────────────────────────────────
    if not listing.brand.strip():
        errors.append("ブランド名が未入力です。")

    if not listing.product_name.strip():
        errors.append("商品名が未入力です。")

    if listing.buyma_price <= 0:
        errors.append(f"販売価格が未設定または 0 以下です（現在: {listing.buyma_price}）。")

    # ── 警告チェック ─────────────────────────────────────────────────
    brand_lc = listing.brand.lower()
    title_lc = listing.product_name.lower()

    if listing.brand and listing.product_name and brand_lc not in title_lc:
        warnings.append(
            f"商品名にブランド名が含まれていません（推奨: 「{listing.brand} ＋ アイテム名」の形式）。"
            "ブランド名を先頭に入れるとSEO効果が高まります。"
        )

    if not listing.description.strip():
        warnings.append("商品説明文が空です。build_listing_description() でテンプレートを生成してください。")
    else:
        desc_lc = listing.description.lower()
        if listing.brand and brand_lc not in desc_lc:
            warnings.append(
                f"説明文に「{listing.brand}」が含まれていません。"
                "タイトルと同じキーワードを本文にも入れるとSEO効果が高まります。"
            )
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in listing.description:
                warnings.append(
                    f"説明文に誇大表現・規約違反になる可能性のある表現が含まれています: 「{phrase}」"
                )

    if listing.stock_count > 2:
        warnings.append(
            f"在庫数が {listing.stock_count} に設定されています。"
            "初心者はリスク管理のため 1〜2 を推奨します。"
        )

    if not listing.source_shop:
        warnings.append("買付先（source_shop）が未設定です。説明文の【買付先】欄に反映されます。")

    return ListingValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ============================================================================
# SheetManager との連携ヘルパー
# ============================================================================

def record_to_listing(
    record,
    image_paths: list[str] | None = None,
    description_template: str = "",
    source_shop: str = "",
    shipping_method: str = "DHL国際宅配便（追跡番号付き）",
    stock_count: int = 1,
) -> "ListingData":
    """ProductRecord から ListingData を生成する。

    説明文はガイドのテンプレート形式（build_listing_description）で生成する。
    description_template を指定した場合はそちらを優先する。
    """
    desc = description_template or build_listing_description(
        brand=record.ブランド,
        product_name=record.商品名,
        source_shop=source_shop,
        shipping_method=shipping_method,
        body=f"型番: {record.型番}" if record.型番 else "",
    )
    return ListingData(
        product_name=record.商品名,
        brand=record.ブランド,
        model_number=record.型番,
        description=desc,
        buyma_price=float(record.BUYMA販売価格 or 0),
        image_paths=image_paths or [],
        source_shop=source_shop,
        shipping_method=shipping_method,
        stock_count=stock_count,
    )


# ============================================================================
# ユーティリティ
# ============================================================================

async def _safe_fill(page, selector: str, value: str) -> None:
    """セレクターが存在する場合のみ入力する。"""
    try:
        el = await page.query_selector(selector)
        if el:
            await el.fill(value)
            await page.wait_for_timeout(300 + _random_type_delay())
    except Exception as e:
        logger.debug("_safe_fill failed [%s]: %s", selector, e)


async def _safe_select(page, selector: str, value: str) -> None:
    """セレクターが存在する場合のみ選択する。"""
    try:
        el = await page.query_selector(selector)
        if el:
            await el.select_option(value=value)
            await page.wait_for_timeout(200)
    except Exception as e:
        logger.debug("_safe_select failed [%s]: %s", selector, e)


def _extract_item_id(url: str) -> Optional[str]:
    import re
    match = re.search(r"/items?/(\d+)", url)
    return match.group(1) if match else None


def _random_jitter(min_sec: float = 1.0, max_sec: float = 3.0) -> float:
    return random.uniform(min_sec, max_sec)


def _random_type_delay() -> int:
    """人間のタイピング速度をエミュレートする待機時間 (ms)。"""
    return random.randint(80, 200)


def _load_session_cookies() -> list[dict[str, object]]:
    import json
    try:
        data: list[dict[str, object]] = json.loads(_SESSION_COOKIE_FILE.read_text())
        return data
    except Exception:
        return []


def _save_session_cookies(cookies: list[dict]) -> None:
    import json
    try:
        _SESSION_COOKIE_FILE.write_text(json.dumps(cookies))
    except Exception as exc:
        logger.debug("buyma_automator: %s", exc)
