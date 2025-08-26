from textual.widgets import DataTable, Static, Label
from textual import work
from datetime import datetime
from .. import logic
from ..widgets.status_log import StatusLog
from rich.text import Text

class ViewMarginRequirementsWidget(Static):
    """A widget to display margin requirements."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None

    def compose(self):
        """Create child widgets."""
        yield Label("Total Margin Requirement: Loading...", id="total_margin_label")
        yield DataTable(id="margin_requirements_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Update the header
        self.app.update_header("Options Trader - Margin Requirements")
        
        # Check market status
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
        
    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            if not exec_window["open"]:
                from configuration import debugMarketOpen
                if not debugMarketOpen:
                    self.app.query_one(StatusLog).add_message("Market is closed. Data may be delayed.")
                else:
                    self.app.query_one(StatusLog).add_message("Market is closed but running in debug mode.")
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

        def get_cell_style(col, val, prev_val=None):
            if col == "Margin":
                try:
                    v = float(str(val).replace("$", "").replace(",", ""))
                    pv = float(str(prev_val).replace("$", "").replace(",", "")) if prev_val is not None else None
                    # Base style - color based on value (low/high)
                    if v < 5000:
                        style = "green"  # Good (low)
                    elif v < 10000:
                        style = "yellow"  # Warning (medium)
                    else:
                        style = "red"   # Bad (high)
                    # Highlight changes - override with bold colors for increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold red"    # Bold red for increase (worse)
                        elif v < pv:
                            style = "bold green"  # Bold green for decrease (better)
                    return style
                except:
                    return ""
            if col == "strike":
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold"  # Bold for increase
                        elif v < pv:
                            style = "bold"  # Bold for decrease
                    return style
                except:
                    pass
            if col == "count":
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold"  # Bold for increase
                        elif v < pv:
                            style = "bold"  # Bold for decrease
                    return style
                except:
                    pass
            return ""

        if margin_data:
            prev_rows = self._prev_rows or []
            for idx, row in enumerate(margin_data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}
                
                # Function to style a cell value
                def style_cell(col_name):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_style(col_name, val, prev_val)
                    # Justify numerical columns to the right
                    right_justify_cols = {"strike", "count", "margin"}
                    justify = "right" if col_name in right_justify_cols else "left"
                    return Text(val, style=style, justify=justify)
                
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