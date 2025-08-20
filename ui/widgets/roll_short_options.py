from textual.widgets import DataTable, Static
from textual import work
from .. import logic

class RollShortOptionsWidget(Static):
    """A widget to display short options to be rolled."""

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="roll_short_options_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns("Ticker", "Expiring Option", "DTE", "Roll To", "Config Status")
        table.add_row("Loading...", "", "", "", "")
        self.run_get_expiring_shorts_data()

    @work
    async def run_get_expiring_shorts_data(self) -> None:
        """Worker to get the expiring shorts data."""
        data = await logic.get_expiring_shorts_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        if data:
            for row in data:
                table.add_row(row["Ticker"], row["Expiring Option"], row["DTE"], row["Roll To"], row["Config Status"])
        else:
            table.add_row("No expiring options found.", "", "", "", "")
