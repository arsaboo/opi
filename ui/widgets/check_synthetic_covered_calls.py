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
            "Strike High",
            "Investment",
            "Max Profit",
            "CAGR",
            "Protection",
            "Margin Req",
            "Ann. ROM %",
        )
        table.add_row("Loading...", "", "", "", "", "", "", "", "", "")
        self.run_get_synthetic_covered_calls_data()

    @work
    async def run_get_synthetic_covered_calls_data(self) -> None:
        """Worker to get synthetic covered calls data."""
        data = await logic.get_vertical_spreads_data(self.app.api, synthetic=True)
        table = self.query_one(DataTable)
        table.clear()
        if data:
            for row in data:
                table.add_row(
                    row["asset"],
                    row["expiration"],
                    row["strike_low"],
                    row["strike_high"],
                    row["investment"],
                    row["max_profit"],
                    row["cagr"],
                    row["protection"],
                    row["margin_req"],
                    row["ann_rom"],
                )
        else:
            table.add_row("No synthetic covered calls found.", "", "", "", "", "", "", "", "", "")
