import asyncio
import unittest
import sys
import types


def import_manager_with_mocks():
    # Provide a fake quote_provider module to avoid starting real streaming
    fake_mod = types.ModuleType("ui.quote_provider")
    def get_provider(_):
        return FakeProvider()
    fake_mod.get_provider = get_provider  # type: ignore[attr-defined]
    sys.modules["ui.quote_provider"] = fake_mod
    from ui.subscription_manager import SubscriptionManager  # type: ignore
    return SubscriptionManager


class FakeProvider:
    def __init__(self) -> None:
        self.opt_subs: set[str] = set()
        self.eq_subs: set[str] = set()
        self.opt_sub_calls: list[tuple[str, list[str]]] = []  # (op, symbols)
        self.eq_sub_calls: list[tuple[str, list[str]]] = []

    async def subscribe_options(self, symbols):
        syms = list(symbols)
        self.opt_sub_calls.append(("sub", syms))
        self.opt_subs.update(syms)

    async def unsubscribe_options(self, symbols):
        syms = list(symbols)
        self.opt_sub_calls.append(("unsub", syms))
        for s in syms:
            self.opt_subs.discard(s)

    async def subscribe_equities(self, symbols):
        syms = list(symbols)
        self.eq_sub_calls.append(("sub", syms))
        self.eq_subs.update(syms)

    async def unsubscribe_equities(self, symbols):
        syms = list(symbols)
        self.eq_sub_calls.append(("unsub", syms))
        for s in syms:
            self.eq_subs.discard(s)


async def wait_until(cond, timeout=1.0):
    start = asyncio.get_event_loop().time()
    while True:
        if cond():
            return True
        if asyncio.get_event_loop().time() - start > timeout:
            return False
        await asyncio.sleep(0.01)


class TestSubscriptionManager(unittest.TestCase):
    def test_reconcile(self):
        async def run():
            SubscriptionManager = import_manager_with_mocks()
            mgr = SubscriptionManager(connect_client=None)
            fake = FakeProvider()
            # Inject fake provider to avoid real streaming
            mgr._provider = fake  # type: ignore[attr-defined]

            # Register first screen
            mgr.register("A", options=["OPT1", "OPT2"], equities=["SPY"]) 
            self.assertTrue(await wait_until(lambda: fake.opt_subs == {"OPT1", "OPT2"}))
            self.assertEqual(fake.eq_subs, {"SPY"})

            # Register second screen with overlap and a new symbol
            mgr.register("B", options=["OPT2", "OPT3"], equities=["QQQ"]) 
            self.assertTrue(await wait_until(lambda: fake.opt_subs == {"OPT1", "OPT2", "OPT3"}))
            self.assertEqual(fake.eq_subs, {"SPY", "QQQ"})

            # Unregister first screen -> drop OPT1 and SPY
            mgr.unregister("A")
            self.assertTrue(await wait_until(lambda: fake.opt_subs == {"OPT2", "OPT3"}))
            self.assertTrue(await wait_until(lambda: fake.eq_subs == {"QQQ"}))

            # Re-register A with OPT3 only (already subscribed)
            mgr.register("A", options=["OPT3"], equities=[])
            await asyncio.sleep(0.05)
            self.assertEqual(fake.opt_subs, {"OPT2", "OPT3"})
            self.assertEqual(fake.eq_subs, {"QQQ"})

        asyncio.run(run())
