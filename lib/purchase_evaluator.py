"""
仕入れ判断エンジン — PurchaseEvaluator

BUYMAにおけるブランド品仕入れの可否を、4大基準に基づいてA〜E判定する。

評価基準と重み:
  1. 発送・物流基準  (weight: 30%) ← 最優先（BUYMAの18日以内ルール）
  2. 市場需要基準    (weight: 25%) ← 売れる確度
  3. 経済性基準      (weight: 30%) ← 利益計算
  4. リスク管理基準  (weight: 15%) ← 真正性・規約遵守

グレード:
  A (85-100): 仕入れ強く推奨 — 全基準クリア。即出品可。
  B (70-84) : 仕入れ推奨     — 大部分クリア。軽微なリスクあり。
  C (55-69) : 条件付き推奨   — 要注意点あり。条件改善で仕入れ可。
  D (40-54) : 仕入れ非推奨   — 重大な懸念。見送り推奨。
  E (0-39)  : 仕入れ禁止     — 基準未達 or BUYMA規約違反リスク。

即時E判定（Disqualifier）:
  - 発送+到着が合計18日超（BUYMA発送期限違反）
  - 仕入れ先が不明（真正性リスク）
  - 現地発送まで10日超
  - 計算後の利益がマイナス
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from lib.profit_calculator import ProfitBreakdown, calculate_profit

logger = logging.getLogger(__name__)

# ============================================================================
# スコアリング重み・しきい値定数
# ============================================================================

# 4大基準の重み
WEIGHT_LOGISTICS = 0.30
WEIGHT_DEMAND = 0.25
WEIGHT_ECONOMICS = 0.30
WEIGHT_RISK = 0.15

# 物流サブスコアの重み
W_DISPATCH = 0.35
W_ARRIVAL = 0.35
W_STOCK = 0.20
W_PACKAGING = 0.10

# 需要サブスコアの重み
W_BRAND_POWER = 0.35
W_SCARCITY = 0.35
W_RESPONSE = 0.30

# 経済性サブスコアの重み
W_PROFIT_RATE = 0.55
W_PRICE_DIFF = 0.30
W_FX_BUFFER = 0.15

# リスクサブスコアの重み
W_AUTHENTICITY = 0.50
W_MODEL_AGE = 0.35
W_VOLUME_ZONE = 0.15

# E判定しきい値
MAX_OVERALL_ON_DISQUALIFY = 39.0

# ============================================================================
# データモデル
# ============================================================================

@dataclass(frozen=True)
class EvaluationInput:
    """仕入れ評価に必要な入力データ。

    Attributes:
        product_name: 商品名
        brand: ブランド名
        model_year: モデル年（例: 2024）
        source_url: 仕入れURL
        source_price: 現地価格（外貨）
        currency: 通貨コード（例: "USD", "EUR"）
        exchange_rate: 為替レート（1外貨単位 = X円）
        buyma_price: BUYMA予定販売価格（JPY）
        japan_retail_price: 日本公式定価（JPY）。不明な場合は 0。

        dispatch_days: 注文から現地発送までの日数
        japan_arrival_days: 現地発送から日本着までの日数
        is_realtime_stock: 仕入れ先の在庫がリアルタイム表示か
        packaging_quality: 梱包品質 "excellent" / "good" / "unknown"

        buyma_rank: BUYMA内お気に入り順位（不明は None）
        sns_trending: SNSでトレンド中か
        japan_soldout: 国内完売か
        japan_exclusive: 日本未入荷カラー/サイズか
        favorites_count: 直近1週間のお気に入り登録数
        has_cart_addition: 直近1週間でカート投入が発生しているか

        source_type: 仕入れ先種別
            "official"    = ブランド公式オンラインストア
            "authorized"  = 正規販売代理店・百貨店
            "select"      = 大手セレクトショップ（BUYMA認定リスト）
            "unknown"     = 不明（即時E判定）
        is_volume_zone: 日本人ボリュームゾーン（Mサイズ・定番色）か

        customs_rate: 関税率（default: 0.10 = 10%）
        shipping_cost_jpy: 国際送料固定費 JPY（default: 2000）
        buyma_fee_rate: BUYMA手数料率（default: 0.077 = 7.7%）
        fx_buffer_rate: 為替リスクバッファ率（default: 0.03 = 3%）
        target_profit_rate: 目標利益率（default: 0.15 = 15%）
        product_category: 商品カテゴリ（例: "bag", "wallet", "sneaker"）。
            空文字列でも可。product_name と合わせて定番カテゴリ判定に使用する。
    """

    product_name: str
    brand: str
    model_year: int
    source_url: str
    source_price: float
    currency: str
    exchange_rate: float
    buyma_price: float
    japan_retail_price: float

    dispatch_days: int
    japan_arrival_days: int
    is_realtime_stock: bool
    packaging_quality: str

    buyma_rank: Optional[int]
    sns_trending: bool
    japan_soldout: bool
    japan_exclusive: bool
    favorites_count: int
    has_cart_addition: bool

    source_type: str
    is_volume_zone: bool

    customs_rate: float = 0.10
    shipping_cost_jpy: float = 2000.0
    buyma_fee_rate: float = 0.077
    fx_buffer_rate: float = 0.03
    target_profit_rate: float = 0.15
    product_category: str = ""


@dataclass
class SubScore:
    """1つのサブ評価項目の結果。"""

    name: str
    score: float        # 0.0 〜 100.0
    max_score: float    # 最大点数
    reason: str         # スコアの理由（人間向け説明）
    passed: bool        # この項目を通過したか


@dataclass
class CriterionResult:
    """4大基準のうち1つの評価結果。"""

    name: str
    weight: float               # 重み係数 (0.0 〜 1.0)
    sub_scores: list[SubScore]
    weighted_score: float       # weight × aggregate_score (0.0 〜 100.0)
    aggregate_score: float      # 集計後スコア (0.0 〜 100.0)
    passed: bool
    disqualified: bool = False
    disqualify_reason: str = ""

    @property
    def contribution(self) -> float:
        """全体スコアへの貢献度 (0〜weight*100)。"""
        return self.aggregate_score * self.weight


@dataclass
class PurchaseScore:
    """仕入れ評価の最終結果。"""

    product_name: str
    brand: str
    source_url: str

    logistics: CriterionResult
    demand: CriterionResult
    economics: CriterionResult
    risk: CriterionResult

    overall_score: float
    grade: str
    grade_label: str

    profit_breakdown: Optional[ProfitBreakdown]
    effective_profit_rate: float     # FX バッファ込みの実質利益率

    critical_issues: list[str]
    improvements: list[str]
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_recommended(self) -> bool:
        """グレード A / B （仕入れ推奨）かどうか。"""
        return self.grade in ("A", "B")

    def summary(self) -> str:
        """評価結果全体（スコア・内訳・課題・提案）をコンソール用文字列に整形する。"""
        lines = [
            f"{'='*60}",
            f"  商品: {self.product_name} ({self.brand})",
            f"  総合スコア: {self.overall_score:.1f} / 100  →  グレード {self.grade}（{self.grade_label}）",
            f"{'='*60}",
            f"  物流    : {self.logistics.aggregate_score:5.1f} pts  (重み {self.logistics.weight:.0%})",
            f"  市場需要: {self.demand.aggregate_score:5.1f} pts  (重み {self.demand.weight:.0%})",
            f"  経済性  : {self.economics.aggregate_score:5.1f} pts  (重み {self.economics.weight:.0%})",
            f"  リスク  : {self.risk.aggregate_score:5.1f} pts  (重み {self.risk.weight:.0%})",
        ]

        if self.profit_breakdown:
            pb = self.profit_breakdown
            lines += [
                f"  {'─'*56}",
                f"  利益額: ¥{pb.profit:,.0f}  (実質利益率: {self.effective_profit_rate:.1%})",
                f"  コスト内訳: 仕入 ¥{pb.jpy_cost:,.0f} + 関税 ¥{pb.customs_cost:,.0f}"
                f" + 送料 ¥{pb.shipping_cost:,.0f} + 手数料 ¥{pb.buyma_fee:,.0f}",
            ]

        if self.critical_issues:
            lines.append(f"  {'─'*56}")
            lines.append("  ⚠️  致命的問題:")
            lines.extend(f"    - {issue}" for issue in self.critical_issues)

        if self.improvements:
            lines.append("  💡 改善提案:")
            lines.extend(f"    - {imp}" for imp in self.improvements)

        lines.append(f"{'='*60}")
        return "\n".join(lines)


# ============================================================================
# 評価エンジン
# ============================================================================

_GRADE_MAP: list[tuple[float, str, str]] = [
    (85.0, "A", "仕入れ強く推奨 — 全基準クリア。即出品可"),
    (70.0, "B", "仕入れ推奨 — 大部分クリア。軽微なリスクあり"),
    (55.0, "C", "条件付き推奨 — 要注意点あり。条件改善で仕入れ可"),
    (40.0, "D", "仕入れ非推奨 — 重大な懸念。見送り推奨"),
    (0.0,  "E", "仕入れ禁止 — 基準未達またはBUYMA規約違反リスク"),
]

_CURRENT_YEAR = datetime.now(timezone.utc).year

# ──────────────────────────────────────────────────────────────────────────────
# 推奨ブランド／定番カテゴリ定数
# ──────────────────────────────────────────────────────────────────────────────

# BUYMAで安定需要があり初心者でも仕入れやすいハイブランド（小文字キーワード）
RECOMMENDED_BRANDS: tuple[str, ...] = (
    "celine",
    "saint laurent",
    "ysl",
    "maison margiela",
    "margiela",
    "jil sander",
    "balenciaga",
)

# 需要が安定している定番カテゴリ（財布・バッグ・スニーカー）
STABLE_CATEGORIES: tuple[str, ...] = (
    "bag", "バッグ",
    "wallet", "財布",
    "sneaker", "スニーカー",
)


def _is_recommended_brand(brand: str) -> bool:
    """ブランド名が推奨ブランドリストに含まれるか判定する（大文字小文字不問）。"""
    b = brand.lower()
    return any(kw in b for kw in RECOMMENDED_BRANDS)


def _is_stable_category(product_name: str, product_category: str) -> bool:
    """商品名またはカテゴリが定番カテゴリ（財布・バッグ・スニーカー）に該当するか判定する。"""
    combined = (product_name + " " + product_category).lower()
    return any(kw in combined for kw in STABLE_CATEGORIES)


class PurchaseEvaluator:
    """ブランド品仕入れの可否を4大基準で評価するエンジン。

    Args:
        buyma_max_days: BUYMAの発送上限日数（default: 18日）。
    """

    def __init__(self, buyma_max_days: int = 18) -> None:
        self._buyma_max_days = buyma_max_days

    # ─────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────

    def evaluate(self, inp: EvaluationInput) -> PurchaseScore:
        """EvaluationInput を受け取り、PurchaseScore を返す。"""

        # 各基準を評価
        logistics = self._score_logistics(inp)
        demand = self._score_demand(inp)
        economics = self._score_economics(inp)
        risk = self._score_risk(inp)

        # 利益計算（FXバッファ込み）
        effective_rate = inp.exchange_rate * (1 + inp.fx_buffer_rate)
        profit_breakdown: Optional[ProfitBreakdown] = None
        effective_profit_rate = 0.0
        try:
            profit_breakdown = calculate_profit(
                local_price=inp.source_price,
                exchange_rate=effective_rate,
                buyma_price=inp.buyma_price,
                customs_rate=inp.customs_rate,
                shipping_cost=inp.shipping_cost_jpy,
                buyma_fee_rate=inp.buyma_fee_rate,
            )
            effective_profit_rate = profit_breakdown.profit_rate
        except Exception:
            logger.debug("利益率計算失敗", exc_info=True)

        # 総合スコア（重み付き合計）
        criteria = [logistics, demand, economics, risk]
        overall = sum(c.aggregate_score * c.weight for c in criteria)

        # 致命的問題 → E に降格
        critical_issues = self._collect_critical_issues(
            inp, logistics, demand, economics, risk
        )
        if critical_issues:
            overall = min(overall, MAX_OVERALL_ON_DISQUALIFY)

        overall = round(overall, 2)

        grade, grade_label = self._grade(overall)
        improvements = self._generate_improvements(inp, logistics, demand, economics, risk)

        return PurchaseScore(
            product_name=inp.product_name,
            brand=inp.brand,
            source_url=inp.source_url,
            logistics=logistics,
            demand=demand,
            economics=economics,
            risk=risk,
            overall_score=overall,
            grade=grade,
            grade_label=grade_label,
            profit_breakdown=profit_breakdown,
            effective_profit_rate=effective_profit_rate,
            critical_issues=critical_issues,
            improvements=improvements,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 基準1: 発送・物流
    # ─────────────────────────────────────────────────────────────────────

    def _score_logistics(self, inp: EvaluationInput) -> CriterionResult:
        total_days = inp.dispatch_days + inp.japan_arrival_days

        # 現地発送スピード
        d = inp.dispatch_days
        if d <= 3:
            disp_score, disp_reason = 100, f"{d}日以内発送（最速）"
        elif d <= 5:
            disp_score, disp_reason = 80, f"{d}日以内発送（良好）"
        elif d <= 7:
            disp_score, disp_reason = 55, f"{d}日発送（やや遅い）"
        elif d <= 10:
            disp_score, disp_reason = 25, f"{d}日発送（リスクあり）"
        else:
            disp_score, disp_reason = 0, f"{d}日発送（発送期限違反の恐れ）"

        # 日本着スピード
        a = inp.japan_arrival_days
        if a <= 5:
            arr_score, arr_reason = 100, f"発送後{a}日着（最速）"
        elif a <= 10:
            arr_score, arr_reason = 80, f"発送後{a}日着（良好）"
        elif a <= 14:
            arr_score, arr_reason = 55, f"発送後{a}日着（やや遅い）"
        elif a <= 18:
            arr_score, arr_reason = 30, f"発送後{a}日着（ギリギリ）"
        else:
            arr_score, arr_reason = 0, f"発送後{a}日着（期限超過）"

        # BUYMAルール上の合計チェック
        disqualified = total_days > self._buyma_max_days
        disqualify_reason = (
            f"合計{total_days}日 > BUYMA上限{self._buyma_max_days}日" if disqualified else ""
        )

        # 在庫精度
        stock_score = 100 if inp.is_realtime_stock else 30
        stock_reason = "リアルタイム在庫（安全）" if inp.is_realtime_stock else "在庫非リアルタイム（取り寄せリスク）"

        # 梱包品質
        pkg_map = {"excellent": (100, "最高品質梱包"), "good": (70, "良好な梱包"), "unknown": (35, "梱包品質不明")}
        pkg_score, pkg_reason = pkg_map.get(inp.packaging_quality, (35, "梱包品質不明"))

        sub_scores = [
            SubScore("現地発送スピード", disp_score, 100, disp_reason, disp_score >= 55),
            SubScore("日本着スピード",   arr_score,  100, arr_reason,  arr_score >= 55),
            SubScore("在庫精度",         stock_score,100, stock_reason, inp.is_realtime_stock),
            SubScore("梱包品質",         pkg_score,  100, pkg_reason,  pkg_score >= 70),
        ]

        # 発送スピードを重視した重み付き平均
        agg = (disp_score * W_DISPATCH + arr_score * W_ARRIVAL + stock_score * W_STOCK + pkg_score * W_PACKAGING)

        return CriterionResult(
            name="発送・物流基準",
            weight=WEIGHT_LOGISTICS,
            sub_scores=sub_scores,
            aggregate_score=round(agg, 2),
            weighted_score=round(agg * WEIGHT_LOGISTICS, 2),
            passed=not disqualified and agg >= 55,
            disqualified=disqualified,
            disqualify_reason=disqualify_reason,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 基準2: 市場需要
    # ─────────────────────────────────────────────────────────────────────

    def _score_demand(self, inp: EvaluationInput) -> CriterionResult:
        # ブランド力
        rank = inp.buyma_rank
        if rank is not None:
            if rank <= 10:
                brand_score = 100
            elif rank <= 50:
                brand_score = 80
            elif rank <= 100:
                brand_score = 65
            elif rank <= 200:
                brand_score = 50
            else:
                brand_score = 35
        else:
            brand_score = 45
        if inp.sns_trending:
            brand_score = min(100, brand_score + 15)

        brand_reason = (
            f"BUYMAランキング{rank}位" if rank else "ランキング不明"
        ) + ("、SNSトレンド中" if inp.sns_trending else "")

        # 推奨ブランドボーナス（CELINE・Saint Laurent・Maison Margiela・Jil Sander・Balenciaga）
        if _is_recommended_brand(inp.brand):
            brand_score = min(100, brand_score + 10)
            brand_reason += "（推奨ブランド）"

        # 定番カテゴリボーナス（財布・バッグ・スニーカー）
        if _is_stable_category(inp.product_name, inp.product_category):
            brand_score = min(100, brand_score + 5)
            brand_reason += "、定番カテゴリ"

        # 希少性
        both_rare = inp.japan_soldout and inp.japan_exclusive
        if both_rare:
            scar_score, scar_reason = 100, "国内完売 かつ 日本未入荷"
        elif inp.japan_soldout:
            scar_score, scar_reason = 85, "国内完売"
        elif inp.japan_exclusive:
            scar_score, scar_reason = 80, "日本未入荷カラー/サイズ"
        else:
            scar_score, scar_reason = 40, "希少性なし"

        # 反応値
        fav = inp.favorites_count
        if fav >= 20 and inp.has_cart_addition:
            resp_score, resp_reason = 100, f"お気に入り{fav}件＋カート投入あり"
        elif fav >= 20:
            resp_score, resp_reason = 80, f"お気に入り{fav}件"
        elif inp.has_cart_addition:
            resp_score, resp_reason = 65, f"カート投入あり（お気に入り{fav}件）"
        elif fav >= 10:
            resp_score, resp_reason = 45, f"お気に入り{fav}件"
        elif fav > 0:
            resp_score, resp_reason = 20 + fav * 2, f"お気に入り{fav}件"
        else:
            resp_score, resp_reason = 15, "反応値なし"

        sub_scores = [
            SubScore("ブランド力",  brand_score, 100, brand_reason,  brand_score >= 50),
            SubScore("希少性",      scar_score,  100, scar_reason,   scar_score  >= 70),
            SubScore("反応値",      resp_score,  100, resp_reason,   resp_score  >= 50),
        ]
        agg = brand_score * W_BRAND_POWER + scar_score * W_SCARCITY + resp_score * W_RESPONSE

        return CriterionResult(
            name="市場需要基準",
            weight=WEIGHT_DEMAND,
            sub_scores=sub_scores,
            aggregate_score=round(agg, 2),
            weighted_score=round(agg * WEIGHT_DEMAND, 2),
            passed=agg >= 55,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 基準3: 経済性
    # ─────────────────────────────────────────────────────────────────────

    def _score_economics(self, inp: EvaluationInput) -> CriterionResult:
        # FX バッファ込みの実質為替レートで利益計算
        effective_rate = inp.exchange_rate * (1 + inp.fx_buffer_rate)
        try:
            pb = calculate_profit(
                local_price=inp.source_price,
                exchange_rate=effective_rate,
                buyma_price=inp.buyma_price,
                customs_rate=inp.customs_rate,
                shipping_cost=inp.shipping_cost_jpy,
                buyma_fee_rate=inp.buyma_fee_rate,
            )
            profit_rate = pb.profit_rate
        except Exception:
            profit_rate = -999.0

        # 利益率スコア
        pr = profit_rate
        if pr >= 0.25:
            profit_score, profit_reason = 100, f"利益率 {pr:.1%}（超高利益）"
        elif pr >= 0.20:
            profit_score, profit_reason = 90, f"利益率 {pr:.1%}（高利益）"
        elif pr >= inp.target_profit_rate:
            profit_score, profit_reason = 75, f"利益率 {pr:.1%}（目標達成）"
        elif pr >= 0.10:
            profit_score, profit_reason = 50, f"利益率 {pr:.1%}（条件付き許容圏 10〜15%）"
        elif pr >= 0.05:
            profit_score, profit_reason = 25, f"利益率 {pr:.1%}（低利益）"
        elif pr >= 0:
            profit_score, profit_reason = 10, f"利益率 {pr:.1%}（ほぼ利益なし）"
        else:
            profit_score, profit_reason = 0, f"利益率 {pr:.1%}（赤字）"

        # 内外価格差スコア
        japan_retail = inp.japan_retail_price
        jpy_cost = inp.source_price * effective_rate  # 仕入れのJPY換算
        if japan_retail > 0:
            diff_rate = (japan_retail - jpy_cost) / japan_retail
            if diff_rate >= 0.30:
                diff_score, diff_reason = 100, f"日本定価より{diff_rate:.0%}安価"
            elif diff_rate >= 0.20:
                diff_score, diff_reason = 85, f"日本定価より{diff_rate:.0%}安価"
            elif diff_rate >= 0.15:
                diff_score, diff_reason = 65, f"日本定価より{diff_rate:.0%}安価"
            elif diff_rate >= 0:
                diff_score, diff_reason = 40, f"日本定価より{diff_rate:.0%}安価（差小）"
            else:
                # 定価超えでも希少品なら許容
                if inp.japan_soldout or inp.japan_exclusive:
                    diff_score = 60
                    diff_reason = f"定価超え{abs(diff_rate):.0%}だが希少品のため許容"
                else:
                    diff_score, diff_reason = 10, f"仕入れが定価より{abs(diff_rate):.0%}高い"
        else:
            diff_score, diff_reason = 50, "日本定価データなし"

        # 為替バッファスコア
        fx = inp.fx_buffer_rate
        if fx >= 0.03:
            fx_score, fx_reason = 100, f"為替バッファ {fx:.0%}（十分）"
        elif fx >= 0.02:
            fx_score, fx_reason = 75, f"為替バッファ {fx:.0%}（最低限）"
        elif fx >= 0.01:
            fx_score, fx_reason = 45, f"為替バッファ {fx:.0%}（不十分）"
        else:
            fx_score, fx_reason = 20, "為替バッファなし（リスク高）"

        sub_scores = [
            SubScore("利益率（FXバッファ込）", profit_score, 100, profit_reason,  profit_score >= 50),
            SubScore("内外価格差",            diff_score,   100, diff_reason,    diff_score  >= 50),
            SubScore("為替リスクバッファ",     fx_score,     100, fx_reason,      fx_score    >= 75),
        ]
        agg = profit_score * W_PROFIT_RATE + diff_score * W_PRICE_DIFF + fx_score * W_FX_BUFFER

        # 赤字は即時 Disqualify
        disqualified = pr < 0
        disqualify_reason = f"利益がマイナス（{pr:.1%}）" if disqualified else ""

        return CriterionResult(
            name="経済性基準",
            weight=WEIGHT_ECONOMICS,
            sub_scores=sub_scores,
            aggregate_score=round(agg, 2),
            weighted_score=round(agg * WEIGHT_ECONOMICS, 2),
            passed=not disqualified and agg >= 55,
            disqualified=disqualified,
            disqualify_reason=disqualify_reason,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 基準4: リスク管理
    # ─────────────────────────────────────────────────────────────────────

    def _score_risk(self, inp: EvaluationInput) -> CriterionResult:
        # 真正性
        source_map = {
            "official":   (100, "ブランド公式オンラインストア"),
            "authorized": (85,  "正規販売代理店・百貨店"),
            "select":     (70,  "BUYMA認定大手セレクトショップ"),
            "unknown":    (0,   "仕入れ先不明（真正性リスク）"),
        }
        auth_score, auth_reason = source_map.get(
            inp.source_type, (0, "不明な仕入れ先種別")
        )
        auth_disqualified = inp.source_type == "unknown"

        # モデル年齢チェック（BUYMA規約：3年以上前のモデルは禁止）
        age = _CURRENT_YEAR - inp.model_year
        if age <= 0:
            age_score, age_reason = 100, f"最新モデル（{inp.model_year}年）"
        elif age == 1:
            age_score, age_reason = 90, f"1年前のモデル（{inp.model_year}年）"
        elif age == 2:
            age_score, age_reason = 65, f"2年前のモデル（{inp.model_year}年）"
        elif age == 3:
            age_score, age_reason = 25, f"3年前のモデル（{inp.model_year}年）— 規約グレーゾーン"
        else:
            age_score, age_reason = 0, f"{age}年前のモデル（{inp.model_year}年）— BUYMA規約違反"

        age_disqualified = age >= 4  # 4年以上前は即 E

        # サイズ/色
        vol_score = 85 if inp.is_volume_zone else 45
        vol_reason = "日本ボリュームゾーン（在庫リスク低）" if inp.is_volume_zone else "ニッチサイズ/色（在庫リスクあり）"

        sub_scores = [
            SubScore("真正性",      auth_score, 100, auth_reason, auth_score >= 70),
            SubScore("モデル年齢",  age_score,  100, age_reason,  age_score  >= 65),
            SubScore("サイズ/色",   vol_score,  100, vol_reason,  vol_score  >= 70),
        ]
        agg = auth_score * W_AUTHENTICITY + age_score * W_MODEL_AGE + vol_score * W_VOLUME_ZONE

        disqualified = auth_disqualified or age_disqualified
        disqualify_reason = ""
        if auth_disqualified:
            disqualify_reason = "仕入れ先が不明（真正性リスク）"
        elif age_disqualified:
            disqualify_reason = f"モデルが{age}年前（BUYMA規約違反）"

        return CriterionResult(
            name="リスク管理基準",
            weight=WEIGHT_RISK,
            sub_scores=sub_scores,
            aggregate_score=round(agg, 2),
            weighted_score=round(agg * WEIGHT_RISK, 2),
            passed=not disqualified and agg >= 55,
            disqualified=disqualified,
            disqualify_reason=disqualify_reason,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 致命的問題の収集
    # ─────────────────────────────────────────────────────────────────────

    def _collect_critical_issues(
        self,
        inp: EvaluationInput,
        logistics: CriterionResult,
        demand: CriterionResult,
        economics: CriterionResult,
        risk: CriterionResult,
    ) -> list[str]:
        issues: list[str] = []
        if logistics.disqualified:
            issues.append(f"【物流】{logistics.disqualify_reason}")
        if inp.dispatch_days > 10:
            issues.append(f"【物流】現地発送まで{inp.dispatch_days}日（BUYMAの信頼スコアに悪影響）")
        if economics.disqualified:
            issues.append(f"【経済性】{economics.disqualify_reason}")
        if risk.disqualified:
            issues.append(f"【リスク】{risk.disqualify_reason}")
        return issues

    # ─────────────────────────────────────────────────────────────────────
    # 改善提案の生成
    # ─────────────────────────────────────────────────────────────────────

    def _generate_improvements(
        self,
        inp: EvaluationInput,
        logistics: CriterionResult,
        demand: CriterionResult,
        economics: CriterionResult,
        risk: CriterionResult,
    ) -> list[str]:
        tips: list[str] = []

        if inp.dispatch_days > 5:
            tips.append("発送スピードの速い仕入れ先に切り替えるか、在庫保持型の仕入れ先を探す")
        if not inp.is_realtime_stock:
            tips.append("リアルタイム在庫表示の仕入れ先（公式サイト等）を優先する")
        if not inp.japan_soldout and not inp.japan_exclusive:
            tips.append("日本未入荷カラー/サイズに絞ることで希少性スコアを向上できる")
        if demand.aggregate_score < 60 and not _is_recommended_brand(inp.brand):
            tips.append(
                "CELINE・Saint Laurent・Maison Margiela・Jil Sander・Balenciaga等の"
                "推奨ブランドを検討することで需要スコアを改善できる"
            )
        if not _is_stable_category(inp.product_name, inp.product_category):
            tips.append("財布・バッグ・スニーカーなど定番カテゴリは需要が安定しやすい")
        if inp.favorites_count < 20:
            tips.append(f"お気に入り登録数が{inp.favorites_count}件。20件超を目安に需要確認後に仕入れる")
        if economics.aggregate_score < 70:
            tips.append(
                "BUYMA販売価格を引き上げるか、送料・関税の低い仕入れ先に変更して利益率を改善する"
            )
        if inp.source_type in ("select", "unknown"):
            tips.append("公式ストアまたは正規代理店からの仕入れに切り替え、真正性を確保する")
        if not inp.is_volume_zone:
            tips.append("日本人ボリュームゾーン（Mサイズ・定番色）を優先し、在庫リスクを下げる")
        if inp.fx_buffer_rate < 0.03:
            tips.append("為替変動バッファを最低3%以上に設定し、急激な円安リスクに備える")

        return tips

    # ─────────────────────────────────────────────────────────────────────
    # グレード判定
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _grade(score: float) -> tuple[str, str]:
        for threshold, grade, label in _GRADE_MAP:
            if score >= threshold:
                return grade, label
        return "E", _GRADE_MAP[-1][2]
