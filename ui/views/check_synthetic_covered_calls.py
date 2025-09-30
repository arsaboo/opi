from textual.widgets import DataTable
from .base_spread_view import BaseSpreadView
from textual import work
from datetime import datetime
from .. import logic
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
from ..utils import style_cell as cell, style_ba, get_refreshed_time_str
import asyncio
import keyboard
from api.order_manager import handle_cancel, reset_cancel_flag, cancel_order
from configuration import stream_quotes
from api.streaming.subscription_manager import get_subscription_manager
from api.streaming.provider import get_provider
from core.spreads_common import days_to_expiry

# Read manual ordering flag from configuration with safe default
try:
    from configuration import manual_order as MANUAL_ORDER
except Exception:
    MANUAL_ORDER = False

# Import the global order monitoring service
try:
    from services.order_monitoring_service import order_monitoring_service
except Exception:
    order_monitoring_service = None

class CheckSyntheticCoveredCallsWidget(BaseSpreadView):
    """A widget to display synthetic covered calls."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._synthetic_covered_calls_data = []  # Store actual synthetic covered calls data for order placement
        self._selected_synthetic_covered_call_data = None  # Store selected data for order placement
        self._previous_market_status = None  # Track previous market status
        self._override_price = None  # User-edited initial price
        self._quote_provider = None
        self._col_keys = []
        self._ba_maps = []  # entries: {row_key, col_key, symbol, last_bid, last_ask}
        self._row_data_by_key = {}

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="synthetic_covered_calls_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Synthetic Covered Calls")
        # Only check market status if not already set
        if self._previous_market_status is None:
            self.check_market_status()

        table = self.query_one(DataTable)
        table.add_columns(
            "Asset",
            "Expiration",
            "Strike Low",
            "Call Low B|A",
            "Put Low B|A",
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
        # Initialize streaming tick if enabled
        self._ba_maps = []
        if stream_quotes:
            try:
                self._quote_provider = get_provider(self.app.api.connectClient)
                self.set_interval(1, self.refresh_streaming_quotes)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Streaming init error: {e}")

        self.run_get_synthetic_covered_calls_data()
        # Add periodic refresh every 15 seconds
        self.set_interval(15, self.run_get_synthetic_covered_calls_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)

    def on_unmount(self) -> None:
        try:
            mgr = get_subscription_manager(self.app.api.connectClient)
            mgr.unregister("synthetic_covered_calls")
        except Exception:
            pass

    # check_market_status inherited from BaseSpreadView

    @work
    async def run_get_synthetic_covered_calls_data(self) -> None:
        """Worker to get synthetic covered calls data."""
        data = await logic.get_vertical_spreads_data(self.app.api, synthetic=True)
        table = self.query_one(DataTable)
        table.clear()
        self._row_data_by_key = {}
        self._ba_maps = []
        refreshed_time = get_refreshed_time_str(self.app, getattr(self, "_quote_provider", None))
        # Status logs removed after debugging; rely on core.common CAGR

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
            if col in ["investment", "max_profit"]:
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
            self._synthetic_covered_calls_data = []  # Clear previous synthetic covered calls data
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                # Store the actual synthetic covered call data for this row
                self._synthetic_covered_calls_data.append(row)

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
                    right_justify_cols = {"strike_low", "call_low_ba", "put_low_ba", "strike_high", "call_high_ba", "investment", "price", "max_profit", "cagr", "protection", "margin_req", "ann_rom"}
                    justify = "right" if col_name in right_justify_cols else "left"

                    # Format percentage values
                    if col_name in ["cagr", "protection", "ann_rom"]:
                        try:
                            # Recompute CAGR directly from the row to avoid upstream drift
                            if col_name == "cagr":
                                inv = float(row.get("investment", 0) or 0)
                                prof = float(row.get("max_profit", 0) or 0)
                                exp = str(row.get("expiration", ""))
                                dte = max(days_to_expiry(exp), 1)
                                roi = prof / max(inv, 1e-9)
                                float_val = (1.0 + roi) ** (365.0 / dte) - 1.0
                            else:
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
                put_low_ba = style_ba_price('put_bid', 'put_ask')

                cells = [
                    Text(str(row["asset"]), style="", justify="left"),
                    Text(str(row["expiration"]), style="", justify="left"),
                    cell("strike_low", row.get("strike_low"), prev_row.get("strike_low")),
                    call_low_ba,  # Styled B|A
                    put_low_ba,   # Styled B|A
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
                self._row_data_by_key[row_key] = row
                # Use symbols from data when present
                try:
                    col_call_low = self._col_keys[3] if len(self._col_keys) > 3 else 3
                    col_put_low = self._col_keys[4] if len(self._col_keys) > 4 else 4
                    col_call_high = self._col_keys[6] if len(self._col_keys) > 6 else 6
                    sym1 = row.get("symbol1")
                    sym2 = row.get("symbol2")
                    psym = row.get("put_symbol")
                    if sym1:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_call_low, "symbol": sym1, "last_bid": None, "last_ask": None})
                    if psym:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_put_low, "symbol": psym, "last_bid": None, "last_ask": None})
                    if sym2:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_call_high, "symbol": sym2, "last_bid": None, "last_ask": None})
                except Exception:
                    pass
            self._prev_rows = data
        else:
            from configuration import spreads as CFG_SPREADS
            try:
                assets = ", ".join(CFG_SPREADS.keys())
            except Exception:
                assets = "configured assets"
            table.add_row("No synthetic covered calls found.", "", "", "", "", "", "", "", "", "", "", "", "", "", refreshed_time)
            try:
                self.app.query_one(StatusLog).add_message(f"No synthetic covered calls found for {assets}. Consider lowering downsideProtection or spread width in configuration.")
            except Exception:
                pass
        # Subscribe symbols via manager
        if stream_quotes and self._ba_maps:
            try:
                mgr = get_subscription_manager(self.app.api.connectClient)
                mgr.register(
                    "synthetic_covered_calls",
                    options=[m["symbol"] for m in self._ba_maps if m.get("symbol")],
                    equities=[],
                )
            except Exception:
                pass

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection."""
        # Prefer row_key mapping for robust selection
        selected_data = None
        try:
            row_key = getattr(event, "row_key", None)
            if row_key is not None:
                selected_data = self._row_data_by_key.get(row_key)
        except Exception:
            selected_data = None
        if selected_data is None:
            row_index = getattr(event, "cursor_row", 0)
            if hasattr(self, '_synthetic_covered_calls_data') and self._synthetic_covered_calls_data and row_index < len(self._synthetic_covered_calls_data):
                selected_data = self._synthetic_covered_calls_data[row_index]
        if selected_data:
            # Store the selected data for later use
            self._selected_synthetic_covered_call_data = selected_data
            # Show order confirmation dialog
            self.show_order_confirmation(selected_data)

    def show_order_confirmation(self, synthetic_covered_call_data) -> None:
        """Show order confirmation dialog."""
        # Calculate spread width
        try:
            spread_width = float(synthetic_covered_call_data.get("strike_high", 0)) - float(synthetic_covered_call_data.get("strike_low", 0))
        except Exception:
            spread_width = ""

        order_details = {
            "Type": "Synthetic Covered Call",
            "Asset": synthetic_covered_call_data.get("asset", ""),
            "Expiration": synthetic_covered_call_data.get("expiration", ""),
            "Strike Low": synthetic_covered_call_data.get("strike_low", ""),
            "Strike High": synthetic_covered_call_data.get("strike_high", ""),
            "Spread Width": spread_width,
            "Investment": f"${synthetic_covered_call_data.get('investment', 0):.2f}",
            "Price": f"${(float(synthetic_covered_call_data.get('investment', 0)) / 100):.2f}",
            "Max Profit": f"${synthetic_covered_call_data.get('max_profit', 0):.2f}",
            "CAGR": f"{synthetic_covered_call_data.get('cagr', 0)*100:.2f}%",
            "Protection": f"{synthetic_covered_call_data.get('protection', 0)*100:.2f}%",
            "Margin Req": f"${synthetic_covered_call_data.get('margin_req', 0):.2f}",
            "Annualized Return": f"{synthetic_covered_call_data.get('ann_rom', 0)*100:.2f}%"
        }
        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, result) -> None:
        """Handle the user's response to the order confirmation, capturing edited price if provided."""
        confirmed = result.get("confirmed") if isinstance(result, dict) else bool(result)
        if confirmed:
            if isinstance(result, dict) and result.get("price") is not None:
                try:
                    self._override_price = float(result.get("price"))
                except Exception:
                    self._override_price = None
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing synthetic covered call order...")
            self.place_synthetic_covered_call_order()
        else:
            self.app.query_one(StatusLog).add_message("Synthetic covered call order cancelled by user.")

    @work
    async def place_synthetic_covered_call_order(self) -> None:
        """Place the synthetic covered call order."""
        try:
            # Use the stored selected data instead of getting cursor position from table
            if self._selected_synthetic_covered_call_data:
                synthetic_covered_call_data = self._selected_synthetic_covered_call_data

                # Extract required data
                asset = synthetic_covered_call_data.get("asset", "")
                expiration = datetime.strptime(synthetic_covered_call_data.get("expiration", ""), "%Y-%m-%d").date()
                strike_low = float(synthetic_covered_call_data.get("strike_low", 0))
                strike_high = float(synthetic_covered_call_data.get("strike_high", 0))
                # Convert total investment ($ per contract) back to option price; ensure 2 decimals for validity
                net_debit = round(float(synthetic_covered_call_data.get("investment", 0)) / 100, 2)

                # Manual mode: place once and manage from Order Management
                if MANUAL_ORDER:
                    # Reset cancel flag and clear keyboard hooks
                    reset_cancel_flag()
                    keyboard.unhook_all()
                    
                    # Place order at chosen price (use edited override if provided)
                    chosen_price = self._override_price if self._override_price is not None else net_debit
                    # Ensure two-decimal precision for submission UI -> API will further normalize tick size
                    try:
                        chosen_price = round(float(chosen_price), 2)
                    except Exception:
                        pass
                    from .. import logic as ui_logic
                    order_id = await ui_logic.synthetic_covered_call_order(
                        self.app.api,
                        asset,
                        expiration,
                        strike_low,
                        strike_high,
                        1,
                        price=chosen_price,
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
                self.app.query_one(StatusLog).add_message(f"Placing synthetic covered call order with automatic price improvement...")
                
                # Use initial price (user override if provided, otherwise computed net debit)
                initial_price = self._override_price if self._override_price is not None else net_debit
                
                # Use the API's place_order method which handles price improvements
                order_func = self.app.api.synthetic_covered_call_order
                order_params = [asset, expiration, strike_low, strike_high, 1]
                
                result = await asyncio.to_thread(
                    self.app.api.place_order, order_func, order_params, initial_price
                )
                
                if result is True:
                    self.app.query_one(StatusLog).add_message("Synthetic covered call order filled successfully!")
                elif result == "cancelled":
                    self.app.query_one(StatusLog).add_message("Synthetic covered call order cancelled by user.")
                else:
                    self.app.query_one(StatusLog).add_message("Synthetic covered call order not filled after all attempts.")
                    
                self._override_price = None
                self._selected_synthetic_covered_call_data = None
                keyboard.unhook_all()
                
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for synthetic covered call order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error placing synthetic covered call order: {e}")

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
        if not stream_quotes or not getattr(self, "_quote_provider", None) or not getattr(self, "_ba_maps", None):
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
                # Keep last style so color remains until next change
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
