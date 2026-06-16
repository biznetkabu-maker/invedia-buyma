"""profit_calculator のユニットテスト。"""

import unittest

from lib.profit_calculator import calculate_profit, try_calculate_profit


class TestCalculateProfit(unittest.TestCase):
    def test_basic_profitable(self):
        bd = calculate_profit(
            local_price=300.0, exchange_rate=150.0,
            buyma_price=80000.0, customs_rate=0.10,
            shipping_cost=2000.0, buyma_fee_rate=0.077,
        )
        self.assertAlmostEqual(bd.jpy_cost, 45000.0)
        self.assertAlmostEqual(bd.customs_cost, 4500.0)
        self.assertAlmostEqual(bd.shipping_cost, 2000.0)
        self.assertAlmostEqual(bd.buyma_fee, 6160.0)
        expected_total = 45000 + 4500 + 2000 + 6160
        self.assertAlmostEqual(bd.total_cost, expected_total)
        self.assertAlmostEqual(bd.profit, 80000 - expected_total)
        self.assertTrue(bd.is_profitable)

    def test_unprofitable(self):
        bd = calculate_profit(
            local_price=500.0, exchange_rate=155.0,
            buyma_price=70000.0,
        )
        self.assertFalse(bd.is_profitable)

    def test_zero_buyma_price_rate(self):
        bd = calculate_profit(
            local_price=100.0, exchange_rate=150.0,
            buyma_price=0.0,
        )
        self.assertEqual(bd.profit_rate, 0.0)

    def test_negative_price_raises(self):
        with self.assertRaises(ValueError):
            calculate_profit(local_price=-100, exchange_rate=150, buyma_price=50000)

    def test_zero_exchange_raises(self):
        with self.assertRaises(ValueError):
            calculate_profit(local_price=100, exchange_rate=0, buyma_price=50000)

    def test_summary_string(self):
        bd = calculate_profit(300, 150, 80000)
        s = bd.summary()
        self.assertIn("BUYMA価格", s)
        self.assertIn("利益", s)


class TestTryCalculateProfit(unittest.TestCase):
    def test_valid_strings(self):
        bd = try_calculate_profit("300", "150", "80000")
        self.assertIsNotNone(bd)
        self.assertAlmostEqual(bd.jpy_cost, 45000.0)

    def test_empty_strings(self):
        self.assertIsNone(try_calculate_profit("", "", ""))

    def test_zero_price(self):
        self.assertIsNone(try_calculate_profit("0", "150", "80000"))

    def test_invalid_string(self):
        self.assertIsNone(try_calculate_profit("abc", "150", "80000"))

    def test_none_values(self):
        self.assertIsNone(try_calculate_profit(None, None, None))


if __name__ == "__main__":
    unittest.main()
