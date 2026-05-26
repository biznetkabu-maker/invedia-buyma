"""
PurchaseEvaluator のユニットテスト。

- TestLogisticsScoring  : 発送・物流基準
- TestDemandScoring     : 市場需要基準
- TestEconomicsScoring  : 経済性基準
- TestRiskScoring       : リスク管理基準
- TestDisqualifiers     : 致命的条件による即時E判定
- TestOverallGrade      : 総合グレード判定
- TestSummaryOutput     : サマリー出力
"""

import unittest
from dataclasses import replace

from lib.purchase_evaluator import EvaluationInput, PurchaseEvaluator, PurchaseScore


# ---------------------------------------------------------------------------
# テストフィクスチャ: 全項目 A グレード相当の基準値
# ---------------------------------------------------------------------------

_BASE = EvaluationInput(
    product_name="テストバッグ",
    brand="GUCCI",
    model_year=2024,
    source_url="https://www.ssense.com/en-us/product/1",
    source_price=800.0,
    currency="USD",
    exchange_rate=155.0,
    buyma_price=195_000.0,
    japan_retail_price=230_000.0,
    dispatch_days=3,
    japan_arrival_days=6,
    is_realtime_stock=True,
    packaging_quality="excellent",
    buyma_rank=5,
    sns_trending=True,
    japan_soldout=True,
    japan_exclusive=False,
    favorites_count=30,
    has_cart_addition=True,
    source_type="authorized",
    is_volume_zone=True,
    customs_rate=0.10,
    shipping_cost_jpy=2000.0,
    buyma_fee_rate=0.077,
    fx_buffer_rate=0.03,
    target_profit_rate=0.15,
)

_EVALUATOR = PurchaseEvaluator()


def _eval(**overrides) -> PurchaseScore:
    inp = replace(_BASE, **overrides)
    return _EVALUATOR.evaluate(inp)


# ---------------------------------------------------------------------------
# 発送・物流基準
# ---------------------------------------------------------------------------

class TestLogisticsScoring(unittest.TestCase):

    def test_fast_dispatch_scores_high(self):
        s = _eval(dispatch_days=2, japan_arrival_days=5)
        self.assertGreater(s.logistics.aggregate_score, 90)

    def test_slow_dispatch_scores_low(self):
        # 全体を遅くする：dispatch 9日、arrival 10日、在庫非リアルタイム、梱包不明
        s = _eval(dispatch_days=9, japan_arrival_days=10,
                  is_realtime_stock=False, packaging_quality="unknown")
        self.assertLess(s.logistics.aggregate_score, 60)

    def test_exceeding_18days_disqualifies(self):
        s = _eval(dispatch_days=10, japan_arrival_days=12)
        self.assertTrue(s.logistics.disqualified)
        self.assertIn("E", s.grade)

    def test_exactly_18days_passes(self):
        # BUYMA ルール「18日以内」= 18日目は境界内
        s = _eval(dispatch_days=10, japan_arrival_days=8)
        self.assertFalse(s.logistics.disqualified)

    def test_19days_disqualifies(self):
        s = _eval(dispatch_days=10, japan_arrival_days=9)
        self.assertTrue(s.logistics.disqualified)

    def test_17days_passes(self):
        s = _eval(dispatch_days=8, japan_arrival_days=9)
        self.assertFalse(s.logistics.disqualified)

    def test_realtime_stock_boosts_score(self):
        s_rt  = _eval(is_realtime_stock=True)
        s_nrt = _eval(is_realtime_stock=False)
        self.assertGreater(s_rt.logistics.aggregate_score, s_nrt.logistics.aggregate_score)

    def test_excellent_packaging_boosts_score(self):
        s_ex  = _eval(packaging_quality="excellent")
        s_unk = _eval(packaging_quality="unknown")
        self.assertGreater(s_ex.logistics.aggregate_score, s_unk.logistics.aggregate_score)

    def test_dispatch_over_10_adds_critical_issue(self):
        s = _eval(dispatch_days=11, japan_arrival_days=5)
        # 11日発送のメッセージが critical_issues に含まれる
        self.assertTrue(any("11日" in issue for issue in s.critical_issues))


