import unittest
from datetime import datetime, timedelta
import sys
import types

# Stub out modules that drag optional deps (telegram) during import
if 'alert' not in sys.modules:
    m = types.ModuleType('alert')
    def botFailed(*args, **kwargs):
        return []
    def alert(*args, **kwargs):
        return None
    m.botFailed = botFailed
    m.alert = alert
    sys.modules['alert'] = m
if 'logger_config' not in sys.modules:
    m2 = types.ModuleType('logger_config')
    def get_logger():
        class _L:
            def __getattr__(self, _):
                return lambda *a, **k: None
        return _L()
    m2.get_logger = get_logger
    sys.modules['logger_config'] = m2

# Modules under test (import after stubs)
import core.vertical_spreads as vs
import core.synthetic_covered_calls as sc


class FakeOptionChain:
    def __init__(self, api, asset, toDate, days):
        self.calls = []
        self.asset = asset

    # For verticals path
    def get(self):
        return self.calls

    # For synthetic path (puts) pass-through mapper
    def mapApiData(self, data, put=False):
        return data


class FakeApi:
    def __init__(self, underlying_price, puts_chain=None):
        self._price = underlying_price
        self._puts_chain = puts_chain or []

    def get_price(self, asset):
        return self._price

    # For synthetic path
    def getPutOptionChain(self, asset, strikes, toDate, days_less):
        return self._puts_chain


def _make_chain_row(date_str, strikes, bids_asks, asset):
    contracts = []
    for i, k in enumerate(strikes):
        bid, ask = bids_asks[i]
        contracts.append({
            "strike": float(k),
            "bid": float(bid),
            "ask": float(ask),
            "symbol": f"{asset}-{k}",
            "underlying": asset,
        })
    return [{"date": date_str, "contracts": contracts}]


class TestVerticalAndSynthetic(unittest.TestCase):
    def setUp(self):
        # Monkeypatch OptionChain in the target modules
        self._old_vc = vs.OptionChain
        self._old_sc = sc.OptionChain
        vs.OptionChain = FakeOptionChain
        sc.OptionChain = FakeOptionChain

    def tearDown(self):
        vs.OptionChain = self._old_vc
        sc.OptionChain = self._old_sc

    def test_bull_call_spread_basic(self):
        asset = "SPY"
        days = 120  # SPY has minDays=90 in configuration; ensure entry passes filter
        date = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        strikes = [400, 420]
        # Long call mid 10.0, short call mid 6.0 -> net_debit 4.0
        calls_ba = [(9.0, 11.0), (5.0, 7.0)]
        chain = _make_chain_row(date, strikes, calls_ba, asset)

        # Prepare fake OptionChain.get to return our calls
        fc = FakeOptionChain(None, asset, None, None)
        fc.calls = chain
        vs.OptionChain = lambda *args, **kwargs: fc

        api = FakeApi(underlying_price=410.0)
        result = vs.bull_call_spread(api, asset, spread=20, days=days, downsideProtection=0.0, price="mid")
        self.assertIsNotNone(result)
        self.assertEqual(result["strike1"], 400.0)
        self.assertEqual(result["strike2"], 420.0)
        self.assertAlmostEqual(result["net_debit"], 4.0, places=2)
        # Investment/profit are per contract in $
        self.assertAlmostEqual(result["total_investment"], 400.0, places=2)
        self.assertAlmostEqual(result["total_return"], 1600.0, places=2)

    def test_synthetic_covered_call_basic(self):
        asset = "$SPX"
        days = 365
        date = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        strikes = [4000, 4200]
        # Long call mid 3053.80->3359.30 mid ~ 3206.55 (we'll pick simple numbers)
        calls_ba = [(100.0, 120.0), (60.0, 80.0)]  # mid 110 and 70
        puts_ba = [(10.0, 12.0), (8.0, 9.0)]      # only low strike used; provide valid numbers for both

        calls = _make_chain_row(date, strikes, calls_ba, asset)
        puts = _make_chain_row(date, strikes, puts_ba, asset)

        # Fake chain/mapper
        fc = FakeOptionChain(None, asset, None, None)
        fc.calls = calls
        sc.OptionChain = lambda *args, **kwargs: fc
        api = FakeApi(underlying_price=4100.0, puts_chain=puts)

        result = sc.synthetic_covered_call_spread(api, asset, spread=200, days=days, downsideProtection=0.0, price="mid")
        self.assertIsNotNone(result)
        # net_debit = long_call_mid - short_call_mid - short_put_mid = 110 - 70 - 11 = 29
        self.assertAlmostEqual(result["net_debit"], 29.0, places=2)
        # Investment and profit in $ per contract
        self.assertAlmostEqual(result["total_investment"], 2900.0, places=2)
        self.assertAlmostEqual(result["total_return"], (200 - 29) * 100.0, places=2)

    def test_synthetic_covered_call_ann_rom(self):
        # Use the same setup as basic test but check return on margin math
        asset = "$SPX"
        days = 365
        date = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        strikes = [4000, 4200]
        calls_ba = [(100.0, 120.0), (60.0, 80.0)]  # mids 110, 70
        puts_ba = [(10.0, 12.0), (8.0, 9.0)]       # low strike put mid 11

        calls = _make_chain_row(date, strikes, calls_ba, asset)
        puts = _make_chain_row(date, strikes, puts_ba, asset)

        fc = FakeOptionChain(None, asset, None, None)
        fc.calls = calls
        sc.OptionChain = lambda *args, **kwargs: fc
        api = FakeApi(underlying_price=4100.0, puts_chain=puts)

        result = sc.synthetic_covered_call_spread(api, asset, spread=200, days=days, downsideProtection=0.0, price="mid")
        self.assertIsNotNone(result)

        # Compute expected margin and ROM using the same helpers used by the module
        from core.margin import calculate_margin_requirement, calculate_annualized_return_on_margin
        net_debit = 29.0
        profit = (200 - net_debit) * 100.0
        from core.spreads_common import days_to_expiry
        dte = days_to_expiry(date)
        # Inputs to margin: put_strike=4000, underlying_value=4100, put_premium=10 (bid)
        margin_req = calculate_margin_requirement(
            asset,
            'synthetic_covered_call',
            put_strike=4000.0,
            underlying_value=4100.0,
            put_premium=10.0,
            max_loss=4000.0 * 100.0,
        )
        expected_rom = round(calculate_annualized_return_on_margin(profit, margin_req, dte), 2)
        self.assertAlmostEqual(result["return_on_margin"], expected_rom, places=2)


if __name__ == "__main__":
    unittest.main()
