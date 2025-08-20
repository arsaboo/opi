from textual.widgets import DataTable, Static
from textual import work
from .. import logic

class CheckSyntheticCoveredCallsWidget(Static):
    """A widget to display synthetic covered calls."""

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="synthetic_covered_calls_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns(
            "Asset",
            "Expiration",
            "Strike Low",
            "Call Low B|A",
            "Put Low B|A",
            "Strike High",
            "Call High B|A",
            "Investment",
            "Max Profit",
            "CAGR",
            "Protection",
            "Margin Req",
            "Ann. ROM %",
        )
        table.add_row("Loading...", "", "", "", "", "", "", "", "", "", "", "", "")
        self.run_get_synthetic_covered_calls_data()

    @work
    async def run_get_synthetic_covered_calls_data(self) -> None:
        """Worker to get synthetic covered calls data."""
        data = await logic.get_vertical_spreads_data(self.app.api, synthetic=True)
        table = self.query_one(DataTable)
        table.clear()
        if data:
            for row in data:
                # Extract bid/ask values from the data with | separator
                call_low_ba = f"{row['bid1']:.2f}|{row['ask1']:.2f}"
                call_high_ba = f"{row['bid2']:.2f}|{row['ask2']:.2f}"
                put_low_ba = f"{row['put_bid']:.2f}|{row['put_ask']:.2f}"
                
                table.add_row(
                    row["asset"],
                    row["expiration"],
                    row["strike_low"],
                    call_low_ba,
                    put_low_ba,
                    row["strike_high"],
                    call_high_ba,
                    row["investment"],
                    row["max_profit"],
                    row["cagr"],
                    row["protection"],
                    row["margin_req"],
                    row["ann_rom"],
                )
        else:
            table.add_row("No synthetic covered calls found.", "", "", "", "", "", "", "", "", "", "", "", "")