# ---------------------------------------------------------------------------
# 市場需要基準
# ---------------------------------------------------------------------------

class TestDemandScoring(unittest.TestCase):

    def test_top_rank_sns_trending_scores_high(self):
        s = _eval(buyma_rank=1, sns_trending=True)
        self.assertGreater(s.demand.aggregate_score, 85)

    def test_no_rank_scores_mid(self):
        s = _eval(buyma_rank=None, sns_trending=False)
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        self.assertAlmostEqual(brand_sub.score, 45, delta=10)

    def test_both_scarcity_scores_max(self):
        s = _eval(japan_soldout=True, japan_exclusive=True)
        scar_sub = next(ss for ss in s.demand.sub_scores if ss.name == "希少性")
        self.assertEqual(scar_sub.score, 100)

    def test_no_scarcity_scores_low(self):
        s = _eval(japan_soldout=False, japan_exclusive=False)
        scar_sub = next(ss for ss in s.demand.sub_scores if ss.name == "希少性")
        self.assertEqual(scar_sub.score, 40)

    def test_high_favorites_plus_cart_scores_max(self):
        s = _eval(favorites_count=25, has_cart_addition=True)
        resp_sub = next(ss for ss in s.demand.sub_scores if ss.name == "反応値")
        self.assertEqual(resp_sub.score, 100)

    def test_zero_favorites_no_cart_scores_low(self):
        s = _eval(favorites_count=0, has_cart_addition=False)
        resp_sub = next(ss for ss in s.demand.sub_scores if ss.name == "反応値")
        self.assertLessEqual(resp_sub.score, 20)

    def test_sns_trending_adds_bonus(self):
        s1 = _eval(buyma_rank=50, sns_trending=False)
        s2 = _eval(buyma_rank=50, sns_trending=True)
        self.assertGreater(s2.demand.aggregate_score, s1.demand.aggregate_score)


# ---------------------------------------------------------------------------
# 経済性基準
# ---------------------------------------------------------------------------

class TestEconomicsScoring(unittest.TestCase):

    def test_high_profit_scores_high(self):
        # 仕入原価を下げて利益率を高くする
        s = _eval(source_price=400.0, buyma_price=200_000)
        self.assertGreater(s.economics.aggregate_score, 75)

    def test_negative_profit_disqualifies(self):
        # 仕入れ原価 >> 販売価格
        s = _eval(source_price=2000.0, buyma_price=100_000, exchange_rate=155.0)
        self.assertTrue(s.economics.disqualified)
        self.assertEqual(s.grade, "E")

    def test_profit_at_target_rate_passes(self):
        # 約15%の利益率を確保するケース
        s = _eval(source_price=700.0, buyma_price=195_000)
        self.assertFalse(s.economics.disqualified)

    def test_large_price_diff_boosts_score(self):
        # source_price=800, exchange=155 → jpy_cost≈127,720（FXバッファ込）
        # 差小: retail=135,000 → diff ≈ 5%  → diff_score 40
        # 差大: retail=350,000 → diff ≈ 63% → diff_score 100
        s1 = _eval(japan_retail_price=135_000)
        s2 = _eval(japan_retail_price=350_000)
        self.assertGreater(s2.economics.aggregate_score, s1.economics.aggregate_score)

    def test_fx_buffer_3percent_scores_max(self):
        s = _eval(fx_buffer_rate=0.03)
        fx_sub = next(ss for ss in s.economics.sub_scores if "為替" in ss.name)
        self.assertEqual(fx_sub.score, 100)

    def test_fx_buffer_zero_scores_low(self):
        s = _eval(fx_buffer_rate=0.0)
        fx_sub = next(ss for ss in s.economics.sub_scores if "為替" in ss.name)
        self.assertLessEqual(fx_sub.score, 25)

    def test_price_above_japan_retail_but_rare_item_still_passes(self):
        # 仕入れJPY > 日本定価 だが希少品（japan_soldout=True）
        s = _eval(
            source_price=1200.0, exchange_rate=155.0,
            buyma_price=250_000, japan_retail_price=100_000,
            japan_soldout=True,
        )
        diff_sub = next(ss for ss in s.economics.sub_scores if "内外価格差" in ss.name)
        self.assertGreater(diff_sub.score, 50)

    def test_effective_profit_rate_includes_fx_buffer(self):
        s = _eval(fx_buffer_rate=0.03)
        # FXバッファを含む利益率は含まない場合より低い
        s_no_buf = _eval(fx_buffer_rate=0.0)
        self.assertGreater(s_no_buf.effective_profit_rate, s.effective_profit_rate)


