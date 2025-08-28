import asyncio
from typing import Dict, Iterable, Optional, Tuple

from schwab.streaming import StreamClient


class StreamingQuoteProvider:
    """Maintains a streaming connection and a local quote cache for option symbols.

    Usage:
      provider = StreamingQuoteProvider(connect_client)
      await provider.start()
      await provider.subscribe_options(["SPXW  251003C06450000", ...])
      bid, ask = provider.get_bid_ask(symbol)
    """

    def __init__(self, connect_client) -> None:
        self.client = connect_client
        self.account_id: Optional[int] = None
        self.stream: Optional[StreamClient] = None
        self._quotes: Dict[str, Dict] = {}
        self._last: Dict[str, Dict[str, float]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Track subscriptions separately for clarity/efficiency
        self._opt_subs: set[str] = set()
        self._eq_subs: set[str] = set()

    async def start(self) -> None:
        if self._running:
            return
        # Determine numeric account id
        r = self.client.get_account_numbers()
        r.raise_for_status()
        data = r.json()
        # Choose first account number
        self.account_id = int(data[0]["accountNumber"]) if data else None
        self.stream = StreamClient(self.client, account_id=self.account_id)
        self.stream.add_level_one_option_handler(self._on_level_one_option)
        # Also handle equities for underlying prices
        try:
            self.stream.add_level_one_equity_handler(self._on_level_one_equity)
        except Exception:
            pass
        await self.stream.login()
        self._running = True
        # Start message pump
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def subscribe_options(self, symbols: Iterable[str]) -> None:
        if not self._running or not self.stream:
            return
        # Avoid re-subscribing existing symbols
        new_syms = [s for s in symbols if s and s not in self._opt_subs]
        if not new_syms:
            return
        await self.stream.level_one_option_subs(new_syms)
        self._opt_subs.update(new_syms)

    async def _pump(self) -> None:
        assert self.stream is not None
        while self._running:
            try:
                await self.stream.handle_message()
            except Exception:
                # Swallow to keep loop alive; connection resiliency could be added
                await asyncio.sleep(0.5)

    async def _on_level_one_option(self, msg: Dict) -> None:
        # Schwab streaming wraps updates in a 'content' list; store each by 'key'
        contents = msg.get("content") or []
        for c in contents:
            key = c.get("key") or c.get("symbol")
            if not key:
                continue
            last = self._last.setdefault(key, {})
            # Extract possible bid/ask fields
            raw_bid = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID") or c.get("bid")
            raw_ask = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK") or c.get("ask")
            raw_last = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST") or c.get("last")
            try:
                if raw_bid is not None:
                    last["bid"] = float(raw_bid)
            except Exception:
                pass
            try:
                if raw_ask is not None:
                    last["ask"] = float(raw_ask)
            except Exception:
                pass
            try:
                if raw_last is not None:
                    last["last"] = float(raw_last)
            except Exception:
                pass
            # Store merged snapshot for get_bid_ask
            snap = {"key": key}
            if "bid" in last:
                snap["BID_PRICE"] = last["bid"]
            if "ask" in last:
                snap["ASK_PRICE"] = last["ask"]
            if "last" in last:
                snap["LAST_PRICE"] = last["last"]
            self._quotes[key] = snap

    async def _on_level_one_equity(self, msg: Dict) -> None:
        contents = msg.get("content") or []
        for c in contents:
            key = c.get("key") or c.get("symbol")
            if not key:
                continue
            last = self._last.setdefault(key, {})
            raw_bid = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID") or c.get("bid")
            raw_ask = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK") or c.get("ask")
            raw_last = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST") or c.get("last")
            try:
                if raw_bid is not None:
                    last["bid"] = float(raw_bid)
            except Exception:
                pass
            try:
                if raw_ask is not None:
                    last["ask"] = float(raw_ask)
            except Exception:
                pass
            try:
                if raw_last is not None:
                    last["last"] = float(raw_last)
            except Exception:
                pass
            snap = {"key": key}
            if "bid" in last:
                snap["BID_PRICE"] = last["bid"]
            if "ask" in last:
                snap["ASK_PRICE"] = last["ask"]
            if "last" in last:
                snap["LAST_PRICE"] = last["last"]
            self._quotes[key] = snap

    async def subscribe_equities(self, symbols: Iterable[str]) -> None:
        if not self._running or not self.stream:
            return
        # Normalize equities to upper case to avoid duplicate variants
        symbols = [s.upper() for s in symbols if s]
        new_syms = [s for s in symbols if s and s not in self._eq_subs]
        if not new_syms:
            return
        await self.stream.level_one_equity_subs(new_syms)
        self._eq_subs.update(new_syms)

    def is_subscribed(self, symbol: str) -> bool:
        return symbol in self._opt_subs or symbol.upper() in self._eq_subs

    def get_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        q = self._quotes.get(symbol)
        if not q:
            return (None, None)
        # Try multiple possible field names from streaming payloads
        bid = (
            q.get("BID_PRICE")
            or q.get("bidPrice")
            or q.get("BID")
            or q.get("bid")
        )
        ask = (
            q.get("ASK_PRICE")
            or q.get("askPrice")
            or q.get("ASK")
            or q.get("ask")
        )
        try:
            bid_f = float(bid) if bid is not None else None
        except Exception:
            bid_f = None
        try:
            ask_f = float(ask) if ask is not None else None
        except Exception:
            ask_f = None
        return (bid_f, ask_f)

    def get_last(self, symbol: str) -> Optional[float]:
        q = self._quotes.get(symbol)
        if not q:
            return None
        last = q.get("LAST_PRICE") or q.get("lastPrice") or q.get("LAST") or q.get("last")
        try:
            return float(last) if last is not None else None
        except Exception:
            return None


_global_provider: Optional[StreamingQuoteProvider] = None

async def ensure_provider(connect_client) -> StreamingQuoteProvider:
    global _global_provider
    if _global_provider is None:
        prov = StreamingQuoteProvider(connect_client)
        await prov.start()
        _global_provider = prov
    return _global_provider

def get_provider(connect_client) -> StreamingQuoteProvider:
    """Synchronous accessor that starts provider lazily in background."""
    global _global_provider
    if _global_provider is None:
        prov = StreamingQuoteProvider(connect_client)
        # Fire-and-forget start; caller can use cache once messages arrive
        asyncio.create_task(prov.start())
        _global_provider = prov
    return _global_provider
