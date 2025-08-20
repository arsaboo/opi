from textual.widgets import DataTable, Static
from textual import work
from .. import logic

class CheckBoxSpreadsWidget(Static):
    """A widget to display box spreads."""

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="box_spreads_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns(
            "Date",
            "Low Strike",
            "High Strike",
            "Net Price",
            "% CAGR",
            "Direction",
            "Borrowed",
            "Repayment",
            "Margin Req",
            "Ann. ROM %",
        )
        table.add_row("Loading...", "", "", "", "", "", "", "", "", "")
        self.run_get_box_spreads_data()

    @work
    async def run_get_box_spreads_data(self) -> None:
        """Worker to get box spreads data."""
        data = await logic.get_box_spreads_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        if data:
            for row in data:
                table.add_row(
                    row["date"],
                    row["low_strike"],
                    row["high_strike"],
                    row["net_price"],
                    row["cagr"],
                    row["direction"],
                    row["borrowed"],
                    row["repayment"],
                    row["margin_req"],
                    row["ann_rom"],
                )
        else:
            table.add_row("No box spreads found.", "", "", "", "", "", "", "", "", "")
