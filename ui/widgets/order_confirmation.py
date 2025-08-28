from textual.screen import ModalScreen
from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.align import Align


class OrderConfirmationScreen(ModalScreen):
    """A modal screen for order confirmation."""

    def __init__(self, order_details, confirm_text="Confirm Order", cancel_text="Cancel"):
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

        # Extract underlying asset if it's an option symbol
        asset = self.order_details.get('Asset', '')
        if 'C' in asset or 'P' in asset:  # Likely an option symbol
            # Extract underlying (e.g., 'SPXW' from 'SPXW  251003C06450000')
            asset = asset.split()[0] if asset else asset

        # Title and asset/type
        if self.order_details.get("Type", "").startswith("Box Spread"):
            title = Text("ORDER CONFIRMATION", style="bold white", justify="center")
            asset_type = Text(
                self.order_details.get("Type", "Box Spread"),
                style="bold yellow",
                justify="center"
            )
        elif "Roll Up Amount" in self.order_details:
            title = Text("ORDER CONFIRMATION", style="bold white", justify="center")
            asset_type = Text(
                f"Rolling Short Calls: {asset}",
                style="bold yellow",
                justify="center"
            )
        else:
            title = Text("ORDER CONFIRMATION", style="bold white", justify="center")
            asset_type = Text(
                f"{self.order_details.get('Type', '')}: {asset}",
                style="bold yellow",
                justify="center"
            )

        # Contract Details Section
        contract_table = Table.grid(padding=(0, 2), expand=True)
        # Expiration: show current → new with arrow if new is present
        current_exp = self.order_details.get("Current Expiration", self.order_details.get("Expiration", ""))
        new_exp = self.order_details.get("New Expiration", "")
        if new_exp:
            expiration_display = f"{current_exp} → {new_exp}"
        else:
            expiration_display = str(current_exp)
        contract_table.add_row(
            Text("Expiration", style="cyan"),
            Text(":", style="white"),
            Text(expiration_display, style="white", justify="left")
        )
        # Strike: show as "Strike" and use arrow if both old and new are present
        strike_low = self.order_details.get('Strike Low', self.order_details.get('Current Strike', ''))
        strike_high = self.order_details.get('Strike High', self.order_details.get('New Strike', ''))
        contract_table.add_row(
            Text("Strike", style="cyan"),
            Text(":", style="white"),
            Text(f"{strike_low} → {strike_high}", style="white", justify="left")
        )
        # For roll short options, show Roll Up and Roll Out if present
        if "Roll Up Amount" in self.order_details:
            # Show Credit Received
            contract_table.add_row(
                Text("Credit Received", style="cyan"),
                Text(":", style="white"),
                Text(f"{self.order_details.get('Credit', '')}", style="bold green", justify="left")
            )
            contract_table.add_row(
                Text("Roll Up (Amount)", style="cyan"),
                Text(":", style="white"),
                Text(f"{self.order_details.get('Roll Up Amount', '')}", style="white", justify="left")
            )
        if "Roll Out (Days)" in self.order_details:
            contract_table.add_row(
                Text("Roll Out (Days)", style="cyan"),
                Text(":", style="white"),
                Text(f"{self.order_details.get('Roll Out (Days)', '')}", style="white", justify="left")
            )
        # Only show Spread Width if not a roll
        if "Roll Up Amount" not in self.order_details and "Roll Out (Days)" not in self.order_details:
            contract_table.add_row(
                Text("Spread Width", style="cyan"),
                Text(":", style="white"),
                Text(str(parse_float(strike_high) - parse_float(strike_low)), style="white", justify="left")
            )

        # Investment & Returns Section
        investment_table = Table.grid(padding=(0, 2), expand=True)
        # Handle box spreads differently
        if self.order_details.get("Type", "").startswith("Box Spread"):
            upfront_amount = parse_float(self.order_details.get('Upfront Amount', 0))
            face_value = parse_float(self.order_details.get('Face Value', 0))

            investment_table.add_row(
                Text("Upfront Amount", style="cyan"),
                Text(":", style="white"),
                Text(f"$ {upfront_amount:.2f}", style="white", justify="right")
            )
            investment_table.add_row(
                Text("Face Value", style="cyan"),
                Text(":", style="white"),
                Text(f"$ {face_value:.2f}", style="white", justify="right")
            )
            # Show both annualized returns if available
            mid_ann_return = self.order_details.get('Annualized Return (Mid)', 0)
            nat_ann_return = self.order_details.get('Annualized Return (Nat)', 0)
            if mid_ann_return and nat_ann_return and (mid_ann_return != nat_ann_return):
                investment_table.add_row(
                    Text("Annualized Return (Mid)", style="cyan"),
                    Text(":", style="white"),
                    Text(f"{parse_float(mid_ann_return):.2f}%", style="bold green", justify="right")
                )
                investment_table.add_row(
                    Text("Annualized Return (Nat)", style="cyan"),
                    Text(":", style="white"),
                    Text(f"{parse_float(nat_ann_return):.2f}%", style="bold green", justify="right")
                )
            else:
                # Fallback to single annualized return
                ann_return = self.order_details.get('Annualized Return', self.order_details.get('ann_rom', 0))
                investment_table.add_row(
                    Text("Annualized Return", style="cyan"),
                    Text(":", style="white"),
                    Text(f"{parse_float(ann_return):.2f}%", style="bold green", justify="right")
                )
        else:
            investment_table.add_row(
                Text("Investment", style="cyan"),
                Text(":", style="white"),
                Text(f"$ {parse_float(self.order_details.get('Investment', 0)):.2f}", style="white", justify="right")
            )
            # Optional: show per-contract Price when provided
            if self.order_details.get('Price') is not None:
                investment_table.add_row(
                    Text("Price", style="cyan"),
                    Text(":", style="white"),
                    Text(f"$ {parse_float(self.order_details.get('Price', 0)):.2f}", style="white", justify="right")
                )
            investment_table.add_row(
                Text("Max Profit", style="cyan"),
                Text(":", style="white"),
                Text(f"$ {parse_float(self.order_details.get('Max Profit', 0)):.2f}", style="bold green", justify="right")
            )
            investment_table.add_row(
                Text("Annualized Return", style="cyan"),
                Text(":", style="white"),
                Text(f"{parse_float(self.order_details.get('Annualized Return', self.order_details.get('ann_rom', 0))):.2f}%", style="bold green", justify="right")
            )
            # Only show CAGR for non-box spreads
            if not self.order_details.get("Type", "").startswith("Box Spread"):
                investment_table.add_row(
                    Text("CAGR", style="cyan"),
                    Text(":", style="white"),
                    Text(f"{parse_float(self.order_details.get('CAGR', 0)):.2f}%", style="white", justify="right")
                )

        # Risk & Margin Section (only for non-box spreads)
        risk_section = None
        if not self.order_details.get("Type", "").startswith("Box Spread"):
            risk_table = Table.grid(padding=(0, 2), expand=True)
            # Only show Downside Protection for non-box spreads
            if not self.order_details.get("Type", "").startswith("Box Spread"):
                risk_table.add_row(
                    Text("Downside Protection", style="cyan"),
                    Text(":", style="white"),
                    Text(f"{parse_float(self.order_details.get('Protection', 0)):.2f}%", style="white", justify="right")
                )
            risk_table.add_row(
                Text("Margin Requirement", style="cyan"),
                Text(":", style="white"),
                Text(f"$ {parse_float(self.order_details.get('Margin Req', 0)):.2f}", style="white", justify="right")
            )
            risk_section = risk_table

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

        # Contract Details
        panel_content.add_row(Text("Contract Details", style="bold underline"))
        panel_content.add_row(contract_table)

        # Only add Investment & Returns and Risk & Margin for non-roll shorts
        if "Roll Up Amount" not in self.order_details:
            # Investment & Returns
            panel_content.add_row(Text("Investment & Returns", style="bold underline"))
            panel_content.add_row(investment_table)

            # Risk & Margin (only for non-box spreads)
            if risk_section:
                panel_content.add_row(Text("Risk & Margin", style="bold underline"))
                panel_content.add_row(risk_section)

        # Instructions
        panel_content.add_row("")  # Spacer
        panel_content.add_row(Align.center(instructions))
        panel_content.add_row("─" * 50)

        panel = Panel.fit(
            panel_content,
            title="Order Confirmation",
            border_style="bold blue"
        )

        yield Static(panel, id="order-confirmation-modal")

    def on_key(self, event):
        if self._loading:
            event.prevent_default()
            return
        if event.key in ("enter", "y"):
            self._loading = True
            self.refresh()
            self.confirm_order()
        elif event.key in ("escape", "n"):
            self.dismiss(False)

    def confirm_order(self):
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
