from textual.widgets import DataTable, Static, Label
from textual import work
from textual.containers import Vertical
from datetime import datetime
from ..widgets.status_log import StatusLog
from ..widgets.order_confirmation import OrderConfirmationScreen
from rich.text import Text
import asyncio
from textual.screen import ModalScreen
from textual.widgets import Static, Input
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.align import Align
import schwab
from schwab.utils import Utils
from configuration import debugCanSendOrders


class OrderCancellationScreen(ModalScreen):
    """A modal screen for order cancellation confirmation."""

    def __init__(self, order_details, confirm_text="Cancel Order", cancel_text="Keep Order"):
        super().__init__()
        self.order_details = order_details
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
        self._loading = False
        self._error = None

    def compose(self):
        def parse_float(value):
            """Safely parse float from string, stripping currency/percentage symbols."""
            if value is None:
                return 0.0
            if isinstance(value, str):
                value = value.replace('$', '').replace('%', '').strip()
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        # Title and asset/type
        title = Text("ORDER CANCELLATION CONFIRMATION", style="bold white", justify="center")
        asset_type = Text(
            f"Order ID: {self.order_details.get('Order ID', '')}",
            style="bold yellow",
            justify="center"
        )

        # Order Details Section
        order_table = Table.grid(padding=(0, 2), expand=True)
        order_table.add_row(
            Text("Status", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Status", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Asset", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Asset", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Order Type", style="cyan"),
            Text(":", style="white"),
            Text(self.order_details.get("Order Type", ""), style="white", justify="left")
        )
        order_table.add_row(
            Text("Quantity", style="cyan"),
            Text(":", style="white"),
            Text(str(self.order_details.get("Quantity", "")), style="white", justify="left")
        )
        order_table.add_row(
            Text("Price", style="cyan"),
            Text(":", style="white"),
            Text(f"$ {parse_float(self.order_details.get('Price', 0)):.2f}", style="white", justify="left")
        )

        # Instructions
        instructions = Text(
            f"[Y / Enter] {self.confirm_text}     [N / Esc] {self.cancel_text}",
            style="bold green",
            justify="center"
        )

        # Compose Rich panel content
        panel_content = Table.grid(expand=True)
        panel_content.add_row(Align.center(title))
        panel_content.add_row(Align.center(asset_type))
        panel_content.add_row("")  # Spacer

        # Order Details
        panel_content.add_row(Text("Order Details", style="bold underline"))
        panel_content.add_row(order_table)

        # Instructions
        panel_content.add_row("")  # Spacer
        panel_content.add_row(Align.center(instructions))
        panel_content.add_row("─" * 50)

        panel = Panel.fit(
            panel_content,
            title="Order Cancellation",
            border_style="bold red"
        )

        yield Static(panel, id="order-cancellation-modal")

    def on_key(self, event):
        if self._loading:
            event.prevent_default()
            return
        if event.key in ("enter", "y"):
            self._loading = True
            self.refresh()
            self.confirm_cancellation()
        elif event.key in ("escape", "n"):
            self.dismiss(False)

    def confirm_cancellation(self):
        import asyncio
        async def do_confirm():
            try:
                await asyncio.sleep(1)
                self.dismiss(True)
            except Exception as e:
                self._loading = False
                self._error = f"Error: {e}"
                self.refresh()
        asyncio.create_task(do_confirm())