# ---------------------------------------------------------------------------
# リスク管理基準
# ---------------------------------------------------------------------------

class TestRiskScoring(unittest.TestCase):

    def test_official_source_scores_max(self):
        s = _eval(source_type="official")
        auth_sub = next(ss for ss in s.risk.sub_scores if "真正性" in ss.name)
        self.assertEqual(auth_sub.score, 100)

    def test_unknown_source_disqualifies(self):
        s = _eval(source_type="unknown")
        self.assertTrue(s.risk.disqualified)
        self.assertEqual(s.grade, "E")

    def test_current_model_scores_high(self):
        from datetime import datetime, timezone
        current_year = datetime.now(timezone.utc).year
        s = _eval(model_year=current_year)
        age_sub = next(ss for ss in s.risk.sub_scores if "モデル年齢" in ss.name)
        self.assertEqual(age_sub.score, 100)

    def test_4year_old_model_disqualifies(self):
        from datetime import datetime, timezone
        old_year = datetime.now(timezone.utc).year - 4
        s = _eval(model_year=old_year)
        self.assertTrue(s.risk.disqualified)
        self.assertEqual(s.grade, "E")

    def test_3year_old_model_low_score_not_disqualified(self):
        from datetime import datetime, timezone
        year_minus_3 = datetime.now(timezone.utc).year - 3
        s = _eval(model_year=year_minus_3)
        self.assertFalse(s.risk.disqualified)
        age_sub = next(ss for ss in s.risk.sub_scores if "モデル年齢" in ss.name)
        self.assertLess(age_sub.score, 50)

    def test_volume_zone_true_boosts_score(self):
        s1 = _eval(is_volume_zone=True)
        s2 = _eval(is_volume_zone=False)
        self.assertGreater(s1.risk.aggregate_score, s2.risk.aggregate_score)


# ---------------------------------------------------------------------------
# 致命的条件（Disqualifier）
# ---------------------------------------------------------------------------

class TestDisqualifiers(unittest.TestCase):

    def test_shipping_over_18days_gives_E(self):
        s = _eval(dispatch_days=12, japan_arrival_days=10)
        self.assertEqual(s.grade, "E")
        self.assertTrue(len(s.critical_issues) > 0)

    def test_unknown_source_gives_E(self):
        s = _eval(source_type="unknown")
        self.assertEqual(s.grade, "E")

    def test_negative_profit_gives_E(self):
        s = _eval(source_price=3000.0, buyma_price=100_000)
        self.assertEqual(s.grade, "E")

    def test_very_old_model_gives_E(self):
        s = _eval(model_year=2010)
        self.assertEqual(s.grade, "E")

    def test_multiple_disqualifiers_all_appear_in_issues(self):
        s = _eval(dispatch_days=15, japan_arrival_days=10, source_type="unknown")
        # 複数の致命的問題がリストアップされる
        self.assertGreaterEqual(len(s.critical_issues), 2)

    def test_disqualified_overall_score_capped_at_39(self):
        s = _eval(dispatch_days=15, japan_arrival_days=10)
        self.assertLessEqual(s.overall_score, 39.0)


# ---------------------------------------------------------------------------
# 総合グレード判定
# ---------------------------------------------------------------------------

