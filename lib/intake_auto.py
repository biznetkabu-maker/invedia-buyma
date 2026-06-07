"""自動モード — BUYMA URL → 仕入先探索 → スクレイプ → シート反映の非対話パイプライン。

intake.py から分離した自動取り込みロジック。共有ヘルパー（``_evaluate`` /
``_build_record`` / ``_scrape_and_select`` 等）は循環 import を避けるため
関数内で ``lib.intake`` から遅延 import する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.intake_funnel import AutoIntakeOutcome

from lib.buyma_demand import BUYMADemandSignal
from lib.forex import get_rate
from lib.intake_cli import (
    cli_print,
)
from lib.intake_cli import (
    print_header as _print_header,
)
from lib.intake_cli import (
    print_score as _print_score,
)
from lib.intake_cli import (
    print_step as _print_step,
)
from lib.sheet_manager import ProductRecord


def auto_intake_from_buyma(
    buyma_url: str,
    *,
    skip_low_grades: bool = True,
) -> bool:
    """BUYMA 商品 URL 1件を自動処理する。"""
    from lib.intake import _check_auto_intake_features

    _print_header()
    _check_auto_intake_features()
    cli_print("  【自動モード】 BUYMA URL から仕入先を探索します\n")
    return _run_auto_intake(
        buyma_url=buyma_url, skip_low_grades=skip_low_grades,
    ).success


def auto_intake_from_sheet(
    *,
    limit: int = 0,
    skip_low_grades: bool = True,
    use_funnel: bool = True,
) -> None:
    """在庫ステータス = BUYMA候補 かつ 仕入れURL が buyma.com の行を処理する。"""
    from lib.intake import _check_auto_intake_features, _open_sheet_manager
    from lib.intake_funnel import (
        filter_eligible_records,
        funnel_enabled,
        mark_auto_skip,
        print_funnel_banner,
        weekly_auto_limit,
    )

    _print_header()
    _check_auto_intake_features()
    cli_print("  【自動モード】 シートの BUYMA候補 行を処理します\n")
    if use_funnel and funnel_enabled():
        print_funnel_banner()

    manager = _open_sheet_manager()
    if manager is None:
        return

    records = manager.get_records_by_status("BUYMA候補")
    buyma_rows = [r for r in records if _is_buyma_reference_url(r.仕入れURL)]
    effective_limit = limit if limit > 0 else (
        weekly_auto_limit() if (use_funnel and funnel_enabled()) else 0
    )

    if use_funnel and funnel_enabled():
        targets, pre_skipped = filter_eligible_records(
            buyma_rows, limit=effective_limit,
        )
        for rec, verdict in pre_skipped:
            name = rec.商品名.strip()
            cli_print(f"  ⏭️  スキップ: {name[:50]} — {verdict.reason}")
            if verdict.skip_status:
                mark_auto_skip(manager, name, verdict.skip_status)
    else:
        targets = buyma_rows[:effective_limit] if effective_limit > 0 else buyma_rows

    if not targets:
        cli_print("  処理対象の BUYMA候補 行がありません。")
        return

    cli_print(f"  実行対象: {len(targets)} 件\n")
    ok = 0
    for i, rec in enumerate(targets, 1):
        cli_print(f"\n{'=' * 60}")
        cli_print(f"  [{i}/{len(targets)}] {rec.商品名 or rec.ブランド}")
        cli_print(f"{'=' * 60}")

        buyma_price_hint = 0.0
        if rec.BUYMA販売価格.strip():
            try:
                buyma_price_hint = float(rec.BUYMA販売価格.replace(",", ""))
            except ValueError:
                pass

        preset = [
            u for u in rec.candidate_url_list()
            if u.strip() and "buyma.com" not in u.lower()
        ]
        outcome = _run_auto_intake(
            buyma_url=rec.仕入れURL.strip(),
            brand_hint=rec.ブランド.strip(),
            product_hint=_product_name_without_brand(rec),
            style_id_hint=rec.型番.strip(),
            buyma_price_hint=buyma_price_hint,
            upsert_name=rec.商品名.strip(),
            skip_low_grades=skip_low_grades,
            preset_candidate_urls=preset,
            use_funnel=use_funnel and funnel_enabled(),
        )
        if outcome.success:
            ok += 1
        elif outcome.skip_status and manager:
            mark_auto_skip(manager, rec.商品名.strip(), outcome.skip_status)

    cli_print(f"\n  完了: {ok}/{len(targets)} 件をシートに反映しました。")


def _product_name_without_brand(record: ProductRecord) -> str:
    """シート行の商品名からブランド接頭辞を除いた名称を推定する。"""
    name = (record.商品名 or "").strip()
    brand = (record.ブランド or "").strip()
    if brand and name.lower().startswith(brand.lower()):
        return name[len(brand):].strip(" -|/：:")
    return name


def _is_buyma_reference_url(url: str) -> bool:
    from lib.buyma_style_id import is_buyma_item_url

    u = (url or "").strip()
    return bool(u) and "buyma.com" in u.lower() and is_buyma_item_url(u)


def _auto_fetch_buyma_info(buyma_url: str) -> Optional[object]:
    """Step 1: BUYMA ページから商品情報を取得する。"""
    from lib.buyma_item_parser import fetch_buyma_item_info_sync

    _print_step(1, "BUYMA 商品情報の取得（自動）")
    cli_print(f"  URL: {buyma_url[:70]}")
    cli_print("  ページを取得中（10〜30秒）...")
    return fetch_buyma_item_info_sync(buyma_url)


def _auto_extract_product_identity(
    info: object,
    product_hint: str,
    brand_hint: str,
    style_id_hint: str,
    category: str,
) -> Optional[tuple]:
    """Step 1b: BUYMA ページ情報からブランド・商品名・型番等を抽出する。

    Returns:
        (brand, product_name, raw_product_name, variant, sheet_style_id,
         supply_style_id, buyma_style_id, page_price_jpy) or None on failure.
    """
    from lib.product_identity import VariantKey
    from lib.supply_search_utils import (
        clean_product_name_for_search,
        dedupe_product_phrase,
        resolve_merchandise_brand,
        resolve_style_id_for_supply_search,
    )

    raw_product_name = dedupe_product_phrase(
        (info.product_name or product_hint or info.raw_title or "").strip()
    )
    brand = resolve_merchandise_brand(
        raw_product_name,
        product_hint,
        info.raw_title,
        info.brand,
        brand_hint,
    )
    product_name = clean_product_name_for_search(raw_product_name, brand) or raw_product_name
    buyma_style_id = style_id_hint or (info.style_id or "")
    variant = VariantKey.resolve(
        brand=brand,
        product_name=product_name,
        sheet_style_id=style_id_hint,
        buyma_style_id=buyma_style_id,
        raw_product_name=raw_product_name,
        raw_title=info.raw_title,
        category=category,
    )
    sheet_style_id = variant.match_ref
    style_context = " ".join(
        x for x in (info.raw_title, raw_product_name, product_name) if x
    ).strip()
    supply_style_id = sheet_style_id or resolve_style_id_for_supply_search(
        style_context, buyma_style_id
    )
    page_price_jpy = info.price_jpy

    cli_print(f"  ブランド: {brand or '（未取得）'}")
    cli_print(f"  商品名:   {product_name or '（未取得）'}")
    if sheet_style_id:
        cli_print(f"  型番:     {sheet_style_id}")
    elif variant.buyma_item_id:
        cli_print(f"  BUYMA ID: {variant.buyma_item_id}（参照用・照合には未使用）")
    elif buyma_style_id:
        cli_print(f"  BUYMA ID: {buyma_style_id}（参照用）")
    if page_price_jpy:
        cli_print(f"  BUYMA価格: ¥{page_price_jpy:,}")

    if not brand or not product_name:
        cli_print("  ❌ ブランドまたは商品名を取得できませんでした。")
        return None

    return (
        brand, product_name, raw_product_name, variant,
        sheet_style_id, supply_style_id, buyma_style_id, page_price_jpy,
    )


def _auto_check_prada_official(
    brand: str,
    supply_style_id: str,
    raw_product_name: str,
    product_name: str,
) -> Optional[object]:
    """Step 1.5: PRADA 公式カタログとの型番照合。"""
    from lib.funnel_policy import official_prada_enabled
    from lib.intake_funnel import is_eyewear_product_name

    if brand != "PRADA" or not supply_style_id or not official_prada_enabled():
        return None

    _print_step(1.5, "PRADA 公式カタログ照合（prada.com）")
    from lib.official_catalog.prada import lookup_prada_official_sync

    cli_print("  型番を公式 SKU と突合（F12/XHR・JSON-LD・DDG）...")
    official_match = lookup_prada_official_sync(
        supply_style_id,
        product_name=raw_product_name or product_name,
        use_playwright=True,
    )
    if official_match:
        cli_print(f"  公式SKU:  {official_match.sku}")
        if official_match.english_name:
            cli_print(f"  英語名:   {official_match.english_name}")
        if official_match.product_url:
            cli_print(f"  公式URL:  {official_match.product_url[:75]}")
        cli_print(f"  ({official_match.identity_note})")
    else:
        cli_print(
            "  ⚠️  公式照合なし（ローカルで scripts/capture_prada_f12.py を実行可能）"
        )
        if is_eyewear_product_name(f"{brand} {product_name}"):
            cli_print(
                "  → サングラスは探索が難しい場合があります。"
                "失敗時は候補URLsに仕入URLを貼って再実行してください。"
            )
    return official_match


def _auto_search_supply_urls(
    brand: str,
    product_name: str,
    supply_style_id: str,
    raw_product_name: str,
    official_match: Optional[object],
    preset_candidate_urls: Optional[list[str]],
    use_funnel: bool,
) -> list[str]:
    """Step 3: 仕入先 URL の自動探索。"""
    from lib.supply_search_utils import url_is_valid_supply_candidate as _url_valid_supply
    from lib.supply_url_finder import discover_supply_urls_funnel, discover_supply_urls_sync

    _print_step(3, "仕入先 URL の自動探索")

    class _Step3Log(list):
        def append(self, item: object) -> None:
            cli_print(item, flush=True)
            super().append(str(item))

    search_log: _Step3Log = _Step3Log()
    if use_funnel:
        cli_print("  漏斗: 候補URLs → 型番site検索 → サイト内検索（最大数分）...", flush=True)
        cli_print("  （探索中… 型番検索の行が順に出ます。1〜3分かかることがあります）", flush=True)
        supply = discover_supply_urls_funnel(
            brand,
            product_name,
            supply_style_id,
            preset_urls=preset_candidate_urls,
            raw_product_name=raw_product_name,
            official_english_name=(
                official_match.english_name if official_match else ""
            ),
            headless=True,
            max_sites=5,
            log_lines=search_log,
        )
    else:
        cli_print("  主要5サイトの検索結果から商品ページ URL を収集中（1〜3分）...")
        supply = discover_supply_urls_sync(
            brand, product_name, supply_style_id,
            raw_product_name=raw_product_name,
            headless=True, max_sites=5,
            log_lines=search_log,
        )
    supply = [s for s in supply if _url_valid_supply(brand, s.product_url)]
    if not supply and search_log and any("OK FARFETCH" in ln for ln in search_log):
        cli_print(
            "  ⚠️  FARFETCH の URL は見つかりましたが形式が不正です。"
            " git pull 後に再実行するか、手動で新品 URL を貼ってください。"
        )
    candidate_urls = [s.product_url for s in supply]
    if supply and not search_log:
        for s in supply:
            cli_print(f"    {s.site_name}: {s.product_url[:65]}")
    return candidate_urls


def _auto_evaluate_and_write(
    *,
    brand: str,
    product_name: str,
    category: str,
    model_year: int,
    source_url: str,
    source_price: float,
    currency: str,
    exchange_rate: float,
    buyma_price: float,
    demand: "BUYMADemandSignal",
    candidate_urls: list[str],
    sheet_style_id: str,
    buyma_style_id: str,
    supply_style_id: str,
    match_score: Optional[object],
    scraped_style_id: str,
    stock_status: str,
    variant: object,
    official_match: Optional[object],
    upsert_name: str,
    skip_low_grades: bool,
) -> "AutoIntakeOutcome":
    """Steps 5-6: グレード判定・シート書き込み。"""
    from lib.intake import _build_record, _evaluate, _write_to_sheet_quiet
    from lib.intake_funnel import SKIP_LOW_GRADE, SKIP_NO_PRICE, AutoIntakeOutcome
    from lib.product_identity import summarize_best_source_result
    from lib.supply_search_utils import style_id_for_matching

    _print_step(5, "仕入れ判断（自動）")
    score = _evaluate(
        brand=brand, product_name=product_name, category=category,
        model_year=model_year, source_url=source_url,
        source_price=source_price, currency=currency,
        exchange_rate=exchange_rate, buyma_price=buyma_price,
        demand_signal=demand,
    )
    _print_score(score)

    if score.grade in ("D", "E") and skip_low_grades:
        cli_print(f"  ⚠️  グレード {score.grade} のためシート反映をスキップしました。")
        return AutoIntakeOutcome(False, SKIP_LOW_GRADE)

    match_style_id = style_id_for_matching(sheet_style_id, buyma_style_id)
    match_score = summarize_best_source_result(
        variant,
        best_url=source_url,
        best_style_id=scraped_style_id or match_style_id,
        best_stock=stock_status,
        best_price_ok=source_price > 0,
        best_price_note=(
            match_score.price_note if match_score else ""
        ) or f"利益判定={score.grade}",
        purchase_grade=score.grade,
        official_sku=official_match.sku if official_match else "",
    )
    cli_print(match_score.format_console())

    _print_step(6, "スプレッドシートへ追加")
    record = _build_record(
        brand=brand, product_name=product_name,
        source_url=source_url, source_price=source_price,
        exchange_rate=exchange_rate, buyma_price=buyma_price,
        candidate_urls=candidate_urls, score=score,
        buyma_style_id=sheet_style_id or buyma_style_id,
        match_score=match_score,
    )
    if upsert_name:
        from dataclasses import replace
        record = replace(record, 商品名=upsert_name)
    if _write_to_sheet_quiet(record):
        cache_mpn = supply_style_id or sheet_style_id
        if cache_mpn and match_score.allows_auto_reflect():
            from lib.supply_url_cache import store_supply_urls

            store_supply_urls(
                brand,
                cache_mpn,
                candidate_urls,
                match_grade=match_score.grade,
                source="auto_intake",
            )
        return AutoIntakeOutcome(True)
    return AutoIntakeOutcome(False, SKIP_NO_PRICE)


def _run_auto_intake(
    *,
    buyma_url: str,
    brand_hint: str = "",
    product_hint: str = "",
    style_id_hint: str = "",
    buyma_price_hint: float = 0.0,
    category: str = "バッグ",
    model_year: int = 2025,
    upsert_name: str = "",
    skip_low_grades: bool = True,
    preset_candidate_urls: Optional[list[str]] = None,
    use_funnel: bool = True,
) -> "AutoIntakeOutcome":
    """BUYMA URL を起点に仕入先探索〜シート反映までを非対話で実行する。"""
    from lib.intake import _run_demand_check, _scrape_and_select
    from lib.intake_funnel import (
        SKIP_BUYMA_FETCH,
        SKIP_NO_PRICE,
        SKIP_NO_SELL_PRICE,
        SKIP_NO_SUPPLY,
        SKIP_OUT_OF_SCOPE,
        AutoIntakeOutcome,
        is_non_apparel_product_name,
    )
    from lib.product_identity import score_when_no_supply
    from lib.supply_search_utils import style_id_for_matching

    buyma_url = buyma_url.strip()
    if not _is_buyma_reference_url(buyma_url):
        cli_print(f"  ❌ BUYMA 商品 URL ではありません: {buyma_url}")
        return AutoIntakeOutcome(False, SKIP_NO_SUPPLY)

    # Step 1: BUYMA 商品情報取得
    info = _auto_fetch_buyma_info(buyma_url)
    if not info:
        cli_print("  ❌ BUYMA ページの取得に失敗しました。")
        return AutoIntakeOutcome(False, SKIP_BUYMA_FETCH)

    # Step 1b: 商品情報の抽出
    identity = _auto_extract_product_identity(
        info, product_hint, brand_hint, style_id_hint, category,
    )
    if identity is None:
        return AutoIntakeOutcome(False, SKIP_BUYMA_FETCH)

    (
        brand, product_name, raw_product_name, variant,
        sheet_style_id, supply_style_id, buyma_style_id, page_price_jpy,
    ) = identity

    # スコープチェック
    if is_non_apparel_product_name(f"{brand} {product_name}") or is_non_apparel_product_name(
        raw_product_name
    ):
        cli_print(
            "  ⏭️  香水・コスメは自動仕入れ検討の対象外です（バッグ・財布向けの探索のため）。"
        )
        cli_print("  → py intake.py で仕入先 URL を手動で貼ってください。")
        return AutoIntakeOutcome(False, SKIP_OUT_OF_SCOPE)

    # Step 1.5: PRADA 公式照合
    official_match = _auto_check_prada_official(
        brand, supply_style_id, raw_product_name, product_name,
    )

    # Step 2: 需要確認
    _print_step(2, "BUYMA 需要確認（自動）")
    demand = _run_demand_check(
        brand,
        product_name,
        display_name=f"{brand} {product_name}",
    )
    cli_print(demand.summary())

    buyma_price = _resolve_buyma_price_auto(demand, page_price_jpy)
    if buyma_price_hint > 0 and buyma_price <= 0:
        buyma_price = buyma_price_hint
        cli_print(f"  → シートの参考価格 ¥{int(buyma_price):,} を使用します。")
    if buyma_price <= 0:
        cli_print("  ❌ 売価を決定できませんでした。手動で intake.py を実行してください。")
        return AutoIntakeOutcome(False, SKIP_NO_SELL_PRICE)

    # Step 3: 仕入先探索
    candidate_urls = _auto_search_supply_urls(
        brand, product_name, supply_style_id, raw_product_name,
        official_match, preset_candidate_urls, use_funnel,
    )
    if not candidate_urls:
        cli_print("  ❌ 仕入先 URL を自動取得できませんでした。")
        cli_print("  → 手動モード: py intake.py で URL を貼り付けてください。")
        return AutoIntakeOutcome(False, SKIP_NO_SUPPLY)

    # Step 4: スクレイプ
    currency = _guess_currency_from_url(candidate_urls[0])
    exchange_rate = _get_exchange_rate_auto(currency)

    _print_step(4, f"{len(candidate_urls)}件のURLを並列スクレイプ（自動）")
    match_style_id = style_id_for_matching(sheet_style_id, buyma_style_id)
    source_url, source_price, match_score, scraped_style_id, stock_status = (
        _scrape_and_select(
            candidate_urls=candidate_urls,
            buyma_price=buyma_price,
            exchange_rate=exchange_rate,
            buyma_style_id=match_style_id,
            brand=brand,
            variant=variant,
        )
    )

    if source_url:
        currency = _guess_currency_from_url(source_url)
        exchange_rate = _get_exchange_rate_auto(currency)

    if source_price <= 0 or not (source_url or "").strip():
        if match_score is None:
            match_score = score_when_no_supply(variant, reason="価格・URL未取得")
        cli_print(match_score.format_console())
        cli_print(
            "  ⚠️  仕入先の価格・在庫を取得できませんでした。"
            "誤ったURLをシートに書かないため、反映をスキップします。"
        )
        from lib.funnel_policy import rescue_hint

        cli_print(f"  → {rescue_hint()}")
        cli_print("  → または py intake.py で正しい新品の商品URLを貼って再登録してください。")
        cli_print(
            "  ※ FARFETCH で ¥数十万が出る場合、定価>転売価格で利益マイナスになることがあります。"
            "ブラウザで価格を確認して手動 intake が確実です。"
        )
        return AutoIntakeOutcome(False, SKIP_NO_PRICE)

    # Steps 5-6: 評価・シート書き込み
    return _auto_evaluate_and_write(
        brand=brand,
        product_name=product_name,
        category=category,
        model_year=model_year,
        source_url=source_url,
        source_price=source_price,
        currency=currency,
        exchange_rate=exchange_rate,
        buyma_price=buyma_price,
        demand=demand,
        candidate_urls=candidate_urls,
        sheet_style_id=sheet_style_id,
        buyma_style_id=buyma_style_id,
        supply_style_id=supply_style_id,
        match_score=match_score,
        scraped_style_id=scraped_style_id,
        stock_status=stock_status,
        variant=variant,
        official_match=official_match,
        upsert_name=upsert_name,
        skip_low_grades=skip_low_grades,
    )


def _resolve_buyma_price_auto(
    demand: BUYMADemandSignal,
    page_price_jpy: Optional[int] = None,
) -> float:
    """非対話モード用: 競合最安×係数、なければ BUYMA ページ価格。"""
    from lib.intake import _price_factor

    factor = _price_factor()
    if demand.min_price:
        suggested = int(round(demand.min_price * factor))
        cli_print(
            f"\n  売価案: 競合最安 ¥{demand.min_price:,} × {factor} "
            f"= ¥{suggested:,}（自動採用）"
        )
        return float(suggested)
    if page_price_jpy and page_price_jpy > 0:
        cli_print(f"\n  競合最安未取得 → BUYMAページ価格 ¥{page_price_jpy:,} を使用")
        return float(page_price_jpy)
    return 0.0


def _get_exchange_rate_auto(currency: str = "EUR") -> float:
    """為替レートを API から取得（非対話）。"""
    if (currency or "").upper() == "JPY":
        cli_print("  → 仕入先は JPY 建て（為替 1.0）")
        return 1.0
    try:
        rate = get_rate(currency, "JPY")
        if rate:
            cli_print(f"  → {currency}/JPY: {rate:.2f}（自動取得）")
            return round(rate, 2)
    except Exception as e:
        cli_print(f"  ⚠️  為替自動取得失敗: {e}")
    cli_print("  → デフォルト為替 155.0 を使用")
    return 155.0


def _guess_currency_from_url(url: str) -> str:
    """仕入先 URL から通貨コードを推定する。"""
    from lib.scraper.price_sanity import infer_currency_from_url

    return infer_currency_from_url(url)
