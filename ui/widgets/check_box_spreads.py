from textual.widgets import DataTable, Static
from textual import work
from datetime import datetime
from .. import logic
from rich.text import Text

class CheckBoxSpreadsWidget(Static):
    """A widget to display box spreads."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None  # Store previous data for comparison

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="box_spreads_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_columns(
            "Direction",
            "Date",
            "Low Strike",
            "High Strike",
            "Low Call B/A",
            "High Call B/A",
            "Low Put B/A",
            "High Put B/A",
            "Net Price",
            "Investment",
            "Repayment",
            "Borrowed",
            "Repayment (Sell)",
            "Ann. Cost/Return %",
            "Margin Req",
            "Refreshed"
        )
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        self.run_get_box_spreads_data()
        # Add periodic refresh every 30 seconds
        self.set_interval(15, self.run_get_box_spreads_data)

    @work
    async def run_get_box_spreads_data(self) -> None:
        """Worker to get box spreads data."""
        data = await logic.get_box_spreads_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        def get_cell_style(col, val, prev_val=None):
            # Color coding logic
            if col in ["cagr", "ann_rom"]:
                try:
                    v = float(str(val).replace("%", ""))
                    pv = float(str(prev_val).replace("%", "")) if prev_val is not None else None
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
            if col == "net_price":
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
            if col in ["low_strike", "high_strike"]:
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
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}

                # Function to style a cell value
                def style_cell(col_name):
                    val = str(row[col_name])
                    prev_val = prev_row.get(col_name)
                    style = get_cell_style(col_name, val, prev_val)
                    # Justify numerical columns to the right
                    right_justify_cols = {
                        "low_strike", "high_strike", "net_price", "investment", "repayment",
                        "borrowed", "repayment_sell", "ann_cost_return", "margin_req"
                    }
                    justify = "right" if col_name in right_justify_cols else "left"

                    # Format percentage values
                    if col_name == "ann_cost_return":
                        try:
                            # Convert to float, multiply by 100, and format with 2 decimal places and % sign
                            float_val = float(val.replace('%', ''))
                            val = f"{float_val:.2f}%"
                            # Update style after formatting
                            # Convert prev_val to the same format for comparison
                            if prev_val is not None:
                                try:
                                    prev_float_val = float(str(prev_val).replace('%', ''))
                                    formatted_prev_val = f"{prev_float_val:.2f}%"
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

                # Compute Ann. Cost/Return % for each row
                ann_cost_return = row.get("ann_cost_return", "")
                # The value from logic already includes the appropriate sign and formatting

                cells = [
                    Text(str(row["direction"]), style="", justify="left"),
                    Text(str(row["date"]), style="", justify="left"),
                    style_cell("low_strike"),
                    style_cell("high_strike"),
                    low_call_ba_text,  # Styled B|A
                    high_call_ba_text,  # Styled B|A
                    low_put_ba_text,  # Styled B|A
                    high_put_ba_text,  # Styled B|A
                    style_cell("net_price"),
                    style_cell("investment"),
                    style_cell("repayment"),
                    style_cell("borrowed"),
                    style_cell("repayment_sell"),
                    style_cell("ann_cost_return"),
                    style_cell("margin_req"),
                    Text(refreshed_time, style="", justify="left")
                ]
                # Add row with styled cells
                table.add_row(*cells)
            self._prev_rows = data
        else:
            table.add_row("No box spreads found.", *[""] * 14, refreshed_time)