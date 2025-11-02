from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Container, Vertical
from textual import work
from textual.binding import Binding
from rich.table import Table
from rich import box
from rich.text import Text

from .base_spread_view import BaseSpreadView
from .. import logic
from ..widgets.status_log import StatusLog
from services.sector_allocation_service import ALL_SECTORS


class SectorAllocationView(BaseSpreadView):
    """Display portfolio sector allocation with a Rich-powered table."""

    can_focus = True
    BINDINGS = [
        Binding("r", "refresh_data", "Refresh data"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_report = None
        self._updated_symbols = set()

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Vertical(
            Static("Sector Allocation Dashboard", id="sector_header", classes="title"),
            Container(
                Static("Loading sector allocation data...", id="sector_chart_display"),
                id="sector_chart_container",
            ),
            Static("Status: Loading...", id="status_text"),
            id="main_container",
        )

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Sector Allocation")

        chart_container = self.query_one("#sector_chart_container")
        chart_container.border_title = "Sector Allocation"

        self.focus()

        self.load_sector_data()

    def action_refresh_data(self) -> None:
        """Trigger a force refresh via keyboard binding."""
        self.load_sector_data(force_refresh=True)

    @work
    async def load_sector_data(self, force_refresh: bool = False) -> None:
        """Load sector allocation data from the API layer."""
        try:
            status_msg = f"Fetching sector allocation data{' (force refresh)' if force_refresh else ''}..."
            self.app.query_one(StatusLog).add_message(status_msg)
            self.query_one("#status_text").update(f"Status: {status_msg}")

            report, updated_symbols = await logic.get_sector_allocation_from_api(
                self.app.api, force_refresh=force_refresh
            )

            self._current_report = report
            self._updated_symbols = updated_symbols

            self.update_sector_chart()

            if updated_symbols:
                updated_list = ", ".join(sorted(updated_symbols))
                self.app.query_one(StatusLog).add_message(
                    f"Updated sector data for: {updated_list}"
                )

            success_msg = (
                f"Sector allocation data loaded successfully. "
                f"({len(updated_symbols)} symbols updated) Press 'r' to refresh."
            )
            self.app.query_one(StatusLog).add_message(success_msg)
            self.query_one("#status_text").update(f"Status: {success_msg}")

        except Exception as exc:  # pragma: no cover - UI path
            error_msg = f"Error loading sector data: {exc}"
            self.app.query_one(StatusLog).add_message(error_msg)
            self.query_one("#status_text").update(f"Status: {error_msg}")

    def update_sector_chart(self) -> None:
        """Refresh the rendered sector table."""
        if not self._current_report:
            self.query_one("#sector_chart_display").update(
                Text("No sector data available.", style="italic")
            )
            return

        sector_percentages = self._current_report.get("sector_percentages", {})
        if not sector_percentages:
            self.query_one("#sector_chart_display").update(
                Text("No sector data available.", style="italic")
            )
            return

        ordered_sectors = [
            (sector, sector_percentages.get(sector, 0.0)) for sector in ALL_SECTORS
        ]
        ordered_sectors.sort(key=lambda item: item[1], reverse=True)

        if not ordered_sectors:
            self.query_one("#sector_chart_display").update(
                Text("All sectors are at 0%.", style="italic")
            )
            return

        max_pct = max(pct for _, pct in ordered_sectors) or 100.0
        table = self._create_sector_table(ordered_sectors, max_pct)
        self.query_one("#sector_chart_display").update(table)

    def _create_sector_table(self, sectors_data, max_pct) -> Table:
        """Build a Rich table renderable that shows sector contributions."""
        sector_values = (
            self._current_report.get("sector_values", {}) if self._current_report else {}
        )
        total_value = (
            self._current_report.get("total_market_value", 0.0)
            if self._current_report
            else 0.0
        )
        gross_value = (
            self._current_report.get("gross_market_value", 0.0)
            if self._current_report
            else 0.0
        )

        table = Table(
            expand=False,
            box=box.SIMPLE_HEAVY,
            show_edge=True,
            pad_edge=False,
            padding=(0, 1),
        )
        table.add_column("Sector", justify="left", style="bold cyan", no_wrap=True)
        table.add_column("Market Value", justify="right", width=16, no_wrap=True)
        table.add_column("Allocation", justify="right", width=10, no_wrap=True)
        table.add_column("Distribution", justify="left", no_wrap=True, width=28)

        max_pct = max_pct or 100.0
        for index, (sector, pct) in enumerate(sectors_data):
            value = sector_values.get(sector, 0.0)
            label = Text(sector)
            bar_width = int(round((pct / max_pct) * 24)) if max_pct else 0
            bar_width = max(0, min(bar_width, 24))
            padding = 24 - bar_width

            bar_text = Text("|", style="dim")
            bar_text.append("#" * bar_width, style="cyan")
            if padding:
                bar_text.append(" " * padding)
            bar_text.append("|", style="dim")

            table.add_row(
                label,
                f"${value:,.2f}",
                f"{pct:,.2f}%",
                bar_text,
                end_section=index == len(sectors_data) - 1,
            )
        total_pct = sum(pct for _, pct in sectors_data)
        table.add_row(
            Text("Total Portfolio Value", style="bold white"),
            Text(f"${total_value:,.2f}", style="bold white"),
            Text(f"{total_pct:,.2f}%", style="bold white"),
            "",
        )

        updated_symbols = sorted(self._updated_symbols)
        updated_hint = (
            f"Refreshed symbols: {', '.join(updated_symbols)}"
            if updated_symbols
            else "No symbol-level updates in this request."
        )
        timestamp = (
            self._current_report.get("as_of", "N/A") if self._current_report else "N/A"
        )
        table.caption = Text(
            f"Gross exposure: ${gross_value:,.2f} | As of {timestamp} | {updated_hint}",
            style="dim",
        )

        return table
