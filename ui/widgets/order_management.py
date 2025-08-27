from textual.widgets import DataTable, Static, Label
from textual import work
from textual.containers import Vertical
from datetime import datetime
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
import asyncio
from textual.screen import ModalScreen
from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.align import Align


class OrderCancellationScreen(ModalScreen):
    """A modal screen for order cancellation confirmation."""

    def __init__(self, order_details, confirm_text="Cancel Order", cancel_text="Keep Order"):
        super().__init__()
        self.order_details = order_details
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
        self._loading = False
        self._error = None

    def compose(self):
        def parse_float(value):
            """Safely parse float from string, stripping currency/percentage symbols."""
            if value is None:
                return 0.0
            if isinstance(value, str):
                value = value.replace('$', '').replace('%', '').strip()
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        # Title and asset/type
        title = Text("ORDER CANCELLATION CONFIRMATION", style="bold white", justify="center")
        asset_type = Text(
            f"Order ID: {self.order_details.get('Order ID', '')}",
            style="bold yellow",
            justify="center"
        )

        # Order Details Section
        order_table = Table.grid(padding=(0, 2), expand=True)
        order_table.add_row(
            Text("Status", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Status", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Asset", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Asset", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Order Type", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Order Type", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Quantity", style="cyan"),
            Text(":", style="white"),
            Text(str(self.order_details.get("Quantity", "")), style="white", justify="left")
        )
        order_table.add_row(
            Text("Price", style="cyan"),
            Text(":", style="white"),
            Text(f"$ {parse_float(self.order_details.get('Price', 0)):.2f}", style="white", justify="left")
        )

        # Instructions
        instructions = Text(
            f"[Y / Enter] {self.confirm_text}     [N / Esc] {self.cancel_text}",
            style="bold green",
            justify="center"
        )

        # Compose Rich panel content
        panel_content = Table.grid(expand=True)
        panel_content.add_row(Align.center(title))
        panel_content.add_row(Align.center(asset_type))
        panel_content.add_row("")  # Spacer

        # Order Details
        panel_content.add_row(Text("Order Details", style="bold underline"))
        panel_content.add_row(order_table)

        # Instructions
        panel_content.add_row("")  # Spacer
        panel_content.add_row(Align.center(instructions))
        panel_content.add_row("─" * 50)

        panel = Panel.fit(
            panel_content,
            title="Order Cancellation",
            border_style="bold red"
        )

        yield Static(panel, id="order-cancellation-modal")

    def on_key(self, event):
        if self._loading:
            event.prevent_default()
            return
        if event.key in ("enter", "y"):
            self._loading = True
            self.refresh()
            self.confirm_cancellation()
        elif event.key in ("escape", "n"):
            self.dismiss(False)

    def confirm_cancellation(self):
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


