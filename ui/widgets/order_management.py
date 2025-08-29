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
from configuration import debugCanSendOrders, stream_quotes
from ..quote_provider import StreamingQuoteProvider


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
        self._quote_provider: StreamingQuoteProvider | None = None
        self._prev_midnat = {}  # orderId -> (mid, nat)

    def compose(self):
        """Create child widgets."""
        with Vertical():
            streaming_hint = "Streaming: ON" if stream_quotes else "Streaming: OFF"
            yield Static(Text(f"Hints: U = Update Price, C = Cancel  |  {streaming_hint}", style="bold yellow"))
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
        # Initialize streaming quotes if enabled
        if stream_quotes:
            try:
                self._quote_provider = StreamingQuoteProvider(self.app.api.connectClient)
                asyncio.create_task(self._quote_provider.start())
                self.set_interval(1, self.refresh_working_quotes)
            except Exception as e:
                self.app.query_one(StatusLog).add_message(f"Streaming init error: {e}")

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

            # Use Schwab edit/replace when available
            new_order_id = await asyncio.to_thread(self.app.api.editOrderPrice, order_id, new_price)

            if new_order_id:
                # Carry over base and step to new order id
                self._base_price[new_order_id] = base
                self._manual_steps[new_order_id] = step
                # Cleanup old mapping
                self._base_price.pop(order_id, None)
                self._manual_steps.pop(order_id, None)
                self.app.query_one(StatusLog).add_message(f"Replaced order {order_id} at ${new_price:.2f} → {new_order_id}.")
                self.run_get_orders_data()
            else:
                self.app.query_one(StatusLog).add_message("Failed to replace/edit order.")
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
            if status in ("ACCEPTED", "WORKING", "PENDING_ACTIVATION"):
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
                    return (None, None)
                client = self.app.api.connectClient
                cost_mid = proceeds_mid = cost_nat = proceeds_nat = 0.0
                for leg in legs:
                    instr = leg.get("instrument", {})
                    symbol = instr.get("symbol")
                    instruction = leg.get("instruction", "BUY_TO_OPEN").upper()
                    if not symbol:
                        continue
                    bid = ask = None
                    # Prefer streaming cache if available
                    if self._quote_provider:
                        bid, ask = self._quote_provider.get_bid_ask(symbol)
                    if bid is None or ask is None:
                        # Fallback to REST quote
                        r = await asyncio.to_thread(client.get_quotes, symbol)
                        if r.status_code != 200 and r.status_code != 201:
                            continue
                        q = r.json()
                        qd = q.get(symbol, {}).get("quote", {})
                        bid = bid if bid is not None else qd.get("bidPrice")
                        ask = ask if ask is not None else qd.get("askPrice")
                    bid = float(bid) if bid is not None else None
                    ask = float(ask) if ask is not None else None
                    if bid is not None and ask is not None:
                        mid = (bid + ask) / 2
                    elif bid is not None:
                        mid = bid
                    elif ask is not None:
                        mid = ask
                    else:
                        mid = 0.0
                    if instruction.startswith("BUY"):
                        cost_mid += mid
                        # Natural for BUY is ask if available else use mid (or bid)
                        cost_nat += (ask if ask is not None else (mid if mid else 0.0))
                    else:
                        proceeds_mid += mid
                        # Natural for SELL is bid if available else use mid (or ask)
                        proceeds_nat += (bid if bid is not None else (mid if mid else 0.0))
                if order_type == "NET_DEBIT":
                    net_mid = cost_mid - proceeds_mid
                    net_nat = cost_nat - proceeds_nat
                else:
                    net_mid = proceeds_mid - cost_mid
                    net_nat = proceeds_nat - cost_nat
                return (net_mid, net_nat)
            except Exception:
                return (None, None)

        if not self._initialized:
            # Build full table once
            table.clear()
            table.add_row(Text("WORKING ORDERS", style="bold white on dark_blue"), *[Text("") for _ in range(8)])
            self._row_positions["working_header"] = 0
            self._row_positions["working_rows"] = []
            # Add working rows
            all_symbols = []
            for order, formatted in working:
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                status_color = "cyan" if formatted["status"] == "WORKING" else ""
                mid_val, nat_val = await compute_mid_nat(order)
                mid_str = f"{mid_val:.2f}" if mid_val is not None else ""
                nat_str = f"{nat_val:.2f}" if nat_val is not None else ""
                # Style mid/nat vs previous
                oid = order.get("orderId")
                prev = self._prev_midnat.get(oid, (None, None))
                is_debit = order.get("orderType") == "NET_DEBIT"
                def style_change(curr, prev_val):
                    if curr is None or prev_val is None:
                        return ""
                    if is_debit:
                        return ("bold green" if curr < prev_val else "bold red" if curr > prev_val else "")
                    else:
                        return ("bold green" if curr > prev_val else "bold red" if curr < prev_val else "")
                mid_style = style_change(mid_val, prev[0])
                nat_style = style_change(nat_val, prev[1])
                row_key = table.add_row(
                    Text(str(formatted["order_id"])),
                    Text(str(formatted["status"]), style=status_color),
                    Text(str(formatted["entered_time"])),
                    Text(str(formatted["asset"])),
                    Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")),
                    Text(str(formatted["quantity"]), justify="right"),
                    Text(price, justify="right"),
                    Text(mid_str, style=mid_style, justify="right"),
                    Text(nat_str, style=nat_style, justify="right"),
                )
                self._row_positions["working_rows"].append(row_key)
                if mid_val is not None and nat_val is not None and oid is not None:
                    self._prev_midnat[oid] = (mid_val, nat_val)
                # Collect symbols for streaming subs
                for leg in order.get("orderLegCollection", [])[:]:
                    sym = leg.get("instrument", {}).get("symbol")
                    if sym:
                        all_symbols.append(sym)
            # Subscribe to option symbols via streaming
            if stream_quotes and self._quote_provider:
                try:
                    await self._quote_provider.subscribe_options(all_symbols)
                except Exception as e:
                    self.app.query_one(StatusLog).add_message(f"Streaming subscribe error: {e}")
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
            all_symbols = []
            for idx, (order, formatted) in enumerate(working):
                row_key = self._row_positions["working_rows"][idx]
                order_type = formatted["order_type"]
                price = formatted["price"]
                try:
                    price = f"{float(price):.2f}"
                except (ValueError, TypeError):
                    price = str(price)
                status = formatted["status"]
                status_color = "cyan" if status == "WORKING" else ("yellow" if status == "PENDING_ACTIVATION" else "")
                mid_val, nat_val = await compute_mid_nat(order)
                mid_str = f"{mid_val:.2f}" if mid_val is not None else ""
                nat_str = f"{nat_val:.2f}" if nat_val is not None else ""
                oid = order.get("orderId")
                prev = self._prev_midnat.get(oid, (None, None))
                is_debit = order.get("orderType") == "NET_DEBIT"
                def style_change(curr, prev_val):
                    if curr is None or prev_val is None:
                        return ""
                    if is_debit:
                        return ("bold green" if curr < prev_val else "bold red" if curr > prev_val else "")
                    else:
                        return ("bold green" if curr > prev_val else "bold red" if curr < prev_val else "")
                mid_style = style_change(mid_val, prev[0])
                nat_style = style_change(nat_val, prev[1])
                # Update columns 0..8
                ck = self._col_keys
                table.update_cell(row_key, ck[0], Text(str(formatted["order_id"])))
                table.update_cell(row_key, ck[1], Text(str(status), style=status_color))
                table.update_cell(row_key, ck[2], Text(str(formatted["entered_time"])))
                table.update_cell(row_key, ck[3], Text(str(formatted["asset"])))
                table.update_cell(row_key, ck[4], Text(str(order_type), style=("red" if "SELL" in order_type.upper() else "green" if "BUY" in order_type.upper() else "")))
                table.update_cell(row_key, ck[5], Text(str(formatted["quantity"]), justify="right"))
                table.update_cell(row_key, ck[6], Text(price, justify="right"))
                table.update_cell(row_key, ck[7], Text(mid_str, style=mid_style, justify="right"))
                table.update_cell(row_key, ck[8], Text(nat_str, style=nat_style, justify="right"))
                if mid_val is not None and nat_val is not None and oid is not None:
                    self._prev_midnat[oid] = (mid_val, nat_val)
                for leg in order.get("orderLegCollection", [])[:]:
                    sym = leg.get("instrument", {}).get("symbol")
                    if sym:
                        all_symbols.append(sym)
            if stream_quotes and self._quote_provider:
                try:
                    await self._quote_provider.subscribe_options(all_symbols)
                except Exception as e:
                    self.app.query_one(StatusLog).add_message(f"Streaming subscribe error: {e}")
            return

        # Fallback: layout changed (orders added/removed) - rebuild once (might flicker briefly)
        self._initialized = False
        self.run_get_orders_data()

    def refresh_working_quotes(self) -> None:
        """Update Mid/Nat for working rows from streaming cache without rebuilding the table."""
        if not stream_quotes or not self._quote_provider:
            return
        try:
            table = self.query_one(DataTable)
            if not self._initialized:
                return
            if not self._working_orders or not self._row_positions["working_rows"]:
                return
            if len(self._working_orders) != len(self._row_positions["working_rows"]):
                return  # layout changed; next run_get_orders_data will rebuild

            def mid_nat_from_cache(order) -> tuple[float | None, float | None]:
                legs = order.get("orderLegCollection", [])
                cost_mid = proceeds_mid = cost_nat = proceeds_nat = 0.0
                for leg in legs:
                    instr = leg.get("instrument", {})
                    symbol = instr.get("symbol")
                    if not symbol:
                        continue
                    bid, ask = self._quote_provider.get_bid_ask(symbol)
                    # Build mid even if one side missing
                    if bid is not None and ask is not None:
                        mid = (bid + ask) / 2
                    elif bid is not None:
                        mid = bid
                    elif ask is not None:
                        mid = ask
                    else:
                        mid = 0.0
                    if leg.get("instruction", "").upper().startswith("BUY"):
                        cost_mid += mid
                        cost_nat += (ask if ask is not None else (mid if mid else 0.0))
                    else:
                        proceeds_mid += mid
                        proceeds_nat += (bid if bid is not None else (mid if mid else 0.0))
                if order.get("orderType") == "NET_DEBIT":
                    net_mid = cost_mid - proceeds_mid
                    net_nat = cost_nat - proceeds_nat
                else:
                    net_mid = proceeds_mid - cost_mid
                    net_nat = proceeds_nat - cost_nat
                return (net_mid, net_nat)

            ck = self._col_keys
            for idx, order in enumerate(self._working_orders):
                row_key = self._row_positions["working_rows"][idx]
                mid_val, nat_val = mid_nat_from_cache(order)
                if mid_val is None or nat_val is None:
                    continue
                mid_str = f"{mid_val:.2f}"
                nat_str = f"{nat_val:.2f}"
                oid = order.get("orderId")
                prev = self._prev_midnat.get(oid, (None, None))
                is_debit = order.get("orderType") == "NET_DEBIT"
                def style_change(curr, prev_val):
                    if curr is None or prev_val is None:
                        return ""
                    if is_debit:
                        return ("bold green" if curr < prev_val else "bold red" if curr > prev_val else "")
                    else:
                        return ("bold green" if curr > prev_val else "bold red" if curr < prev_val else "")
                mid_style = style_change(mid_val, prev[0])
                nat_style = style_change(nat_val, prev[1])
                table.update_cell(row_key, ck[7], Text(mid_str, style=mid_style, justify="right"))
                table.update_cell(row_key, ck[8], Text(nat_str, style=nat_style, justify="right"))
                if oid is not None:
                    self._prev_midnat[oid] = (mid_val, nat_val)
        except Exception:
            # Non-fatal; next tick will try again
            pass

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



