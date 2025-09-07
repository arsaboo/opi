from textual.widgets import DataTable
from .base_spread_view import BaseSpreadView
from textual import work
from datetime import datetime
from .. import logic
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
from ..utils import style_cell as cell, style_ba
import asyncio
import keyboard
from api.order_manager import handle_cancel, reset_cancel_flag, cancel_order
from configuration import stream_quotes
from api.streaming.provider import get_provider
from api.streaming.subscription_manager import get_subscription_manager

# Import the global order monitoring service
try:
    from services.order_monitoring_service import order_monitoring_service
except Exception:
    order_monitoring_service = None

# Read manual ordering flag from configuration with safe default
try:
    from configuration import manual_order as MANUAL_ORDER
except Exception:
    MANUAL_ORDER = False

class CheckVerticalSpreadsWidget(BaseSpreadView):
    """A widget to display vertical spreads."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._vertical_spreads_data = []  # Store actual vertical spreads data for order placement
        self._previous_market_status = None  # Track previous market status
        self._override_price = None  # User-edited initial price
        self._quote_provider = None
        self._col_keys = []
        self._ba_maps = []  # entries: {row_key, col_key, symbol, last_bid, last_ask}

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
        try:
            self._col_keys = list(table.columns.keys())
        except Exception:
            self._col_keys = []
        if stream_quotes:
            try:
                self._quote_provider = get_provider(self.app.api.connectClient)
                self.set_interval(1, self.refresh_streaming_quotes)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Streaming init error: {e}")
        self.run_get_vertical_spreads_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_vertical_spreads_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)

    def on_unmount(self) -> None:
        try:
            mgr = get_subscription_manager(self.app.api.connectClient)
            mgr.unregister("vertical_spreads")
        except Exception:
            pass

    # check_market_status inherited from BaseSpreadView

    @work
    async def run_get_vertical_spreads_data(self) -> None:
        """Worker to get vertical spreads data."""
        data = await logic.get_vertical_spreads_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        self._ba_maps = []
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
                    return style_ba(row[bid_col], row[ask_col], prev_row.get(bid_col), prev_row.get(ask_col))

                call_low_ba = style_ba_price('bid1', 'ask1')
                call_high_ba = style_ba_price('bid2', 'ask2')

                cells = [
                    Text(str(row["asset"]), style="", justify="left"),
                    Text(str(row["expiration"]), style="", justify="left"),
                    cell("strike_low", row.get("strike_low"), prev_row.get("strike_low")),
                    call_low_ba,  # Styled B|A
                    cell("strike_high", row.get("strike_high"), prev_row.get("strike_high")),
                    call_high_ba,  # Styled B|A
                    cell("investment", row.get("investment"), prev_row.get("investment")),
                    cell("price", row.get("price"), prev_row.get("price")),
                    cell("max_profit", row.get("max_profit"), prev_row.get("max_profit")),
                    cell("cagr", row.get("cagr"), prev_row.get("cagr")),
                    cell("protection", row.get("protection"), prev_row.get("protection")),
                    cell("margin_req", row.get("margin_req"), prev_row.get("margin_req")),
                    cell("ann_rom", row.get("ann_rom"), prev_row.get("ann_rom")),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                row_key = table.add_row(*cells)
                # Use symbols directly from data when available
                try:
                    sym1 = row.get("symbol1")
                    sym2 = row.get("symbol2")
                    col_low = self._col_keys[3] if len(self._col_keys) > 3 else 3
                    col_high = self._col_keys[5] if len(self._col_keys) > 5 else 5
                    if sym1:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_low, "symbol": sym1, "last_bid": None, "last_ask": None})
                    if sym2:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_high, "symbol": sym2, "last_bid": None, "last_ask": None})
                except Exception:
                    pass
            self._prev_rows = data
        else:
            table.add_row("No vertical spreads found.", "", "", "", "", "", "", "", "", "", "", "", "", refreshed_time)
        # Subscribe for streaming quotes via manager
        if stream_quotes and self._ba_maps:
            try:
                mgr = get_subscription_manager(self.app.api.connectClient)
                mgr.register("vertical_spreads", options=[m["symbol"] for m in self._ba_maps if m.get("symbol")], equities=[])
            except Exception:
                pass

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

                # Manual mode: place once and manage from Order Management
                if MANUAL_ORDER:
                    # Reset cancel flag and clear keyboard hooks
                    reset_cancel_flag()
                    keyboard.unhook_all()
                    
                    # Place order at initial price
                    from .. import logic as ui_logic
                    order_id = await ui_logic.vertical_call_order(
                        self.app.api,
                        asset,
                        expiration,
                        strike_low,
                        strike_high,
                        1,
                        price=net_debit,
                    )
                    
                    if order_id is None:
                        self.app.query_one(StatusLog).add_message("Order not placed (debug mode).")
                        self.app.query_one(StatusLog).add_message(f"Asset: {asset}, Expiration: {expiration}, Strike Low: {strike_low}, Strike High: {strike_high}, Price: {net_debit}")
                    else:
                        self.app.query_one(StatusLog).add_message("Manual order placed. Manage from Order Management (U=Update, C=Cancel).")
                    
                    self._override_price = None
                    keyboard.unhook_all()
                    return

                # Non-manual: use API's built-in price improvement logic
                self.app.query_one(StatusLog).add_message(f"Placing vertical spread order with automatic price improvement...")
                
                # Use initial price (user override if provided, otherwise computed net debit)
                initial_price = self._override_price if self._override_price is not None else net_debit
                
                # Use the API's place_order method which handles price improvements
                order_func = self.app.api.vertical_call_order
                order_params = [asset, expiration, strike_low, strike_high, 1]
                
                result = await asyncio.to_thread(
                    self.app.api.place_order, order_func, order_params, initial_price
                )
                
                if result is True:
                    self.app.query_one(StatusLog).add_message("Vertical spread order filled successfully!")
                elif result == "cancelled":
                    self.app.query_one(StatusLog).add_message("Vertical spread order cancelled by user.")
                else:
                    self.app.query_one(StatusLog).add_message("Vertical spread order not filled after all attempts.")
                    
                self._override_price = None
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
                    from .. import logic as ui_logic
                    await ui_logic.cancel_order(self.app.api, order_id)
                    self.app.query_one(StatusLog).add_message("Order cancelled by user.")
                    return "cancelled"
                except Exception as e:
                    self.app.query_one(StatusLog).add_message(f"Error cancelling order: {e}")
                    return False

            try:
                if current_time - last_status_check >= 1:  # Check every second
                    from .. import logic as ui_logic
                    order_status = await ui_logic.check_order(self.app.api, order_id)
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

    def refresh_streaming_quotes(self) -> None:
        if not stream_quotes or not self._quote_provider or not self._ba_maps:
            return
        try:
            table = self.query_one(DataTable)
            for m in self._ba_maps:
                sym = m.get("symbol")
                if not sym:
                    continue
                bid, ask = self._quote_provider.get_bid_ask(sym)
                if bid is None and ask is None:
                    continue
                if bid is None:
                    bid = m.get("last_bid")
                if ask is None:
                    ask = m.get("last_ask")
                if bid is None and ask is None:
                    continue
                prev_bid, prev_ask = m.get("last_bid"), m.get("last_ask")
                m["last_bid"], m["last_ask"] = bid, ask
                # Persist last styles so color remains until a change occurs
                prev_bid_style = m.get("last_bid_style", "")
                prev_ask_style = m.get("last_ask_style", "")
                bid_style = prev_bid_style
                ask_style = prev_ask_style
                try:
                    if prev_bid is not None and bid is not None:
                        if float(bid) > float(prev_bid):
                            bid_style = "green"
                        elif float(bid) < float(prev_bid):
                            bid_style = "red"
                except Exception:
                    pass
                try:
                    if prev_ask is not None and ask is not None:
                        if float(ask) < float(prev_ask):
                            ask_style = "green"
                        elif float(ask) > float(prev_ask):
                            ask_style = "red"
                except Exception:
                    pass
                # Save styles so they persist on next tick if value unchanged
                m["last_bid_style"] = bid_style
                m["last_ask_style"] = ask_style
                ba_text = Text()
                ba_text.append(f"{float(bid):.2f}" if bid is not None else "", style=bid_style)
                ba_text.append("|")
                ba_text.append(f"{float(ask):.2f}" if ask is not None else "", style=ask_style)
                table.update_cell(m["row_key"], m["col_key"], ba_text)
        except Exception:
            pass

def round_to_nearest_five_cents(price):
    """Round price to nearest $0.05."""
    return round(price * 20) / 20
