from textual.widgets import DataTable, Static
from textual import work
from textual.screen import Screen
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
import asyncio


class OrderManagementWidget(Static):
    """A widget to manage and display recent orders."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._orders_data = []

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
            "Entered Time",
            "Asset",
            "Order Type",
            "Quantity",
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
        """Worker to get recent orders data."""
        orders = await asyncio.to_thread(self.app.api.getRecentOrders, 50)
        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")
        self._orders_data = []

        if orders:
            for order in orders:
                formatted = self.app.api.formatOrderForDisplay(order)
                self._orders_data.append(order)
                cells = [
                    Text(str(formatted["order_id"]), style="", justify="left"),
                    Text(str(formatted["status"]), style="", justify="left"),
                    Text(str(formatted["entered_time"]), style="", justify="left"),
                    Text(str(formatted["asset"]), style="", justify="left"),
                    Text(str(formatted["order_type"]), style="", justify="left"),
                    Text(str(formatted["quantity"]), style="", justify="right"),
                    Text(str(formatted["price"]), style="", justify="right"),
                ]
                table.add_row(*cells)
        else:
            table.add_row("No recent orders found.", *[""] * 6)

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection for canceling an order."""
        row_index = event.cursor_row
        if hasattr(self, '_orders_data') and self._orders_data and row_index < len(self._orders_data):
            selected_order = self._orders_data[row_index]
            # Only allow cancel if status is ACCEPTED or WORKING
            status = selected_order.get("status", "")
            if status in ("ACCEPTED", "WORKING"):
                self.show_cancel_confirmation(selected_order)
            else:
                self.app.query_one(StatusLog).add_message("Order cannot be cancelled (not in ACCEPTED/WORKING status).")

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
        screen = OrderConfirmationScreen(order_details, confirm_text="Cancel Order", cancel_text="Keep Order")
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