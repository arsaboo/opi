from textual.screen import ModalScreen
from textual.widgets import Label, Button, Static
from textual.containers import Container, Vertical, Horizontal
from textual import work


class OrderConfirmationDialog(ModalScreen):
    """A modal dialog for confirming order placement."""

    def __init__(self, order_details):
        super().__init__()
        self.order_details = order_details

    def compose(self):
        """Create child widgets."""
        yield Container(
            Vertical(
                Label("Confirm Order Placement", id="title"),
                Static(self.format_order_details(), id="order_details"),
                Horizontal(
                    Button("Confirm", id="confirm_btn", variant="primary"),
                    Button("Cancel", id="cancel_btn", variant="default"),
                    id="buttons"
                ),
                id="dialog"
            ),
            id="overlay"
        )

    def format_order_details(self):
        """Format the order details for display."""
        details = "Order Details:\\n"
        for key, value in self.order_details.items():
            details += f"  {key}: {value}\\n"
        return details

    def on_button_pressed(self, event) -> None:
        """Handle button presses."""
        if event.button.id == "confirm_btn":
            self.dismiss(True)  # User confirmed
        elif event.button.id == "cancel_btn":
            self.dismiss(False)  # User cancelled