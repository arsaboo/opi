import asyncio
import time
from typing import Dict, Iterable, Optional, Tuple

from schwab.streaming import StreamClient
from status import publish, publish_exception
import alert


class StreamingQuoteProvider:
    def __init__(self, connect_client) -> None:
        self.client = connect_client
        self.account_id: Optional[int] = None
        self.stream: Optional[StreamClient] = None
        self._quotes: Dict[str, Dict] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._opt_subs: set[str] = set()
        self._eq_subs: set[str] = set()
        # Persist last-good values per symbol so UI doesn't flap when a field is missing
        self._last: Dict[str, Dict[str, float]] = {}
        # Reconnect control
        self._error_streak: int = 0
        # Extended failure tracking
        self._last_success_time: float = time.time()
        self._failure_notified: bool = False
        # Heartbeat/timeout tracking
        self._last_message_time: float = time.time()
        self._watchdog_last_restart: float = 0.0
        self._restart_lock: asyncio.Lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return
        r = self.client.get_account_numbers()
        r.raise_for_status()
        data = r.json()
        self.account_id = int(data[0]["accountNumber"]) if data else None
        self.stream = StreamClient(self.client, account_id=self.account_id)
        self.stream.add_level_one_option_handler(self._on_level_one_option)
        try:
            self.stream.add_level_one_equity_handler(self._on_level_one_equity)
        except Exception:
            pass
        await self.stream.login()
        self._running = True
        self._task = asyncio.create_task(self._pump())
        self._watchdog_task = asyncio.create_task(self._heartbeat_watchdog())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except Exception:
                pass
            self._watchdog_task = None
        try:
            if self.stream:
                # Try to logout/close cleanly
                try:
                    await self.stream.logout()
                except Exception:
                    pass
        finally:
            self.stream = None

    async def subscribe_options(self, symbols: Iterable[str]) -> None:
        if not self._running or not self.stream:
            return
        new_syms = [s for s in symbols if s and s not in self._opt_subs]
        if not new_syms:
            return
        await self.stream.level_one_option_subs(new_syms)
        self._opt_subs.update(new_syms)

    async def unsubscribe_options(self, symbols: Iterable[str]) -> None:
        if not symbols:
            return
        to_drop = {s for s in symbols if s in self._opt_subs}
        if not to_drop:
            return
        try:
            unsubs = getattr(self.stream, "level_one_option_unsubs", None) if self.stream else None
            if callable(unsubs):
                await unsubs(list(to_drop))
        except Exception:
            pass
        self._opt_subs.difference_update(to_drop)

    async def subscribe_equities(self, symbols: Iterable[str]) -> None:
        if not self._running or not self.stream:
            return
        symbols = [s.upper() for s in symbols if s]
        new_syms = [s for s in symbols if s and s not in self._eq_subs]
        if not new_syms:
            return
        await self.stream.level_one_equity_subs(new_syms)
        self._eq_subs.update(new_syms)

    async def unsubscribe_equities(self, symbols: Iterable[str]) -> None:
        if not symbols:
            return
        norm = [s.upper() for s in symbols if s]
        to_drop = {s for s in norm if s in self._eq_subs}
        if not to_drop:
            return
        try:
            unsubs = getattr(self.stream, "level_one_equity_unsubs", None) if self.stream else None
            if callable(unsubs):
                await unsubs(list(to_drop))
        except Exception:
            pass
        self._eq_subs.difference_update(to_drop)

    async def _pump(self) -> None:
        assert self.stream is not None
        while self._running:
            try:
                # Use a timeout to periodically check for heartbeat
                await asyncio.wait_for(self.stream.handle_message(), timeout=30.0)
                # Update last success time and reset failure tracking
                self._last_success_time = time.time()
                # Update last message time for heartbeat
                self._last_message_time = time.time()
                self._failure_notified = False
                # If we had errors previously, reset streak on success
                if self._error_streak:
                    self._error_streak = 0
            except asyncio.TimeoutError:
                # Check if we've exceeded the heartbeat timeout (5 minutes = 300 seconds)
                time_since_last_message = time.time() - self._last_message_time
                if time_since_last_message > 300:  # 5 minutes
                    # Trigger a restart due to heartbeat timeout
                    try:
                        publish(f"Streaming connection heartbeat timeout after {int(time_since_last_message)}s, restarting...")
                    except Exception:
                        pass
                    await self._restart_stream_for_heartbeat_timeout()
                    continue  # Continue the loop after restart
                # If we haven't exceeded the heartbeat timeout, continue waiting for messages
                continue
            except (ConnectionResetError, OSError) as e:
                # Socket dropped; attempt reconnect with backoff and resubscribe
                self._error_streak += 1
                backoff = min(30, 2 ** min(5, self._error_streak))
                try:
                    publish(f"Streaming connection lost; reconnecting in {backoff}s (attempt {self._error_streak}).")
                except Exception:
                    pass
                
                # Check for extended failure (5 minutes)
                if time.time() - self._last_success_time > 300 and not self._failure_notified:
                    try:
                        alert.alert(None, "Quote feed has been failing for more than 5 minutes. Please check connection.", True)
                        self._failure_notified = True
                    except Exception:
                        pass

                await asyncio.sleep(backoff)
                try:
                    await self._restart_stream()
                    try:
                        publish("Streaming connection re-established.")
                        # Reset failure tracking on successful reconnection
                        self._last_success_time = time.time()
                        self._last_message_time = time.time()  # Reset message time on successful connection
                        self._watchdog_last_restart = self._last_message_time
                        self._failure_notified = False
                    except Exception:
                        pass
                except Exception as re:
                    # Keep loop alive; next iteration will backoff more
                    publish_exception(re, prefix="Streaming restart failed")
                    await asyncio.sleep(1)
            except Exception as e:
                # Generic, transient issue; small pause
                await asyncio.sleep(0.5)

    async def _restart_stream(self) -> None:
        """Recreate the StreamClient, login, and resubscribe symbols."""
        if not self._running:
            return
        async with self._restart_lock:
            if not self._running:
                return
            # Close previous stream if exists
            try:
                if self.stream:
                    try:
                        await self.stream.logout()
                    except Exception:
                        pass
            finally:
                self.stream = None

            # Rebuild stream and handlers, then login
            self.stream = StreamClient(self.client, account_id=self.account_id)
            self.stream.add_level_one_option_handler(self._on_level_one_option)
            try:
                self.stream.add_level_one_equity_handler(self._on_level_one_equity)
            except Exception:
                pass
            await self.stream.login()
            # Resubscribe existing symbol sets
            try:
                if self._opt_subs:
                    await self.stream.level_one_option_subs(list(self._opt_subs))
            except Exception:
                pass
            try:
                if self._eq_subs:
                    await self.stream.level_one_equity_subs(list(self._eq_subs))
            except Exception:
                pass
            # Reset heartbeat timing on successful restart
            self._last_message_time = time.time()
            self._watchdog_last_restart = self._last_message_time

    async def _restart_stream_for_heartbeat_timeout(self) -> None:
        """Restart the stream specifically due to heartbeat timeout - reset the error streak."""
        # Reset the error streak for heartbeat timeouts to avoid exponential backoff
        # since this is a different type of failure
        self._error_streak = 0
        await self._restart_stream()
        # Update last message time on successful restart to prevent immediate restart cycle
        self._last_message_time = time.time()
        self._watchdog_last_restart = self._last_message_time

    async def _heartbeat_watchdog(self) -> None:
        """Monitor the heartbeat independently of the pump and trigger restarts when stale."""
        try:
            while self._running:
                await asyncio.sleep(60)
                if not self._running:
                    break
                elapsed = time.time() - self._last_message_time
                if elapsed <= 300:
                    continue
                now = time.time()
                # Avoid rapid-fire restarts if multiple triggers occur
                if now - self._watchdog_last_restart < 60:
                    continue
                try:
                    publish(
                        f"Streaming heartbeat stale for {int(elapsed)}s; forcing restart via watchdog."
                    )
                except Exception:
                    pass
                try:
                    await self._restart_stream_for_heartbeat_timeout()
                except Exception as exc:
                    publish_exception(exc, prefix="Heartbeat watchdog restart failed")
        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as exc:
            publish_exception(exc, prefix="Heartbeat watchdog crashed")

    async def _on_level_one_option(self, msg: Dict) -> None:
        contents = msg.get("content") or []
        for c in contents:
            key = c.get("key") or c.get("symbol")
            if not key:
                continue
            last = self._last.setdefault(key, {})
            # Normalize and update last-good only if present and valid
            rb = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID") or c.get("bid")
            ra = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK") or c.get("ask")
            rl = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST") or c.get("last")
            try:
                if rb is not None:
                    fb = float(rb)
                    if fb > 0:
                        last["bid"] = fb
            except Exception:
                pass
            try:
                if ra is not None:
                    fa = float(ra)
                    if fa > 0:
                        last["ask"] = fa
            except Exception:
                pass
            try:
                if rl is not None:
                    fl = float(rl)
                    if fl > 0:
                        last["last"] = fl
            except Exception:
                pass
            # Publish a normalized snapshot using last-good values
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
            # Normalize and update last-good only if present and valid
            rb = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID") or c.get("bid")
            ra = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK") or c.get("ask")
            rl = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST") or c.get("last")
            try:
                if rb is not None:
                    fb = float(rb)
                    if fb > 0:
                        last["bid"] = fb
            except Exception:
                pass
            try:
                if ra is not None:
                    fa = float(ra)
                    if fa > 0:
                        last["ask"] = fa
            except Exception:
                pass
            try:
                if rl is not None:
                    fl = float(rl)
                    if fl > 0:
                        last["last"] = fl
            except Exception:
                pass
            # Publish a normalized snapshot using last-good values
            snap = {"key": key}
            if "bid" in last:
                snap["BID_PRICE"] = last["bid"]
            if "ask" in last:
                snap["ASK_PRICE"] = last["ask"]
            if "last" in last:
                snap["LAST_PRICE"] = last["last"]
            self._quotes[key] = snap

    def is_subscribed(self, symbol: str) -> bool:
        return symbol in self._opt_subs or symbol.upper() in self._eq_subs

    def get_full_quote(self, symbol: str) -> Optional[Dict]:
        return self._quotes.get(symbol)

    def get_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        q = self.get_full_quote(symbol)
        if not q:
            return (None, None)
        bid = q.get("BID_PRICE") or q.get("bidPrice") or q.get("BID") or q.get("bid")
        ask = q.get("ASK_PRICE") or q.get("askPrice") or q.get("ASK") or q.get("ask")
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
        q = self.get_full_quote(symbol)
        if not q:
            return None
        last = q.get("LAST_PRICE") or q.get("lastPrice") or q.get("LAST") or q.get("last")
        try:
            return float(last) if last is not None else None
        except Exception:
            return None

    # Duplicate helper methods removed (see earlier definitions above)

    def get_all_subscribed(self) -> set[str]:
        return set(self._opt_subs) | set(self._eq_subs)

    def get_last_heartbeat_time(self) -> Optional[float]:
        """Return the timestamp (epoch seconds) of the most recent message."""
        return self._last_message_time


_global_provider: Optional[StreamingQuoteProvider] = None

async def ensure_provider(connect_client) -> StreamingQuoteProvider:
    global _global_provider
    if _global_provider is None:
        prov = StreamingQuoteProvider(connect_client)
        await prov.start()
        _global_provider = prov
    return _global_provider

def get_provider(connect_client) -> StreamingQuoteProvider:
    global _global_provider
    if _global_provider is None:
        prov = StreamingQuoteProvider(connect_client)
        asyncio.create_task(prov.start())
        _global_provider = prov
    return _global_provider
