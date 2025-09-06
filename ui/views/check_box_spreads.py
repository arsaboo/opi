from textual.widgets import DataTable
from .base_spread_view import BaseSpreadView
from textual import work

from datetime import datetime
import asyncio
import keyboard
from .. import logic
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
from ..utils import style_cell as cell, style_ba, style_flags
from configuration import stream_quotes
from api.streaming.subscription_manager import get_subscription_manager
from api.streaming.provider import get_provider
from api.order_manager import handle_cancel, reset_cancel_flag, cancel_order
from core.common import round_to_nearest_five_cents

# Read manual ordering flag from configuration with safe default
try:
    from configuration import manual_order as MANUAL_ORDER
except Exception:
    MANUAL_ORDER = False

class CheckBoxSpreadsWidget(BaseSpreadView):
    """A widget to display box spreads."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None  # Store previous data for comparison
        self._box_spreads_data = []  # Store actual box spreads data for order placement
        self._previous_market_status = None  # Track previous market status
        self._override_price = None  # User-edited initial price

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="box_spreads_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Sell Box Spreads")
        # Only check market status if not already set
        if self._previous_market_status is None:
            self.check_market_status()

        table = self.query_one(DataTable)
        table.add_columns(
            "Direction",
            "Date",
            "DTE",
            "Low Strike",
            "High Strike",
            "Low Call B/A",
            "High Call B/A",
            "Low Put B/A",
            "High Put B/A",
            "Mid Net Price",
            "Nat Net Price",
            "Borrowed",
            "Face Value",
            "Mid Ann. Cost %",
            "Nat Ann. Cost %",
            "Flags",
            "Refreshed"
        )
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        table.cursor_type = "row"
        table.focus()
        try:
            self._col_keys = list(table.columns.keys())
        except Exception:
            self._col_keys = []
        self.run_get_box_spreads_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_box_spreads_data)
        # Add periodic market status check every 30 seconds
        self.set_interval(30, self.check_market_status)
        # Streaming maps
        self._ba_maps = []
        if stream_quotes:
            try:
                self._quote_provider = get_provider(self.app.api.connectClient)
                self.set_interval(1, self.refresh_streaming_quotes)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Streaming init error: {e}")

    def on_unmount(self) -> None:
        try:
            mgr = get_subscription_manager(self.app.api.connectClient)
            mgr.unregister("box_spreads")
        except Exception:
            pass

    # check_market_status inherited from BaseSpreadView

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection."""
        # Get the selected row data
        row_index = event.cursor_row
        if hasattr(self, '_box_spreads_data') and self._box_spreads_data and row_index < len(self._box_spreads_data):
            selected_data = self._box_spreads_data[row_index]
            # Show order confirmation dialog
            self.show_order_confirmation(selected_data)

    def show_order_confirmation(self, box_spread_data) -> None:
        """Show order confirmation screen."""
        # Set type to "Box Spread: Buy" or "Box Spread: Sell"
        direction = box_spread_data.get("direction", "")
        type_label = f"Box Spread {direction}" if direction else "Box Spread"

        # Get values for order details directly from the data
        mid_net_price = box_spread_data.get("mid_net_price", "")
        nat_net_price = box_spread_data.get("nat_net_price", "")
        mid_annualized_return = box_spread_data.get("mid_annualized_return", "")
        nat_annualized_return = box_spread_data.get("nat_annualized_return", "")
        days_to_expiry = box_spread_data.get("days_to_expiry", "")
        face_value = box_spread_data.get("face_value", "")

        # Get upfront amount based on direction
        upfront_amount = box_spread_data.get("mid_upfront_amount",
                                           box_spread_data.get("investment",
                                           box_spread_data.get("borrowed", 0)))

        # Default price suggestion (per contract): prefer mid, fallback to nat
        suggested_price = None
        try:
            suggested_price = (
                float(mid_net_price)
                if mid_net_price not in (None, "")
                else float(nat_net_price) if nat_net_price not in (None, "") else None
            )
        except Exception:
            suggested_price = None

        order_details = {
            "Type": type_label,
            "Direction": direction,
            "Expiration": box_spread_data.get("date", ""),
            "Days to Expiry": days_to_expiry,
            "Strike Low": box_spread_data.get("low_strike", ""),
            "Strike High": box_spread_data.get("high_strike", ""),
            "Spread Width": float(box_spread_data.get("high_strike", 0)) - float(box_spread_data.get("low_strike", 0)) if box_spread_data.get("high_strike") and box_spread_data.get("low_strike") else "",
            "Face Value": face_value,  # Pass numeric value, let order confirmation screen format it
            # Editable price input (per contract)
            "Price": suggested_price,
            "Mid Net Price": mid_net_price,
            "Nat Net Price": nat_net_price,
            "Upfront Amount": upfront_amount,  # Pass numeric value, let order confirmation screen format it
            "Annualized Return (Mid)": mid_annualized_return,  # Pass numeric value, let order confirmation screen format it
            "Annualized Return (Nat)": nat_annualized_return,  # Pass numeric value, let order confirmation screen format it
            # Do not include "Protection" for box spreads
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
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing box spread order...")
            self.place_box_spread_order()
        else:
            self.app.query_one(StatusLog).add_message("Box spread order cancelled by user.")

    @work
    async def place_box_spread_order(self) -> None:
        """Place the box spread SELL order with automatic price improvement and UI feedback."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row

            if cursor_row < len(self._box_spreads_data):
                row = self._box_spreads_data[cursor_row]

                # Extract symbols for the 4 legs
                low_call_symbol = row.get("low_call_symbol")
                high_call_symbol = row.get("high_call_symbol")
                low_put_symbol = row.get("low_put_symbol")
                high_put_symbol = row.get("high_put_symbol")

                if not all([low_call_symbol, high_call_symbol, low_put_symbol, high_put_symbol]):
                    self.app.query_one(StatusLog).add_message("Error: Missing option leg symbols for box spread.")
                    return

                # Determine initial price (credit per contract)
                try:
                    initial_price = (
                        self._override_price
                        if self._override_price is not None
                        else float(row.get("mid_net_price")) if row.get("mid_net_price") not in (None, "")
                        else float(row.get("nat_net_price")) if row.get("nat_net_price") not in (None, "")
                        else None
                    )
                except Exception:
                    initial_price = None

                if initial_price is None:
                    self.app.query_one(StatusLog).add_message("Error: Could not determine initial price for box spread.")
                    return

                # Reset cancel flag and set keyboard cancel handler
                try:
                    reset_cancel_flag()
                    keyboard.unhook_all()
                    keyboard.on_press(handle_cancel)
                except Exception:
                    pass

                # Manual vs automatic handling
                try:
                    if MANUAL_ORDER:
                        # Place once at selected price; manage from Order Management
                        order_id = await asyncio.to_thread(
                            self.app.api.sell_box_spread_order,
                            low_call_symbol,
                            high_call_symbol,
                            low_put_symbol,
                            high_put_symbol,
                            1,
                            price=initial_price,
                        )
                        if order_id is None:
                            self.app.query_one(StatusLog).add_message("Order not placed (debug mode).")
                            self.app.query_one(StatusLog).add_message(
                                f"Legs: {low_call_symbol} / {high_call_symbol} / {high_put_symbol} / {low_put_symbol} @ ${initial_price:.2f}"
                            )
                        else:
                            self.app.query_one(StatusLog).add_message(
                                "Manual order placed. Manage from Order Management (U=Update, C=Cancel)."
                            )
                        return
                    else:
                        # Use API-level placement with price improvements and monitoring
                        order_func = self.app.api.sell_box_spread_order
                        order_params = [
                            low_call_symbol,
                            high_call_symbol,
                            low_put_symbol,
                            high_put_symbol,
                            1,  # quantity
                        ]

                        self.app.query_one(StatusLog).add_message(
                            f"Placing SELL box spread @ ${initial_price:.2f} (will improve if not filled)"
                        )

                        result = await asyncio.to_thread(
                            self.app.api.place_order, order_func, order_params, initial_price
                        )

                        if result is True:
                            self.app.query_one(StatusLog).add_message("Box spread order filled successfully!")
                        elif result == "cancelled":
                            self.app.query_one(StatusLog).add_message("Box spread order cancelled by user.")
                        else:
                            self.app.query_one(StatusLog).add_message("Box spread order not filled after attempts.")
                finally:
                    self._override_price = None
                    try:
                        keyboard.unhook_all()
                    except Exception:
                        pass
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for box spread order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error placing box spread order: {e}")

    @work
    async def run_get_box_spreads_data(self) -> None:
        """Worker to get box spreads data."""
        data = await logic.get_box_spreads_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        self._ba_maps = []
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_style(col, val, prev_val=None):
            # Color coding logic
            if col in ["cagr", "ann_rom", "mid_annualized_return", "nat_annualized_return"]:
                try:
                    v = float(str(val).replace("%", ""))
                    pv = float(str(prev_val).replace("%", "")) if prev_val is not None else None
                    # For sell box cost rates (positive): lower is better
                    style = ""
                    # Highlight changes: lower vs previous = better (bold green), higher = worse (bold red)
                    if pv is not None:
                        if v < pv:
                            style = "bold green"
                        elif v > pv:
                            style = "bold red"
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
            if col in ["net_price", "mid_net_price", "nat_net_price"]:
                try:
                    v = float(val)
                    pv = float(prev_val) if prev_val is not None else None
                    # Base style - no specific color for base value
                    style = ""
                    # Highlight changes - color based on increase/decrease
                    if pv is not None:
                        if v > pv:
                            style = "bold red"    # Bold red for increase (worse for Sell, better for Buy)
                        elif v < pv:
                            style = "bold green"  # Bold green for decrease (better for Sell, worse for Buy)
                    return style
                except:
                    pass
            if col == "ann_cost_return":
                try:
                    v = float(str(val).replace("%", ""))
                    pv = float(str(prev_val).replace("%", "")) if prev_val is not None else None
                    # Lower cost is better
                    style = ""
                    if pv is not None:
                        if v < pv:
                            style = "bold green"
                        elif v > pv:
                            style = "bold red"
                    return style
                except:
                    return ""
            if col in ["low_strike", "high_strike", "days_to_expiry"]:
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
            return ""

        if data:
            prev_rows = self._prev_rows or []
            self._box_spreads_data = []  # Clear previous box spreads data
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}
                self._box_spreads_data.append(row)  # Store actual data for order placement

                # Function to style a cell value
                def style_cell(col_name):
                    val = str(row[col_name]) if row[col_name] is not None else ""
                    prev_val = prev_row.get(col_name)
                    style = get_cell_style(col_name, val, prev_val)
                    # Justify numerical columns to the right
                    right_justify_cols = {
                        "low_strike", "high_strike", "net_price", "repayment",
                        "borrowed", "repayment_sell", "ann_cost_return", "margin_req",
                        "mid_net_price", "nat_net_price", "mid_annualized_return", "nat_annualized_return",
                        "mid_upfront_amount", "mid_borrowed", "nat_upfront_amount",
                        "nat_borrowed", "face_value", "days_to_expiry"
                    }
                    justify = "right" if col_name in right_justify_cols else "left"

                    # Format percentage values
                    if col_name in ["ann_cost_return", "mid_annualized_return", "nat_annualized_return"]:
                        try:
                            # Convert to float and format with 2 decimal places and % sign
                            float_val = float(val)
                            val = f"{float_val:.2f}%"
                            # Update style after formatting
                            # Convert prev_val to the same format for comparison
                            if prev_val is not None:
                                try:
                                    prev_float_val = float(prev_val)
                                    formatted_prev_val = f"{prev_float_val:.2f}%"
                                except ValueError:
                                    formatted_prev_val = prev_val
                            else:
                                formatted_prev_val = prev_val
                            style = get_cell_style(col_name, val, formatted_prev_val)
                        except ValueError:
                            pass  # Keep original value if conversion fails
                    elif col_name in ["borrowed", "mid_upfront_amount", "nat_upfront_amount",
                                      "face_value"]:
                        # Format monetary values
                        try:
                            float_val = float(val)
                            val = f"${float_val:,.2f}"
                            # Update style after formatting
                            if prev_val is not None:
                                try:
                                    prev_float_val = float(prev_val)
                                    formatted_prev_val = f"${prev_float_val:,.2f}"
                                except ValueError:
                                    formatted_prev_val = prev_val
                            else:
                                formatted_prev_val = prev_val
                            style = get_cell_style(col_name, val, formatted_prev_val)
                        except ValueError:
                            pass  # Keep original value if conversion fails

                    return Text(val, style=style, justify=justify)

                # Handle B|A prices with separate coloring for bid and ask
                def style_ba_price(bid_val, ask_val, prev_bid_val=None, prev_ask_val=None):
                    return style_ba(bid_val, ask_val, prev_bid_val, prev_ask_val)

                # Extract bid/ask values for styling
                low_call_ba = row["low_call_ba"]
                high_call_ba = row["high_call_ba"]
                low_put_ba = row["low_put_ba"]
                high_put_ba = row["high_put_ba"]

                # Previous values for comparison
                prev_low_call_ba = prev_row.get("low_call_ba", "")
                prev_high_call_ba = prev_row.get("high_call_ba", "")
                prev_low_put_ba = prev_row.get("low_put_ba", "")
                prev_high_put_ba = prev_row.get("high_put_ba", "")

                # Parse current bid/ask values
                try:
                    low_call_bid, low_call_ask = map(float, low_call_ba.split("/"))
                    high_call_bid, high_call_ask = map(float, high_call_ba.split("/"))
                    low_put_bid, low_put_ask = map(float, low_put_ba.split("/"))
                    high_put_bid, high_put_ask = map(float, high_put_ba.split("/"))
                except:
                    # If parsing fails, use default styling
                    low_call_ba_text = Text(low_call_ba)
                    high_call_ba_text = Text(high_call_ba)
                    low_put_ba_text = Text(low_put_ba)
                    high_put_ba_text = Text(high_put_ba)
                else:
                    # Parse previous bid/ask values
                    try:
                        prev_low_call_bid, prev_low_call_ask = map(float, prev_low_call_ba.split("/"))
                    except:
                        prev_low_call_bid, prev_low_call_ask = None, None

                    try:
                        prev_high_call_bid, prev_high_call_ask = map(float, prev_high_call_ba.split("/"))
                    except:
                        prev_high_call_bid, prev_high_call_ask = None, None

                    try:
                        prev_low_put_bid, prev_low_put_ask = map(float, prev_low_put_ba.split("/"))
                    except:
                        prev_low_put_bid, prev_low_put_ask = None, None

                    try:
                        prev_high_put_bid, prev_high_put_ask = map(float, prev_high_put_ba.split("/"))
                    except:
                        prev_high_put_bid, prev_high_put_ask = None, None

                    # Style each B|A price separately
                    low_call_ba_text = style_ba_price(
                        low_call_bid, low_call_ask, prev_low_call_bid, prev_low_call_ask
                    )
                    high_call_ba_text = style_ba_price(
                        high_call_bid, high_call_ask, prev_high_call_bid, prev_high_call_ask
                    )
                    low_put_ba_text = style_ba_price(
                        low_put_bid, low_put_ask, prev_low_put_bid, prev_low_put_ask
                    )
                    high_put_ba_text = style_ba_price(
                        high_put_bid, high_put_ask, prev_high_put_bid, prev_high_put_ask
                    )

                # Style the flags column
                flags_text = style_flags(row.get("flags", ""))

                # Format face value via shared helper
                face_value_text = cell("face_value", row.get("face_value"), prev_row.get("face_value"))

                cells = [
                    Text(str(row["direction"]), style="", justify="left"),
                    Text(str(row["date"]), style="", justify="left"),
                    cell("days_to_expiry", row.get("days_to_expiry"), prev_row.get("days_to_expiry")),
                    cell("low_strike", row.get("low_strike"), prev_row.get("low_strike")),
                    cell("high_strike", row.get("high_strike"), prev_row.get("high_strike")),
                    low_call_ba_text,  # Styled B|A
                    high_call_ba_text,  # Styled B|A
                    low_put_ba_text,  # Styled B|A
                    high_put_ba_text,  # Styled B|A
                    cell("mid_net_price", row.get("mid_net_price"), prev_row.get("mid_net_price")),
                    cell("nat_net_price", row.get("nat_net_price"), prev_row.get("nat_net_price")),
                    cell("mid_upfront_amount", row.get("mid_upfront_amount"), prev_row.get("mid_upfront_amount")),
                    face_value_text,
                    cell("mid_annualized_return", row.get("mid_annualized_return"), prev_row.get("mid_annualized_return")),
                    cell("nat_annualized_return", row.get("nat_annualized_return"), prev_row.get("nat_annualized_return")),
                    flags_text,
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                row_key = table.add_row(*cells)
                # Map symbols for streaming updates if present
                try:
                    lcs = row.get("low_call_symbol")
                    hcs = row.get("high_call_symbol")
                    lps = row.get("low_put_symbol")
                    hps = row.get("high_put_symbol")
                    col_lc = self._col_keys[5] if len(self._col_keys) > 5 else 5
                    col_hc = self._col_keys[6] if len(self._col_keys) > 6 else 6
                    col_lp = self._col_keys[7] if len(self._col_keys) > 7 else 7
                    col_hp = self._col_keys[8] if len(self._col_keys) > 8 else 8
                    if lcs:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_lc, "symbol": lcs, "last_bid": locals().get("low_call_bid"), "last_ask": locals().get("low_call_ask")})
                    if hcs:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_hc, "symbol": hcs, "last_bid": locals().get("high_call_bid"), "last_ask": locals().get("high_call_ask")})
                    if lps:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_lp, "symbol": lps, "last_bid": locals().get("low_put_bid"), "last_ask": locals().get("low_put_ask")})
                    if hps:
                        self._ba_maps.append({"row_key": row_key, "col_key": col_hp, "symbol": hps, "last_bid": locals().get("high_put_bid"), "last_ask": locals().get("high_put_ask")})
                except Exception:
                    pass
            self._prev_rows = data
            # Subscribe to leg symbols for streaming via manager
            if stream_quotes and self._ba_maps:
                try:
                    mgr = get_subscription_manager(self.app.api.connectClient)
                    syms = [m["symbol"] for m in self._ba_maps if m.get("symbol")]
                    mgr.register("box_spreads", options=syms, equities=[])
                except Exception:
                    pass
        else:
            # 17 columns total now (1 + 15 blanks + 1 time)
            table.add_row("No box spreads found.", *[""] * 15, refreshed_time)

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
                # Persist last styles so color remains until change
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
                # Save styles for next tick
                m["last_bid_style"] = bid_style
                m["last_ask_style"] = ask_style
                ba_text = Text()
                ba_text.append(f"{float(bid):.2f}" if bid is not None else "", style=bid_style)
                ba_text.append("|")
                ba_text.append(f"{float(ask):.2f}" if ask is not None else "", style=ask_style)
                table.update_cell(m["row_key"], m["col_key"], ba_text)
        except Exception:
            pass




