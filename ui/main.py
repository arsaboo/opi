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

    CSS = """
    #main_container {
        height: 1fr;
    }

    #status_log {
        height: 5;
        border: round green;
    }
    """

    BINDINGS = [
        ("1", "roll_short_options", "Roll Shorts"),
        ("2", "check_box_spreads", "Box Spreads"),
        ("3", "check_vertical_spreads", "Vertical Spreads"),
        ("4", "check_synthetic_covered_calls", "Synth Cov Calls"),
        ("5", "view_margin_requirements", "View Margin"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.api = Api(apiKey, apiRedirectUri, appSecret)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Container(id="main_container")
        yield StatusLog(id="status_log")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.query_one(StatusLog).add_message("Initializing API...")
        if not self.setup_api_with_retry():
            self.query_one(StatusLog).add_message("API initialization failed. Please check your configuration and token.")
            return
        self.query_one(StatusLog).add_message("API initialized successfully.")
        self.query_one(StatusLog).add_message("Welcome to the Options Trading Bot! Press a key to select an option.")
        main_container = self.query_one("#main_container")
        main_container.mount(Static("Welcome! Please select an option from the footer.", id="welcome_message"))

    def setup_api_with_retry(self, max_attempts=3):
        """Set up the API with retry logic specifically for authentication errors"""
        for attempt in range(1, max_attempts + 1):
            try:
                self.api.setup()
                return True
            except Exception as e:
                error_str = str(e)
                self.query_one(StatusLog).add_message(f"API setup error: {error_str}")

                is_last_attempt = attempt >= max_attempts

                if "refresh_token_authentication_error" in error_str and not is_last_attempt:
                    self.query_one(StatusLog).add_message("Token authentication failed. Deleting token and retrying...")
                    self.api.delete_token()

                if is_last_attempt:
                    self.query_one(StatusLog).add_message(f"Failed to initialize API after {max_attempts} attempts")
                    try:
                        alert.botFailed(None, f"Failed to initialize API after {max_attempts} attempts: {error_str}")
                    except alert.BotFailedError:
                        pass # Error is already logged, just preventing the crash
                    return False

                self.query_one(StatusLog).add_message(f"Retrying setup (attempt {attempt}/{max_attempts})...")
                time.sleep(2)

        return False

    def action_roll_short_options(self) -> None:
        """Action to roll short options."""
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(RollShortOptionsWidget())
        self.query_one(StatusLog).add_message("Roll Short Options selected.")

    def action_check_box_spreads(self) -> None:
        """Action to check box spreads."""
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckBoxSpreadsWidget())
        self.query_one(StatusLog).add_message("Check Box Spreads selected.")

    def action_check_vertical_spreads(self) -> None:
        """Action to check vertical spreads."""
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckVerticalSpreadsWidget())
        self.query_one(StatusLog).add_message("Check Vertical Spreads selected.")

    def action_check_synthetic_covered_calls(self) -> None:
        """Action to check synthetic covered calls."""
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(CheckSyntheticCoveredCallsWidget())
        self.query_one(StatusLog).add_message("Check Synthetic Covered Calls selected.")

    def action_view_margin_requirements(self) -> None:
        """Action to view margin requirements."""
        main_container = self.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(ViewMarginRequirementsWidget())
        self.query_one(StatusLog).add_message("View Margin Requirements selected.")

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_quit(self) -> None:
        """An action to quit the app."""
        self.exit()

if __name__ == "__main__":
    app = OpiApp()
    app.run()