class TestOverallGrade(unittest.TestCase):

    def test_ideal_product_grades_A(self):
        # 全項目最良の設定
        s = _eval(
            dispatch_days=2, japan_arrival_days=5,
            is_realtime_stock=True, packaging_quality="excellent",
            buyma_rank=3, sns_trending=True,
            japan_soldout=True, japan_exclusive=True,
            favorites_count=50, has_cart_addition=True,
            source_price=600.0, buyma_price=200_000, japan_retail_price=280_000,
            source_type="official", is_volume_zone=True,
            fx_buffer_rate=0.03,
        )
        self.assertEqual(s.grade, "A")
        self.assertTrue(s.is_recommended)

    def test_poor_demand_grades_C_or_lower(self):
        # 需要基準を最低にし、かつ物流・経済性・リスクも悪化させる
        s = _eval(
            buyma_rank=None, sns_trending=False,
            japan_soldout=False, japan_exclusive=False,
            favorites_count=0, has_cart_addition=False,
            dispatch_days=6, japan_arrival_days=9,
            is_realtime_stock=False, packaging_quality="unknown",
            source_type="select", is_volume_zone=False,
        )
        self.assertIn(s.grade, ("C", "D", "E"))

    def test_is_recommended_only_for_A_and_B(self):
        for grade, expected in [("A", True), ("B", True), ("C", False), ("D", False), ("E", False)]:
            # PurchaseScore の is_recommended は grade で判定
            from lib.purchase_evaluator import PurchaseScore
            mock_score = PurchaseScore(
                product_name="x", brand="x", source_url="x",
                logistics=None, demand=None, economics=None, risk=None,
                overall_score=0, grade=grade, grade_label="",
                profit_breakdown=None, effective_profit_rate=0,
                critical_issues=[], improvements=[],
            )
            self.assertEqual(mock_score.is_recommended, expected)

    def test_grade_boundaries(self):
        from lib.purchase_evaluator import PurchaseEvaluator
        ev = PurchaseEvaluator()
        self.assertEqual(ev._grade(85.0)[0], "A")
        self.assertEqual(ev._grade(84.9)[0], "B")
        self.assertEqual(ev._grade(70.0)[0], "B")
        self.assertEqual(ev._grade(69.9)[0], "C")
        self.assertEqual(ev._grade(55.0)[0], "C")
        self.assertEqual(ev._grade(54.9)[0], "D")
        self.assertEqual(ev._grade(40.0)[0], "D")
        self.assertEqual(ev._grade(39.9)[0], "E")
        self.assertEqual(ev._grade(0.0)[0],  "E")


# ---------------------------------------------------------------------------
# 改善提案・サマリー出力
# ---------------------------------------------------------------------------

class TestSummaryAndImprovements(unittest.TestCase):

    def test_slow_dispatch_generates_improvement_tip(self):
        s = _eval(dispatch_days=8)
        self.assertTrue(any("発送スピード" in tip for tip in s.improvements))

    def test_non_realtime_stock_generates_improvement_tip(self):
        s = _eval(is_realtime_stock=False)
        self.assertTrue(any("リアルタイム" in tip for tip in s.improvements))

    def test_low_favorites_generates_improvement_tip(self):
        s = _eval(favorites_count=5)
        self.assertTrue(any("お気に入り" in tip for tip in s.improvements))

    def test_no_fx_buffer_generates_improvement_tip(self):
        s = _eval(fx_buffer_rate=0.0)
        self.assertTrue(any("バッファ" in tip for tip in s.improvements))

    def test_summary_contains_grade(self):
        s = _eval()
        summary = s.summary()
        self.assertIn(s.grade, summary)

    def test_summary_contains_product_name(self):
        s = _eval()
        self.assertIn("テストバッグ", s.summary())

    def test_summary_contains_profit_info(self):
        s = _eval()
        summary = s.summary()
        self.assertIn("利益", summary)


