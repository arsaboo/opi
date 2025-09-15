from textual.widgets import Static
from textual import work
from textual.timer import Timer
from rich.text import Text
from typing import Optional

from api.streaming.provider import get_provider, ensure_provider
from configuration import stream_quotes


class AppHeader(Static):
    """Single-line header showing SPX and the current screen title.

    Subscribes to and displays $SPX using streaming quotes and performs
    a one-time REST query to fetch previous close for delta/percent.
    """

    SPX_SYM = "$SPX"

    def __init__(self) -> None:
        super().__init__()
        self._provider = None
        self._spx_prev: Optional[float] = None
        self._title: str = "Options Trader"
        self._tick: Optional[Timer] = None

    def on_mount(self) -> None:
        # styling consistent with original Header
        self.styles.background = "darkblue"
        self.styles.color = "white"
        self.styles.text_style = "bold"
        try:
            self._provider = get_provider(self.app.api.connectClient)
        except Exception:
            self._provider = None
        # Initialize: fetch previous close and ensure streaming subs
        self._init_header()
        # Refresh paint every second
        self._tick = self.set_interval(1, self.refresh_view)

    def set_title(self, title: str) -> None:
        self._title = title
        self.refresh()

    @work
    async def _init_header(self) -> None:
        # One-time previous close via REST for SPX
        try:
            r = self.app.api.connectClient.get_quotes([self.SPX_SYM])
            r.raise_for_status()
            data = r.json()
            def prev_close(q: dict) -> Optional[float]:
                quote = q.get("quote", {}) if isinstance(q, dict) else {}
                pc = quote.get("previousClose") or quote.get("closePrice") or quote.get("regularMarketPreviousClose")
                try:
                    return float(pc) if pc is not None else None
                except Exception:
                    return None
            self._spx_prev = prev_close(data.get(self.SPX_SYM, {}))
        except Exception:
            # Previous close is optional; continue
            pass

        # Ensure provider and subscribe to both symbols
        try:
            if stream_quotes:
                prov = await ensure_provider(self.app.api.connectClient)
                self._provider = prov
                await prov.subscribe_equities([self.SPX_SYM])
        except Exception:
            pass

    def refresh_view(self) -> None:
        # Build left indices both as Text (styled) and plain string to compute padding
        left_text = Text()
        left_plain_parts: list[str] = []

        def add_symbol(label: str, symbol: str, prev: Optional[float]) -> None:
            last = None
            if self._provider:
                try:
                    last = self._provider.get_last(symbol)
                except Exception:
                    last = None
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
                seg_plain = f"{label:>3} {last_str} {sign}{delta:.2f} ({sign}{pct:.2f}%)  "
                left_plain_parts.append(seg_plain)
                left_text.append(f"{label:>3} {last_str} ")
                left_text.append(f"{sign}{delta:.2f}", style=color)
                left_text.append(f" ({sign}{pct:.2f}%)  ", style=color)
            else:
                seg = f"{label:>3} {last_str}   "
                left_plain_parts.append(seg)
                left_text.append(seg)

        add_symbol("SPX", self.SPX_SYM, self._spx_prev)

        left_plain = "".join(left_plain_parts)
        width = getattr(self.size, "width", 0) or 0
        title = self._title
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


