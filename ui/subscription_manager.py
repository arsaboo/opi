from typing import Iterable, Optional, Set, Dict
import asyncio
from .quote_provider import get_provider


class SubscriptionManager:
    """Aggregates subscription requests from multiple screens and subscribes once per change.

    Screens call register(screen_id, options, equities). Manager computes unions and only
    subscribes new symbols to the shared provider.
    """

    def __init__(self, connect_client) -> None:
        self._provider = get_provider(connect_client)
        self._screens: Dict[str, Dict[str, Set[str]]] = {}
        self._last_opts: Set[str] = set()
        self._last_eqs: Set[str] = set()

    def register(self, screen_id: str, options: Iterable[str] = (), equities: Iterable[str] = ()) -> None:
        opts = {s for s in options if s}
        eqs = {s.upper() for s in equities if s}
        self._screens[screen_id] = {"options": opts, "equities": eqs}
        self._reconcile()

    def unregister(self, screen_id: str) -> None:
        if screen_id in self._screens:
            del self._screens[screen_id]
            self._reconcile()

    def _reconcile(self) -> None:
        desired_opts: Set[str] = set()
        desired_eqs: Set[str] = set()
        for entry in self._screens.values():
            desired_opts |= entry.get("options", set())
            desired_eqs |= entry.get("equities", set())
        # Determine changes
        new_opts = desired_opts - self._last_opts
        new_eqs = desired_eqs - self._last_eqs
        removed_opts = self._last_opts - desired_opts
        removed_eqs = self._last_eqs - desired_eqs
        # Unsubscribe removed first
        if removed_opts:
            asyncio.create_task(self._provider.unsubscribe_options(list(removed_opts)))
        if removed_eqs:
            asyncio.create_task(self._provider.unsubscribe_equities(list(removed_eqs)))
        # Subscribe new
        if new_opts:
            asyncio.create_task(self._provider.subscribe_options(new_opts))
        if new_eqs:
            asyncio.create_task(self._provider.subscribe_equities(new_eqs))
        self._last_opts = desired_opts
        self._last_eqs = desired_eqs


_manager: Optional[SubscriptionManager] = None


def get_subscription_manager(connect_client) -> SubscriptionManager:
    global _manager
    if _manager is None:
        _manager = SubscriptionManager(connect_client)
    return _manager