class OrderReplaceConfirmationScreen(ModalScreen):
    """A modal screen for order price replacement confirmation with editable price."""

    def __init__(self, order_details, confirm_text="Replace Order", cancel_text="Back"):
        super().__init__()
        self.order_details = order_details
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
        self._loading = False

    def compose(self):
        def parse_float(value):
            if value is None:
                return 0.0
            if isinstance(value, str):
                value = value.replace('$', '').strip()
            try:
                return float(value)
            except Exception:
                return 0.0

        title = Text("ORDER PRICE UPDATE", style="bold white", justify="center")
        subtitle = Text(f"Order ID: {self.order_details.get('Order ID', '')}", style="bold yellow", justify="center")

        tbl = Table.grid(padding=(0, 2), expand=True)
        tbl.add_row(Text("Asset", style="cyan"), Text(":"), Text(self.order_details.get('Asset', ''), style="white"))
        tbl.add_row(Text("Type", style="cyan"), Text(":"), Text(self.order_details.get('Order Type', ''), style="white"))
        tbl.add_row(Text("Quantity", style="cyan"), Text(":"), Text(str(self.order_details.get('Quantity', '')), style="white"))
        tbl.add_row(Text("Current Price", style="cyan"), Text(":"), Text(f"$ {parse_float(self.order_details.get('Current Price', 0)):.2f}", style="white"))

        # Editable New Price
        new_price_val = f"{parse_float(self.order_details.get('New Price', 0)):.2f}"
        tbl.add_row(Text("New Price", style="cyan"), Text(":"), Text(new_price_val, style="white"))

        instructions = Text(f"[Y / Enter] {self.confirm_text}     [N / Esc] {self.cancel_text}", style="bold green", justify="center")

        panel_content = Table.grid(expand=True)
        panel_content.add_row(Align.center(title))
        panel_content.add_row(Align.center(subtitle))
        panel_content.add_row("")
        panel_content.add_row(tbl)
        panel_content.add_row("")
        panel_content.add_row(Align.center(Text("Edit New Price ($)", style="bold white")))
        panel = Panel.fit(panel_content, title="Confirm Replace", border_style="bold blue")
        yield Static(panel)
        yield Input(value=new_price_val, id="replace_price_input")

    def on_key(self, event):
        if self._loading:
            event.prevent_default()
            return
        if event.key in ("enter", "y"):
            self._loading = True
            self.refresh()
            self.confirm()
        elif event.key in ("escape", "n"):
            self.dismiss({"confirmed": False})

    def confirm(self):
        import asyncio
        async def do_confirm():
            inp = self.query_one("#replace_price_input", Input)
            val = inp.value.strip()
            try:
                price = float(val)
            except Exception:
                price = None
            self.dismiss({"confirmed": True, "price": price})
        asyncio.create_task(do_confirm())


