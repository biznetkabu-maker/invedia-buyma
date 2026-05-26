"""
BUYMA 候補の漏斗（ファネル）自動化ポリシー。

方針・上限・除外は funnel_policy.py を参照（単一ソース）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from lib.funnel_policy import (
    POLICY_ID,
    POLICY_LABEL,
    SKIP_NO_STYLE,
    SKIP_OUT_OF_SCOPE,
    STATUS_AUTO_SKIP_PREFIX,
    STATUS_BUYMA_CANDIDATE,
    funnel_enabled,
    is_hard_excluded_product_name,
    require_style_id,
    rescue_hint,
    weekly_auto_limit,
)

if TYPE_CHECKING:
    from lib.sheet_manager import ProductRecord, SheetManager


@dataclass(frozen=True)
class FunnelEligibility:
    eligible: bool
    reason: str = ""
    skip_status: str = ""


@dataclass(frozen=True)
class AutoIntakeOutcome:
    success: bool
    skip_status: str = ""


def resolve_sheet_style_id(record: "ProductRecord") -> str:
    from lib.product_identity import VariantKey

    return VariantKey.from_record(record).match_ref


def is_non_apparel_product_name(name: str) -> bool:
    return is_hard_excluded_product_name(name)


def is_eyewear_product_name(name: str) -> bool:
    from lib.funnel_policy import is_eyewear_product_name as _is_eye

    return _is_eye(name)


def is_auto_skip_status(status: str) -> bool:
    s = (status or "").strip()
    return s.startswith(STATUS_AUTO_SKIP_PREFIX)


def assess_record_eligibility(record: "ProductRecord") -> FunnelEligibility:
    """シート行が --auto-sheet 対象か（方針A）。"""
    if not funnel_enabled():
        return FunnelEligibility(True)

    status = (record.在庫ステータス or "").strip()
    if status != STATUS_BUYMA_CANDIDATE:
        return FunnelEligibility(
            False,
            reason=f"在庫ステータスが {STATUS_BUYMA_CANDIDATE} ではない",
            skip_status=SKIP_OUT_OF_SCOPE,
        )

    name = (record.商品名 or record.ブランド or "").strip()
    preset = _preset_supply_urls(record)

    if is_hard_excluded_product_name(name):
        if _re_nylon_pouch(name):
            reason = "Re-Nylon ポーチ系は自動対象外（候補URLsで救済可）"
        else:
            reason = "香水・コスメ等は自動対象外"
        return FunnelEligibility(False, reason=reason, skip_status=SKIP_OUT_OF_SCOPE)

    style = resolve_sheet_style_id(record)
    if require_style_id() and not style and not preset:
        return FunnelEligibility(
            False,
            reason="型番なし（BUYMA商品IDのみ）かつ候補URLsなし",
            skip_status=SKIP_NO_STYLE,
        )

    return FunnelEligibility(True)


def _re_nylon_pouch(name: str) -> bool:
    import re

    return bool(
        re.search(
            r"re[-\s]?nylon.*(?:ポーチ|pouch)|(?:ポーチ|pouch).*re[-\s]?nylon",
            name or "",
            re.I,
        )
    )


def filter_eligible_records(
    records: list["ProductRecord"],
    *,
    limit: int = 0,
) -> tuple[list["ProductRecord"], list[tuple["ProductRecord", FunnelEligibility]]]:
    eligible: list[ProductRecord] = []
    skipped: list[tuple[ProductRecord, FunnelEligibility]] = []
    cap = limit if limit > 0 else weekly_auto_limit()

    for rec in records:
        verdict = assess_record_eligibility(rec)
        if verdict.eligible:
            eligible.append(rec)
            if len(eligible) >= cap:
                break
        else:
            skipped.append((rec, verdict))
    return eligible, skipped


def _preset_supply_urls(record: "ProductRecord") -> list[str]:
    from lib.buyma_style_id import is_buyma_item_url

    urls = record.candidate_url_list()
    return [
        u for u in urls
        if u.strip() and "buyma.com" not in u.lower()
        and not is_buyma_item_url(u)
    ]


def mark_auto_skip(
    manager: Optional["SheetManager"],
    product_name: str,
    skip_status: str,
) -> bool:
    if not manager or not (product_name or "").strip():
        return False
    if not skip_status.startswith(STATUS_AUTO_SKIP_PREFIX):
        skip_status = f"{STATUS_AUTO_SKIP_PREFIX}_{skip_status}"
    return manager.update_status(product_name.strip(), skip_status)


def print_funnel_banner() -> None:
    print(
        f"  [漏斗モード 方針{POLICY_ID}] {POLICY_LABEL} / "
        f"週次上限 {weekly_auto_limit()} 件 / "
        f"型番必須={'ON' if require_style_id() else 'OFF'}"
    )
    print(f"  失敗→自動見送り（削除しない）/ 救済: {rescue_hint()}")
