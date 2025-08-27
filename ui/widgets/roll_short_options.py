from textual.widgets import DataTable, Static
from textual import work
from textual.screen import Screen
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from .. import logic
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
import asyncio

class RollShortOptionsWidget(Static):
    """A widget to display short options to be rolled."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._roll_data = []  # Store the actual roll data for each row

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="roll_short_options_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Update the header
        self.app.update_header("Options Trader - Roll Short Calls")

        # Check market status
        self.check_market_status()

        table = self.query_one(DataTable)
        table.add_columns(
            "Ticker",
            "Current Strike",
            "Expiration",
            "DTE",
            "Underlying Price",
            "Status",
            "Quantity",
            "New Strike",
            "New Expiration",
            "Roll Out (Days)",
            "Credit",
            "Cr/Day",
            "Extrinsic",
            "Strike Δ",
            "Config Status",
            "Refreshed"
        )
        # Style the header
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        # Enable row selection
        table.cursor_type = "row"
        # Make sure the table can receive focus
        table.focus()
        self.run_get_expiring_shorts_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_expiring_shorts_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            current_status = "open" if exec_window["open"] else "closed"

            # Check if market status has changed
            if not hasattr(self, '_previous_market_status'):
                self._previous_market_status = None

            if self._previous_market_status != current_status:
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
            self.app.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection."""
        # Get the selected row data
        row_index = event.cursor_row
        if hasattr(self, '_roll_data') and self._roll_data and row_index < len(self._roll_data):
            selected_data = self._roll_data[row_index]
            # Show order confirmation dialog
            self.show_order_confirmation(selected_data)

    def show_order_confirmation(self, roll_data) -> None:
        """Show order confirmation screen."""
        # Calculate roll up amount (difference between new and current strike)
        try:
            roll_up_amount = float(roll_data.get("New Strike", 0)) - float(roll_data.get("Current Strike", 0))
        except Exception:
            roll_up_amount = ""
        roll_out_days = roll_data.get("Roll Out (Days)", "")
        underlying_value = roll_data.get("Underlying Price", "")

        order_details = {
            "Asset": roll_data.get("Ticker", ""),
            "Current Strike": roll_data.get("Current Strike", ""),
            "New Strike": roll_data.get("New Strike", ""),
            "Current Expiration": roll_data.get("Expiration", ""),  # Current expiration
            "New Expiration": roll_data.get("New Expiration", ""),  # New expiration
            "Credit": roll_data.get("Credit", ""),
            "Quantity": roll_data.get("Quantity", roll_data.get("count", "")),
            "Roll Up Amount": roll_up_amount,
            "Roll Out (Days)": roll_out_days,
            "Current Underlying Value": underlying_value
        }
        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, confirmed: bool) -> None:
        """Handle the user's response to the order confirmation."""
        if confirmed:
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing order...")
            # Place the order using the existing functions
            self.place_order()
        else:
            self.app.query_one(StatusLog).add_message("Order cancelled by user.")

    @work
    async def place_order(self) -> None:
        """Place the order using the existing functions."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row

            if cursor_row < len(self._roll_data):
                roll_data = self._roll_data[cursor_row]

                # We need to convert the roll_data back to the format expected by the existing functions
                # This is a simplified example - you'll need to adapt this to your actual data structure
                short_position = {
                    "stockSymbol": roll_data.get("Ticker", ""),
                    "strike": roll_data.get("Current Strike", ""),
                    "expiration": roll_data.get("Expiration", ""),
                    "optionSymbol": "",  # This would need to be retrieved from the actual position data
                    "count": roll_data.get("Quantity", roll_data.get("count", 1))
                }

                # Call the appropriate roll function based on the asset
                from cc import RollSPX, RollCalls
                if roll_data.get("Ticker") == "$SPX":
                    # Execute RollSPX in a separate thread to avoid blocking the UI
                    loop = asyncio.get_event_loop()
                    with ThreadPoolExecutor() as executor:
                        await loop.run_in_executor(executor, RollSPX, self.app.api, short_position)
                else:
                    # Execute RollCalls in a separate thread to avoid blocking the UI
                    loop = asyncio.get_event_loop()
                    with ThreadPoolExecutor() as executor:
                        await loop.run_in_executor(executor, RollCalls, self.app.api, short_position)

                self.app.query_one(StatusLog).add_message("Order placement completed!")
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error placing order: {e}")

    @work
    async def run_get_expiring_shorts_data(self) -> None:
        """Worker to get the expiring shorts data."""
        data = await logic.get_expiring_shorts_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_class(col, val, prev_val=None):
            if col == "Credit":
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style for positive/negative
                    style = "green" if v > 0 else "red" if v < 0 else ""
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Or any other style for increase
                        elif v < pv:
                            style = "bold red"    # Or any other style for decrease
                    return style
                except:
                    return ""
            if col == "Strike Δ":
                try:
                    v = float(val)
                    if v > 0:
                        return "green"
                    elif v < 0:
                        return "red"
                except:
                    pass
            if col == "Config Status":
                if val == "Not Configured":
                    return "yellow"
            if col == "Status":
                if val == "OTM":
                    return "green"
                elif val in ("ITM", "Deep ITM"):
                    return "red"
                elif val == "Just ITM":
                    return "yellow"
                return ""
            if col == "Cr/Day":
                try:
                    v = float(val)
                    return "green" if v > 0 else "red" if v < 0 else ""
                except:
                    return ""
            if col == "Extrinsic":
                try:
                    v = float(val)
                    return "green" if v < 1 else "red"  # Low extrinsic = low risk
                except:
                    return ""
            return ""

        if data:
            prev_rows = self._prev_rows or []
            self._roll_data = []  # Clear previous roll data
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                # Store the actual roll data for this row
                self._roll_data.append(row)

                # Function to style a cell value
                def style_cell(col_name, col_index):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_class(col_name, val, prev_val)
                    # Justify Credit, Cr/Day, Extrinsic, Strike Δ to the right
                    justify = "right" if col_index in [10, 11, 12, 13] else "left"
                    return Text(val, style=style, justify=justify)

                cells = [
                    Text(str(row["Ticker"]), style="", justify="left"),
                    Text(str(row["Current Strike"]), style="", justify="right"),
                    Text(str(row["Expiration"]), style="", justify="left"),
                    Text(str(row["DTE"]), style="", justify="right"),
                    Text(str(row.get("Underlying Price", "")), style="", justify="right"),
                    Text(str(row.get("Status", "")), style=get_cell_class("Status", row.get("Status", "")), justify="left"),
                    Text(str(row.get("Quantity", row.get("count", ""))), style="", justify="right"),
                    Text(str(row["New Strike"]), style="", justify="right"),
                    Text(str(row["New Expiration"]), style="", justify="left"),
                    Text(str(row["Roll Out (Days)"]), style="", justify="right"),
                    style_cell("Credit", 10),
                    style_cell("Cr/Day", 11),
                    style_cell("Extrinsic", 12),
                    style_cell("Strike Δ", 13),
                    Text(str(row["Config Status"]), style=get_cell_class("Config Status", row["Config Status"]), justify="left"),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = data
        else:
            table.add_row("No expiring options found.", *[""] * 15, refreshed_time)