class OrderManagementWidget(Static):
    """A widget to manage and display recent orders."""

    def __init__(self):
        super().__init__()
        self._working_orders = []
        self._filled_orders = []
        self._other_orders = []
        self._manual_steps = {}
        self._base_price = {}
        self._selected_order_id = None
        self._initialized = False
        self._row_positions = {"working_header": 0, "working_rows": [], "working_sep": None,
                               "filled_header": None, "filled_rows": [], "filled_sep": None,
                               "other_header": None, "other_rows": []}
        self._col_keys = []

    def compose(self):
        """Create child widgets."""
        with Vertical():
            yield Static(Text("Hints: U = Update Price, C = Cancel", style="bold yellow"))
            yield DataTable(id="order_management_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Update the header
        self.app.update_header("Options Trader - Order Management")

        table = self.query_one(DataTable)
        table.add_columns(
            "Order ID",
            "Status",
            "Time",
            "Asset",
            "Type",
            "Qty",
            "Price",
            "Mid",
            "Nat"
        )
        # Cache column keys for update_cell
        try:
            self._col_keys = list(table.columns.keys())
        except Exception:
            self._col_keys = list(range(9))
        table.zebra_stripes = True
        table.header_style = "bold on blue"
        table.cursor_type = "row"
        table.focus()
        self.run_get_orders_data()
        self.set_interval(15, self.run_get_orders_data)

    def on_key(self, event) -> None:
        """Handle key events for manual order actions."""
        key = getattr(event, 'key', '').lower()
        if key == 'c':
            order = self._get_selected_working_order()
            if order:
                self.show_cancel_confirmation(order)
                event.prevent_default()
        elif key == 'u':
            self.replace_selected_order_price()
            event.prevent_default()

    def _get_selected_working_order(self):
        table = self.query_one(DataTable)
        row_index = getattr(table, 'cursor_row', None)
        if row_index is None:
            return None
        # First row is the WORKING ORDERS header
        header_rows = 1
        if row_index <= 0:
            return None
        if row_index <= len(self._working_orders):
            return self._working_orders[row_index - header_rows]
        return None

    @work
    async def replace_selected_order_price(self) -> None:
        """Replace selected working order with an improved price using existing approach (−1% per step)."""
        try:
            order = self._get_selected_working_order()
            if not order:
                self.app.query_one(StatusLog).add_message("Select a WORKING order to update price.")
                return

            formatted = self.app.api.formatOrderForDisplay(order)
            order_id = formatted.get('order_id')
            current_price = formatted.get('price')
            try:
                current_price = float(current_price)
            except Exception:
                self.app.query_one(StatusLog).add_message("Unable to parse current price for selected order.")
                return

            # Determine base price at first update
            base = self._base_price.get(order_id, current_price)
            self._base_price[order_id] = base
            step = self._manual_steps.get(order_id, 0) + 1
            self._manual_steps[order_id] = step

            # Compute improved price and round to $0.05
            def round_to_nearest_five_cents(price):
                return round(price * 20) / 20

            # Determine debit vs credit from full order prior to suggestion
            client = self.app.api.connectClient
            account_hash = self.app.api.getAccountHash()
            r = await asyncio.to_thread(client.get_order, order_id, account_hash)
            r.raise_for_status()
            full_order = r.json()
            order_type_str = full_order.get("orderType", "NET_DEBIT")
            is_debit = (order_type_str == "NET_DEBIT")

            new_price = round_to_nearest_five_cents(base + step * 0.05) if is_debit else round_to_nearest_five_cents(base - step * 0.05)

            # Show confirmation modal with editable price
            details = {
                "Order ID": order_id,
                "Asset": formatted.get('asset', ''),
                "Order Type": formatted.get('order_type', ''),
                "Quantity": formatted.get('quantity', ''),
                "Current Price": current_price,
                "New Price": new_price,
            }
            screen = OrderReplaceConfirmationScreen(details)

            def _cb(payload):
                import asyncio as _asyncio
                _asyncio.create_task(self._handle_replace_confirmation(payload, order, base, step, new_price))

            self.app.push_screen(screen, callback=_cb)
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error replacing order: {e}")

    async def _handle_replace_confirmation(self, payload, order, base, step, suggested_price):
        try:
            if not payload or not payload.get('confirmed'):
                self.app.query_one(StatusLog).add_message("Replacement cancelled.")
                return

            formatted = self.app.api.formatOrderForDisplay(order)
            order_id = formatted.get('order_id')
            new_price = payload.get('price') if payload.get('price') is not None else suggested_price

            # Build replacement order from existing order legs
            client = self.app.api.connectClient
            account_hash = self.app.api.getAccountHash()
            # Fetch full order details
            r = await asyncio.to_thread(client.get_order, order_id, account_hash)
            r.raise_for_status()
            full_order = r.json()

            # Attempt to cancel existing order first
            try:
                await asyncio.to_thread(self.app.api.cancelOrder, order_id)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Warning: could not cancel order {order_id}: {e}")

            ob = schwab.orders.generic.OrderBuilder()
            order_type_str = full_order.get("orderType", "NET_DEBIT")
            order_type_enum = getattr(schwab.orders.common.OrderType, order_type_str, schwab.orders.common.OrderType.NET_DEBIT)
            legs = full_order.get("orderLegCollection", [])
            for leg in legs:
                instr = leg.get("instrument", {})
                symbol = instr.get("symbol")
                qty = leg.get("quantity", 1)
                instruction_str = leg.get("instruction", "BUY_TO_OPEN")
                try:
                    instruction_enum = getattr(schwab.orders.common.OptionInstruction, instruction_str)
                except Exception:
                    instruction_enum = schwab.orders.common.OptionInstruction.BUY_TO_OPEN if instruction_str.upper().startswith("BUY") else schwab.orders.common.OptionInstruction.SELL_TO_OPEN
                ob.add_option_leg(instruction_enum, symbol, qty)

            ob.set_duration(schwab.orders.common.Duration.DAY)
            ob.set_session(schwab.orders.common.Session.NORMAL)
            ob.set_price(str(abs(new_price)))
            ob.set_order_type(order_type_enum)
            ob.set_order_strategy_type(schwab.orders.common.OrderStrategyType.SINGLE)
            co = full_order.get("complexOrderStrategyType")
            if co:
                try:
                    co_enum = getattr(schwab.orders.common.ComplexOrderStrategyType, co)
                    ob.set_complex_order_strategy_type(co_enum)
                except Exception:
                    pass

            if not debugCanSendOrders:
                print("Replacement order (debug): ", ob.build())
                new_order_id = None
            else:
                r2 = await asyncio.to_thread(client.place_order, account_hash, ob)
                new_order_id = Utils(client, account_hash).extract_order_id(r2)

            if new_order_id:
                # Carry over base and step to new order id
                self._base_price[new_order_id] = base
                self._manual_steps[new_order_id] = step
                # Cleanup old mapping
                self._base_price.pop(order_id, None)
                self._manual_steps.pop(order_id, None)
                self.app.query_one(StatusLog).add_message(f"Placed replacement order {new_order_id} at ${new_price:.2f}.")
                self.run_get_orders_data()
            else:
                self.app.query_one(StatusLog).add_message("Failed to replace order.")
        except Exception as e:
            self.app.query_one(StatusLog).add_message(f"Error replacing order: {e}")

    @work
    async def run_get_orders_data(self) -> None:
        """Incrementally update orders; rebuild only on first load or layout change."""
        orders = await asyncio.to_thread(self.app.api.getRecentOrders, 50)
        table = self.query_one(DataTable)

        # Partition orders
        working = []
        filled = []
        other = []
        for order in orders or []:
            formatted = self.app.api.formatOrderForDisplay(order)
            status = formatted["status"]
            if status in ("ACCEPTED", "WORKING"):
                working.append((order, formatted))
            elif status == "FILLED":
                filled.append((order, formatted))
            else:
                other.append((order, formatted))

        # Helper to compute Mid/Nat for an order (async)
        async def compute_mid_nat(order):
            try:
                order_type = order.get("orderType", "NET_DEBIT")
                legs = order.get("orderLegCollection", [])
                if not legs:
                    return ("", "")
                client = self.app.api.connectClient
                cost_mid = proceeds_mid = cost_nat = proceeds_nat = 0.0
                for leg in legs:
                    instr = leg.get("instrument", {})
                    symbol = instr.get("symbol")
                    instruction = leg.get("instruction", "BUY_TO_OPEN").upper()
                    if not symbol:
                        continue
                    r = await asyncio.to_thread(client.get_quotes, symbol)
                    if r.status_code != 200 and r.status_code != 201:
                        continue
                    q = r.json()
                    qd = q.get(symbol, {}).get("quote", {})
                    bid = qd.get("bidPrice") or 0.0
                    ask = qd.get("askPrice") or 0.0
                    mid = (float(bid) + float(ask)) / 2 if (bid and ask) else 0.0
                    if instruction.startswith("BUY"):
                        cost_mid += mid
                        cost_nat += float(ask) if ask else mid
                    else:
                        proceeds_mid += mid
                        proceeds_nat += float(bid) if bid else mid
                if order_type == "NET_DEBIT":
                    net_mid = cost_mid - proceeds_mid
                    net_nat = cost_nat - proceeds_nat
                else:
                    net_mid = proceeds_mid - cost_mid
                    net_nat = proceeds_nat - cost_nat
                return (f"{net_mid:.2f}", f"{net_nat:.2f}")
            except Exception:
                return ("", "")

        if not self._initialized:
            # Build full table once
            table.clear()
            table.add_row(Text("WORKING ORDERS", style="bold white on dark_blue"), *[Text("") for _ in range(8)])
            self._row_positions["working_header"] = 0
            self._row_positions["working_rows"] = []
            # Add working rows
            for order, formatted in working:
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                status_color = "cyan" if formatted["status"] == "WORKING" else ""
                mid_str, nat_str = await compute_mid_nat(order)
                row_key = table.add_row(
                    Text(str(formatted["order_id"])),
                    Text(str(formatted["status"]), style=status_color),
                    Text(str(formatted["entered_time"])),
                    Text(str(formatted["asset"])),
                    Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")),
                    Text(str(formatted["quantity"]), justify="right"),
                    Text(price, justify="right"),
                    Text(mid_str, justify="right"),
                    Text(nat_str, justify="right"),
                )
                self._row_positions["working_rows"].append(row_key)
            # Separator
            table.add_row(*[Text("") for _ in range(9)])
            self._row_positions["working_sep"] = len(self._row_positions["working_rows"]) + 1
            # Filled header + rows
            table.add_row(Text("FILLED ORDERS", style="bold white on dark_blue"), *[Text("") for _ in range(8)])
            for order, formatted in filled:
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                table.add_row(
                    Text(str(formatted["order_id"])),
                    Text(str(formatted["status"]), style="green"),
                    Text(str(formatted["entered_time"])),
                    Text(str(formatted["asset"])),
                    Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")),
                    Text(str(formatted["quantity"]), justify="right"),
                    Text(price, justify="right"),
                    Text("", justify="right"),
                    Text("", justify="right"),
                )
            # Separator
            table.add_row(*[Text("") for _ in range(9)])
            # Other header + rows
            table.add_row(Text("OTHER ORDERS (Canceled / Expired / Replaced)", style="bold white on dark_blue"), *[Text("") for _ in range(8)])
            for order, formatted in other:
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                status_color = {"CANCELED": "gray", "EXPIRED": "yellow", "REPLACED": "magenta"}.get(formatted["status"], "")
                table.add_row(
                    Text(str(formatted["order_id"])),
                    Text(str(formatted["status"]), style=status_color),
                    Text(str(formatted["entered_time"])),
                    Text(str(formatted["asset"])),
                    Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")),
                    Text(str(formatted["quantity"]), justify="right"),
                    Text(price, justify="right"),
                    Text("", justify="right"),
                    Text("", justify="right"),
                )

            # Update internal lists
            self._working_orders = [o for o, _ in working]
            self._filled_orders = [o for o, _ in filled]
            self._other_orders = [o for o, _ in other]
            self._initialized = True

            # Default selection: first working order else header
            try:
                if working:
                    if hasattr(table, "move_cursor"):
                        table.move_cursor(1, 0)
                    self._selected_order_id = working[0][0].get("orderId")
                else:
                    if hasattr(table, "move_cursor"):
                        table.move_cursor(0, 0)
                    self._selected_order_id = None
            except Exception:
                pass
            return

        # Incremental update of working rows only (if count/order IDs unchanged)
        prev_ids = [str(o.get("orderId")) for o in self._working_orders]
        new_ids = [str(o.get("orderId")) for o, _ in working]
        if prev_ids == new_ids and len(self._row_positions["working_rows"]) == len(new_ids):
            # Update cells in place
            for idx, (order, formatted) in enumerate(working):
                row_key = self._row_positions["working_rows"][idx]
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                status = formatted["status"]
                status_color = "cyan" if status == "WORKING" else ""
                mid_str, nat_str = await compute_mid_nat(order)
                # Update columns 0..8
                ck = self._col_keys
                table.update_cell(row_key, ck[0], Text(str(formatted["order_id"])))
                table.update_cell(row_key, ck[1], Text(str(status), style=status_color))
                table.update_cell(row_key, ck[2], Text(str(formatted["entered_time"])))
                table.update_cell(row_key, ck[3], Text(str(formatted["asset"])))
                table.update_cell(row_key, ck[4], Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")))
                table.update_cell(row_key, ck[5], Text(str(formatted["quantity"]), justify="right"))
                table.update_cell(row_key, ck[6], Text(price, justify="right"))
                table.update_cell(row_key, ck[7], Text(mid_str, justify="right"))
                table.update_cell(row_key, ck[8], Text(nat_str, justify="right"))
            return

        # Fallback: layout changed (orders added/removed) — rebuild once (might flicker briefly)
        self._initialized = False
        self.run_get_orders_data()

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection by updating selection only; use U/C for actions."""
        try:
            r = event.cursor_row
            w = len(self._working_orders)
            f = len(self._filled_orders)
            order = None
            if 1 <= r <= w:
                order = self._working_orders[r-1]
            elif r >= w + 3 and r <= w + 2 + f:
                order = self._filled_orders[r - (w + 3)]
            elif r >= w + 2 + f + 3:
                idx = r - (w + 2 + f + 3)
                if 0 <= idx < len(self._other_orders):
                    order = self._other_orders[idx]
            if order:
                self._selected_order_id = order.get("orderId")
        except Exception:
            pass
        # Friendly hint
        self.app.query_one(StatusLog).add_message("Order selected. Press U to update price or C to cancel.")

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
        screen = OrderCancellationScreen(order_details, confirm_text="Cancel Order", cancel_text="Keep Order")
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



