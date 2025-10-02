from textual.widgets import RichLog

class StatusLog(RichLog):
    """A widget to display status messages."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Status Log"

    def add_message(self, message: str) -> None:
        """Add a message to the log."""
        self.write(message)
