import unittest
from datetime import datetime, timedelta
import json
import sys
import types

# Provide dummies for optional third-party deps imported by strategies.py
if "keyboard" not in sys.modules:
    sys.modules["keyboard"] = types.ModuleType("keyboard")
if "inputimeout" not in sys.modules:
    m = types.ModuleType("inputimeout")
    class TimeoutOccurred(Exception):
        pass
    def inputimeout(*args, **kwargs):
        raise TimeoutOccurred()
    m.TimeoutOccurred = TimeoutOccurred
    m.inputimeout = inputimeout
    sys.modules["inputimeout"] = m
if "prettytable" not in sys.modules:
    m = types.ModuleType("prettytable")
    class PrettyTable:
        def __init__(self, *args, **kwargs):
            pass
        def add_row(self, *args, **kwargs):
            pass
    m.PrettyTable = PrettyTable
    sys.modules["prettytable"] = m
if "tzlocal" not in sys.modules:
    m = types.ModuleType("tzlocal")
    def get_localzone():
        return None
    m.get_localzone = get_localzone
    sys.modules["tzlocal"] = m

from core.box_spreads import calculate_box_spread


def make_chain(date_str: str, strikes, bids_asks, prefix: str):
    """Helper to build a minimal chain list for calls/puts.

    strikes: list[float]
    bids_asks: list[tuple[bid, ask]] same length as strikes
    prefix: symbol prefix
    """
    contracts = []
    for i, k in enumerate(strikes):
        bid, ask = bids_asks[i]
        contracts.append({
            "strike": k,
            "bid": bid,
            "ask": ask,
            "symbol": f"SYM-{prefix}-{k}"
        })
    return [{"date": date_str, "contracts": contracts}]


class TestBoxSpreads(unittest.TestCase):
    def test_box_spread_buy_and_sell(self):
        # Build synthetic one-day chain at T+20 days
        days = 20
        date = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        spread = 100
        strikes = [100, 200]

        # Choose mid prices to produce a clear positive trade price = 6.0 for both buy and sell
        # low_call mid=5, high_call mid=2, low_put mid=2, high_put mid=5
        c_ba = [(5.0, 5.0), (2.0, 2.0)]
        p_ba = [(2.0, 2.0), (5.0, 5.0)]

        calls = json.dumps(make_chain(date, strikes, c_ba, "C"))
        puts = json.dumps(make_chain(date, strikes, p_ba, "P"))

        # Buy box: mid_trade_price = -(LP+HC - HP - LC) = 6
        buy = calculate_box_spread(spread, calls, puts, trade="buy")
        self.assertIsNotNone(buy)
        self.assertEqual(buy["direction"], "Buy")
        self.assertEqual(buy["face_value"], spread * 100)
        # Upfront = mid_trade_price * 100 = 600
        self.assertAlmostEqual(buy["mid_upfront_amount"], 600.0, places=2)
        # Annualized return = ((face - upfront)/face) * (365/days)
        expected_buy_ann = ((spread * 100 - 600.0) / (spread * 100)) * (365 / days) * 100
        self.assertAlmostEqual(buy["mid_annualized_return"], round(expected_buy_ann, 2), places=2)

        # Sell box: mid_trade_price = (LC + HP - HC - LP) = 6
        sell = calculate_box_spread(spread, calls, puts, trade="sell")
        self.assertIsNotNone(sell)
        self.assertEqual(sell["direction"], "Sell")
        self.assertEqual(sell["face_value"], spread * 100)
        # Borrowed = upfront (= mid_trade_price * 100)
        self.assertAlmostEqual(sell["borrowed"], 600.0, places=2)
        expected_sell_ann = ((600.0 - spread * 100) / (spread * 100)) * (365 / days) * 100
        self.assertAlmostEqual(sell["mid_annualized_return"], round(expected_sell_ann, 2), places=2)


if __name__ == '__main__':
    unittest.main()
