from textual.widgets import DataTable, Static, Label
from textual import work
from .. import logic

class ViewMarginRequirementsWidget(Static):
    """A widget to display margin requirements."""

    def compose(self):
        """Create child widgets."""
        yield Label("Total Margin Requirement: Loading...", id="total_margin_label")
        yield DataTable(id="margin_requirements_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns(
            "Symbol",
            "Type",
            "Strike",
            "Expiration",
            "Count",
            "Margin",
        )
        table.add_row("Loading...", "", "", "", "", "")
        self.run_get_margin_requirements_data()

    @work
    async def run_get_margin_requirements_data(self) -> None:
        """Worker to get margin requirements data."""
        margin_data, total_margin = await logic.get_margin_requirements_data(self.app.api)
        
        table = self.query_one(DataTable)
        table.clear()

        total_margin_label = self.query_one("#total_margin_label", Label)
        total_margin_label.update(f"Total Margin Requirement: ${total_margin:,.2f}")

        if margin_data:
            for row in margin_data:
                table.add_row(
                    row["symbol"],
                    row["type"],
                    row["strike"],
                    row["expiration"],
                    row["count"],
                    row["margin"],
                )
        else:
            table.add_row("No margin requirements found.", "", "", "", "", "")
