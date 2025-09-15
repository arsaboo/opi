import unittest
import sys
import types

# Stub schwab packages to allow importing OrderManager without real deps
if 'schwab' not in sys.modules:
    schwab = types.ModuleType('schwab')
    orders = types.ModuleType('schwab.orders')
    options = types.ModuleType('schwab.orders.options')
    generic = types.ModuleType('schwab.orders.generic')
    common = types.ModuleType('schwab.orders.common')

    class OptionSymbol:
        def __init__(self, *a, **k):
            pass
        def build(self):
            return "OPT"

    class OrderBuilder:
        def __init__(self):
            self._spec = {}
        def add_option_leg(self, *a, **k):
            return self
        def set_duration(self, *a, **k):
            return self
        def set_session(self, *a, **k):
            return self
        def set_price(self, *a, **k):
            return self
        def set_order_type(self, *a, **k):
            return self
        def set_order_strategy_type(self, *a, **k):
            return self
        def set_complex_order_strategy_type(self, *a, **k):
            return self
        def set_special_instruction(self, *a, **k):
            return self
        def build(self):
            return self._spec

    class _C:
        NET_DEBIT = 'NET_DEBIT'
        NET_CREDIT = 'NET_CREDIT'
        SINGLE = 'SINGLE'
        DIAGONAL = 'DIAGONAL'
        VERTICAL = 'VERTICAL'
        CUSTOM = 'CUSTOM'
        DAY = 'DAY'
        NORMAL = 'NORMAL'
        BUY_TO_OPEN = 'BUY_TO_OPEN'
        SELL_TO_OPEN = 'SELL_TO_OPEN'
        BUY_TO_CLOSE = 'BUY_TO_CLOSE'
        ALL_OR_NONE = 'ALL_OR_NONE'

    options.OptionSymbol = OptionSymbol
    generic.OrderBuilder = OrderBuilder
    common.Duration = _C
    common.Session = _C
    common.OrderType = _C
    common.OrderStrategyType = _C
    common.ComplexOrderStrategyType = _C
    common.OptionInstruction = _C

    sys.modules['schwab'] = schwab
    sys.modules['schwab.orders'] = orders
    sys.modules['schwab.orders.options'] = options
    sys.modules['schwab.orders.generic'] = generic
    sys.modules['schwab.orders.common'] = common

# Stub integrations/telegram and status dependencies pulled by api.order_manager imports
if 'integrations.telegram' not in sys.modules:
    pkg = types.ModuleType('integrations.telegram')
    def get_notifier():
        class N:
            def send(self, *a, **k):
                pass
        return N()
    pkg.get_notifier = get_notifier
    sys.modules['integrations.telegram'] = pkg
if 'status' not in sys.modules:
    st = types.ModuleType('status')
    def notify(*a, **k):
        pass
    def notify_exception(*a, **k):
        pass
    st.notify = notify
    st.notify_exception = notify_exception
    sys.modules['status'] = st

from api.order_manager import OrderManager


class FakeApi:
    def getAccountHash(self):
        return "HASH"

    @property
    def connectClient(self):
        class CC:
            def place_order(self, *a, **k):
                class R:
                    status_code = 200
                return R()
        return CC()


class TestOrderPlacement(unittest.TestCase):
    def test_place_order_with_improvement_debit(self):
        om = OrderManager(FakeApi())

        calls = []
        def fake_vertical(symbol, expiration, k1, k2, qty, *, price):
            calls.append(price)
            return "OID1"

        # Name to influence tick inference
        fake_vertical.__name__ = 'vertical_call_order'

        # Simulate one timeout then a fill
        states = iter(["timeout", True])
        om.monitor_order = lambda *_a, **_k: next(states)

        ok = om.place_order_with_improvement(fake_vertical, ["SPY", "2025-01-17", 400, 420, 1], 1.00)
        self.assertTrue(ok)
        # Debit order: price increases by $0.01 for SPY on retry
        self.assertEqual(calls, [1.00, 1.01])

    def test_place_order_with_improvement_credit(self):
        om = OrderManager(FakeApi())

        calls = []
        def fake_roll(old_sym, new_sym, qty, *, price):
            calls.append(price)
            return "OID2"

        fake_roll.__name__ = 'roll_over'
        # Two timeouts then success
        states = iter(["timeout", "timeout", True])
        om.monitor_order = lambda *_a, **_k: next(states)

        # Use negative initial price to exercise credit logic path
        ok = om.place_order_with_improvement(fake_roll, ["OPT-OLD", "OPT-NEW", 1], -1.00)
        self.assertTrue(ok)
        # Credit order: price decreases by $0.01 each retry from -1.00
        self.assertEqual(calls, [-1.00, -1.01, -1.02])


if __name__ == '__main__':
    unittest.main()
