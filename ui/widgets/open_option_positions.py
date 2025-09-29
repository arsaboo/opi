from datetime import datetime

from rich.text import Text
from textual import work
from textual.widgets import DataTable, Static

from .. import logic
from ..widgets.status_log import StatusLog
from ..utils import style_cell as cell


class OpenOptionPositionsWidget(Static):
    """Display all open option positions in a read-only table."""

    REFRESH_SECONDS = 20
    MARKET_STATUS_SECONDS = 30

    def __init__(self):
        super().__init__()
        self._previous_market_status = None
        self._prev_rows = None
        self._initial_load = True

    def compose(self):
        yield DataTable(id="open_option_positions_table")

    def on_mount(self) -> None:
        self.app.update_header("Options Trader - Open Option Positions")
        table = self.query_one(DataTable)
        table.add_columns(
            "Ticker",
            "Option",
            "Side",
            "Type",
            "Current Strike",
            "Expiration",
            "DTE",
            "Underlying",
            "Status",
            "Qty",
            "Avg Price",
            "Mark",
            "P/L Day",
            "P/L Open",
            "Refreshed",
        )
        table.zebra_stripes = True
        table.cursor_type = "row"
        table.focus()

        self.refresh_positions()
        self.set_interval(self.REFRESH_SECONDS, self.refresh_positions)
        self.set_interval(self.MARKET_STATUS_SECONDS, self.check_market_status)

    def check_market_status(self) -> None:
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            current_status = "open" if exec_window.get("open") else "closed"
            if self._previous_market_status != current_status:
                message = "Market is now OPEN!" if current_status == "open" else "Market is closed."
                self.query_one(StatusLog).add_message(message)
                self._previous_market_status = current_status
        except Exception as exc:
            try:
                self.query_one(StatusLog).add_message(f"Error checking market status: {exc}")
            except Exception:
                pass

    @work
    async def refresh_positions(self) -> None:
        try:
            data = await logic.get_open_option_positions_data(self.app.api)
        except Exception as exc:
            try:
                self.query_one(StatusLog).add_message(f"Failed to load option positions: {exc}")
            except Exception:
                pass
            return

        table = self.query_one(DataTable)
        prev_rows = self._prev_rows or []
        cursor_col = getattr(table, "cursor_column", 0)
        cursor_row = getattr(table, "cursor_row", 0)

        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        for idx, row in enumerate(data):
            prev_row = prev_rows[idx] if idx < len(prev_rows) else {}
            table.add_row(
                Text(str(row.get("Ticker", "")), justify="left"),
                Text(str(row.get("Option Symbol", "")), justify="left"),
                Text(str(row.get("Side", "")), justify="left"),
                Text(str(row.get("Type", "")), justify="left"),
                cell("Current Strike", row.get("Current Strike"), prev_row.get("Current Strike")),
                Text(str(row.get("Expiration", "")), justify="left"),
                cell("DTE", row.get("DTE"), prev_row.get("DTE")),
                cell("Underlying", row.get("Underlying"), prev_row.get("Underlying")),
                cell("Status", row.get("Status"), prev_row.get("Status")),
                cell("Qty", row.get("Qty"), prev_row.get("Qty")),
                cell("Avg Price", row.get("Avg Price"), prev_row.get("Avg Price")),
                cell("Mark", row.get("Mark"), prev_row.get("Mark")),
                cell("P/L Day", row.get("P/L Day"), prev_row.get("P/L Day")),
                cell("P/L Open", row.get("P/L Open"), prev_row.get("P/L Open")),
                Text(refreshed_time, justify="left"),
            )

        if data:
            try:
                table.move_cursor(row=min(cursor_row, len(data) - 1), column=cursor_col)
            except Exception:
                pass

        self._prev_rows = data

        if self._initial_load:
            try:
                self.query_one(StatusLog).add_message(f"Loaded {len(data)} open option positions.")
            except Exception:
                pass
            self._initial_load = False
        elif not data:
            try:
                self.query_one(StatusLog).add_message("No open option positions found.")
            except Exception:
                pass
