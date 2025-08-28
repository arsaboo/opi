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
import keyboard
from order_utils import handle_cancel, reset_cancel_flag, cancel_order, monitor_order

# Read manual ordering flag from configuration with safe default
try:
    from configuration import manual_order as MANUAL_ORDER
except Exception:
    MANUAL_ORDER = False

class CheckVerticalSpreadsWidget(Static):
    """A widget to display vertical spreads."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._vertical_spreads_data = []  # Store actual vertical spreads data for order placement
        self._previous_market_status = None  # Track previous market status
        self._override_price = None  # User-edited initial price

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="vertical_spreads_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Vertical Spreads")
        # Only check market status if not already set
        if self._previous_market_status is None:
            self.check_market_status()

        table = self.query_one(DataTable)
        table.add_columns(
            "Asset",
            "Expiration",
            "Strike Low",
            "Call Low B|A",
            "Strike High",
            "Call High B|A",
            "Investment",
            "Price",
            "Max Profit",
            "CAGR",
            "Protection",
            "Margin Req",
            "Ann. ROM %",
            "Refreshed"
        )
        # Style the header
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        # Enable row selection
        table.cursor_type = "row"
        # Make sure the table can receive focus
        table.focus()
        self.run_get_vertical_spreads_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_vertical_spreads_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            current_status = "open" if exec_window["open"] else "closed"
            # Only log if status changed
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

    @work
    async def run_get_vertical_spreads_data(self) -> None:
        """Worker to get vertical spreads data."""
        data = await logic.get_vertical_spreads_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_style(col, val, prev_val=None):
            if col in ["cagr", "ann_rom"]:
                try:
                    v = float(val.replace('%', ''))
                    pv = float(prev_val.replace('%', '')) if prev_val is not None else None
                    # Base style - color based on value (positive/negative)
                    style = "green" if v > 0 else "red" if v < 0 else ""
                    # Highlight changes - override with bold colors for increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Bold green for increase
                        elif v < pv:
                            style = "bold red"    # Bold red for decrease
                    return style
                except:
                    return ""
            if col == "margin_req":
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold red"    # Bold red for increase (worse)
                        elif v < pv:
                            style = "bold green"  # Bold green for decrease (better)
                    elif v < 1000:
                        style = "green"  # Good (low)
                    elif v > 10000:
                        style = "red"   # Bad (high)
                    return style
                except:
                    pass
            if col == "protection":
                try:
                    v = float(val.replace('%', ''))
                    pv = float(prev_val.replace('%', '')) if prev_val is not None else None
                    # Base style - color based on value (high/low)
                    style = "green" if v >= 0.1 else "red"  # Green for adequate protection, red for low
                    # Highlight changes - override with bold colors for increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Bold green for increase (better)
                        elif v < pv:
                            style = "bold red"    # Bold red for decrease (worse)
                    return style
                except:
                    pass
            if col in ["strike_low", "strike_high"]:
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold"  # Bold for increase
                        elif v < pv:
                            style = "bold"  # Bold for decrease
                    return style
                except:
                    pass
            if col in ["investment", "price", "max_profit"]:
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Bold green for increase (better for profit, neutral for investment)
                            # For investment, increase might not be "better", but we'll keep it green for consistency
                        elif v < pv:
                            style = "bold red"   # Bold red for decrease (worse for profit, neutral for investment)
                            # For investment, decrease might not be "worse", but we'll keep it red for consistency
                    return style
                except:
                    pass
            return ""

        if data:
            prev_rows = self._prev_rows or []
            self._vertical_spreads_data = []  # Clear previous vertical spreads data
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                # Store the actual vertical spread data for this row
                self._vertical_spreads_data.append(row)

                # Derive per-contract price from total investment when possible
                try:
                    row["price"] = round(float(row.get("investment", 0)) / 100, 2)
                except Exception:
                    row["price"] = ""
                try:
                    if prev_row:
                        prev_row["price"] = round(float(prev_row.get("investment", 0)) / 100, 2)
                except Exception:
                    pass

                # Function to style a cell value
                def style_cell(col_name):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_style(col_name, val, prev_val)
                    # Justify numerical columns to the right
                    right_justify_cols = {"strike_low", "call_low_ba", "strike_high", "call_high_ba", "investment", "price", "max_profit", "cagr", "protection", "margin_req", "ann_rom"}
                    justify = "right" if col_name in right_justify_cols else "left"

                    # Format percentage values
                    if col_name in ["cagr", "protection", "ann_rom"]:
                        try:
                            # Convert to float, multiply by 100, and format with 2 decimal places and % sign
                            float_val = float(val.replace('%', ''))
                            val = f"{float_val * 100:.2f}%"
                            # Update style after formatting
                            # Convert prev_val to the same format for comparison
                            if prev_val is not None:
                                try:
                                    prev_float_val = float(str(prev_val).replace('%', ''))
                                    formatted_prev_val = f"{prev_float_val * 100:.2f}%"
                                except ValueError:
                                    formatted_prev_val = prev_val
                            else:
                                formatted_prev_val = prev_val
                            style = get_cell_style(col_name, val, formatted_prev_val)
                        except ValueError:
                            pass  # Keep original value if conversion fails

                    return Text(val, style=style, justify=justify)

                # Handle B|A prices with separate coloring for bid and ask
                def style_ba_price(bid_col, ask_col):
                    bid_val = row[bid_col]
                    ask_val = row[ask_col]
                    prev_bid_val = prev_row.get(bid_col)
                    prev_ask_val = prev_row.get(ask_col)

                    # Style for bid (green for increase, red for decrease)
                    bid_style = ""
                    if prev_bid_val is not None:
                        try:
                            prev_bid_float = float(prev_bid_val)
                            bid_float = float(bid_val)
                            if bid_float > prev_bid_float:
                                bid_style = "green"
                            elif bid_float < prev_bid_float:
                                bid_style = "red"
                        except ValueError:
                            pass

                    # Style for ask (green for decrease, red for increase - since lower ask is better)
                    ask_style = ""
                    if prev_ask_val is not None:
                        try:
                            prev_ask_float = float(prev_ask_val)
                            ask_float = float(ask_val)
                            if ask_float < prev_ask_float:
                                ask_style = "green"
                            elif ask_float > prev_ask_float:
                                ask_style = "red"
                        except ValueError:
                            pass

                    # Create a Text object with separately styled bid and ask
                    ba_text = Text()
                    ba_text.append(f"{bid_val:.2f}", style=bid_style)
                    ba_text.append("|", style="")  # No style for the separator
                    ba_text.append(f"{ask_val:.2f}", style=ask_style)

                    return ba_text

                call_low_ba = style_ba_price('bid1', 'ask1')
                call_high_ba = style_ba_price('bid2', 'ask2')

                cells = [
                    Text(str(row["asset"]), style="", justify="left"),
                    Text(str(row["expiration"]), style="", justify="left"),
                    style_cell("strike_low"),
                    call_low_ba,  # Styled B|A
                    style_cell("strike_high"),
                    call_high_ba,  # Styled B|A
                    style_cell("investment"),
                    style_cell("price"),
                    style_cell("max_profit"),
                    style_cell("cagr"),
                    style_cell("protection"),
                    style_cell("margin_req"),
                    style_cell("ann_rom"),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = data
        else:
            table.add_row("No vertical spreads found.", "", "", "", "", "", "", "", "", "", "", "", "", refreshed_time)

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection."""
        # Get the selected row data
        row_index = event.cursor_row
        if hasattr(self, '_vertical_spreads_data') and self._vertical_spreads_data and row_index < len(self._vertical_spreads_data):
            selected_data = self._vertical_spreads_data[row_index]
            # Show order confirmation dialog
            self.show_order_confirmation(selected_data)

    def show_order_confirmation(self, vertical_spread_data) -> None:
        """Show order confirmation screen."""
        # Calculate spread width
        try:
            spread_width = float(vertical_spread_data.get("strike_high", 0)) - float(vertical_spread_data.get("strike_low", 0))
        except Exception:
            spread_width = ""

        order_details = {
            "Type": "Vertical Spread",
            "Asset": vertical_spread_data.get("asset", ""),
            "Expiration": vertical_spread_data.get("expiration", ""),
            "Strike Low": vertical_spread_data.get("strike_low", ""),
            "Strike High": vertical_spread_data.get("strike_high", ""),
            "Spread Width": spread_width,
            "Investment": f"${vertical_spread_data.get('investment', 0):.2f}",
            "Price": f"${(float(vertical_spread_data.get('investment', 0)) / 100):.2f}",
            "Max Profit": f"${vertical_spread_data.get('max_profit', 0):.2f}",
            "CAGR": f"{vertical_spread_data.get('cagr', 0)*100:.2f}%",
            "Protection": f"{vertical_spread_data.get('protection', 0)*100:.2f}%",
            "Margin Req": f"${vertical_spread_data.get('margin_req', 0):.2f}",
            "Annualized Return": f"{vertical_spread_data.get('ann_rom', 0)*100:.2f}%"
        }
        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, result) -> None:
        """Handle the user's response to the order confirmation, capturing edited price if provided."""
        confirmed = result.get("confirmed") if isinstance(result, dict) else bool(result)
        if confirmed:
            # Capture price override if present
            if isinstance(result, dict) and result.get("price") is not None:
                try:
                    self._override_price = float(result.get("price"))
                except Exception:
                    self._override_price = None
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing vertical spread order...")
            self.place_vertical_spread_order()
        else:
            self.app.query_one(StatusLog).add_message("Vertical spread order cancelled by user.")

    @work
    async def place_vertical_spread_order(self) -> None:
        """Place the vertical spread order."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row

            if cursor_row < len(self._vertical_spreads_data):
                vertical_spread_data = self._vertical_spreads_data[cursor_row]

                # Extract required data
                asset = vertical_spread_data.get("asset", "")
                expiration = datetime.strptime(vertical_spread_data.get("expiration", ""), "%Y-%m-%d").date()
                strike_low = float(vertical_spread_data.get("strike_low", 0))
                strike_high = float(vertical_spread_data.get("strike_high", 0))
                net_debit = float(vertical_spread_data.get("investment", 0)) / 100  # Convert from total to per contract

                # Place the order using the api method
                from strategies import monitor_order
                from order_utils import handle_cancel, reset_cancel_flag
                import keyboard

                try:
                    # Reset cancel flag and clear keyboard hooks
                    reset_cancel_flag()
                    keyboard.unhook_all()
                    keyboard.on_press(handle_cancel)

                    # Try prices in sequence, starting with original price
                    # Use user override if provided; otherwise default to computed net debit
                    initial_price = self._override_price if self._override_price is not None else net_debit
                    order_id = None
                    filled = False

                    attempts = [0] if MANUAL_ORDER else range(0, 76)
                    for i in attempts:  # 0 = original price, 1-75 = improvements
                        if not cancel_order:  # Check if cancelled
                            current_price = (
                                initial_price if i == 0
                                else round_to_nearest_five_cents(initial_price + i * 0.05)
                            )

                            if i > 0:
                                self.app.query_one(StatusLog).add_message(f"Trying new price: ${current_price} (improvement #{i})")

                            # Place order
                            order_id = await asyncio.to_thread(
                                self.app.api.vertical_call_order,
                                asset,
                                expiration,
                                strike_low,
                                strike_high,
                                1,  # quantity
                                price=current_price
                            )

                            # Check if order was placed (None when debugCanSendOrders is False)
                            if order_id is None:
                                self.app.query_one(StatusLog).add_message("Order not placed (debug mode).")
                                self.app.query_one(StatusLog).add_message(f"Asset: {asset}, Expiration: {expiration}, Strike Low: {strike_low}, Strike High: {strike_high}, Price: {current_price}")
                                break

                            if MANUAL_ORDER:
                                self.app.query_one(StatusLog).add_message("Manual order placed. Manage from Order Management (U=Update, C=Cancel).")
                                break
                            # Monitor with 60s timeout
                            self.app.query_one(StatusLog).add_message(f"Monitoring order {order_id}...")
                            result = await self.monitor_order_ui(order_id, timeout=60, manual=False)

                            # Add status update based on result
                            if result is True:
                                self.app.query_one(StatusLog).add_message(f"Order {order_id} filled successfully!")
                            elif result == "cancelled":
                                self.app.query_one(StatusLog).add_message(f"Order {order_id} cancelled by user.")
                            elif result == "rejected":
                                self.app.query_one(StatusLog).add_message(f"Order {order_id} rejected.")
                            elif result == "timeout":
                                self.app.query_one(StatusLog).add_message(f"Order {order_id} timed out.")

                            if result is True:  # Order filled
                                filled = True
                                break
                            elif result == "cancelled":  # User cancelled
                                break
                            elif result == "rejected":  # Order rejected
                                if MANUAL_ORDER:
                                    break
                                continue  # Try next price
                            # On timeout, continue to next price improvement

                            # Brief pause between attempts
                            if i > 0 and not MANUAL_ORDER:
                                await asyncio.sleep(1)
                        else:
                            break

                    if filled:
                        self.app.query_one(StatusLog).add_message("Vertical spread order filled successfully!")
                        self._override_price = None  # reset after use
                    elif cancel_order:
                        self.app.query_one(StatusLog).add_message("Vertical spread order cancelled by user.")
                        if order_id:
                            try:
                                await asyncio.to_thread(self.app.api.cancelOrder, order_id)
                                self.app.query_one(StatusLog).add_message("Order cancelled successfully.")
                            except Exception as e:
                                self.app.query_one(StatusLog).add_message(f"Error cancelling order: {e}")
                    else:
                        self.app.query_one(StatusLog).add_message("Vertical spread order not filled after all attempts.")
                except Exception as e:
                    self.app.query_one(StatusLog).add_message(f"Error placing vertical spread order: {e}")
                finally:
                    self._override_price = None  # ensure cleanup
                    keyboard.unhook_all()
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for vertical spread order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error placing vertical spread order: {e}")

    async def monitor_order_ui(self, order_id, timeout=60, manual=False):
        """Monitor order status and update UI with status changes"""
        import time
        start_time = time.time()
        last_status_check = 0
        last_print_time = 0
        print_interval = 1

        while time.time() - start_time < timeout:
            current_time = time.time()
            elapsed_time = int(current_time - start_time)

            if cancel_order:
                try:
                    await asyncio.to_thread(self.app.api.cancelOrder, order_id)
                    self.app.query_one(StatusLog).add_message("Order cancelled by user.")
                    return "cancelled"
                except Exception as e:
                    self.app.query_one(StatusLog).add_message(f"Error cancelling order: {e}")
                    return False

            try:
                if current_time - last_status_check >= 1:  # Check every second
                    order_status = await asyncio.to_thread(self.app.api.checkOrder, order_id)
                    last_status_check = current_time

                    if current_time - last_print_time >= print_interval:
                        remaining = int(timeout - elapsed_time)
                        status_str = order_status['status']
                        rejection_reason = order_status.get('rejection_reason', '')

                        status_msg = f"Status: {status_str} {rejection_reason} | Time remaining: {remaining}s | Price: {order_status.get('price', 'N/A')} | Filled: {order_status.get('filledQuantity', '0')}"
                        self.app.query_one(StatusLog).add_message(status_msg)
                        last_print_time = current_time

                    if order_status["filled"]:
                        self.app.query_one(StatusLog).add_message("Order filled successfully!")
                        return True
                    elif order_status["status"] == "REJECTED":
                        rejection_msg = f"Order rejected: {order_status.get('rejection_reason', 'No reason provided')}"
                        self.app.query_one(StatusLog).add_message(rejection_msg)
                        return "rejected"
                    elif order_status["status"] == "CANCELED":
                        self.app.query_one(StatusLog).add_message("Order cancelled.")
                        return False

                await asyncio.sleep(0.1)  # Small sleep to prevent CPU thrashing

            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Error checking order status: {e}")
                return False

        # If we reach here, order timed out
        if manual:
            self.app.query_one(StatusLog).add_message("Order timed out. Use Order Management (U to update, C to cancel).")
            return "timeout"
        else:
            self.app.query_one(StatusLog).add_message("Order timed out, moving to price improvement...")
            try:
                await asyncio.to_thread(self.app.api.cancelOrder, order_id)
            except:
                pass
            return "timeout"

def round_to_nearest_five_cents(price):
    """Round price to nearest $0.05."""
    return round(price * 20) / 20