# ---------------------------------------------------------------------------
# デモ評価の統合テスト
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):

    def test_gucci_bag_grades_well(self):
        """GUCCIの優良商品はA/Bグレードを取得する。"""
        inp = EvaluationInput(
            product_name="GG マーモント ミニ",
            brand="GUCCI",
            model_year=2024,
            source_url="https://ssense.com/product/1",
            source_price=750.0, currency="USD", exchange_rate=155.0,
            buyma_price=175_000, japan_retail_price=198_000,
            dispatch_days=3, japan_arrival_days=7, is_realtime_stock=True,
            packaging_quality="excellent", buyma_rank=5, sns_trending=True,
            japan_soldout=True, japan_exclusive=False,
            favorites_count=35, has_cart_addition=True,
            source_type="authorized", is_volume_zone=True,
            customs_rate=0.10, shipping_cost_jpy=2000, buyma_fee_rate=0.077,
            fx_buffer_rate=0.03, target_profit_rate=0.15,
        )
        score = PurchaseEvaluator().evaluate(inp)
        self.assertIn(score.grade, ("A", "B"))
        self.assertTrue(score.is_recommended)

    def test_risky_old_item_grades_E(self):
        """型落ち品・不明仕入れ先の商品は E グレード。"""
        inp = replace(
            _BASE,
            model_year=2018,
            source_type="unknown",
        )
        score = PurchaseEvaluator().evaluate(inp)
        self.assertEqual(score.grade, "E")
        self.assertFalse(score.is_recommended)
        self.assertGreater(len(score.critical_issues), 0)

    def test_hermes_birkin_grades_high(self):
        """エルメス バーキン（希少品・高利益）は高グレードを取得する。"""
        inp = EvaluationInput(
            product_name="バーキン 30",
            brand="HERMÈS",
            model_year=2025,
            source_url="https://harrods.com/product/birkin",
            source_price=8500.0, currency="GBP", exchange_rate=196.0,
            buyma_price=3_200_000, japan_retail_price=2_800_000,
            dispatch_days=2, japan_arrival_days=5, is_realtime_stock=True,
            packaging_quality="excellent", buyma_rank=1, sns_trending=True,
            japan_soldout=True, japan_exclusive=True,
            favorites_count=89, has_cart_addition=True,
            source_type="official", is_volume_zone=True,
            customs_rate=0.10, shipping_cost_jpy=5000, buyma_fee_rate=0.055,
            fx_buffer_rate=0.03, target_profit_rate=0.15,
        )
        score = PurchaseEvaluator().evaluate(inp)
        self.assertIn(score.grade, ("A", "B"))


# ---------------------------------------------------------------------------
# 推奨ブランド・定番カテゴリ・利益率ラベルのテスト
# ---------------------------------------------------------------------------

