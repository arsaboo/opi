import unittest
from datetime import datetime, timedelta

from core.common import calculate_cagr, classify_status
from core.spreads_common import mid_price, days_to_expiry, crossed_quote, valid_ba


class TestCAGRAndUtils(unittest.TestCase):
    def test_calculate_cagr_basic(self):
        # 10% return over 365 days -> ~10%
        cagr, pct = calculate_cagr(1000.0, 100.0, 365)
        self.assertAlmostEqual(pct, 10.0, places=2)

    def test_calculate_cagr_large(self):
        # 3x return over a year -> 200%
        cagr, pct = calculate_cagr(1000.0, 2000.0, 365)
        self.assertAlmostEqual(pct, 200.0, places=2)

    def test_calculate_cagr_short_period(self):
        # 10% in 30 days -> annualized > 100%
        cagr, pct = calculate_cagr(1000.0, 100.0, 30)
        self.assertGreater(pct, 100.0)

    def test_mid_price_and_ba_helpers(self):
        self.assertEqual(mid_price(2.0, 4.0), 3.0)
        self.assertTrue(valid_ba(1, 2, 3, 4))
        self.assertFalse(valid_ba(1, None))
        self.assertTrue(crossed_quote(5.0, 4.9))
        self.assertFalse(crossed_quote(4.0, 5.0))

    def test_days_to_expiry(self):
        date = (datetime.today() + timedelta(days=15)).strftime("%Y-%m-%d")
        self.assertIn(days_to_expiry(date), {14, 15, 16})

    def test_classify_status_percent_thresholds(self):
        # Underlying 100; thresholds as fractions
        underlying = 100.0
        itm = 0.02  # 2%
        deep_itm = 0.05  # 5%
        deep_otm = 0.01  # 1%

        # Deep OTM
        self.assertEqual(classify_status(105.0, underlying, itm_limit=itm, deep_itm_limit=deep_itm, deep_otm_limit=deep_otm), "deep_OTM")
        # OTM (above underlying but within deep-OTM threshold)
        self.assertEqual(classify_status(100.5, underlying, itm_limit=itm, deep_itm_limit=deep_itm, deep_otm_limit=deep_otm), "OTM")
        # just ITM
        self.assertEqual(classify_status(99.5, underlying, itm_limit=itm, deep_itm_limit=deep_itm, deep_otm_limit=deep_otm), "just_ITM")
        # ITM
        self.assertEqual(classify_status(98.0, underlying, itm_limit=itm, deep_itm_limit=deep_itm, deep_otm_limit=deep_otm), "ITM")
        # deep ITM
        self.assertEqual(classify_status(90.0, underlying, itm_limit=itm, deep_itm_limit=deep_itm, deep_otm_limit=deep_otm), "deep_ITM")


if __name__ == "__main__":
    unittest.main()
