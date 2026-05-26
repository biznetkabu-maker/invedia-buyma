"""funnel_policy のユニットテスト。"""

import os
import unittest
from unittest.mock import patch

from lib.funnel_policy import (
    DEFAULT_WEEKLY_LIMIT,
    funnel_enabled,
    is_eyewear_product_name,
    is_hard_excluded_product_name,
    official_prada_enabled,
    require_style_id,
    rescue_hint,
    weekly_auto_limit,
)


class TestWeeklyAutoLimit(unittest.TestCase):
    def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(weekly_auto_limit(), DEFAULT_WEEKLY_LIMIT)

    def test_custom(self):
        with patch.dict(os.environ, {"INTAKE_WEEKLY_LIMIT": "100"}):
            self.assertEqual(weekly_auto_limit(), 100)

    def test_invalid(self):
        with patch.dict(os.environ, {"INTAKE_WEEKLY_LIMIT": "abc"}):
            self.assertEqual(weekly_auto_limit(), DEFAULT_WEEKLY_LIMIT)

    def test_zero_clamped(self):
        with patch.dict(os.environ, {"INTAKE_WEEKLY_LIMIT": "0"}):
            self.assertEqual(weekly_auto_limit(), 1)


class TestFunnelEnabled(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(funnel_enabled())

    def test_disabled_false(self):
        with patch.dict(os.environ, {"INTAKE_FUNNEL": "false"}):
            self.assertFalse(funnel_enabled())

    def test_disabled_zero(self):
        with patch.dict(os.environ, {"INTAKE_FUNNEL": "0"}):
            self.assertFalse(funnel_enabled())


class TestRequireStyleId(unittest.TestCase):
    def test_default_required(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(require_style_id())

    def test_disabled(self):
        with patch.dict(os.environ, {"INTAKE_REQUIRE_STYLE": "no"}):
            self.assertFalse(require_style_id())


class TestOfficialPradaEnabled(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(official_prada_enabled())

    def test_disabled(self):
        with patch.dict(os.environ, {"INTAKE_OFFICIAL_PRADA": "false"}):
            self.assertFalse(official_prada_enabled())


class TestIsHardExcluded(unittest.TestCase):
    def test_perfume(self):
        self.assertTrue(is_hard_excluded_product_name("オードパルファム 50ml"))

    def test_cosmetic(self):
        self.assertTrue(is_hard_excluded_product_name("リップスティック レッド"))

    def test_re_nylon_pouch(self):
        self.assertTrue(is_hard_excluded_product_name("Re-Nylon ポーチ ミニ"))

    def test_normal_bag(self):
        self.assertFalse(is_hard_excluded_product_name("サフィアーノ トートバッグ"))

    def test_empty_string(self):
        self.assertFalse(is_hard_excluded_product_name(""))


class TestIsEyewear(unittest.TestCase):
    def test_sunglasses(self):
        self.assertTrue(is_eyewear_product_name("ラウンド サングラス"))

    def test_eyewear(self):
        self.assertTrue(is_eyewear_product_name("Rectangular Eyewear Frame"))

    def test_not_eyewear(self):
        self.assertFalse(is_eyewear_product_name("トートバッグ レザー"))


class TestRescueHint(unittest.TestCase):
    def test_returns_string(self):
        hint = rescue_hint()
        self.assertIn("候補URLs", hint)


if __name__ == "__main__":
    unittest.main()
