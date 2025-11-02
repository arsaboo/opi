from textual.app import App, ComposeResult
import asyncio
from textual.containers import Container

from textual.widgets import Footer, Static
from .widgets.status_log import StatusLog
from .widgets.roll_short_options import RollShortOptionsWidget
from .widgets.open_option_positions import OpenOptionPositionsWidget
from .views.check_box_spreads import CheckBoxSpreadsWidget
from .views.check_vertical_spreads import CheckVerticalSpreadsWidget
from .views.check_synthetic_covered_calls import CheckSyntheticCoveredCallsWidget
from .widgets.view_margin_requirements import ViewMarginRequirementsWidget
from .views.sector_allocation_view import SectorAllocationView
from api.streaming.provider import ensure_provider, get_provider
from state_manager import load_symbols, save_symbols
import os

# Get SchwabAccountID from environment variables
SchwabAccountID = os.getenv("SCHWAB_ACCOUNT_ID")
from .widgets.app_header import AppHeader
from status import status_queue, set_ui_active


class OpiApp(App):
    """A Textual app to manage the options trading bot."""

    TITLE = "Options Trader"

    CSS = """

    #main_container {
        height: 1fr;
        margin-top: 1;
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

        color: green;

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

        color: green;

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
        ("7", "open_option_positions", "Open Positions"),
        ("8", "view_sector_allocation", "Sector Allocation"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, api=None):

        super().__init__()

        self.api = api  # API instance is passed in

        self._previous_market_status = None  # Track previous market status

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield AppHeader()
        yield Container(id="main_container")
        yield StatusLog(id="status_log")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Mark UI as active so downstream code routes messages to Status Log
        try:
            set_ui_active(True)
        except Exception:
            pass
        self.check_market_status()
        self.check_expiring_options()
        self.query_one(StatusLog).add_message(
            "Welcome to the Options Trading Bot! Press a key to select an option."
        )
        main_container = self.query_one("#main_container")
        main_container.mount(
            Static(
                "Welcome to Options Trader! Use the footer menu to navigate between features.",
                id="welcome_message",
            )
        )
        # Initialize global order monitoring service
        try:
            from services.order_monitoring_service import order_monitoring_service
            order_monitoring_service.set_app_reference(self)
        except Exception as e:
            self.query_one(StatusLog).add_message(f"Error initializing order monitoring service: {e}")

        # Warm up streaming provider early to reduce initial delay
        try:
            async def _warm_and_load():
                prov = await ensure_provider(self.api.connectClient)
                # Load and pre-subscribe saved symbols once provider is ready
                try:
                    acc = SchwabAccountID
                    saved = load_symbols(acc)
                    if saved:
                        # Heuristic: treat strings with spaces as options, others as equities
                        opts = [s for s in saved if " " in s]
                        eqs = [s for s in saved if " " not in s]
                        if opts:
                            await prov.subscribe_options(opts)
                        if eqs:
                            await prov.subscribe_equities(eqs)
                        self.query_one(StatusLog).add_message(
                            f"Pre-subscribed {len(saved)} saved symbols."
                        )
                except Exception as e:
                    # Non-fatal
                    self.query_one(StatusLog).add_message(f"State load error: {e}")
            asyncio.create_task(_warm_and_load())
        except Exception:
            pass

        # Drain global status queue into the Status Log so non-UI code can report messages
        try:
            async def _drain_status_log():
                while True:
                    try:
                        # Drain burst
                        drained = 0
                        while not status_queue.empty() and drained < 50:
                            item = status_queue.get_nowait()
                            msg = item.get("message", "")
                            if msg:
                                # Keep it simple; we could style per level later
                                self.query_one(StatusLog).add_message(msg)
                            drained += 1
                    except Exception:
                        # Never let logging break the UI loop
                        pass
                    await asyncio.sleep(0.25)

            asyncio.create_task(_drain_status_log())
        except Exception:
            pass

        # ML features removed

    def action_roll_short_options(self) -> None:
        """Action to roll short options."""
        self.update_header("Options Trader - Roll Short Calls")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = RollShortOptionsWidget()
        widget._previous_market_status = self._previous_market_status  # Pass status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Roll Short Options selected.")

    def action_check_box_spreads(self) -> None:
        """Action to check box spreads."""
        self.update_header("Options Trader - Box Spreads")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = CheckBoxSpreadsWidget()
        widget._previous_market_status = self._previous_market_status  # Pass status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Check Box Spreads selected.")

    def action_check_vertical_spreads(self) -> None:
        """Action to check vertical spreads."""
        self.update_header("Options Trader - Vertical Spreads")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = CheckVerticalSpreadsWidget()
        widget._previous_market_status = self._previous_market_status  # Pass status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Check Vertical Spreads selected.")

    def on_exit(self) -> None:
        """Persist current subscriptions to state-<accountId>.json upon exit."""
        # Stop all order monitoring tasks
        try:
            from services.order_monitoring_service import order_monitoring_service
            order_monitoring_service.stop_all_monitoring()
        except Exception:
            pass

        try:
            acc = SchwabAccountID
            prov = get_provider(self.api.connectClient)
            symbols = list(prov.get_all_subscribed()) if prov else []
            save_symbols(acc, symbols)
        except Exception:
            # Best-effort persistence; ignore errors on shutdown
            pass
        # Try to stop streaming provider gracefully
        try:
            prov = get_provider(self.api.connectClient)
            if prov is not None:
                import asyncio as _asyncio
                _asyncio.create_task(prov.stop())
        except Exception:
            pass

    def action_check_synthetic_covered_calls(self) -> None:
        """Action to check synthetic covered calls."""
        self.update_header("Options Trader - Synthetic Covered Calls")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = CheckSyntheticCoveredCallsWidget()
        widget._previous_market_status = self._previous_market_status  # Pass status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Check Synthetic Covered Calls selected.")

    def action_view_margin_requirements(self) -> None:
        """Action to view margin requirements."""
        self.update_header("Options Trader - Margin Requirements")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = ViewMarginRequirementsWidget()
        widget._previous_market_status = self._previous_market_status  # Pass status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("View Margin Requirements selected.")

    def action_order_management(self) -> None:
        """Action to manage orders."""
        self.update_header("Options Trader - Order Management")
        from .widgets.order_management import OrderManagementWidget
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(OrderManagementWidget())
        self.query_one(StatusLog).add_message("Order Management selected.")

    def action_open_option_positions(self) -> None:
        """Action to view all open option positions."""
        self.update_header("Options Trader - Open Option Positions")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = OpenOptionPositionsWidget()
        widget._previous_market_status = self._previous_market_status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Open Option Positions selected.")

    def action_view_sector_allocation(self) -> None:
        """Action to view sector allocation."""
        self.update_header("Options Trader - Sector Allocation")
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        widget = SectorAllocationView()
        widget._previous_market_status = self._previous_market_status
        main_container.mount(widget)
        self.query_one(StatusLog).add_message("Sector Allocation selected.")

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.api.getOptionExecutionWindow()
            current_status = "open" if exec_window["open"] else "closed"
            # Only log if status changed
            if self._previous_market_status != current_status:
                if current_status == "open":
                    self.query_one(StatusLog).add_message(
                        "Market is now OPEN! Trades can be placed."
                    )
                else:
                    message = "Market is closed"
                    from configuration import debugMarketOpen
                    if debugMarketOpen:
                        message += " but the program will work in debug mode"
                    self.query_one(StatusLog).add_message(message + ".")
                self._previous_market_status = current_status
        except Exception as e:
            self.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    def check_expiring_options(self) -> None:
        """Check for options expiring today and schedule notification 60 minutes before market close."""
        try:
            # Get today's date
            from datetime import datetime, timedelta
            import pytz
            from tzlocal import get_localzone

            # Get market hours
            exec_window = self.api.getOptionExecutionWindow()

            # Check if we have market hours data
            if "closeDate" in exec_window and exec_window["closeDate"]:
                close_time = exec_window["closeDate"]

                # Get today's date
                today = datetime.now().date()

                # Get expiring shorts data (synchronously to avoid event-loop conflicts)
                short_positions = self.api.updateShortPosition()

                # Filter for options expiring today
                expiring_today = [
                    p for p in short_positions
                    if datetime.strptime(p["expiration"], "%Y-%m-%d").date() == today
                ]

                if expiring_today:
                    # Calculate 60 minutes before market close
                    notification_time = close_time - timedelta(minutes=60)
                    current_time = datetime.now(pytz.UTC)

                    # If we're within the notification window, send alert
                    if current_time >= notification_time and current_time < close_time:
                        option_symbols = [p["optionSymbol"] for p in expiring_today]
                        message = f"Options expiring today: {', '.join(option_symbols)}. Market closes in 60 minutes."

                        # Send notification
                        try:
                            import alert
                            alert.alert(None, message)
                        except Exception:
                            pass

                        self.query_one(StatusLog).add_message(message)
        except Exception as e:
            self.query_one(StatusLog).add_message(f"Error checking expiring options: {e}")

    def update_header(self, title: str) -> None:
        """Update the app title."""

        # Route to custom header widget
        try:
            header = self.query_one(AppHeader)
            header.set_title(title)
        except Exception:
            pass

    def action_toggle_dark(self) -> None:
        """Toggle between Textual built-in themes.
        Switches self.theme between "textual-dark" and "textual-light" and logs a short message.
        """
        try:
            current = getattr(self, "theme", "textual-dark")
            new_theme = (
                "textual-dark" if current == "textual-light" else "textual-light"
            )
            self.theme = new_theme
            try:
                self.query_one(StatusLog).add_message("Theme: " + new_theme)
            except Exception:
                pass
        except Exception as e:
            try:
                self.query_one(StatusLog).add_message(
                    "Theme toggle unavailable: " + str(e)
                )
            except Exception:
                pass

    def action_quit(self) -> None:
        """An action to quit the app."""
        self.exit()


if __name__ == "__main__":
    app = OpiApp()
    app.run()
