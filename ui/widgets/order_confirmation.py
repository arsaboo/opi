from textual.screen import ModalScreen
from textual.widgets import Static, LoadingIndicator
from rich.panel import Panel
from rich.text import Text
from rich.table import Table


class OrderConfirmationScreen(ModalScreen):
    """A modal screen for order confirmation."""

    def __init__(self, order_details, confirm_text="Confirm Order", cancel_text="Cancel Order"):
        super().__init__()
        self.order_details = order_details
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
        self._loading = False
        self._error = None

    def compose(self):
        # Title and asset/type
        title = Text("Confirm Order", style="bold underline", justify="center")
        asset_type = Text(
            f"{self.order_details.get('Type', '')}: {self.order_details.get('Asset', '')}",
            style="bold yellow",
            justify="center"
        )

        # Order details as a Rich Table
        table = Table.grid(padding=(0, 2))
        for field, value in self.order_details.items():
            # Skip the "Type" and "Asset" fields since they're already shown in the header
            if field not in ["Type", "Asset"]:
                table.add_row(
                    Text(str(field), style="bold cyan"),
                    Text(str(value), style="white")
                )

        # Instructions
        instructions = Text(
            f"[Enter/Y] {self.confirm_text}   [Esc/N] {self.cancel_text}",
            style="bold green",
            justify="center"
        )

        # Loading indicator or error
        feedback = ""
        if self._loading:
            feedback = LoadingIndicator()
        elif self._error:
            feedback = Text(self._error, style="bold red")

        # Compose Rich panel content
        panel_content = Table.grid(expand=True)
        panel_content.add_row(title)
        panel_content.add_row(asset_type)
        panel_content.add_row(table)
        panel_content.add_row(instructions)
        if feedback:
            panel_content.add_row(feedback)

        panel = Panel(
            panel_content,
            title="Order Confirmation",
            border_style="bold blue"
        )

        yield Static(panel, id="order-confirmation-modal")

    def on_key(self, event):
        if self._loading:
            event.prevent_default()
            return
        if event.key in ("enter", "y"):
            self._loading = True
            self.refresh()
            self.confirm_order()
        elif event.key in ("escape", "n"):
            self.dismiss(False)

    def confirm_order(self):
        import asyncio
        async def do_confirm():
            try:
                await asyncio.sleep(1)
                self.dismiss(True)
            except Exception as e:
                self._loading = False
                self._error = f"Error: {e}"
                self.refresh()
        asyncio.create_task(do_confirm())