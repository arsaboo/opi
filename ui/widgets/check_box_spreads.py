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

class CheckBoxSpreadsWidget(Static):
    """A widget to display box spreads."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None  # Store previous data for comparison
        self._box_spreads_data = []  # Store actual box spreads data for order placement
        self._previous_market_status = None  # Track previous market status

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="box_spreads_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Box Spreads")
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
            "Investment",
            "Borrowed",
            "Face Value",
            "Mid Ann. Return %",
            "Nat Ann. Return %",
            "Flags",
            "Refreshed"
        )
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        table.cursor_type = "row"
        table.focus()
        self.run_get_box_spreads_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_box_spreads_data)
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

        order_details = {
            "Type": type_label,
            "Direction": direction,
            "Expiration": box_spread_data.get("date", ""),
            "Days to Expiry": days_to_expiry,
            "Strike Low": box_spread_data.get("low_strike", ""),
            "Strike High": box_spread_data.get("high_strike", ""),
            "Spread Width": float(box_spread_data.get("high_strike", 0)) - float(box_spread_data.get("low_strike", 0)) if box_spread_data.get("high_strike") and box_spread_data.get("low_strike") else "",
            "Face Value": face_value,  # Pass numeric value, let order confirmation screen format it
            "Mid Net Price": mid_net_price,
            "Nat Net Price": nat_net_price,
            "Upfront Amount": upfront_amount,  # Pass numeric value, let order confirmation screen format it
            "Annualized Return (Mid)": mid_annualized_return,  # Pass numeric value, let order confirmation screen format it
            "Annualized Return (Nat)": nat_annualized_return,  # Pass numeric value, let order confirmation screen format it
            # Do not include "Protection" for box spreads
        }
        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, confirmed: bool) -> None:
        """Handle the user's response to the order confirmation."""
        if confirmed:
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing box spread order...")
            self.place_box_spread_order()
        else:
            self.app.query_one(StatusLog).add_message("Box spread order cancelled by user.")

    @work
    async def place_box_spread_order(self) -> None:
        """Place the box spread order."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row

            if cursor_row < len(self._box_spreads_data):
                box_spread_data = self._box_spreads_data[cursor_row]

                # Extract required data
                # Note: Box spread order placement is more complex and would require implementing
                # the actual order construction in the API. For now, we'll just log the attempt.
                direction = box_spread_data.get("direction", "")
                expiration = box_spread_data.get("date", "")
                low_strike = box_spread_data.get("low_strike", "")
                high_strike = box_spread_data.get("high_strike", "")
                net_price = box_spread_data.get("net_price", "")

                self.app.query_one(StatusLog).add_message(f"Box spread order placement not yet implemented.")
                self.app.query_one(StatusLog).add_message(f"Would place {direction} box spread:")
                self.app.query_one(StatusLog).add_message(f"  Expiration: {expiration}")
                self.app.query_one(StatusLog).add_message(f"  Low Strike: {low_strike}")
                self.app.query_one(StatusLog).add_message(f"  High Strike: {high_strike}")
                self.app.query_one(StatusLog).add_message(f"  Net Price: {net_price}")
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
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_style(col, val, prev_val=None):
            # Color coding logic
            if col in ["cagr", "ann_rom", "mid_annualized_return", "nat_annualized_return"]:
                try:
                    v = float(str(val).replace("%", ""))
                    pv = float(str(prev_val).replace("%", "")) if prev_val is not None else None
                    # For box spreads:
                    # - Buying: Higher positive returns are better (green)
                    # - Selling: Higher (less negative) returns are better (green)
                    # Base style - color based on value (positive/green, negative/red)
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
                    style = "green" if v > 0 else "red" if v < 0 else ""
                    if pv is not None:
                        if v > pv:
                            style = "bold green"  # Bold green for increase
                        elif v < pv:
                            style = "bold red"    # Bold red for decrease
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
                        "low_strike", "high_strike", "net_price", "investment", "repayment",
                        "borrowed", "repayment_sell", "ann_cost_return", "margin_req",
                        "mid_net_price", "nat_net_price", "mid_annualized_return", "nat_annualized_return",
                        "mid_upfront_amount", "mid_investment", "mid_borrowed", "nat_upfront_amount",
                        "nat_investment", "nat_borrowed", "face_value", "days_to_expiry"
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
                    elif col_name in ["investment", "borrowed", "mid_upfront_amount", "nat_upfront_amount",
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
                flags = row.get("flags", "")
                flags_style = "bold red" if flags else ""
                flags_text = Text(flags, style=flags_style, justify="left")

                # Format face value
                try:
                    face_value = float(row.get("face_value", 0))
                    face_value_text = Text(f"${face_value:,.2f}", style="", justify="right")
                except:
                    face_value_text = Text("", style="", justify="right")

                cells = [
                    Text(str(row["direction"]), style="", justify="left"),
                    Text(str(row["date"]), style="", justify="left"),
                    style_cell("days_to_expiry"),
                    style_cell("low_strike"),
                    style_cell("high_strike"),
                    low_call_ba_text,  # Styled B|A
                    high_call_ba_text,  # Styled B|A
                    low_put_ba_text,  # Styled B|A
                    high_put_ba_text,  # Styled B|A
                    style_cell("mid_net_price"),
                    style_cell("nat_net_price"),
                    style_cell("mid_upfront_amount") if row["direction"] == "Buy" else Text("", justify="right"),
                    style_cell("mid_upfront_amount") if row["direction"] == "Sell" else Text("", justify="right"),
                    face_value_text,
                    style_cell("mid_annualized_return"),
                    style_cell("nat_annualized_return"),
                    flags_text,
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = data
        else:
            table.add_row("No box spreads found.", *[""] * 16, refreshed_time)