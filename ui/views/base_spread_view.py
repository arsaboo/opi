from textual.widgets import Static


class BaseSpreadView(Static):
    """Base class for spreads-style views.

    Provides common helpers: market status logging and simple streaming setup hooks.
    """

    def __init__(self) -> None:
        super().__init__()
        self._previous_market_status: str | None = None

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            current_status = "open" if exec_window.get("open") else "closed"
            if self._previous_market_status != current_status:
                from ..widgets.status_log import StatusLog
                if current_status == "open":
                    self.app.query_one(StatusLog).add_message("Market is now OPEN! Trades can be placed.")
                else:
                    from configuration import debugMarketOpen
                    if not debugMarketOpen:
                        self.app.query_one(StatusLog).add_message("Market is closed. Data may be delayed.")
                    else:
                        self.app.query_one(StatusLog).add_message("Market is closed but running in debug mode.")
                self._previous_market_status = current_status
        except Exception as e:
            try:
                from ..widgets.status_log import StatusLog
                self.app.query_one(StatusLog).add_message(f"Error checking market status: {e}")
            except Exception:
                pass

