from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Container, Vertical
from textual import events


class OrderConfirmationScreen(Screen):
    """A full-screen confirmation screen for order placement."""

    def __init__(self, order_details, confirm_text="Confirm", cancel_text="Cancel"):
        super().__init__()
        self.order_details = order_details
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text

    def compose(self):
        yield Container(
            Vertical(
                Static("Confirm Order Placement", id="title"),
                DataTable(id="order_details_table"),
                Static(f"[Enter/Y] {self.confirm_text}   [Esc/N] {self.cancel_text}", id="confirmation_hint"),
                id="confirmation_screen"
            ),
            id="confirmation_overlay"
        )

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("Field", "Value")
        for key, value in self.order_details.items():
            table.add_row(str(key), str(value))
        table.focus()

    async def on_key(self, event: events.Key):
        if event.key in ("enter", "y"):
            self.dismiss(True)
        elif event.key in ("escape", "n"):
            self.dismiss(False)