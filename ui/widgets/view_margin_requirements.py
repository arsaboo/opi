from textual.widgets import DataTable, Static, Label
from textual import work
from datetime import datetime
from .. import logic
from ..widgets.status_log import StatusLog
from rich.text import Text
from ..utils import style_cell as cell

class ViewMarginRequirementsWidget(Static):
    """A widget to display margin requirements."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._previous_market_status = None  # Track previous market status

    def compose(self):
        """Create child widgets."""
        yield Label("Total Margin Requirement: Loading...", id="total_margin_label")
        yield DataTable(id="margin_requirements_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Margin Requirements")
        # Only check market status if not already set
        if self._previous_market_status is None:
            self.check_market_status()

        table = self.query_one(DataTable)
        table.add_columns(
            "Symbol",
            "Type",
            "Strike",
            "Expiration",
            "Count",
            "Margin",
            "Refreshed"
        )
        # Style the header
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        # Enable row selection
        table.cursor_type = "row"
        # Make sure the table can receive focus
        table.focus()
        self.run_get_margin_requirements_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_margin_requirements_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            current_status = "open" if exec_window["open"] else "closed"
            # Only log if status changed
            if self._previous_market_status != current_status:
                if current_status == "open":
                    self.app.query_one(StatusLog).add_message("Market is now OPEN! Trades can be placed.")
                else:
                    from configuration import debugMarketOpen
                    if not debugMarketOpen:
                        self.app.query_one(StatusLog).add_message("Market is closed. Data may be delayed.")
                    else:
                        self.app.query_one(StatusLog).add_message("Market is closed but running in debug mode.")
                self._previous_market_status = current_status
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    @work
    async def run_get_margin_requirements_data(self) -> None:
        """Worker to get margin requirements data."""
        margin_data, total_margin = await logic.get_margin_requirements_data(self.app.api)

        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        total_margin_label = self.query_one("#total_margin_label", Label)
        total_margin_label.update(f"Total Margin Requirement: ${total_margin:,.2f}")

        # Using shared cell styling from ui.utils
        if margin_data:
            prev_rows = self._prev_rows or []
            for idx, row in enumerate(margin_data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                def style_cell(col_name):
                    return cell(col_name, row.get(col_name), prev_row.get(col_name))

                cells = [
                    Text(str(row["symbol"]), style="", justify="left"),
                    Text(str(row["type"]), style="", justify="left"),
                    style_cell("strike"),
                    Text(str(row["expiration"]), style="", justify="left"),
                    style_cell("count"),
                    style_cell("margin"),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = margin_data
        else:
            table.add_row("No margin requirements found.", "", "", "", "", "", refreshed_time)

