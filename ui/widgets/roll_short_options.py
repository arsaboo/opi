from textual.widgets import DataTable, Static
from textual import work
from datetime import datetime
from .. import logic
from rich.text import Text

class RollShortOptionsWidget(Static):
    """A widget to display short options to be rolled."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="roll_short_options_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns(
            "Ticker",
            "Current Strike",
            "Expiration",
            "DTE",
            "New Strike",
            "New Expiration",
            "Roll Out (Days)",
            "Credit",
            "Strike Δ",
            "Config Status",
            "Refreshed"
        )
        # Style the header
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        table.add_row("Loading...", "", "", "", "", "", "", "", "", "", "")
        self.run_get_expiring_shorts_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_expiring_shorts_data)

    @work
    async def run_get_expiring_shorts_data(self) -> None:
        """Worker to get the expiring shorts data."""
        data = await logic.get_expiring_shorts_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_class(col, val, prev_val=None):
            if col == "Credit":
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style for positive/negative
                    style = "green" if v > 0 else "red" if v < 0 else ""
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Or any other style for increase
                        elif v < pv:
                            style = "bold red"    # Or any other style for decrease
                    return style
                except:
                    return ""
            if col == "Strike Δ":
                try:
                    v = float(val)
                    if v > 0:
                        return "green"
                    elif v < 0:
                        return "red"
                except:
                    pass
            if col == "Config Status":
                if val == "Not Configured":
                    return "yellow"
            return ""

        if data:
            prev_rows = self._prev_rows or []
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}
                
                # Function to style a cell value
                def style_cell(col_name, col_index):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_class(col_name, val, prev_val)
                    # Justify Credit and Strike Δ to the right
                    justify = "right" if col_index in [7, 8] else "left"
                    return Text(val, style=style, justify=justify)
                
                cells = [
                    Text(str(row["Ticker"]), style="", justify="left"),
                    Text(str(row["Current Strike"]), style="", justify="right"),
                    Text(str(row["Expiration"]), style="", justify="left"),
                    Text(str(row["DTE"]), style="", justify="right"),
                    Text(str(row["New Strike"]), style="", justify="right"),
                    Text(str(row["New Expiration"]), style="", justify="left"),
                    Text(str(row["Roll Out (Days)"]), style="", justify="right"),
                    style_cell("Credit", 7),
                    style_cell("Strike Δ", 8),
                    Text(str(row["Config Status"]), style=get_cell_class("Config Status", row["Config Status"]), justify="left"),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = data
        else:
            table.add_row("No expiring options found.", "", "", "", "", "", "", "", "", "", refreshed_time)