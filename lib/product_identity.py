"""
商品同一性（VariantKey）と自動反映可否（MatchScore）。

型番を軸に BUYMA 候補と仕入先スクレイプ結果を突き合わせ、
同一性スコア S/A/B/C/F をシート・ログに残す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from lib.style_id_utils import scraped_matches_buyma_style

if TYPE_CHECKING:
    from lib.sheet_manager import ProductRecord

MatchGrade = Literal["S", "A", "B", "C", "F"]

_GRADES_AUTO_OK: frozenset[str] = frozenset({"S", "A"})

_NUMERIC_BUYMA_ID = re.compile(r"^\d{7,}$")


@dataclass(frozen=True)
class VariantKey:
    """照合に使う SKU キー（型番中心）。"""

    brand: str
    style_id: str
    buyma_item_id: str = ""
    color: str = ""
    size: str = ""
    category: str = ""

    @property
    def has_match_ref(self) -> bool:
        """照合に使える型番があるかを返す。"""
        return bool((self.style_id or "").strip())

    @property
    def match_ref(self) -> str:
        """照合用の型番文字列（前後空白除去）を返す。"""
        return (self.style_id or "").strip()

    @classmethod
    def resolve(
        cls,
        *,
        brand: str = "",
        product_name: str = "",
        sheet_style_id: str = "",
        buyma_style_id: str = "",
        raw_product_name: str = "",
        raw_title: str = "",
        category: str = "",
    ) -> VariantKey:
        """シート・BUYMA・商品名から照合用型番を確定する。"""
        from lib.supply_search_utils import (
            normalize_brand_name,
            sheet_style_id_value,
        )

        norm_brand = normalize_brand_name(brand)
        raw = (raw_product_name or product_name or "").strip()
        name_for_resolve = (product_name or raw).strip()
        style_context = " ".join(
            x for x in (raw_title, raw, name_for_resolve) if x
        ).strip() or name_for_resolve

        sheet_raw = (sheet_style_id or "").strip()
        buyma_raw = (buyma_style_id or "").strip()

        resolved = sheet_style_id_value(style_context, buyma_raw or sheet_raw)
        if not resolved and buyma_raw:
            resolved = sheet_style_id_value(style_context, buyma_raw)

        buyma_item_id = ""
        for candidate in (sheet_raw, buyma_raw):
            if candidate and _NUMERIC_BUYMA_ID.match(candidate):
                buyma_item_id = candidate
                break

        return cls(
            brand=norm_brand,
            style_id=resolved or "",
            buyma_item_id=buyma_item_id,
            category=(category or "").strip(),
        )

    @classmethod
    def from_record(cls, record: ProductRecord) -> VariantKey:
        """ProductRecord から VariantKey を生成する。"""
        return cls.resolve(
            brand=record.ブランド,
            product_name=record.商品名,
            sheet_style_id=record.型番,
        )


@dataclass(frozen=True)
class MatchScore:
    """同一性・価格根拠の要約（シート列・ログ用）。"""

    grade: str
    identity_note: str = ""
    price_note: str = ""

    def allows_auto_reflect(self) -> bool:
        """S/A のみ自動シート反映を推奨（運用ガイド）。"""
        return self.grade in _GRADES_AUTO_OK

    def format_console(self) -> str:
        """同一性スコアをコンソール表示用の複数行文字列に整形する。"""
        lines = [f"  【同一性スコア】 {self.grade}"]
        if self.identity_note:
            lines.append(f"    同一性: {self.identity_note}")
        if self.price_note:
            lines.append(f"    価格根拠: {self.price_note}")
        if self.grade in _GRADES_AUTO_OK:
            lines.append("    → 自動反映の信頼度: 高")
        elif self.grade == "B":
            lines.append("    → 手動確認を推奨")
        else:
            lines.append("    → 自動見送りまたは手動 intake を推奨")
        return "\n".join(lines)


def _purchase_grade_ok(grade: str) -> bool:
    return (grade or "").strip().upper() in ("A", "B", "C")


def score_from_best_candidate(
    variant: VariantKey,
    *,
    url: str = "",
    scraped_style_id: str | None = None,
    stock_status: str = "unknown",
    price_ok: bool = False,
    price_note: str = "",
    purchase_grade: str = "",
    url_style_hint: bool = False,
) -> MatchScore:
    """選定された仕入先1件から MatchScore を算出する。"""
    ref = variant.match_ref
    style_match = (
        not ref
        or scraped_matches_buyma_style(scraped_style_id, ref)
    )
    in_stock = stock_status == "in_stock"
    grade_ok = _purchase_grade_ok(purchase_grade)

    identity_parts: list[str] = []
    if ref:
        identity_parts.append(f"型番={ref}")
    if variant.buyma_item_id:
        identity_parts.append(f"BUYMA ID={variant.buyma_item_id}(参照)")
    if url_style_hint:
        identity_parts.append("URL型番ヒントあり")
    elif ref and url:
        identity_parts.append("URL型番ヒントなし")

    if scraped_style_id:
        identity_parts.append(f"仕入ID={scraped_style_id}")
    elif ref:
        identity_parts.append("仕入ID未取得")

    if not ref:
        return MatchScore(
            grade="F",
            identity_note="照合用型番なし",
            price_note=price_note or "型番未確定",
        )

    if not style_match:
        return MatchScore(
            grade="F",
            identity_note="; ".join(identity_parts) + " → 型番不一致",
            price_note=price_note or "別SKUの可能性",
        )

    if not price_ok:
        return MatchScore(
            grade="F",
            identity_note="; ".join(identity_parts),
            price_note=price_note or "妥当な価格なし",
        )

    if not in_stock:
        g = "B" if grade_ok else "C"
        return MatchScore(
            grade=g,
            identity_note="; ".join(identity_parts) + f"; 在庫={stock_status}",
            price_note=price_note or "在庫不明・欠品",
        )

    if not grade_ok:
        return MatchScore(
            grade="B",
            identity_note="; ".join(identity_parts),
            price_note=price_note or f"利益判定={purchase_grade or '?'}",
        )

    if url_style_hint and ref:
        grade: MatchGrade = "S"
    else:
        grade = "A"

    return MatchScore(
        grade=grade,
        identity_note="; ".join(identity_parts),
        price_note=price_note or "価格妥当・在庫あり",
    )


def score_when_no_supply(
    variant: VariantKey,
    *,
    reason: str = "",
) -> MatchScore:
    """仕入先・価格が取れなかったとき。"""
    ref = variant.match_ref
    if not ref:
        return MatchScore("F", "照合用型番なし", reason or "仕入先なし")
    return MatchScore(
        "C" if ref else "F",
        f"型番={ref}; 仕入先未確定",
        reason or "仕入先なし",
    )


def summarize_best_source_result(
    variant: VariantKey,
    *,
    best_url: str = "",
    best_style_id: str | None = None,
    best_stock: str = "unknown",
    best_price_ok: bool = False,
    best_price_note: str = "",
    purchase_grade: str = "",
    brand: str = "",
    official_sku: str = "",
) -> MatchScore:
    """選定 URL の URL 型番ヒントを含めてスコア化。"""
    url_hint = False
    if variant.match_ref and best_url:
        from lib.supply_search_utils import url_matches_style_hint

        url_hint = url_matches_style_hint(
            variant.match_ref, best_url,
        )
    base = score_from_best_candidate(
        variant,
        url=best_url,
        scraped_style_id=best_style_id,
        stock_status=best_stock,
        price_ok=best_price_ok,
        price_note=best_price_note,
        purchase_grade=purchase_grade,
        url_style_hint=url_hint,
    )
    ref = variant.match_ref
    if not ref or not official_sku:
        return base
    from lib.style_id_utils import style_ids_equivalent

    if style_ids_equivalent(official_sku, best_style_id or ref):
        note = base.identity_note + f"; 公式SKU一致={official_sku}"
        if base.grade == "A" and url_hint:
            return MatchScore("S", note, base.price_note)
        if base.grade == "A":
            return MatchScore("A", note, base.price_note)
    return base
