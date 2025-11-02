from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Container
from textual.widgets import Tabs, Tab
from rich.text import Text

from .base_spread_view import BaseSpreadView
from ..widgets.view_margin_requirements import ViewMarginRequirementsWidget
from ..widgets.open_option_positions import OpenOptionPositionsWidget
from .sector_allocation_view import SectorAllocationView


class PortfolioDashboardView(BaseSpreadView):
    """Unified dashboard grouping portfolio widgets under tabs."""

    can_focus = True

    BINDINGS = [
        Binding("m", "switch_tab('portfolio-tab-margin')", "Margin"),
        Binding("o", "switch_tab('portfolio-tab-positions')", "Open Positions"),
        Binding("s", "switch_tab('portfolio-tab-sectors')", "Sector Allocation"),
    ]

    _TAB_ORDER = [
        "portfolio-tab-margin",
        "portfolio-tab-positions",
        "portfolio-tab-sectors",
    ]

    _TAB_TITLES = {
        "portfolio-tab-margin": "Margin Requirements",
        "portfolio-tab-positions": "Open Option Positions",
        "portfolio-tab-sectors": "Sector Allocation",
    }

    def __init__(self) -> None:
        super().__init__()
        self._widgets = {
            "portfolio-tab-margin": ViewMarginRequirementsWidget(),
            "portfolio-tab-positions": OpenOptionPositionsWidget(),
            "portfolio-tab-sectors": SectorAllocationView(),
        }
        self._active_tab = "portfolio-tab-margin"

    def compose(self) -> ComposeResult:
        """Create the tabbed dashboard layout."""
        content_children = [self._widgets[key] for key in self._TAB_ORDER]
        margin_label = Text.assemble(("M", "yellow bold"), ("argin", ""))
        positions_label = Text.assemble(("O", "yellow bold"), ("pen Positions", ""))
        sectors_label = Text.assemble(("S", "yellow bold"), ("ector Allocation", ""))
        yield Vertical(
            Tabs(
                Tab(margin_label, id="portfolio-tab-margin"),
                Tab(positions_label, id="portfolio-tab-positions"),
                Tab(sectors_label, id="portfolio-tab-sectors"),
                id="portfolio-tabs",
            ),
            Container(*content_children, id="portfolio-content"),
            id="portfolio-dashboard",
        )

    def on_mount(self) -> None:
        """Focus and display the initial tab."""
        for widget in self._widgets.values():
            if hasattr(widget, "_previous_market_status"):
                widget._previous_market_status = self._previous_market_status

        self._show_widget(self._active_tab)
        self._update_header(self._active_tab)
        self.query_one("#portfolio-tabs", Tabs).focus()
        self.query_one("#portfolio-tabs", Tabs).active = self._active_tab

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Switch content when a tab is chosen."""
        tab_id = getattr(event.tab, "id", None)
        if tab_id and tab_id in self._widgets:
            self._activate_and_show(tab_id)

    def action_switch_tab(self, tab_id: str) -> None:
        """Keyboard shortcut to switch to a specific tab."""
        if tab_id in self._widgets:
            self._activate_and_show(tab_id)

    def _show_widget(self, tab_id: str) -> None:
        """Display the widget corresponding to tab_id."""
        for key, widget in self._widgets.items():
            widget.display = key == tab_id
            if key == tab_id and hasattr(widget, "focus"):
                widget.focus()

    def _activate_and_show(self, tab_id: str) -> None:
        """Centralized handler to activate a tab and show its content."""
        self._active_tab = tab_id
        tabs = self.query_one("#portfolio-tabs", Tabs)
        tabs.active = tab_id
        self._show_widget(tab_id)
        self._update_header(tab_id)

    def _update_header(self, tab_id: str) -> None:
        """Set the application header to reflect the current tab."""
        label = self._TAB_TITLES.get(tab_id, "Portfolio")
        self.app.update_header(f"Options Trader - Portfolio Dashboard - {label}")