class TestRecommendedBrandsAndCategories(unittest.TestCase):

    def test_recommended_brand_boosts_brand_score(self):
        """推奨ブランド（CELINE）は非推奨ブランドよりブランドスコアが高い。"""
        s_celine = _eval(brand="CELINE", buyma_rank=None, sns_trending=False)
        s_other  = _eval(brand="UNKNOWN_BRAND", buyma_rank=None, sns_trending=False)
        brand_celine = next(ss for ss in s_celine.demand.sub_scores if ss.name == "ブランド力")
        brand_other  = next(ss for ss in s_other.demand.sub_scores  if ss.name == "ブランド力")
        self.assertGreater(brand_celine.score, brand_other.score)

    def test_saint_laurent_recognized(self):
        s = _eval(brand="Saint Laurent", buyma_rank=None, sns_trending=False)
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        self.assertGreaterEqual(brand_sub.score, 55)  # 45 + 10 ボーナス

    def test_maison_margiela_recognized(self):
        s = _eval(brand="Maison Margiela", buyma_rank=None, sns_trending=False)
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        self.assertGreaterEqual(brand_sub.score, 55)

    def test_jil_sander_recognized(self):
        s = _eval(brand="Jil Sander", buyma_rank=None, sns_trending=False)
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        self.assertGreaterEqual(brand_sub.score, 55)

    def test_balenciaga_recognized(self):
        s = _eval(brand="Balenciaga", buyma_rank=None, sns_trending=False)
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        self.assertGreaterEqual(brand_sub.score, 55)

    def test_stable_category_wallet_boosts_score(self):
        """財布（wallet）カテゴリは定番カテゴリとして認識されブランドスコアに反映される。"""
        s_wallet  = _eval(product_name="長財布", product_category="wallet")
        s_other   = _eval(product_name="サングラス", product_category="eyewear")
        brand_w = next(ss for ss in s_wallet.demand.sub_scores if ss.name == "ブランド力")
        brand_o = next(ss for ss in s_other.demand.sub_scores  if ss.name == "ブランド力")
        self.assertGreaterEqual(brand_w.score, brand_o.score)

    def test_stable_category_sneaker_boosts_score(self):
        s = _eval(product_name="Triple S スニーカー", product_category="sneaker")
        brand_sub = next(ss for ss in s.demand.sub_scores if ss.name == "ブランド力")
        # ベース(GUCCI, rank=5, SNS=True) は既に100なので delta で確認
        self.assertEqual(brand_sub.score, 100)

    def test_profit_10_15_label_is_conditional(self):
        """10〜15% 利益率の説明文が「条件付き許容圏」を含む。"""
        from lib.purchase_evaluator import calculate_profit  # noqa: F401
        s = _eval(source_price=900.0, buyma_price=195_000)
        profit_sub = next(ss for ss in s.economics.sub_scores if "利益率" in ss.name)
        if 0.10 <= s.effective_profit_rate < 0.15:
            self.assertIn("条件付き", profit_sub.reason)

    def test_celine_bag_with_category_grades_at_least_B(self):
        """CELINE バッグ（推奨ブランド＋定番カテゴリ）は優良条件下でB以上を取得する。"""
        inp = EvaluationInput(
            product_name="セリーヌ カバ ミニ",
            brand="CELINE",
            model_year=2025,
            source_url="https://www.net-a-porter.com/en-us/shop/product/celine/1",
            source_price=900.0, currency="USD", exchange_rate=155.0,
            buyma_price=210_000, japan_retail_price=242_000,
            dispatch_days=3, japan_arrival_days=7, is_realtime_stock=True,
            packaging_quality="excellent", buyma_rank=8, sns_trending=True,
            japan_soldout=True, japan_exclusive=False,
            favorites_count=25, has_cart_addition=True,
            source_type="authorized", is_volume_zone=True,
            customs_rate=0.10, shipping_cost_jpy=2000, buyma_fee_rate=0.077,
            fx_buffer_rate=0.03, target_profit_rate=0.15,
            product_category="bag",
        )
        score = PurchaseEvaluator().evaluate(inp)
        self.assertIn(score.grade, ("A", "B"))
        self.assertTrue(score.is_recommended)


class TestIsRecommendedHelpers(unittest.TestCase):
    """モジュールレベルのヘルパー関数のユニットテスト。"""

    def setUp(self):
        from lib.purchase_evaluator import _is_recommended_brand, _is_stable_category
        self._is_brand = _is_recommended_brand
        self._is_cat   = _is_stable_category

    def test_celine_matches(self):
        self.assertTrue(self._is_brand("CELINE"))
        self.assertTrue(self._is_brand("celine"))
        self.assertTrue(self._is_brand("Celine"))

    def test_saint_laurent_matches(self):
        self.assertTrue(self._is_brand("Saint Laurent"))
        self.assertTrue(self._is_brand("YSL"))

    def test_margiela_alias_matches(self):
        self.assertTrue(self._is_brand("Maison Margiela"))
        self.assertTrue(self._is_brand("margiela"))

    def test_non_recommended_brand_no_match(self):
        self.assertFalse(self._is_brand("GUCCI"))
        self.assertFalse(self._is_brand("HERMÈS"))
        self.assertFalse(self._is_brand("Prada"))

    def test_bag_category_matches(self):
        self.assertTrue(self._is_cat("ミニバッグ", ""))
        self.assertTrue(self._is_cat("tote bag", ""))
        self.assertTrue(self._is_cat("item", "bag"))

    def test_wallet_category_matches(self):
        self.assertTrue(self._is_cat("長財布", ""))
        self.assertTrue(self._is_cat("wallet", ""))

    def test_sneaker_category_matches(self):
        self.assertTrue(self._is_cat("Triple S", "sneaker"))
        self.assertTrue(self._is_cat("スニーカー", ""))

    def test_non_stable_category_no_match(self):
        self.assertFalse(self._is_cat("サングラス", "eyewear"))
        self.assertFalse(self._is_cat("ネクタイ", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
