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

class CheckSyntheticCoveredCallsWidget(Static):
    """A widget to display synthetic covered calls."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._synthetic_covered_calls_data = []  # Store actual synthetic covered calls data for order placement

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="synthetic_covered_calls_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Update the header
        self.app.update_header("Options Trader - Synthetic Covered Calls")

        # Check market status
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

        self.run_get_synthetic_covered_calls_data()
        # Add periodic refresh every 15 seconds
        self.set_interval(15, self.run_get_synthetic_covered_calls_data)

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            if not exec_window["open"]:
                from configuration import debugMarketOpen
                if not debugMarketOpen:
                    self.app.query_one(StatusLog).add_message("Market is closed. Data may be delayed.")
                else:
                    self.app.query_one(StatusLog).add_message("Market is closed but running in debug mode.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    @work
    async def run_get_synthetic_covered_calls_data(self) -> None:
        """Worker to get synthetic covered calls data."""
        data = await logic.get_vertical_spreads_data(self.app.api, synthetic=True)
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
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                # Function to style a cell value
                def style_cell(col_name):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_style(col_name, val, prev_val)
                    # Justify numerical columns to the right
                    right_justify_cols = {"strike_low", "call_low_ba", "put_low_ba", "strike_high", "call_high_ba", "investment", "max_profit", "cagr", "protection", "margin_req", "ann_rom"}
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
                put_low_ba = style_ba_price('put_bid', 'put_ask')

                cells = [
                    Text(str(row["asset"]), style="", justify="left"),
                    Text(str(row["expiration"]), style="", justify="left"),
                    style_cell("strike_low"),
                    call_low_ba,  # Styled B|A
                    put_low_ba,   # Styled B|A
                    style_cell("strike_high"),
                    call_high_ba,  # Styled B|A
                    style_cell("investment"),
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
            table.add_row("No synthetic covered calls found.", "", "", "", "", "", "", "", "", "", "", "", "", refreshed_time)

    def check_market_status(self) -> None:
        """Check and display market status information."""
        try:
            exec_window = self.app.api.getOptionExecutionWindow()
            if not exec_window["open"]:
                from configuration import debugMarketOpen
                if not debugMarketOpen:
                    self.app.query_one(StatusLog).add_message("Market is closed. Data may be delayed.")
                else:
                    self.app.query_one(StatusLog).add_message("Market is closed but running in debug mode.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error checking market status: {e}")

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection."""
        # Get the selected row data
        row_index = event.cursor_row
        if hasattr(self, '_synthetic_covered_calls_data') and self._synthetic_covered_calls_data and row_index < len(self._synthetic_covered_calls_data):
            selected_data = self._synthetic_covered_calls_data[row_index]
            # Show order confirmation dialog
            self.show_order_confirmation(selected_data)

    def show_order_confirmation(self, synthetic_covered_call_data) -> None:
        """Show order confirmation dialog."""
        order_details = {
            "Type": "Synthetic Covered Call",
            "Asset": synthetic_covered_call_data.get("asset", ""),
            "Expiration": synthetic_covered_call_data.get("expiration", ""),
            "Strike Low": synthetic_covered_call_data.get("strike_low", ""),
            "Strike High": synthetic_covered_call_data.get("strike_high", ""),
            "Investment": synthetic_covered_call_data.get("investment", ""),
            "Max Profit": synthetic_covered_call_data.get("max_profit", ""),
            "Annualized Return": synthetic_covered_call_data.get("ann_rom", "")
        }
        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, confirmed: bool) -> None:
        """Handle the user's response to the order confirmation."""
        if confirmed:
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing synthetic covered call order...")
            self.place_synthetic_covered_call_order()
        else:
            self.app.query_one(StatusLog).add_message("Synthetic covered call order cancelled by user.")

    @work
    async def place_synthetic_covered_call_order(self) -> None:
        """Place the synthetic covered call order."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row

            if cursor_row < len(self._synthetic_covered_calls_data):
                synthetic_covered_call_data = self._synthetic_covered_calls_data[cursor_row]

                # TODO: Implement actual synthetic covered call order placement
                # This would involve calling the appropriate strategy functions
                # from strategies.py to place the synthetic covered call order

                self.app.query_one(StatusLog).add_message("Synthetic covered call order placement not yet implemented.")
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for synthetic covered call order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error placing synthetic covered call order: {e}")