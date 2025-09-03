from textual.widgets import DataTable, Static
from textual import work
from datetime import datetime
from .. import logic
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
from ..utils import style_cell as cell
import asyncio
import keyboard
from api.orders import handle_cancel, reset_cancel_flag, cancel_order, monitor_order
from core.common import round_to_nearest_five_cents
from configuration import stream_quotes

from api.streaming.provider import get_provider
try:
    from configuration import manual_order as MANUAL_ORDER
except Exception:
    MANUAL_ORDER = False

class RollShortOptionsWidget(Static):
    """A widget to display short options to be rolled."""

    def __init__(self):
        super().__init__()
        self._prev_rows = None
        self._roll_data = []  # Store the actual roll data for each row
        self._previous_market_status = None  # Track previous market status
        self._override_credit = None  # User-edited initial credit

    def compose(self):
        """Create child widgets."""
        yield DataTable(id="roll_short_options_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        self.app.update_header("Options Trader - Roll Short Calls")
        # Only check market status if not already set
        if self._previous_market_status is None:
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
            "Days Δ",
            "Credit",
            "Cr/Day",
            "CrDayPerPt",
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
        # Streaming
        self._credit_maps = []
        self._last_stream_opts: set[str] = set()
        self._last_stream_eqs: set[str] = set()

        try:
            self._col_keys = list(self.query_one(DataTable).columns.keys())
        except Exception:
            self._col_keys = []

        if stream_quotes:
            try:
                self._quote_provider = get_provider(self.app.api.connectClient)
                self.set_interval(1, self.refresh_streaming_credit)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Streaming init error: {e}")


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
        roll_out_days = roll_data.get("Days Δ", "") or roll_data.get("Roll Out (Days)", "")
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
            "Days Δ": roll_out_days,
            "Current Underlying Value": underlying_value
        }

        screen = OrderConfirmationScreen(order_details)
        self.app.push_screen(screen, callback=self.handle_order_confirmation)

    def handle_order_confirmation(self, result) -> None:
        """Handle the user's response to the order confirmation and capture edited credit."""
        confirmed = result.get("confirmed") if isinstance(result, dict) else bool(result)
        if confirmed:
            if isinstance(result, dict) and result.get("credit") is not None:
                try:
                    self._override_credit = float(result.get("credit"))
                except Exception:
                    self._override_credit = None
            self.app.query_one(StatusLog).add_message("Order confirmed. Placing order...")
            # Place the order using the existing functions
            self.place_order()
        else:
            self.app.query_one(StatusLog).add_message("Order cancelled by user.")

    @work
    async def place_order(self) -> None:
        """Place the roll order with price improvements and UI monitoring."""
        try:
            # Get the selected row data
            table = self.query_one(DataTable)
            cursor_row = table.cursor_row
            if cursor_row < len(self._roll_data):
                roll_data = self._roll_data[cursor_row]
                # Extract necessary data
                old_symbol = roll_data.get("optionSymbol", "")
                new_symbol = roll_data.get("New Option Symbol", "")
                amount = int(roll_data.get("Quantity", 1))
                credit = roll_data.get("Credit", "N/A")
                if not old_symbol or not new_symbol or credit == "N/A":
                    self.app.query_one(StatusLog).add_message("Error: Missing or invalid data for roll order.")
                    return
                credit = float(credit)
                initial_price = self._override_credit if self._override_credit is not None else credit
                filled = False

                # Try prices in sequence; single attempt in manual mode
                attempts = [0] if MANUAL_ORDER else range(76)
                for i in attempts:
                    current_price = (
                        initial_price if i == 0
                        else round_to_nearest_five_cents(initial_price - i * 0.05)
                    )

                    if i > 0:
                        self.app.query_one(StatusLog).add_message(f"Trying improved price: ${current_price} (attempt #{i})")

                    # Place the order
                    from .. import logic as ui_logic
                    order_id = await ui_logic.roll_over(self.app.api, old_symbol, new_symbol, amount, current_price)

                    if order_id is None:
                        self.app.query_one(StatusLog).add_message("Order not placed (debug mode or error).")
                        break

                    # Manual mode: do not monitor; use Order Management to manage
                    if MANUAL_ORDER:
                        self.app.query_one(StatusLog).add_message("Manual roll order placed. Manage from Order Management (U=Update, C=Cancel).")
                        self._override_credit = None
                        return
                    # Non-manual: start monitoring feedback
                    self.app.query_one(StatusLog).add_message(f"Monitoring roll order {order_id}...")
                    result = await self.monitor_order_ui(order_id)

                    if result is True:
                        self.app.query_one(StatusLog).add_message("Roll order filled successfully!")
                        filled = True
                        break
                    elif result == "cancelled":
                        self.app.query_one(StatusLog).add_message("Roll order cancelled.")
                        break
                    elif result == "rejected":
                        self.app.query_one(StatusLog).add_message("Roll order rejected, trying next price...")
                        continue
                    elif result == "timeout":
                        if MANUAL_ORDER:
                            self.app.query_one(StatusLog).add_message("Roll order timed out. Use Order Management (U to update, C to cancel).")
                            break
                        else:
                            self.app.query_one(StatusLog).add_message("Roll order timed out, trying next price...")
                            # Cancel the timed-out order before next attempt
                            try:
                                from .. import logic as ui_logic
                                await ui_logic.cancel_order(self.app.api, order_id)
                            except Exception as e:
                                self.app.query_one(StatusLog).add_message(f"Error cancelling timed-out order: {e}")
                            continue

                    # Brief pause between attempts
                    if i > 0 and not MANUAL_ORDER:
                        await asyncio.sleep(1)
                if not filled:
                    self.app.query_one(StatusLog).add_message("Roll order not filled after all attempts.")
            else:
                self.app.query_one(StatusLog).add_message("Error: No valid row selected for roll order placement.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error in place_order: {e}")

    async def monitor_order_ui(self, order_id, timeout=60, manual=False):
        """Monitor order status and update UI with status changes (reused from check_vertical_spreads.py)."""
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
                    order_status = await asyncio.to_thread(self.app.api.checkOrder, order_id)
                    last_status_check = current_time
                    if current_time - last_print_time >= print_interval:
                        remaining = int(timeout - elapsed_time)
                        status_str = order_status['status']
                        rejection_reason = order_status.get('rejection_reason', '')
                        status_msg = f"Status: {status_str} {rejection_reason} | Time remaining: {remaining} s | Price: {order_status.get('price', 'N/A')} | Filled: {order_status.get('filledQuantity', '0')}"
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
                from .. import logic as ui_logic
                await ui_logic.cancel_order(self.app.api, order_id)
            except:
                pass
            return "timeout"

    @work
    async def run_get_expiring_shorts_data(self) -> None:
        """Worker to get the expiring shorts data."""
        data = await logic.get_expiring_shorts_data(self.app.api)
        table = self.query_one(DataTable)
        table.clear()
        self._credit_maps = []
        refreshed_time = datetime.now().strftime("%H:%M:%S")

        if data:
            prev_rows = self._prev_rows or []
            self._roll_data = []  # Clear previous roll data
            for idx, row in enumerate(data):
                prev_row = prev_rows[idx] if idx < len(prev_rows) else {}
                self._roll_data.append(row)
                cells = [
                    Text(str(row["Ticker"]), style="", justify="left"),
                    cell("Current Strike", row.get("Current Strike"), prev_row.get("Current Strike")),
                    Text(str(row["Expiration"]), style="", justify="left"),
                    cell("DTE", row.get("DTE"), prev_row.get("DTE")),
                    cell("Underlying Price", row.get("Underlying Price"), prev_row.get("Underlying Price")),
                    cell("Status", row.get("Status", ""), prev_row.get("Status")),
                    cell("Quantity", row.get("Quantity", row.get("count", "")), prev_row.get("Quantity", prev_row.get("count"))),
                    Text(str(row.get("New Strike", "")), style="", justify="center"),
                    Text(str(row.get("New Expiration", "")), style="", justify="center"),
                    Text(str(row.get("Roll Out (Days)", "")), style="", justify="center"),
                    cell("Credit", row.get("Credit"), prev_row.get("Credit")),
                    cell("Cr/Day", row.get("Cr/Day"), prev_row.get("Cr/Day")),
                    cell("CrDayPerPt", row.get("CrDayPerPt"), prev_row.get("CrDayPerPt")),
                    cell("Extrinsic", row.get("Extrinsic"), prev_row.get("Extrinsic")),
                    cell("Strike Δ", row.get("Strike Δ"), prev_row.get("Strike Δ")),
                    cell("Config Status", row.get("Config Status"), prev_row.get("Config Status")),
                    Text(refreshed_time, style="", justify="left"),
                ]
                # Add row with styled cells
                row_key = table.add_row(*cells)
                # Map symbols for streaming roll credit
                try:
                    old_sym = row.get("optionSymbol")
                    new_sym = row.get("New Option Symbol")
                    ticker = row.get("Ticker")
                    strike = float(row.get("Current Strike", 0)) if row.get("Current Strike") else 0.0
                    cols = list(self.query_one(DataTable).columns.keys())
                    col_under = (cols.index("Underlying Price") if "Underlying Price" in cols else 4)
                    col_extr = (cols.index("Extrinsic") if "Extrinsic" in cols else 13)
                    col_credit = (cols.index("Credit") if "Credit" in cols else 10)
                    self._credit_maps.append({
                        "row_key": row_key,
                        "col_credit": col_credit,
                        "col_under": col_under,
                        "col_extr": col_extr,
                        "old_symbol": old_sym,
                        "new_symbol": new_sym,
                        "ticker": ticker,
                        "strike": strike,
                    })
                except Exception:
                    pass
            self._prev_rows = data
            # Reconcile streaming symbols for options and equities (subscribe/unsubscribe)
            if stream_quotes and getattr(self, "_quote_provider", None):
                try:
                    opt_syms = []
                    equities = []
                    for m in self._credit_maps:
                        if m.get("old_symbol"):
                            opt_syms.append(m["old_symbol"])
                        if m.get("new_symbol"):
                            opt_syms.append(m["new_symbol"])
                        if m.get("ticker"):
                            equities.append(m["ticker"])
                    desired_opts = {s for s in opt_syms if s}
                    desired_eqs = {s for s in equities if s}
                    # Unsubscribe removed
                    removed_opts = self._last_stream_opts - desired_opts
                    removed_eqs = {s for s in (self._last_stream_eqs - desired_eqs)}
                    if removed_opts:
                        asyncio.create_task(self._quote_provider.unsubscribe_options(list(removed_opts)))
                    if removed_eqs:
                        asyncio.create_task(self._quote_provider.unsubscribe_equities(list(removed_eqs)))
                    # Subscribe added
                    added_opts = desired_opts - self._last_stream_opts
                    added_eqs = desired_eqs - self._last_stream_eqs
                    if added_opts:
                        asyncio.create_task(self._quote_provider.subscribe_options(list(added_opts)))
                    if added_eqs:
                        asyncio.create_task(self._quote_provider.subscribe_equities(list(added_eqs)))
                    # Update snapshots
                    self._last_stream_opts = desired_opts
                    self._last_stream_eqs = desired_eqs
                except Exception:
                    pass
        else:
            try:
                # message in first col, refreshed in last col
                total_cols = len(self.query_one(DataTable).columns)
                empties = max(0, total_cols - 2)
            except Exception:
                empties = 15
            table.add_row("No expiring options found.", *[""] * empties, refreshed_time)

    def refresh_streaming_credit(self) -> None:
        if not stream_quotes or not getattr(self, "_quote_provider", None) or not getattr(self, "_credit_maps", None):
            return
        try:
            table = self.query_one(DataTable)
            for m in self._credit_maps:
                old_sym = m.get("old_symbol")
                new_sym = m.get("new_symbol")
                ticker = m.get("ticker")
                strike = m.get("strike", 0.0)
                # Update credit if both side quotes present
                if old_sym and new_sym:
                    nbid, _ = self._quote_provider.get_bid_ask(new_sym)
                    _, oask = self._quote_provider.get_bid_ask(old_sym)
                    if nbid is not None and oask is not None:
                        credit = nbid - oask
                        prev = m.get("last_credit")
                        # Persist last style so highlight remains until the next change
                        style = m.get("last_credit_style", "")
                        try:
                            if prev is not None:
                                if float(credit) > float(prev):
                                    style = "bold green"
                                elif float(credit) < float(prev):
                                    style = "bold red"
                        except Exception:
                            pass
                        m["last_credit"] = credit
                        m["last_credit_style"] = style
                        table.update_cell(m["row_key"], m["col_credit"], Text(f"{credit:.2f}", style=style, justify="right"))
                # Update underlying price from equity stream
                if ticker:
                    last = self._quote_provider.get_last(ticker)
                    if last is not None:
                        prev_under = m.get("last_under")
                        # Keep last style until value changes
                        style = m.get("last_under_style", "")
                        try:
                            if prev_under is not None:
                                if float(last) > float(prev_under):
                                    style = "bold green"
                                elif float(last) < float(prev_under):
                                    style = "bold red"
                        except Exception:
                            pass
                        m["last_under"] = last
                        m["last_under_style"] = style
                        table.update_cell(m["row_key"], m["col_under"], Text(f"{last:.2f}", style=style, justify="right"))
                # Update extrinsic = option_price - intrinsic (calls)
                if old_sym and ticker:
                    # option price: prefer last; else mid of bid/ask
                    last_opt = self._quote_provider.get_last(old_sym)
                    bid, ask = self._quote_provider.get_bid_ask(old_sym)
                    opt_price = None
                    if last_opt is not None:
                        opt_price = last_opt
                    elif bid is not None and ask is not None:
                        opt_price = (bid + ask) / 2
                    # intrinsic for short call
                    last_under = self._quote_provider.get_last(ticker)
                    if opt_price is not None and last_under is not None:
                        intrinsic = max(0.0, float(last_under) - float(strike))
                        extrinsic = opt_price - intrinsic
                        # Color extrinsic consistently with initial render: green if low (<1), red otherwise
                        try:
                            extr_style = "green" if float(extrinsic) < 1 else "red"
                        except Exception:
                            extr_style = ""
                        table.update_cell(m["row_key"], m["col_extr"], Text(f"{extrinsic:.2f}", style=extr_style, justify="right"))
        except Exception:
            pass
