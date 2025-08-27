import time
import alert
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Static
from .widgets.status_log import StatusLog
from .widgets.roll_short_options import RollShortOptionsWidget
from .widgets.check_box_spreads import CheckBoxSpreadsWidget
from .widgets.check_vertical_spreads import CheckVerticalSpreadsWidget
from .widgets.check_synthetic_covered_calls import CheckSyntheticCoveredCallsWidget
from .widgets.view_margin_requirements import ViewMarginRequirementsWidget
from api import Api
from configuration import apiKey, apiRedirectUri, appSecret

class OpiApp(App):
    """A Textual app to manage the options trading bot."""

    TITLE = "Options Trader"

    CSS = """
    #main_container {
        height: 1fr;
    }

    #status_log {
        height: 5;
        border: round green;
    }

    /* Table styling */
    DataTable {
        height: 1fr;
    }

    /* Header styling */
    Header {
        background: darkblue;
        color: white;
        text-style: bold;
    }

    /* Row styling */
    DataTable Row {
        color: white;
    }

    /* Welcome message */
    #welcome_message {
        content-align: center middle;
        width: 100%;
        height: 100%;
        color: yellow;
        text-style: bold;
    }

    /* Order Management Screen */
    #order_management_container {
        height: 1fr;
        align: center middle;
    }

    #title {
        content-align: center middle;
        width: 100%;
        height: 3;
        color: yellow;
        text-style: bold;
    }

    #buttons {
        height: 3;
        margin: 1;
        align: center middle;
    }

    /* Order Confirmation Dialog */
    #overlay {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }

    #dialog {
        padding: 2;
        width: 80%;
        height: auto;
        background: $surface;
        border: round $primary;
        align: center middle;
    }

    #order_details {
        margin: 1;
        padding: 1;
        border: round white;
        height: auto;
    }

    /* Button styling */
    Button {
        margin: 1;
    }

    /* Cell Styles */
    .positive {
        color: green;
        text-style: bold;
    }
    .negative {
        color: red;
        text-style: bold;
    }
    .warning {
        color: yellow;
        text-style: bold;
    }
    .high {
        color: lime;
        text-style: bold;
    }
    .low {
        color: orange;
        text-style: bold;
    }
    .info {
        color: blue;
        text-style: bold;
    }
    .changed-up {
        background: #003300;
        color: lime;
        text-style: bold;
    }
    .changed-down {
        background: #330000;
        color: red;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("1", "roll_short_options", "Roll Shorts"),
        ("2", "check_box_spreads", "Box Spreads"),
        ("3", "check_vertical_spreads", "Vertical Spreads"),
        ("4", "check_synthetic_covered_calls", "Synth Cov Calls"),
        ("5", "view_margin_requirements", "View Margin"),
        ("6", "order_management", "Order Management"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, api=None):
        super().__init__()
        self.api = api  # API instance is passed in

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Container(id="main_container")
        yield StatusLog(id="status_log")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Check market status
        self.check_market_status()
        
        self.query_one(StatusLog).add_message("Welcome to the Options Trading Bot! Press a key to select an option.")
        main_container = self.query_one("#main_container")
        main_container.mount(Static("Welcome to Options Trader! Use the footer menu to navigate between features.", id="welcome_message"))

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.api.getOptionExecutionWindow()
            if exec_window["open"]:
                self.query_one(StatusLog).add_message("Market is open, running the program now...")
            else:
                message = "Market is closed"
                from configuration import debugMarketOpen
                if debugMarketOpen:
                    message += " but the program will work in debug mode"
                self.query_one(StatusLog).add_message(message + ".")

        except Exception as e:
            self.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    def update_header(self, title: str) -> None:
        """Update the app title."""
        self.title = title
        # Force a refresh of the header
        header = self.query_one(Header)
        header.refresh()

    def action_roll_short_options(self) -> None:
        """Action to roll short options."""
        self.update_header("Options Trader - Roll Short Calls")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(RollShortOptionsWidget())
        self.query_one(StatusLog).add_message("Roll Short Options selected.")

    def action_check_box_spreads(self) -> None:
        """Action to check box spreads."""
        self.update_header("Options Trader - Box Spreads")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckBoxSpreadsWidget())
        self.query_one(StatusLog).add_message("Check Box Spreads selected.")

    def action_check_vertical_spreads(self) -> None:
        """Action to check vertical spreads."""
        self.update_header("Options Trader - Vertical Spreads")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckVerticalSpreadsWidget())
        self.query_one(StatusLog).add_message("Check Vertical Spreads selected.")

    def action_check_synthetic_covered_calls(self) -> None:
        """Action to check synthetic covered calls."""
        self.update_header("Options Trader - Synthetic Covered Calls")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckSyntheticCoveredCallsWidget())
        self.query_one(StatusLog).add_message("Check Synthetic Covered Calls selected.")

    def action_view_margin_requirements(self) -> None:
        """Action to view margin requirements."""
        self.update_header("Options Trader - Margin Requirements")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(ViewMarginRequirementsWidget())
        self.query_one(StatusLog).add_message("View Margin Requirements selected.")

    def action_order_management(self) -> None:
        """Action to manage orders."""
        self.update_header("Options Trader - Order Management")
        from .widgets.order_management import OrderManagementWidget
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(OrderManagementWidget())
        self.query_one(StatusLog).add_message("Order Management selected.")

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_quit(self) -> None:
        """An action to quit the app."""
        self.exit()

if __name__ == "__main__":
    app = OpiApp()
    app.run()