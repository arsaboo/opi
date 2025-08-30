from textual.widgets import Static
from textual import work
from textual.timer import Timer
from rich.text import Text
from typing import Dict, Optional

from api.streaming.provider import get_provider, ensure_provider
from configuration import stream_quotes


class AppHeader(Static):
    """Single-line header with indices (SPX, NDX) and current screen title."""

    CANDIDATES = {
        "SPX": ["$SPX", "$SPX.X"],
        "NDX": ["$NDX", "$NDX.X"],
    }

    def __init__(self) -> None:
        super().__init__()
        self._provider = None
        self._chosen: Dict[str, Optional[str]] = {k: None for k in self.CANDIDATES}
        self._prev_close: Dict[str, Optional[float]] = {k: None for k in self.CANDIDATES}
        self._rest_last: Dict[str, Optional[float]] = {k: None for k in self.CANDIDATES}
        self._title: str = "Options Trader"
        self._tick: Optional[Timer] = None
        self._poll: Optional[Timer] = None

    def on_mount(self) -> None:
        # styling consistent with original Header
        self.styles.background = "darkblue"
        self.styles.color = "white"
        self.styles.text_style = "bold"
        try:
            self._provider = get_provider(self.app.api.connectClient)
        except Exception:
            self._provider = None
        # Resolve best symbols and prev close
        self._init_symbols()
        # Refresh paint every second
        self._tick = self.set_interval(1, self.refresh_view)
        # Poll REST last every 10s as fallback
        self._poll = self.set_interval(10, self._poll_last_rest)

    def set_title(self, title: str) -> None:
        self._title = title
        self.refresh()

    @work
    async def _init_symbols(self) -> None:
        try:
            # Probe all candidates; pick first that returns a quote
            all_syms = []
            for arr in self.CANDIDATES.values():
                all_syms.extend(arr)
            r = self.app.api.connectClient.get_quotes(all_syms)
            r.raise_for_status()
            data = r.json()
            for label, cands in self.CANDIDATES.items():
                chosen = None
                prev = None
                for sym in cands:
                    q = data.get(sym) or {}
                    last = q.get("quote", {}).get("lastPrice")
                    pcls = (
                        q.get("quote", {}).get("previousClose")
                        or q.get("quote", {}).get("closePrice")
                        or q.get("quote", {}).get("regularMarketPreviousClose")
                    )
                    if last is not None or pcls is not None:
                        chosen = sym
                        try:
                            prev = float(pcls) if pcls is not None else None
                        except Exception:
                            prev = None
                        break
                self._chosen[label] = chosen
                self._prev_close[label] = prev
            # Ensure provider is running, then subscribe to chosen symbols (avoid redundancy)
            if stream_quotes:
                prov = await ensure_provider(self.app.api.connectClient)
                self._provider = prov
                to_sub = [s for s in self._chosen.values() if s]
                if to_sub:
                    await prov.subscribe_equities(to_sub)
        except Exception:
            pass

    @work
    async def _poll_last_rest(self) -> None:
        try:
            syms = [s for s in self._chosen.values() if s]
            if not syms:
                return
            r = self.app.api.connectClient.get_quotes(syms)
            r.raise_for_status()
            data = r.json()
            for label, sym in self._chosen.items():
                if not sym:
                    continue
                q = data.get(sym) or {}
                last = (
                    q.get("quote", {}).get("lastPrice")
                    or q.get("quote", {}).get("regularMarketLastPrice")
                    or q.get("quote", {}).get("mark")
                )
                try:
                    self._rest_last[label] = float(last) if last is not None else None
                except Exception:
                    pass
        except Exception:
            pass

    def refresh_view(self) -> None:
        # Build left indices both as Text (styled) and plain string to compute padding
        left_text = Text()
        left_plain_parts: list[str] = []

        def add_label(label: str) -> None:
            last = None
            sym = self._chosen.get(label)
            if sym and self._provider:
                try:
                    last = self._provider.get_last(sym)
                except Exception:
                    last = None
            if last is None:
                last = self._rest_last.get(label)
            prev = self._prev_close.get(label)
            if last is None:
                seg = f"{label} —   "
                left_plain_parts.append(seg)
                left_text.append(seg)
                return
            last_str = f"{last:,.2f}"
            if prev and prev > 0:
                delta = last - prev
                pct = 100.0 * delta / prev
                sign = "+" if delta >= 0 else ""
                color = "bold green" if delta >= 0 else "bold red"
                # Plain string for width calc
                seg_plain = f"{label:>3} {last_str} {sign}{delta:.2f} ({sign}{pct:.2f}%)  "
                left_plain_parts.append(seg_plain)
                # Styled text
                left_text.append(f"{label:>3} {last_str} ")
                left_text.append(f"{sign}{delta:.2f}", style=color)
                left_text.append(f" ({sign}{pct:.2f}%)  ", style=color)
            else:
                seg = f"{label:>3} {last_str}   "
                left_plain_parts.append(seg)
                left_text.append(seg)

        add_label("SPX")
        add_label("NDX")

        left_plain = "".join(left_plain_parts)
        width = getattr(self.size, "width", 0) or 0
        title = self._title
        # Compute padding to approximately center the title, accounting for left content
        if width > 0:
            pad = max(1, (width - len(title)) // 2 - len(left_plain))
        else:
            pad = 2
        pad_str = " " * pad

        out = Text()
        out.append(left_text)
        out.append(pad_str)
        out.append(title)
        self.update(out)