class OrderManagementWidget(Static):
    """A widget to manage and display recent orders."""

    def __init__(self):
        super().__init__()
        self._working_orders = []
        self._filled_orders = []
        self._other_orders = []

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="order_management_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Update the header
        self.app.update_header("Options Trader - Order Management")

        table = self.query_one(DataTable)
        table.add_columns(
            "Order ID",
            "Status",
            "Time",
            "Asset",
            "Type",
            "Qty",
            "Price"
        )
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        table.cursor_type = "row"
        table.focus()
        self.run_get_orders_data()
        self.set_interval(15, self.run_get_orders_data)

    @work
    async def run_get_orders_data(self) -> None:
        """Worker to get recent orders data and display in sections."""
        orders = await asyncio.to_thread(self.app.api.getRecentOrders, 50)
        table = self.query_one(DataTable)
        table.clear()

        self._working_orders = []
        self._filled_orders = []
        self._other_orders = []

        if orders:
            # WORKING ORDERS Section
            table.add_row(
                Text("WORKING ORDERS", style="bold white on dark_blue"),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style="")
            )
            for order in orders:
                formatted = self.app.api.formatOrderForDisplay(order)
                status = formatted["status"]
                if status in ("ACCEPTED", "WORKING"):
                    order_type = formatted["order_type"]
                    price = formatted["price"]
                    type_color = "red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else ""
                    try:
                        price = f"{float(price):.2f}"
                    except (ValueError, TypeError):
                        price = str(price)
                    # Show status in the Status column
                    status_color = "cyan" if status == "WORKING" else ""
                    table.add_row(
                        Text(str(formatted["order_id"]), style="", justify="left"),
                        Text(str(status), style=status_color, justify="left"),
                        Text(str(formatted["entered_time"]), style="", justify="left"),
                        Text(str(formatted["asset"]), style="", justify="left"),
                        Text(str(order_type), style=type_color, justify="left"),
                        Text(str(formatted["quantity"]), style="", justify="right"),
                        Text(price, style="", justify="right")
                    )
                    self._working_orders.append(order)

            # Separator
            table.add_row(
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style="")
            )

            # FILLED ORDERS Section
            table.add_row(
                Text("FILLED ORDERS", style="bold white on dark_blue"),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style="")
            )
            for order in orders:
                formatted = self.app.api.formatOrderForDisplay(order)
                status = formatted["status"]
                if status == "FILLED":
                    order_type = formatted["order_type"]
                    price = formatted["price"]
                    type_color = "red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else ""
                    try:
                        price = f"{float(price):.2f}"
                    except (ValueError, TypeError):
                        price = str(price)
                    # Show status in the Status column
                    status_color = "green"
                    table.add_row(
                        Text(str(formatted["order_id"]), style="", justify="left"),
                        Text(str(status), style=status_color, justify="left"),
                        Text(str(formatted["entered_time"]), style="", justify="left"),
                        Text(str(formatted["asset"]), style="", justify="left"),
                        Text(str(order_type), style=type_color, justify="left"),
                        Text(str(formatted["quantity"]), style="", justify="right"),
                        Text(price, style="", justify="right")
                    )
                    self._filled_orders.append(order)

            # Separator
            table.add_row(
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style="")
            )

            # OTHER ORDERS Section
            table.add_row(
                Text("OTHER ORDERS (Canceled / Expired / Replaced)", style="bold white on dark_blue"),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style=""),
                Text("", style="")
            )
            for order in orders:
                formatted = self.app.api.formatOrderForDisplay(order)
                status = formatted["status"]
                if status not in ("ACCEPTED", "WORKING", "FILLED"):
                    order_type = formatted["order_type"]
                    price = formatted["price"]
                    status_color = {
                        "CANCELED": "gray",
                        "EXPIRED": "yellow",
                        "REPLACED": "magenta"
                    }.get(status, "")
                    type_color = "red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else ""
                    try:
                        price = f"{float(price):.2f}"
                    except (ValueError, TypeError):
                        price = str(price)
                    table.add_row(
                        Text(str(formatted["order_id"]), style="", justify="left"),
                        Text(str(status), style=status_color, justify="left"),
                        Text(str(formatted["entered_time"]), style="", justify="left"),
                        Text(str(formatted["asset"]), style="", justify="left"),
                        Text(str(order_type), style=type_color, justify="left"),
                        Text(str(formatted["quantity"]), style="", justify="right"),
                        Text(price, style="", justify="right")
                    )
                    self._other_orders.append(order)

        else:
            table.add_row("No recent orders found.", *[""] * 6)

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection for canceling an order."""
        row_index = event.cursor_row
        # Determine which section the row belongs to
        # This is simplified; in practice, you might need to track row indices per section
        if row_index < len(self._working_orders) + 1:  # +1 for header
            if self._working_orders:
                selected_order = self._working_orders[row_index - 1]  # Adjust for header
                status = selected_order.get("status", "")
                if status in ("ACCEPTED", "WORKING"):
                    self.show_cancel_confirmation(selected_order)
                else:
                    self.app.query_one(StatusLog).add_message("Order cannot be cancelled (not in ACCEPTED/WORKING status).")
        # For filled and other, no action needed as per original

    def show_cancel_confirmation(self, order) -> None:
        """Show order cancellation confirmation screen."""
        order_details = {
            "Order ID": order.get("orderId", ""),
            "Status": order.get("status", ""),
            "Asset": order.get("orderLegCollection", [{}])[0].get("instrument", {}).get("symbol", ""),
            "Order Type": order.get("orderLegCollection", [{}])[0].get("instruction", ""),
            "Quantity": order.get("orderLegCollection", [{}])[0].get("quantity", ""),
            "Price": order.get("price", "")
        }
        screen = OrderCancellationScreen(order_details, confirm_text="Cancel Order", cancel_text="Keep Order")
        self.app.push_screen(screen, callback=lambda confirmed: self.handle_cancel_confirmation(confirmed, order))

    def handle_cancel_confirmation(self, confirmed: bool, order) -> None:
        """Handle user's response to cancel confirmation."""
        if confirmed:
            self.app.query_one(StatusLog).add_message(f"Cancelling order {order.get('orderId', '')}...")
            self.cancel_order(order)
        else:
            self.app.query_one(StatusLog).add_message("Order cancellation aborted.")

    @work
    async def cancel_order(self, order) -> None:
        """Cancel the selected order."""
        try:
            order_id = order.get("orderId", "")
            await asyncio.to_thread(self.app.api.cancelOrder, order_id)
            self.app.query_one(StatusLog).add_message(f"Order {order_id} cancelled.")
            self.run_get_orders_data()
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error cancelling order: {e}")

    def show_main_menu(self) -> None:
        """Show the main menu."""
        # Update the header
        self.app.update_header("Options Trader")

        # Remove this widget and show the welcome message
        main_container = self.app.query_one("#main_container")
        main_container.remove_children()
        main_container.mount(Static("Welcome to Options Trader! Use the footer menu to navigate between features.", id="welcome_message"))