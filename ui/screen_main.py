from textual.app import App
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Header, Footer, Static, DataTable, LoadingIndicator
from textual.reactive import reactive
from textual.screen import Screen
from textual.message import Message
import sys
import os
import sys
import os
import datetime
import traceback
from logger_config import get_logger

# Add parent directory to path for importing main functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import UI utilities
from ui.ui_utils import (
    process_box_spreads_data,
    process_vertical_spreads_data,
    process_margin_requirements_data,
    process_orders_data
)

logger = get_logger()


class ButtonClicked(Message):
    """Custom message for button clicks"""

    def __init__(self, option_id):
        super().__init__()
        self.option_id = option_id


class ClickableButton(Button):
    """Custom button class to ensure click handling works"""

    def __init__(self, label, option_id, *args, **kwargs):
        super().__init__(label, *args, **kwargs)
        self.option_id = option_id

    def on_click(self, event):
        """Handle button clicks directly"""
        # Post a custom message to the parent screen
        self.post_message(ButtonClicked(self.option_id))


class MainMenuScreen(Screen):
    """Main menu screen for options trading application"""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "roll_short", "Roll Short Options"),
        ("2", "box_spreads", "Check Box Spreads"),
        ("3", "vertical_spreads", "Check Vertical Spreads"),
        ("4", "synthetic_calls", "Check Synthetic Covered Calls"),
        ("5", "margin_requirements", "View Margin Requirements"),
        ("6", "view_orders", "View/Cancel Orders"),
        ("enter", "place_order", "Place Order"),
        ("space", "place_order", "Place Order (Space)"),  # Alternative key for testing
        ("t", "place_order", "Place Order (Test)"),  # Test key
        ("escape", "cancel_action", "Cancel"),
    ]

    selected_option = reactive("1")
    market_status = reactive("")
    is_loading = reactive(False)

    def __init__(self, api, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = api
        self.shorts = []
        self.exec_window = {}
        # Store previous data for color comparison
        self.previous_data = {}
        # Store current spreads data for order placement
        self.current_spreads_data = []
        self.current_screen_type = None
        # Initialize pending order to None
        self.pending_order = None
        print("DEBUG: MainMenuScreen initialized, pending_order set to None")

    def compose(self):
        """Create the UI layout"""
        yield Header(show_clock=True)

        with Vertical(id="main-container"):
            # Market status and current screen
            yield Static(self.market_status, id="market-status")
            yield Static("Welcome - Select an option from the footer", id="current-screen")

            # Content section - minimal spacing
            yield LoadingIndicator(id="loading")
            yield Static("Select an option to begin", id="content-display")
            yield DataTable(id="results-table")

        yield Footer()

    def on_button_clicked(self, message: ButtonClicked):
        """Handle custom button clicked messages"""
        option_id = message.option_id

        # Debug: Show that button was pressed
        content = self.query_one("#content-display")
        content.update(f"Custom button {option_id} clicked!")

        if option_id == "0":
            content.update("Exiting application...")
            self.app.exit()
        else:
            content.update(f"Processing option {option_id}...")
            self.handle_option_sync(option_id)

    def on_mount(self):
        """Initialize the screen when mounted"""
        self.query_one("#loading").display = False
        self.query_one("#results-table").display = False
        self.update_market_status()
        self.query_one("#content-display").update("Welcome! Use the footer keys to navigate:\n1-4: Trading Options  |  5: Margin Requirements  |  Q: Quit\n\nFor spreads: Use ↑↓ arrows to select, SPACE/ENTER to place order")

        # Set up automatic market status updates every 30 seconds
        self.set_interval(30, self.update_market_status)

        # Debug: Print when screen is mounted
        print("DEBUG: MainMenuScreen mounted")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        """Handle when a table row is highlighted/selected"""
        if self.current_screen_type in ["spreads", "synthetic", "roll_short", "box_spreads"] and self.current_spreads_data:
            try:
                row_key = event.row_key.value if hasattr(event.row_key, 'value') else event.row_key
                if 0 <= row_key < len(self.current_spreads_data):
                    selected_row = self.current_spreads_data[row_key]
                    asset = selected_row.get('asset', 'Unknown')

                    # Update current screen to show selected row info
                    current_screen = self.query_one("#current-screen")
                    if self.current_screen_type == "roll_short":
                        credit = selected_row.get('credit', 0)
                        current_screen.update(f"Roll Short Options - Selected: {asset} (Credit: ${credit})")
                    elif self.current_screen_type == "box_spreads":
                        direction = selected_row.get('Direction', 'Unknown')
                        rom = selected_row.get('Ann ROM %', '0%')
                        current_screen.update(f"Check Box Spreads - Selected: {asset} {direction} (ROM: {rom})")
                    elif self.current_screen_type == "spreads":
                        rom = selected_row.get('ann_rom', '0%')
                        current_screen.update(f"Vertical Spreads - Selected: {asset} (ROM: {rom})")
                    elif self.current_screen_type == "synthetic":
                        rom = selected_row.get('ann_rom', '0%')
                        current_screen.update(f"Synthetic Covered Calls - Selected: {asset} (ROM: {rom})")
            except Exception:
                pass  # Ignore errors during row highlighting

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """Handle when a table row is selected (Enter key pressed)"""
        print(f"DEBUG: Row selected event - row {event.row_key}")
        self.action_place_order()

    def on_key(self, event):
        """Handle key presses for debugging"""
        # Just log the key press - let BINDINGS handle the action
        if event.key in ["enter", "return", "\n", "\r", "space", "t"]:
            pass

        # Don't handle the key here - let the BINDINGS system handle it
        return False

    def on_click(self, event):
        """Handle all click events for debugging"""
        # Try to find which button was clicked by checking coordinates
        buttons = self.query("Button")
        clicked_button = None

        for button in buttons:
            # Get button's screen coordinates
            try:
                button_region = button.region
                if (button_region.x <= event.x <= button_region.x + button_region.width and
                    button_region.y <= event.y <= button_region.y + button_region.height):
                    clicked_button = button
                    break
            except Exception:
                continue

        if clicked_button:
            button_id = clicked_button.id

            # Handle the button click manually
            if button_id == "option-0":
                self.query_one("#content-display").update("Exiting application...")
                self.app.exit()
            elif button_id in ["option-1", "option-2", "option-3", "option-4", "option-5"]:
                option_num = button_id.split("-")[1]
                self.handle_option_sync(option_num)

        # Let the event propagate
        return False

    def update_market_status(self):
        """Update market status display"""
        try:
            self.exec_window = self.api.getOptionExecutionWindow()
            if self.exec_window.get("open", False):
                self.market_status = "[green]Market is OPEN[/green]"
            else:
                self.market_status = "[red]Market is CLOSED[/red]"
        except Exception as e:
            self.market_status = f"[yellow]Status unknown: {str(e)}[/yellow]"

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button press events"""
        button_id = event.button.id

        # Handle button press
        try:
            content = self.query_one("#content-display")

            if button_id == "option-0":
                content.update("Exiting application...")
                self.app.exit()
            elif button_id in ["option-1", "option-2", "option-3", "option-4", "option-5"]:
                option_num = button_id.split("-")[1]
                # Call immediately without delay
                self.handle_option_sync(option_num)
            else:
                content.update(f"Unknown button: {button_id}")

        except Exception as e:
            # If we can't update the display, at least print to console
            print(f"Button press error: {e}")

    def _show_immediate_loading_table(self, option):
        """Show an empty table immediately with appropriate columns for the screen type"""
        # Hide content display immediately
        content = self.query_one("#content-display")
        content.display = False

        # Show table immediately with loading row
        table = self.query_one("#results-table")
        table.display = True
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.can_focus = True
        table.show_cursor = True
        table.clear(columns=True)

        # Set up columns based on screen type
        if option == "1":  # Roll Short Options
            columns = ['asset', 'cur_strike', 'cur_exp', 'roll_strike', 'roll_exp', 'credit', 'ann_rom', 'status']
            self.current_screen_type = "roll_short"
        elif option == "2":  # Box Spreads
            columns = ['asset', 'Date', 'Direction', 'Low Strike', 'High Strike', 'Net Price', 'Investment', 'Borrowed', 'Repayment', 'CAGR', 'Margin Req', 'Ann ROM %']
            self.current_screen_type = "box_spreads"
        elif option == "3":  # Vertical Spreads
            columns = ['asset', 'expiration', 'strike_low', 'strike_high', 'investment', 'max_profit', 'ann_rom']
            self.current_screen_type = "spreads"
        elif option == "4":  # Synthetic Calls
            columns = ['asset', 'expiration', 'strike_low', 'strike_high', 'investment', 'max_profit', 'ann_rom']
            self.current_screen_type = "synthetic"
        elif option == "5":  # Margin Requirements
            columns = ['symbol', 'position_type', 'quantity', 'margin_req', 'current_value']
            self.current_screen_type = "margin"
        elif option == "6":  # Orders
            columns = ['order_id', 'symbol', 'status', 'order_type', 'quantity']
            self.current_screen_type = "orders"
        else:
            columns = ['status']

        table.add_columns(*columns)

        # Add a loading row immediately
        loading_row = ['Loading...' if i == 0 else '' for i in range(len(columns))]
        table.add_row(*loading_row)

        # Focus the table
        table.focus()

        # Clear current spreads data
        self.current_spreads_data = []

    def show_spreads_table(self, spreads_data, screen_type="spreads"):
        """Show spreads table in the main menu DataTable widget (in-place update)"""
        try:
            # Store data for order placement
            self.current_spreads_data = spreads_data
            self.current_screen_type = screen_type

            # Hide content display when showing table
            content = self.query_one("#content-display")
            content.display = False

            table = self.query_one("#results-table")
            table.display = True
            table.cursor_type = "row"
            table.zebra_stripes = True
            table.can_focus = True
            table.show_cursor = True

            # Clear existing data but keep columns if they match
            try:
                current_columns = [col.label if hasattr(col, 'label') else str(col) for col in table.columns] if table.columns else []
            except AttributeError:
                current_columns = []

            new_columns = list(spreads_data[0].keys()) if spreads_data else []

            if current_columns != new_columns:
                table.clear(columns=True)
                if spreads_data and new_columns:
                    table.add_columns(*new_columns)
            else:
                # Just clear rows, keep columns
                table.clear()

            if not spreads_data:
                # Show "No data found" message
                if new_columns:
                    no_data_row = ['No data found' if i == 0 else '' for i in range(len(new_columns))]
                    table.add_row(*no_data_row)
                else:
                    # No columns at all, create a basic one
                    table.add_columns("Status")
                    table.add_row("No data found")
                return

            # Add rows with color formatting (existing color logic)
            for row_idx, row in enumerate(spreads_data):
                formatted_row = []
                row_key = row.get('asset', row_idx)

                for col in new_columns:
                    value = str(row.get(col, ''))

                    # Get previous value for comparison
                    prev_value = None
                    if row_key in self.previous_data and col in self.previous_data[row_key]:
                        prev_value = self.previous_data[row_key][col]

                    # Store current value for next comparison
                    if row_key not in self.previous_data:
                        self.previous_data[row_key] = {}
                    self.previous_data[row_key][col] = value

                    # Apply colors based on column type and value changes
                    if col.lower() in ['cagr', 'cagr_percentage', 'ann_rom', 'ann. rom %', '% cagr']:
                        # Green for positive percentages, red for negative, plus change indicators
                        if '%' in value:
                            try:
                                num_val = float(value.replace('%', ''))
                                prev_num = None
                                if prev_value and '%' in prev_value:
                                    prev_num = float(prev_value.replace('%', ''))

                                # Determine color based on value and change
                                if prev_num is not None:
                                    if num_val > prev_num:
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"
                                    elif num_val < prev_num:
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"
                                    else:
                                        value = f"[yellow]→ {value}[/yellow]"
                                else:
                                    if num_val > 0:
                                        value = f"[green]  {value}[/green]"
                                    elif num_val < 0:
                                        value = f"[bright_red]  {value}[/bright_red]"
                                    else:
                                        value = f"  {value}"
                            except ValueError:
                                pass

                    elif col.lower() in ['strike_low', 'strike_high', 'strike1', 'strike2', 'low strike', 'high strike', 'cur_strike', 'roll_strike', 'strike']:
                        # Color strikes based on changes
                        try:
                            num_val = float(value)
                            prev_num = None
                            if prev_value:
                                prev_num = float(prev_value)

                            if prev_num is not None:
                                if num_val > prev_num:
                                    value = f"[bold bright_green]↗ {value}[/bold bright_green]"
                                elif num_val < prev_num:
                                    value = f"[bold bright_red]↘ {value}[/bold bright_red]"
                                else:
                                    value = f"[bold cyan]→ {value}[/bold cyan]"  # No change, but bold
                            else:
                                value = f"[bold cyan]  {value}[/bold cyan]"  # First time with space reservation
                        except ValueError:
                            value = f"[bold]  {value}[/bold]"

                    elif col.lower() in ['call_low_ba', 'call_high_ba', 'call low b/a', 'call high b/a']:
                        # Color bid/ask spreads based on changes - separate arrows for bid and ask with perfect alignment
                        if prev_value and prev_value != value:
                            try:
                                if '/' in value and '/' in prev_value:
                                    curr_parts = value.split('/')
                                    prev_parts = prev_value.split('/')
                                    if len(curr_parts) == 2 and len(prev_parts) == 2:
                                        curr_bid, curr_ask = float(curr_parts[0]), float(curr_parts[1])
                                        prev_bid, prev_ask = float(prev_parts[0]), float(prev_parts[1])

                                        # Initialize color variables with defaults
                                        bid_color = "white"
                                        ask_color = "white"
                                        bid_arrow = " "
                                        ask_arrow = " "

                                        # Create arrows for bid and ask separately
                                        if curr_bid > prev_bid:
                                            bid_arrow = "↗"
                                            bid_color = "bright_green"
                                        elif curr_bid < prev_bid:
                                            bid_arrow = "↘"
                                            bid_color = "bright_red"

                                        if curr_ask > prev_ask:
                                            ask_arrow = "↗"
                                            ask_color = "bright_green"
                                        elif curr_ask < prev_ask:
                                            ask_arrow = "↘"
                                            ask_color = "bright_red"

                                        # Format with perfect alignment: bid right-aligned, ask left-aligned, centered separator
                                        bid_with_arrow = f"{bid_arrow} {curr_parts[0]}" if bid_arrow.strip() else f"  {curr_parts[0]}"
                                        ask_with_arrow = f"{ask_arrow} {curr_parts[1]}" if ask_arrow.strip() else f"  {curr_parts[1]}"

                                        value = f"[{bid_color}]{bid_with_arrow:>9}[/{bid_color}][dim white] | [/dim white][{ask_color}]{ask_with_arrow:<9}[/{ask_color}]"
                            except (ValueError, IndexError):
                                # Fallback with proper alignment
                                if '/' in value:
                                    parts = value.split('/')
                                    if len(parts) == 2:
                                        value = f"  {parts[0]:>6} | {parts[1]:<6}  "
                                    else:
                                        value = f"      {value}      "
                                else:
                                    value = f"      {value}      "
                        else:
                            # First time - format with proper alignment and reserved space for arrows
                            if '/' in value:
                                parts = value.split('/')
                                if len(parts) == 2:
                                    # Reserve space for arrow with proper formatting
                                    value = f"[white] {parts[0]:>7}[/white][dim white] | [/dim white][white]{parts[1]:<7} [/white]"
                                else:
                                    value = f"      {value}      "
                            else:
                                value = f"      {value}      "

                    elif col.lower() in ['protection', 'downside_protection']:
                        # Color protection percentages based on changes
                        if '%' in value:
                            try:
                                num_val = float(value.replace('%', ''))
                                prev_num = None
                                if prev_value and '%' in prev_value:
                                    prev_num = float(prev_value.replace('%', ''))

                                if prev_num is not None:
                                    if num_val > prev_num:
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"  # More protection = better
                                    elif num_val < prev_num:
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"      # Less protection = worse
                                    else:
                                        value = f"[yellow]→ {value}[/yellow]"
                                else:
                                    # Color based on protection level - reserve space for arrow
                                    if num_val > 10:  # Good protection
                                        value = f"[green]  {value}[/green]"
                                    elif num_val > 5:  # Moderate protection
                                        value = f"[yellow]  {value}[/yellow]"
                                    else:  # Low protection
                                        value = f"[bright_red]  {value}[/bright_red]"
                            except ValueError:
                                pass

                    elif col.lower() in ['credit', 'net_debit', 'net price', 'margin']:
                        # Green for positive credits/returns, red for negative
                        try:
                            # Handle margin amounts with commas
                            clean_value = value.replace(',', '').replace('$', '')
                            num_val = float(clean_value)
                            prev_num = None
                            if prev_value:
                                clean_prev = prev_value.replace(',', '').replace('$', '')
                                prev_num = float(clean_prev)

                            if prev_num is not None:
                                if num_val > prev_num:
                                    if col.lower() == 'credit':
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"  # More credit = better
                                    elif col.lower() == 'margin':
                                        value = f"[bold bright_red]↗ {value}[/bold bright_red]"    # More margin = worse
                                    elif col.lower() == 'net price':
                                        # For box spreads: positive net price means we pay (debit), negative means we receive (credit)
                                        value = f"[bold bright_red]↗ {value}[/bold bright_red]"    # Higher net price = more we pay
                                    else:
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"
                                elif num_val < prev_num:
                                    if col.lower() == 'credit':
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"     # Less credit = worse
                                    elif col.lower() == 'margin':
                                        value = f"[bold bright_green]↘ {value}[/bold bright_green]" # Less margin = better
                                    elif col.lower() == 'net price':
                                        value = f"[bold bright_green]↘ {value}[/bold bright_green]" # Lower net price = less we pay
                                    else:
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"
                                else:
                                    value = f"[yellow]→ {value}[/yellow]"
                            else:
                                # First time display with space reservation and proper coloring
                                if col.lower() == 'net price':
                                    # For box spreads: show net price with context
                                    if num_val > 0:
                                        value = f"[bright_red]  {value}[/bright_red]"  # We pay (debit)
                                    elif num_val < 0:
                                        value = f"[green]  {value}[/green]"  # We receive (credit)
                                    else:
                                        value = f"  {value}"
                                else:
                                    if num_val > 0:
                                        value = f"[green]  {value}[/green]"
                                    elif num_val < 0:
                                        value = f"[bright_red]  {value}[/bright_red]"
                                    else:
                                        value = f"  {value}"
                        except ValueError:
                            value = f"  {value}"
                    elif col.lower() in ['total_return', 'max_profit', 'borrowed', 'repayment', 'investment']:
                        # Handle box spread financial columns with proper context
                        try:
                            num_val = float(value)
                            prev_num = None
                            if prev_value:
                                prev_num = float(prev_value)

                            if prev_num is not None:
                                if num_val > prev_num:
                                    if col.lower() == 'borrowed':
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"  # More borrowed = more leverage
                                    elif col.lower() == 'repayment':
                                        value = f"[bold bright_red]↗ {value}[/bold bright_red]"     # More repayment = higher cost
                                    else:
                                        value = f"[bold bright_green]↗ {value}[/bold bright_green]"
                                elif num_val < prev_num:
                                    if col.lower() == 'borrowed':
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"     # Less borrowed = less leverage
                                    elif col.lower() == 'repayment':
                                        value = f"[bold bright_green]↘ {value}[/bold bright_green]" # Less repayment = lower cost
                                    else:
                                        value = f"[bold bright_red]↘ {value}[/bold bright_red]"
                                else:
                                    value = f"[yellow]→ {value}[/yellow]"
                            else:
                                # Color based on column meaning
                                if col.lower() == 'borrowed':
                                    value = f"[green]  ${num_val:,.2f}[/green]"  # Borrowed amount (what we get)
                                elif col.lower() == 'repayment':
                                    value = f"[cyan]  ${num_val:,.2f}[/cyan]"    # What we must pay back
                                elif col.lower() == 'investment':
                                    value = f"[yellow]  ${num_val:,.2f}[/yellow]" # Our investment
                                else:
                                    if num_val > 0:
                                        value = f"[green]  {value}[/green]"
                                    else:
                                        value = f"  {value}"
                        except ValueError:
                            value = f"  {value}"

                    elif col.lower() in ['count']:
                        # Color count changes
                        try:
                            num_val = int(value)
                            prev_num = None
                            if prev_value:
                                prev_num = int(prev_value)

                            if prev_num is not None:
                                if num_val > prev_num:
                                    value = f"[bold bright_green]↗ {value}[/bold bright_green]"
                                elif num_val < prev_num:
                                    value = f"[bold bright_red]↘ {value}[/bold bright_red]"
                                else:
                                    value = f"[yellow]→ {value}[/yellow]"
                            else:
                                value = f"[cyan]  {value}[/cyan]"
                        except ValueError:
                            value = f"  {value}"
                    elif col.lower() in ['direction', 'trade_direction']:
                        # Color code trading direction
                        if value.lower() == 'sell':
                            value = f"[yellow]{value}[/yellow]"
                        elif value.lower() == 'buy':
                            value = f"[cyan]{value}[/cyan]"
                    elif col.lower() in ['symbol', 'asset']:
                        # Make symbols stand out
                        value = f"[bold cyan]{value}[/bold cyan]"
                    elif col.lower() in ['cur_exp', 'roll_exp', 'expiry', 'expiration', 'date']:
                        # Color date columns with subtle coloring
                        value = f"[dim cyan]{value}[/dim cyan]"
                    elif col.lower() in ['type']:
                        # Color option types
                        if 'call' in value.lower():
                            value = f"[green]{value}[/green]"
                        elif 'put' in value.lower():
                            value = f"[bright_red]{value}[/bright_red]"
                        else:
                            value = f"[white]{value}[/white]"
                    elif col.lower() in ['refreshed']:
                        # Subtle coloring for refresh timestamps
                        value = f"[dim white]{value}[/dim white]"
                    elif col.lower() in ['status', 'error']:
                        # Color code status messages
                        if 'error' in value.lower():
                            value = f"[bright_red]{value}[/bright_red]"
                        elif 'no' in value.lower() and 'found' in value.lower():
                            value = f"[yellow]{value}[/yellow]"
                        else:
                            value = f"[cyan]{value}[/cyan]"

                    formatted_row.append(value)

                table.add_row(*formatted_row)

            # Focus the table so arrow keys work
            table.focus()

            # Update screen title to remove "Loading..."
            screen_names = {
                "roll_short": "Roll Short Options",
                "box_spreads": "Check Box Spreads",
                "spreads": "Check Vertical Spreads",
                "synthetic": "Synthetic Covered Calls",
                "margin": "View Margin Requirements",
                "orders": "View/Cancel Orders"
            }
            current_screen = self.query_one("#current-screen")
            current_screen.update(f"{screen_names.get(screen_type, 'Unknown')} - {len(spreads_data)} items")

        except Exception as e:
            print(f"DEBUG: Table error: {e}")
            import traceback
            traceback.print_exc()
            content = self.query_one("#content-display")
            content.display = True
            content.update(f"[red]Table error: {str(e)}[/red]")

    def handle_option_sync(self, option):
        import datetime
        try:
            # IMMEDIATE UI updates for instant responsiveness
            screen_names = {
                "1": "Roll Short Options",
                "2": "Check Box Spreads",
                "3": "Check Vertical Spreads",
                "4": "Synthetic Covered Calls",
                "5": "View Margin Requirements",
                "6": "View/Cancel Orders"
            }
            current_screen = self.query_one("#current-screen")
            current_screen.update(f"{screen_names.get(option, 'Unknown Option')}")

            # Immediately show empty table with proper structure - NO data loading yet
            self._show_immediate_empty_table(option)

            # Stop any previous refresh timer immediately
            if hasattr(self, '_refresh_timer') and self._refresh_timer:
                self._refresh_timer.stop()
                self._refresh_timer = None

            # Schedule the actual data loading with a small delay to ensure UI update completes first
            if option == "1":
                self.set_timer(0.1, self._refresh_roll_short_simple)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_roll_short_simple)
            elif option == "2":
                self.set_timer(0.1, self._refresh_box_spreads)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_box_spreads)
            elif option == "3":
                self.set_timer(0.1, self._refresh_vertical_spreads)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_vertical_spreads)
            elif option == "4":
                self.set_timer(0.1, self._refresh_synthetic_calls)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_synthetic_calls)
            elif option == "5":
                self.set_timer(0.1, self._refresh_margin_requirements)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_margin_requirements)
            elif option == "6":
                self.set_timer(0.1, self._refresh_orders)  # 100ms delay
                self._refresh_timer = self.set_interval(30, self._refresh_orders)
        except Exception as e:
            self.query_one("#content-display").update(f"[red]Error: {str(e)}[/red]")

    def _show_immediate_empty_table(self, option):
        """Show an empty table immediately with appropriate columns - no loading message"""
        # Hide content display immediately
        content = self.query_one("#content-display")
        content.display = False

        # Show table immediately
        table = self.query_one("#results-table")
        table.display = True
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.can_focus = True
        table.show_cursor = True
        table.clear(columns=True)

        # Set up columns based on screen type
        if option == "1":  # Roll Short Options
            columns = ['asset', 'cur_strike', 'cur_exp', 'roll_strike', 'roll_exp', 'credit', 'ann_rom', 'status']
            self.current_screen_type = "roll_short"
        elif option == "2":  # Box Spreads
            columns = ['asset', 'Date', 'Direction', 'Low Strike', 'High Strike', 'Net Price', 'Investment', 'Borrowed', 'Repayment', 'CAGR', 'Margin Req', 'Ann ROM %']
            self.current_screen_type = "box_spreads"
        elif option == "3":  # Vertical Spreads
            columns = ['asset', 'expiration', 'strike_low', 'strike_high', 'investment', 'max_profit', 'ann_rom']
            self.current_screen_type = "spreads"
        elif option == "4":  # Synthetic Calls
            columns = ['asset', 'expiration', 'strike_low', 'strike_high', 'investment', 'max_profit', 'ann_rom']
            self.current_screen_type = "synthetic"
        elif option == "5":  # Margin Requirements
            columns = ['symbol', 'position_type', 'quantity', 'margin_req', 'current_value']
            self.current_screen_type = "margin"
        elif option == "6":  # Orders
            columns = ['order_id', 'symbol', 'status', 'order_type', 'quantity']
            self.current_screen_type = "orders"
        else:
            columns = ['status']

        table.add_columns(*columns)

        # Focus the table immediately
        table.focus()

        # Clear current spreads data
        self.current_spreads_data = []

    def _refresh_roll_short_simple(self):
        """Get roll short options using the actual cc.py logic with timeout protection"""
        import datetime
        import threading
        import time
        now_str = datetime.datetime.now().strftime('%H:%M:%S')

        print("DEBUG: _refresh_roll_short_simple called")

        try:
            # Step 1: Get short positions using the correct API method with timeout
            print("DEBUG: Calling updateShortPosition...")

            # Use a simple timeout mechanism
            start_time = time.time()
            timeout_seconds = 30  # 30 second timeout

            short_positions = self.api.updateShortPosition()
            print(f"DEBUG: API returned: {type(short_positions)}, count: {len(short_positions) if short_positions else 0}")

            if time.time() - start_time > timeout_seconds:
                self._update_table_with_message([{'asset': 'Timeout', 'status': 'API call timed out', 'cur_strike': '', 'cur_exp': '', 'roll_strike': '', 'roll_exp': '', 'credit': '', 'ann_rom': '', 'refreshed': now_str}], "roll_short")
                return

            if short_positions is None:
                self._update_table_with_message([{'asset': 'No Data', 'status': 'API returned None', 'cur_strike': '', 'cur_exp': '', 'roll_strike': '', 'roll_exp': '', 'credit': '', 'ann_rom': '', 'refreshed': now_str}], "roll_short")
                return

            if not short_positions:
                self._update_table_with_message([{'asset': 'No Positions', 'status': 'No short positions found', 'cur_strike': '', 'cur_exp': '', 'roll_strike': '', 'roll_exp': '', 'credit': '', 'ann_rom': '', 'refreshed': now_str}], "roll_short")
                return

            # Step 2: Process SHORT POSITIONS LIMIT (prevent hanging on large datasets)
            max_positions_to_process = 10  # Limit to first 10 positions to prevent hanging
            positions_to_process = short_positions[:max_positions_to_process]

            if len(short_positions) > max_positions_to_process:
                print(f"DEBUG: Limiting processing to first {max_positions_to_process} of {len(short_positions)} positions")

            table_data = []
            from configuration import configuration
            from cc import find_best_rollover, _calculate_roll_metrics
            from datetime import datetime, timedelta
            from optionChain import OptionChain

            for i, short in enumerate(positions_to_process):
                # Add timeout check for each position
                if time.time() - start_time > timeout_seconds:
                    print(f"DEBUG: Timeout reached while processing position {i}")
                    break

                print(f"DEBUG: Processing short position {i+1}/{len(positions_to_process)}: {short.get('stockSymbol', 'Unknown')}")

                try:
                    symbol = short["stockSymbol"]

                    # ALWAYS create basic table row first with all available position data
                    table_row = {
                        'asset': symbol,
                        'cur_strike': short.get('strike', 'Unknown'),
                        'cur_exp': short.get('expiration', 'Unknown'),
                        'roll_strike': '',
                        'roll_exp': '',
                        'credit': '',
                        'ann_rom': '',
                        'status': 'Processing...',
                        'refreshed': now_str
                    }

                    # Check if asset is in configuration
                    if symbol not in configuration:
                        print(f"Configuration for {symbol} not found")
                        table_row['status'] = 'No Config'
                        table_data.append(table_row)
                        continue

                    # Try to get option chain for roll analysis with timeout protection
                    try:
                        print(f"DEBUG: Getting option chain for {symbol}")
                        days = configuration[symbol]["maxRollOutWindow"]
                        short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
                        toDate = short_expiration + timedelta(days=days)

                        # Check timeout before expensive operation
                        if time.time() - start_time > timeout_seconds:
                            print(f"DEBUG: Timeout before option chain for {symbol}")
                            table_row['status'] = 'Timeout'
                            table_data.append(table_row)
                            break

                        optionChain = OptionChain(self.api, symbol, toDate, days)
                        chain = optionChain.get()

                        if not chain:
                            print(f"No option chain data for {symbol}")
                            table_row['status'] = 'No Chain Data'
                            table_data.append(table_row)
                            continue

                        # Check timeout before roll analysis
                        if time.time() - start_time > timeout_seconds:
                            print(f"DEBUG: Timeout before roll analysis for {symbol}")
                            table_row['status'] = 'Timeout'
                            table_data.append(table_row)
                            break

                        # Find best rollover using cc.py logic (now with timeout protection)
                        print(f"DEBUG: Finding best rollover for {symbol}")
                        roll = find_best_rollover(self.api, chain, short)

                        if roll:
                            print(f"DEBUG: Found roll for {symbol}, calculating metrics")
                            # Calculate roll metrics using cc.py logic
                            metrics = _calculate_roll_metrics(self.api, short, chain, roll)

                            if metrics:
                                # Update table row with roll data
                                table_row.update({
                                    'cur_strike': metrics["short_strike"],
                                    'roll_strike': metrics["new_strike"],
                                    'roll_exp': metrics["ret"]["expiration"],
                                    'credit': f"{metrics['credit']:.2f}",
                                    'ann_rom': f"{metrics['rom']:.1f}%",
                                    'status': 'Roll Available'
                                })
                                print(f"DEBUG: Added roll candidate for {symbol}")
                            else:
                                print(f"DEBUG: Could not calculate metrics for {symbol}")
                                table_row['status'] = 'Metrics Failed'
                        else:
                            print(f"DEBUG: No roll opportunity found for {symbol}")
                            table_row['status'] = 'No Roll Found'

                    except Exception as chain_error:
                        print(f"DEBUG: Error getting chain/roll for {symbol}: {chain_error}")
                        table_row['status'] = f'Chain Error: {str(chain_error)[:20]}...'

                    # ALWAYS add the row to table_data (with basic info at minimum)
                    table_data.append(table_row)

                except Exception as short_error:
                    print(f"DEBUG: Error processing {short.get('stockSymbol', 'Unknown')}: {short_error}")
                    # Even on error, try to show basic position info
                    error_row = {
                        'asset': short.get('stockSymbol', 'Unknown'),
                        'cur_strike': short.get('strike', 'Unknown'),
                        'cur_exp': short.get('expiration', 'Unknown'),
                        'roll_strike': '',
                        'roll_exp': '',
                        'credit': '',
                        'ann_rom': '',
                        'status': f'Error: {str(short_error)[:30]}...',
                        'refreshed': now_str
                    }
                    table_data.append(error_row)

            print(f"DEBUG: Created table with {len(table_data)} rows in {time.time() - start_time:.2f} seconds")
            if table_data:
                self.show_spreads_table(table_data, "roll_short")
            else:
                self._update_table_with_message([{'asset': 'No Data', 'status': 'No positions to display', 'cur_strike': '', 'cur_exp': '', 'roll_strike': '', 'roll_exp': '', 'credit': '', 'ann_rom': '', 'refreshed': now_str}], "roll_short")

        except Exception as e:
            print(f"DEBUG: Exception in _refresh_roll_short_simple: {e}")
            self._update_table_with_message([{'asset': 'Error', 'status': f'Error: {str(e)}', 'cur_strike': '', 'cur_exp': '', 'roll_strike': '', 'roll_exp': '', 'credit': '', 'ann_rom': '', 'refreshed': now_str}], "roll_short")

    def _update_table_with_message(self, message_data, screen_type):
        """Update table with a message instead of showing text display"""
        self.show_spreads_table(message_data, screen_type)

    def _refresh_box_spreads(self):
        import datetime
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        try:
            table_data = process_box_spreads_data(self.api)
            if table_data:
                # Add refreshed timestamp to all rows and fix formatting
                for row in table_data:
                    # Fix financial values display based on direction
                    direction = row.get('Direction', '').lower()
                    net_price = row.get('Net Price', 0)

                    # Get the strike difference (this is the spread width)
                    low_strike = float(row.get('Low Strike', 0))
                    high_strike = float(row.get('High Strike', 0))
                    spread_width = high_strike - low_strike

                    # Calculate days to expiration for CAGR
                    try:
                        exp_date_str = row.get('Date', '')
                        exp_date = datetime.datetime.strptime(exp_date_str, '%Y-%m-%d').date()
                        today = datetime.date.today()
                        days_to_exp = (exp_date - today).days
                        years_to_exp = days_to_exp / 365.25
                    except:
                        days_to_exp = 0
                        years_to_exp = 1  # Default to prevent division by zero

                    if direction == 'buy':
                        # Buy box spread: We pay net price upfront, receive spread width at expiration
                        row['Direction'] = 'Buy (Invest)'
                        investment = abs(float(str(net_price).replace('$', '').replace(',', ''))) * 100  # Multiply by 100 for lot size
                        repayment = spread_width * 100  # Convert to per-contract value

                        # Calculate CAGR for investment scenario
                        if investment > 0 and years_to_exp > 0:
                            cagr = ((repayment / investment) ** (1 / years_to_exp) - 1) * 100
                            row['CAGR'] = f"{cagr:.2f}%"
                        else:
                            row['CAGR'] = "N/A"

                        row['Investment'] = f"${investment:,.2f}"  # What we pay upfront
                        row['Borrowed'] = f"$0.00"  # We don't borrow anything
                        row['Repayment'] = f"${repayment:,.2f}"  # What we receive at expiration
                        row['Net Price'] = f"${investment:,.2f}"

                    elif direction == 'sell':
                        # Sell box spread: We receive net price upfront, pay spread width at expiration
                        row['Direction'] = 'Sell (Borrow)'
                        borrowed = abs(float(str(net_price).replace('$', '').replace(',', ''))) * 100  # Multiply by 100 for lot size
                        repayment = spread_width * 100  # What we must pay back

                        # Calculate CAGR for borrowing scenario (cost of borrowing)
                        if borrowed > 0 and years_to_exp > 0:
                            cagr = ((repayment / borrowed) ** (1 / years_to_exp) - 1) * 100
                            row['CAGR'] = f"{cagr:.2f}%"
                        else:
                            row['CAGR'] = "N/A"

                        row['Investment'] = f"$0.00"  # We don't invest anything upfront
                        row['Borrowed'] = f"${borrowed:,.2f}"  # What we receive upfront (the loan)
                        row['Repayment'] = f"${repayment:,.2f}"  # What we pay back at expiration
                        row['Net Price'] = f"${borrowed:,.2f}"

                    # Format Ann ROM % to exactly 2 decimal places
                    ann_rom = row.get('Ann ROM %', '0%')
                    if isinstance(ann_rom, str) and '%' in ann_rom:
                        try:
                            rom_value = float(ann_rom.replace('%', ''))
                            row['Ann ROM %'] = f"{rom_value:.2f}%"
                        except ValueError:
                            row['Ann ROM %'] = "0.00%"
                    elif isinstance(ann_rom, (int, float)):
                        row['Ann ROM %'] = f"{ann_rom:.2f}%"
                    else:
                        row['Ann ROM %'] = "0.00%"

                    # Format Margin Req properly
                    margin_req = row.get('Margin Req', 0)
                    if isinstance(margin_req, (int, float)) and margin_req > 0:
                        row['Margin Req'] = f"${margin_req:,.2f}"
                    elif isinstance(margin_req, str) and margin_req.strip():
                        # If it's already a string, ensure it's properly formatted
                        try:
                            clean_margin = margin_req.replace('$', '').replace(',', '')
                            margin_val = float(clean_margin)
                            row['Margin Req'] = f"${margin_val:,.2f}"
                        except ValueError:
                            row['Margin Req'] = "$0.00"
                    else:
                        row['Margin Req'] = "$0.00"

                    # Remove any existing 'refreshed' key to avoid duplicates
                    if 'refreshed' in row:
                        del row['refreshed']

                    # Create new ordered dictionary with correct column order
                    ordered_row = {}
                    column_order = ['asset', 'Date', 'Direction', 'Low Strike', 'High Strike', 'Net Price', 'Investment', 'Borrowed', 'Repayment', 'CAGR', 'Margin Req', 'Ann ROM %', 'refreshed']

                    for col in column_order:
                        if col == 'refreshed':
                            ordered_row[col] = now_str
                        else:
                            ordered_row[col] = row.get(col, '')

                    # Replace the row with the ordered version
                    row.clear()
                    row.update(ordered_row)

                self.show_spreads_table(table_data, "box_spreads")
            else:
                # Show "No data" message in table format with correct column order
                empty_data = [{'asset': 'No box spreads found', 'Date': '', 'Direction': '', 'Low Strike': '', 'High Strike': '', 'Net Price': '', 'Investment': '', 'Borrowed': '', 'Repayment': '', 'CAGR': '', 'Margin Req': '', 'Ann ROM %': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "box_spreads")
        except Exception as e:
            print(f"DEBUG: Error in _refresh_box_spreads: {e}")
            import traceback
            traceback.print_exc()
            # Show error in table format with correct column order
            error_data = [{'asset': 'Error loading data', 'Date': str(e)[:50], 'Direction': '', 'Low Strike': '', 'High Strike': '', 'Net Price': '', 'Investment': '', 'Borrowed': '', 'Repayment': '', 'CAGR': '', 'Margin Req': '', 'Ann ROM %': '', 'refreshed': now_str}]
            self.show_spreads_table(error_data, "box_spreads")

    def _refresh_vertical_spreads(self):
        import datetime
        try:
            spreads_data = process_vertical_spreads_data(self.api, False)
            now_str = datetime.datetime.now().strftime('%H:%M:%S')
            if spreads_data:
                for row in spreads_data:
                    row['refreshed'] = now_str
                self.show_spreads_table(spreads_data, "spreads")
            else:
                # Show "No data" message in table format
                empty_data = [{'asset': 'No vertical spreads found', 'expiration': '', 'strike_low': '', 'strike_high': '', 'investment': '', 'max_profit': '', 'ann_rom': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "spreads")
        except Exception as e:
            print(f"DEBUG: Error in _refresh_vertical_spreads: {e}")
            import traceback
            traceback.print_exc()
            # Show error in table format
            error_data = [{'asset': 'Error loading data', 'expiration': str(e)[:50], 'strike_low': '', 'strike_high': '', 'investment': '', 'max_profit': '', 'ann_rom': '', 'refreshed': datetime.datetime.now().strftime('%H:%M:%S')}]
            self.show_spreads_table(error_data, "spreads")

    def _refresh_synthetic_calls(self):
        import datetime
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        try:
            spreads_data = process_vertical_spreads_data(self.api, True)
            if spreads_data:
                for row in spreads_data:
                    row['refreshed'] = now_str
                self.show_spreads_table(spreads_data, "synthetic")
            else:
                # Show "No data" message in table format
                empty_data = [{'asset': 'No synthetic calls found', 'expiration': '', 'strike_low': '', 'strike_high': '', 'investment': '', 'max_profit': '', 'ann_rom': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "synthetic")
        except Exception as e:
            print(f"DEBUG: Error in _refresh_synthetic_calls: {e}")
            import traceback
            traceback.print_exc()
            # Show error in table format
            error_data = [{'asset': 'Error loading data', 'expiration': str(e)[:50], 'strike_low': '', 'strike_high': '', 'investment': '', 'max_profit': '', 'ann_rom': '', 'refreshed': now_str}]
            self.show_spreads_table(error_data, "synthetic")

    def _refresh_margin_requirements(self):
        import datetime
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        try:
            table_data = process_margin_requirements_data(self.api)
            if table_data:
                # Add refreshed timestamp to all rows
                for row in table_data:
                    if 'refreshed' not in row:
                        row['refreshed'] = now_str
                self.show_spreads_table(table_data, "margin")
            else:
                # Show "No data" message in table format
                empty_data = [{'symbol': 'No positions found', 'position_type': '', 'quantity': '', 'margin_req': '', 'current_value': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "margin")
        except Exception as e:
            print(f"DEBUG: Error in _refresh_margin_requirements: {e}")
            import traceback
            traceback.print_exc()
            # Show error in table format
            error_data = [{'symbol': 'Error loading data', 'position_type': str(e)[:50], 'quantity': '', 'margin_req': '', 'current_value': '', 'refreshed': now_str}]
            self.show_spreads_table(error_data, "margin")

    def _refresh_orders(self):
        """Show current orders and allow cancellation"""
        import datetime
        now_str = datetime.datetime.now().strftime('%H:%M:%S')

        try:
            table_data = process_orders_data(self.api)
            if table_data:
                # Add refreshed timestamp to all rows
                for row in table_data:
                    if 'refreshed' not in row:
                        row['refreshed'] = now_str
                self.show_spreads_table(table_data, "orders")
            else:
                empty_data = [{'order_id': 'No orders found', 'symbol': '', 'status': '', 'order_type': '', 'quantity': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "orders")
        except Exception as e:
            error_data = [{'order_id': 'Error loading data', 'symbol': str(e)[:50], 'status': '', 'order_type': '', 'quantity': '', 'refreshed': now_str}]
            self.show_spreads_table(error_data, "orders")

    def place_selected_order(self):
        """Place order for selected spread - similar to original implementation"""
        print("DEBUG: place_selected_order called")

        if not self.current_spreads_data:
            content = self.query_one("#content-display")
            content.display = True
            content.update("[yellow]No data available for order placement[/yellow]")
            return

        # Get selected row from table
        table = self.query_one("#results-table")
        try:
            cursor_row = table.cursor_row
            print(f"DEBUG: cursor_row = {cursor_row}")
            if cursor_row < 0 or cursor_row >= len(self.current_spreads_data):
                content = self.query_one("#content-display")
                content.display = True
                content.update("[yellow]Please select a row first (use arrow keys, then press Enter)[/yellow]")
                return
        except AttributeError:
            content = self.query_one("#content-display")
            content.display = True
            content.update("[yellow]Please select a row first (use arrow keys, then press Enter)[/yellow]")
            return

        try:
            selected_row = self.current_spreads_data[cursor_row]
            print(f"DEBUG: selected_row asset = {selected_row.get('asset')}")
            content = self.query_one("#content-display")
            content.display = True

            # Handle different screen types
            if self.current_screen_type == "roll_short":
                # Roll short options order placement
                self._show_roll_order_confirmation(selected_row)
            elif self.current_screen_type == "box_spreads":
                # Handle box spread orders
                self._show_box_spread_order_confirmation(selected_row)
            elif self.current_screen_type in ["spreads", "synthetic"]:
                # Only allow trading for vertical spreads and synthetic calls
                if selected_row.get('asset') == 'TOTAL':
                    content.update("[yellow]Order placement not available for this selection[/yellow]")
                    return
                self._show_spread_order_confirmation(selected_row)
            else:
                content.update("[yellow]Order placement not available for this screen[/yellow]")

        except Exception as e:
            content = self.query_one("#content-display")
            content.display = True
            content.update(f"[red]Error preparing order: {str(e)}[/red]")

    def _show_roll_order_confirmation(self, selected_row):
        """Show confirmation for rolling short options"""
        content = self.query_one("#content-display")

        asset = selected_row.get('asset', 'Unknown')
        cur_strike = selected_row.get('cur_strike', 0)
        cur_exp = selected_row.get('cur_exp', 'Unknown')
        roll_strike = selected_row.get('roll_strike', 0)
        roll_exp = selected_row.get('roll_exp', 'Unknown')
        credit = selected_row.get('credit', 0)

        print(f"DEBUG: About to show roll order confirmation for {asset}")

        # Display roll order details
        order_details = f"""
[bold cyan]ROLL ORDER CONFIRMATION[/bold cyan]
Asset: [bold white]{asset}[/bold white]
Strategy: [yellow]Roll Short Option[/yellow]

Current Position:
  Strike: [bold cyan]{cur_strike}[/bold cyan]
  Expiration: [dim cyan]{cur_exp}[/dim cyan]

Roll To:
  Strike: [bold cyan]{roll_strike}[/bold cyan]
  Expiration: [dim cyan]{roll_exp}[/dim cyan]

Expected Credit: [green]${credit}[/green]

[bold yellow]Press SPACE again to confirm roll, ESC to cancel[/bold yellow]
"""
        content.update(order_details)

        # Store the selected row for confirmation
        self.pending_order = selected_row
        print(f"DEBUG: Set pending_order to roll {selected_row.get('asset')}")

    def _show_spread_order_confirmation(self, selected_row):
        """Show confirmation for spread orders (existing logic)"""
        asset = selected_row.get('asset', 'Unknown')
        date = selected_row.get('expiration', 'Unknown')
        strike_low = selected_row.get('strike_low', 0)
        strike_high = selected_row.get('strike_high', 0)
        investment = selected_row.get('investment', 0)
        max_profit = selected_row.get('max_profit', 0)
        margin_req = selected_row.get('margin_req', 0)
        rom = selected_row.get('ann_rom', '0%')

        print(f"DEBUG: About to show order confirmation for {asset}")

        # Display order details
        order_details = f"""
[bold cyan]ORDER CONFIRMATION[/bold cyan]
Asset: [bold white]{asset}[/bold white]
Expiration: [dim cyan]{date}[/dim cyan]
Strategy: [yellow]{'Synthetic Covered Call' if self.current_screen_type == 'synthetic' else 'Vertical Call Spread'}[/yellow]
Low Strike: [bold cyan]{strike_low}[/bold cyan]
High Strike: [bold cyan]{strike_high}[/bold cyan]
Investment: [green]{investment}[/green]
Max Profit: [green]{max_profit}[/green]
Margin Req: [white]{margin_req}[/white]
Ann. ROM: [bold bright_green]{rom}[/bold bright_green]

[bold yellow]Press SPACE again to confirm order, ESC to cancel[/bold yellow]
"""
        content = self.query_one("#content-display")
        content.update(order_details)

        # Store the selected row for confirmation
        self.pending_order = selected_row
        print(f"DEBUG: Set pending_order to {selected_row.get('asset')}")

    def _show_box_spread_order_confirmation(self, selected_row):
        """Show confirmation for box spread orders"""
        asset = selected_row.get('asset', 'Unknown')
        date = selected_row.get('Date', 'Unknown')
        direction = selected_row.get('Direction', 'Unknown')
        strike_low = selected_row.get('Low Strike', 0)
        strike_high = selected_row.get('High Strike', 0)
        net_price = selected_row.get('Net Price', 0)
        borrowed = selected_row.get('Borrowed', 0)
        repayment = selected_row.get('Repayment', 0)
        margin_req = selected_row.get('Margin Req', 0)
        rom = selected_row.get('Ann ROM %', '0%')

        print(f"DEBUG: About to show box spread order confirmation for {asset}")

        # Display box spread order details
        order_details = f"""
[bold cyan]BOX SPREAD ORDER CONFIRMATION[/bold cyan]
Asset: [bold white]{asset}[/bold white]
Expiration: [dim cyan]{date}[/dim cyan]
Strategy: [yellow]Box Spread ({direction})[/yellow]
Low Strike: [bold cyan]{strike_low}[/bold cyan]
High Strike: [bold cyan]{strike_high}[/bold cyan]
Net Price: [green]{net_price}[/green]
Borrowed: [green]{borrowed}[/green]
Repayment: [white]{repayment}[/white]
Margin Req: [white]{margin_req}[/white]
Ann. ROM: [bold bright_green]{rom}[/bold bright_green]

[bold yellow]Press SPACE again to confirm box spread order, ESC to cancel[/bold yellow]
"""
        content = self.query_one("#content-display")
        content.update(order_details)

        # Store the selected row for confirmation
        self.pending_order = selected_row
        print(f"DEBUG: Set pending_order to box spread {selected_row.get('asset')}")

    def confirm_and_place_order(self):
        """Actually place the order after confirmation"""
        print("DEBUG: confirm_and_place_order called")

        if not hasattr(self, 'pending_order') or not self.pending_order:
            print("DEBUG: No pending order found, returning")
            return

        try:
            selected_row = self.pending_order
            asset = selected_row.get('asset')

            print(f"DEBUG: About to place order for {asset}")

            content = self.query_one("#content-display")
            content.update(f"[green]Placing order for {asset}...[/green]")

            # Clear pending order IMMEDIATELY to prevent confirmation loop
            self.pending_order = None
            print("DEBUG: Cleared pending_order BEFORE placing order")

            if self.current_screen_type == "roll_short":
                # Handle roll short options order
                self._place_roll_order(selected_row)
            elif self.current_screen_type == "box_spreads":
                # Handle box spread orders
                self._place_box_spread_order(selected_row)
            elif self.current_screen_type in ["spreads", "synthetic"]:
                # Handle regular spread orders
                self._place_spread_order(selected_row)
            else:
                content.update("[red]Unknown order type[/red]")

        except Exception as e:
            content = self.query_one("#content-display")
            content.update(f"[red]Error placing order: {str(e)}[/red]")
            # Make sure pending order is cleared even on error
            self.pending_order = None
            print("DEBUG: Cleared pending_order after error")

    def _place_roll_order(self, selected_row):
        """Place a roll order for short options with detailed UI feedback"""
        content = self.query_one("#content-display")

        try:
            asset = selected_row.get('asset')
            cur_strike = selected_row.get('cur_strike')
            cur_exp = selected_row.get('cur_exp')
            credit = selected_row.get('credit', 0)

            print(f"DEBUG: Roll order details - Asset: {asset}, Current: {cur_strike}/{cur_exp}, Credit: {credit}")

            # Find the actual short position using the correct data
            content.update(f"[cyan]Finding short position for {asset}...[/cyan]")
            shorts = self.api.updateShortPosition()
            current_short = None

            for short in shorts:
                if (short["stockSymbol"] == asset and
                    float(short["strike"]) == float(cur_strike) and
                    short["expiration"] == cur_exp):
                    current_short = short
                    break

            if not current_short:
                content.update(f"[red]Could not find current short position for {asset} strike {cur_strike} exp {cur_exp}[/red]")
                print(f"DEBUG: Available shorts: {[(s['stockSymbol'], s['strike'], s['expiration']) for s in shorts]}")
                return

            print(f"DEBUG: Found current short: {current_short}")

            # Instead of using RollCalls, implement the roll logic directly in the UI for better feedback
            content.update(f"[cyan]Analyzing roll opportunity for {asset}...[/cyan]")

            try:
                from configuration import configuration
                from cc import find_best_rollover, _calculate_roll_metrics
                from datetime import datetime, timedelta
                from optionChain import OptionChain

                # Get option chain
                days = configuration[asset]["maxRollOutWindow"]
                short_expiration = datetime.strptime(current_short["expiration"], "%Y-%m-%d").date()
                toDate = short_expiration + timedelta(days=days)
                optionChain = OptionChain(self.api, asset, toDate, days)
                chain = optionChain.get()

                if not chain:
                    content.update(f"[red]Could not get option chain for {asset}[/red]")
                    return

                # Find best rollover
                content.update(f"[cyan]Finding best roll target for {asset}...[/cyan]")
                roll = find_best_rollover(self.api, chain, current_short)

                if not roll:
                    content.update(f"[red]No suitable roll target found for {asset}[/red]")
                    return

                # Calculate metrics
                content.update(f"[cyan]Calculating roll metrics for {asset}...[/cyan]")
                metrics = _calculate_roll_metrics(self.api, current_short, chain, roll)

                if not metrics:
                    content.update(f"[red]Could not calculate roll metrics for {asset}[/red]")
                    return

                # Show detailed roll information
                roll_credit = round(metrics["credit"], 2)
                new_strike = metrics["new_strike"]
                new_exp = metrics["ret"]["expiration"]

                content.update(f"""[bold green]ROLLING {asset}:[/bold green]
[cyan]From:[/cyan] Strike {cur_strike}, Exp {cur_exp}
[cyan]To:[/cyan] Strike {new_strike}, Exp {new_exp}
[cyan]Net Credit:[/cyan] ${roll_credit}
[cyan]Annualized Return:[/cyan] {metrics['annualized_return']:.1f}%
[cyan]Return on Margin:[/cyan] {metrics['rom']:.1f}%

[yellow]Placing roll order...[/yellow]""")

                # Place the roll order using the API
                try:
                    print(f"DEBUG: Placing roll order - Old: {current_short['optionSymbol']}, New: {roll['symbol']}, Credit: {roll_credit}")

                    order_id = self.api.rollOver(
                        current_short['optionSymbol'],  # old symbol
                        roll['symbol'],                 # new symbol
                        int(current_short['count']),    # amount
                        roll_credit                     # expected credit
                    )

                    print(f"DEBUG: Roll order placed, order_id: {order_id}")

                    if order_id and not str(order_id).startswith("Error"):
                        content.update(f"""[bold green]✅ ROLL ORDER PLACED SUCCESSFULLY![/bold green]

[white]Order ID:[/white] [bold cyan]{order_id}[/bold cyan]
[white]Asset:[/white] [bold]{asset}[/bold]
[white]Strategy:[/white] Roll Short Call
[white]From:[/white] Strike {cur_strike} → {new_strike}
[white]Expected Credit:[/white] [green]${roll_credit}[/green]
[white]New Expiration:[/white] {new_exp}

[dim]The order has been submitted and will be monitored for execution.[/dim]
[dim]Refreshing positions in 3 seconds...[/dim]""")

                        # Refresh the roll short data after a delay
                        self.set_timer(3.0, self._refresh_roll_short_simple)
                    else:
                        content.update(f"""[red]❌ ROLL ORDER FAILED[/red]

[white]Asset:[/white] [bold]{asset}[/bold]
[white]Error:[/white] {order_id}
[white]Expected Credit:[/white] ${roll_credit}

[yellow]Please check your account or try again.[/yellow]""")

                except Exception as order_error:
                    content.update(f"""[red]❌ ROLL ORDER ERROR[/red]

[white]Asset:[/white] [bold]{asset}[/bold]
[white]Error:[/white] {str(order_error)}

[yellow]Please check your connection and try again.[/yellow]""")
                    print(f"DEBUG: Roll order exception: {order_error}")
                    import traceback
                    traceback.print_exc()

            except Exception as analysis_error:
                content.update(f"""[red]❌ ROLL ANALYSIS ERROR[/red]

[white]Asset:[/white] [bold]{asset}[/bold]
[white]Error:[/white] {str(analysis_error)}

[yellow]Could not analyze roll opportunity.[/yellow]""")
                print(f"DEBUG: Roll analysis exception: {analysis_error}")
                import traceback
                traceback.print_exc()

        except Exception as e:
            content.update(f"""[red]❌ ROLL ORDER SYSTEM ERROR[/red]

[white]Error:[/white] {str(e)}

[yellow]Please try again or check the console for details.[/yellow]""")
            print(f"DEBUG: Error in _place_roll_order: {e}")
            import traceback
            traceback.print_exc()

    def _place_spread_order(self, selected_row):
        """Place spread orders (existing logic)"""
        content = self.query_one("#content-display")

        try:
            asset = selected_row.get('asset')
            date = selected_row.get('expiration')
            strike_low = selected_row.get('strike_low')
            strike_high = selected_row.get('strike_high')

            # Get additional data needed for order (this would need to be stored in spreads data)
            net_debit = float(str(selected_row.get('investment', 0))) / 100  # Convert back to per-share

            try:
                # Parse date
                from datetime import datetime
                order_date = datetime.strptime(date, "%Y-%m-%d")

                # For now, just try the initial price (we'll add price improvements later)
                initial_price = net_debit

                content.update(f"[cyan]Trying price: ${initial_price:.2f}[/cyan]")

                # Place order based on strategy type
                if self.current_screen_type == "synthetic":
                    order_id = self.api.synthetic_covered_call_order(
                        asset, order_date, strike_low, strike_high, 1, price=initial_price
                    )
                else:
                    order_id = self.api.vertical_call_order(
                        asset, order_date, strike_low, strike_high, 1, initial_price
                    )

                content.update(f"[bold green]Order placed successfully! Order ID: {order_id}[/bold green]")

            except Exception as order_error:
                content.update(f"[red]Order failed: {str(order_error)}[/red]")

        except Exception as e:
            content.update(f"[red]Error placing spread order: {str(e)}[/red]")

    def _place_box_spread_order(self, selected_row):
        """Place box spread orders using data from BoxSpread function"""
        content = self.query_one("#content-display")

        try:
            asset = selected_row.get('asset', 'Unknown')
            date = selected_row.get('Date', 'Unknown')
            strike_low = selected_row.get('Low Strike', 0)
            strike_high = selected_row.get('High Strike', 0)
            net_price = selected_row.get('Net Price', 0)
            direction = selected_row.get('Direction', 'Sell')

            content.update(f"[cyan]Placing {direction.lower()} box spread order for {asset}...[/cyan]")
            content.update(f"[cyan]Date: {date}, Strikes: {strike_low}-{strike_high}, Net Price: ${net_price}[/cyan]")

            try:
                # Parse the date
                from datetime import datetime
                order_date = datetime.strptime(date, "%Y-%m-%d")

                # Place the box spread order directly
                # Use the same approach as other strategies - call the API method directly
                if direction.lower() == "sell":
                    # For sell box spread, we're receiving net credit
                    order_id = self.api.box_spread_order(
                        asset,
                        order_date,
                        strike_low,
                        strike_high,
                        1,  # quantity
                        net_price
                    )
                else:
                    # For buy box spread, we're paying net debit
                    order_id = self.api.box_spread_order(
                        asset,
                        order_date,
                        strike_low,
                        strike_high,
                        1,  # quantity
                        net_price
                    )

                if order_id and not str(order_id).startswith("Error"):
                    content.update(f"[bold green]Box spread order placed successfully! Order ID: {order_id}[/bold green]")
                    # Refresh the box spreads data after a short delay
                    self.set_timer(2.0, self._refresh_box_spreads)
                else:
                    content.update(f"[red]Box spread order failed: {order_id}[/red]")

            except AttributeError:
                # If box_spread_order method doesn't exist, show error message
                content.update("[red]Box spread order method not available in API yet.[/red]")
                content.update("[yellow]Please implement the box_spread_order method in your API class.[/yellow]")
            except Exception as order_error:
                content.update(f"[red]Box spread order failed: {str(order_error)}[/red]")

        except Exception as e:
            content.update(f"[red]Error placing box spread order: {str(e)}[/red]")
            print(f"DEBUG: Error in _place_box_spread_order: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_orders(self):
        """Show current orders and allow cancellation"""
        import datetime
        now_str = datetime.datetime.now().strftime('%H:%M:%S')

        try:
            table_data = process_orders_data(self.api)
            if table_data:
                # Add refreshed timestamp to all rows
                for row in table_data:
                    if 'refreshed' not in row:
                        row['refreshed'] = now_str
                self.show_spreads_table(table_data, "orders")
            else:
                empty_data = [{'order_id': 'No orders found', 'symbol': '', 'status': '', 'order_type': '', 'quantity': '', 'refreshed': now_str}]
                self.show_spreads_table(empty_data, "orders")
        except Exception as e:
            error_data = [{'order_id': 'Error loading data', 'symbol': str(e)[:50], 'status': '', 'order_type': '', 'quantity': '', 'refreshed': now_str}]
            self.show_spreads_table(error_data, "orders")

    def cancel_selected_order(self):
        """Cancel the selected order"""
        if not self.current_spreads_data or self.current_screen_type != "orders":
            content = self.query_one("#content-display")
            content.display = True
            content.update("[yellow]No orders available for cancellation[/yellow]")
            return

        # Get selected row from table
        table = self.query_one("#results-table")
        try:
            cursor_row = table.cursor_row
            if cursor_row < 0 or cursor_row >= len(self.current_spreads_data):
                content = self.query_one("#content-display")
                content.display = True
                content.update("[yellow]Please select an order first (use arrow keys)[/yellow]")
                return
        except AttributeError:
            content = self.query_one("#content-display")
            content.display = True
            content.update("[yellow]Please select an order first (use arrow keys)[/yellow]")
            return

        try:
            selected_order = self.current_spreads_data[cursor_row]
            order_id = selected_order.get('order_id')
            symbol = selected_order.get('symbol', 'Unknown')

            content = self.query_one("#content-display")
            content.display = True

            if not order_id or order_id == 'Unknown':
                content.update("[yellow]Invalid order selected[/yellow]")
                return

            # Show confirmation for order cancellation
            if not hasattr(self, 'pending_cancel_order') or not self.pending_cancel_order:
                # First press - show confirmation

                cancel_details = f"""
[bold red]CANCEL ORDER CONFIRMATION[/bold red]
Order ID: [bold white]{order_id}[/bold white]
Symbol: [bold white]{symbol}[/bold white]
Status: [yellow]{selected_order.get('status', 'Unknown')}[/yellow]

[bold yellow]Press SPACE again to confirm cancellation, ESC to cancel[/bold yellow]
"""
                content.update(cancel_details)
                self.pending_cancel_order = selected_order
                print(f"DEBUG: Set pending_cancel_order for {order_id}")
            else:
                # Second press - actually cancel the order
                print(f"DEBUG: Canceling order {order_id}")
                try:
                    content.update(f"[yellow]Canceling order {order_id}...[/yellow]")

                    # Cancel the order using the existing API method
                    try:
                        self.api.cancelOrder(order_id)
                        content.update(f"[bold green]Order {order_id} cancelled successfully![/bold green]")
                        # Refresh the orders list after a short delay
                        self.set_timer(1.0, self._refresh_orders)
                    except Exception as cancel_error:
                        content.update(f"[red]Error canceling order: {str(cancel_error)}[/red]")

                finally:
                    self.pending_cancel_order = None
                    print("DEBUG: Cleared pending_cancel_order")



        except Exception as e:
            content = self.query_one("#content-display")

            content.display = True
            content.update(f"[red]Error processing order cancellation: {str(e)}[/red]")

    def action_roll_short(self):
        self.handle_option_sync("1")
    def action_box_spreads(self):
        self.handle_option_sync("2")
    def action_vertical_spreads(self):
        self.handle_option_sync("3")
    def action_synthetic_calls(self):
        self.handle_option_sync("4")
    def action_margin_requirements(self):
        self.handle_option_sync("5")
    def action_view_orders(self):
        self.handle_option_sync("6")
    def action_place_order(self):
        """Handle order placement when Enter is pressed"""
        print("DEBUG: action_place_order called")  # Debug print

        # Check if we're in order management mode
        if self.current_screen_type == "orders":
            self.cancel_selected_order()
            return

        # Show status in status bar (cleaner version)
        try:
            current_screen = self.query_one("#current-screen")
            if hasattr(self, 'pending_order') and self.pending_order is not None:
                asset = self.pending_order.get('asset', 'Unknown')
                if self.current_screen_type == "roll_short":
                    current_screen.update(f"Roll Short Options - Confirming roll for {asset}")
                elif self.current_screen_type == "box_spreads":
                    direction = self.pending_order.get('Direction', 'Unknown')
                    current_screen.update(f"Check Box Spreads - Confirming {direction} order for {asset}")
                elif self.current_screen_type == "synthetic":
                    current_screen.update(f"Synthetic Covered Calls - Confirming order for {asset}")
                else:
                    current_screen.update(f"Vertical Spreads - Confirming order for {asset}")
            else:
                if self.current_screen_type == "roll_short":
                    current_screen.update("Roll Short Options - Select row and press SPACE to roll")
                elif self.current_screen_type == "box_spreads":
                    current_screen.update("Check Box Spreads - Select row and press SPACE to place order")
                elif self.current_screen_type == "synthetic":
                    current_screen.update("Synthetic Covered Calls - Select row and press SPACE to place order")
                else:
                    current_screen.update("Vertical Spreads - Select row and press SPACE to place order")
        except Exception:
            pass

        print(f"DEBUG: Has pending_order: {hasattr(self, 'pending_order') and self.pending_order is not None}")
        if hasattr(self, 'pending_order') and self.pending_order is not None:
            print(f"DEBUG: pending_order asset: {self.pending_order.get('asset', 'Unknown')}")

        if hasattr(self, 'pending_order') and self.pending_order is not None:
            # Second Enter press - confirm and place order
            print("DEBUG: Confirming pending order")
            self.confirm_and_place_order()
        else:
            # First Enter press - show order details
            print("DEBUG: Placing selected order (showing confirmation)")
            self.place_selected_order()
    def action_cancel_action(self):
        """Handle cancel when Escape is pressed"""
        if hasattr(self, 'pending_cancel_order') and self.pending_cancel_order:
            # Cancel pending order cancellation
            self.pending_cancel_order = None
            content = self.query_one("#content-display")
            content.display = False
            self.query_one("#results-table").display = True
        elif hasattr(self, 'pending_order') and self.pending_order:
            # Cancel pending order
            self.pending_order = None
            content = self.query_one("#content-display")
            content.display = False
            self.query_one("#results-table").display = True
        else:
            content = self.query_one("#content-display")
            content.display = True
            content.update("Action cancelled")
            self.query_one("#results-table").display = False
    def action_quit(self):
        self.app.exit()


class OptionsTradingApp(App):
    """Main Textual application"""
    TITLE = "Options Trading System"

    def __init__(self, api, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
            self.api = api
            css_path = os.path.join(os.path.dirname(__file__), "styles.css")
            if os.path.exists(css_path):
                self.CSS_PATH = css_path
        except Exception as e:
            if "I/O operation on closed file" in str(e):
                raise RuntimeError("Failed to initialize Textual app due to I/O access issues.")
            else:
                raise

    def on_mount(self):

        self.push_screen(MainMenuScreen(self.api))

    def on_key(self, event):
        """Handle key presses at the app level"""
        print(f"DEBUG APP LEVEL: Key pressed: '{event.key}'")

        # Forward to the current screen's main menu if it exists
        try:
            current_screen = self.screen
            if hasattr(current_screen, 'on_key'):
                return current_screen.on_key(event)
        except Exception as e:
            print(f"DEBUG APP: Error forwarding key: {e}")

        return False

    def _test_roll_short_functionality(self):
        """Test function to debug roll short options issues"""
        try:
            print("DEBUG: Testing roll short functionality...")

            # Test 1: Check if API method exists and works
            try:
                short_positions = self.api.updateShortPosition()
                print(f"DEBUG: API updateShortPosition() returned: {type(short_positions)}, length: {len(short_positions) if short_positions else 'None'}")
                if short_positions:
                    print(f"DEBUG: First short position: {short_positions[0]}")
            except Exception as api_error:
                print(f"DEBUG: API updateShortPosition() failed: {api_error}")
                return False

            # Test 2: Check configuration
            try:
                from configuration import configuration
                print(f"DEBUG: Configuration loaded, assets: {list(configuration.keys())}")
            except Exception as config_error:
                print(f"DEBUG: Configuration loading failed: {config_error}")
                return False

            # Test 3: Check cc module imports
            try:
                from cc import find_best_rollover, _calculate_roll_metrics
                print("DEBUG: cc module imports successful")
            except Exception as cc_error:
                print(f"DEBUG: cc module import failed: {cc_error}")
                return False

            return True

        except Exception as e:
            print(f"DEBUG: Test failed with error: {e}")
            return False
            try:
                from cc import find_best_rollover, _calculate_roll_metrics
                print("DEBUG: cc module imports successful")
            except Exception as cc_error:
                print(f"DEBUG: cc module import failed: {cc_error}")
                return False

            return True

        except Exception as e:
            print(f"DEBUG: Test failed with error: {e}")
            return False
            # First Enter press - show order details
            print("DEBUG: Placing selected order (showing confirmation)")
            self.place_selected_order()
    def action_cancel_action(self):
        """Handle cancel when Escape is pressed"""
        if hasattr(self, 'pending_cancel_order') and self.pending_cancel_order:
            # Cancel pending order cancellation
            self.pending_cancel_order = None
            content = self.query_one("#content-display")
            content.display = False
            self.query_one("#results-table").display = True
        elif hasattr(self, 'pending_order') and self.pending_order:
            # Cancel pending order
            self.pending_order = None
            content = self.query_one("#content-display")
            content.display = False
            self.query_one("#results-table").display = True
        else:
            content = self.query_one("#content-display")
            content.display = True
            content.update("Action cancelled")
            self.query_one("#results-table").display = False
    def action_quit(self):
        self.app.exit()


class OptionsTradingApp(App):
    """Main Textual application"""
    TITLE = "Options Trading System"

    def __init__(self, api, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
            self.api = api
            css_path = os.path.join(os.path.dirname(__file__), "styles.css")
            if os.path.exists(css_path):
                self.CSS_PATH = css_path
        except Exception as e:
            if "I/O operation on closed file" in str(e):
                raise RuntimeError("Failed to initialize Textual app due to I/O access issues.")
            else:
                raise

    def on_mount(self):

        self.push_screen(MainMenuScreen(self.api))

    def on_key(self, event):
        """Handle key presses at the app level"""
        print(f"DEBUG APP LEVEL: Key pressed: '{event.key}'")

        # Forward to the current screen's main menu if it exists
        try:
            current_screen = self.screen
            if hasattr(current_screen, 'on_key'):
                return current_screen.on_key(event)
        except Exception as e:
            print(f"DEBUG APP: Error forwarding key: {e}")

        return False

    def _test_roll_short_functionality(self):
        """Test function to debug roll short options issues"""
        try:
            print("DEBUG: Testing roll short functionality...")

            # Test 1: Check if API method exists and works
            try:
                short_positions = self.api.updateShortPosition()
                print(f"DEBUG: API updateShortPosition() returned: {type(short_positions)}, length: {len(short_positions) if short_positions else 'None'}")
                if short_positions:
                    print(f"DEBUG: First short position: {short_positions[0]}")
            except Exception as api_error:
                print(f"DEBUG: API updateShortPosition() failed: {api_error}")
                return False

            # Test 2: Check configuration
            try:
                from configuration import configuration
                print(f"DEBUG: Configuration loaded, assets: {list(configuration.keys())}")
            except Exception as config_error:
                print(f"DEBUG: Configuration loading failed: {config_error}")
                return False

            # Test 3: Check cc module imports
            try:
                from cc import find_best_rollover, _calculate_roll_metrics
                print("DEBUG: cc module imports successful")
            except Exception as cc_error:
                print(f"DEBUG: cc module import failed: {cc_error}")
                return False

            return True

        except Exception as e:
            print(f"DEBUG: Test failed with error: {e}")
            return False
            try:
                from cc import find_best_rollover, _calculate_roll_metrics
                print("DEBUG: cc module imports successful")
            except Exception as cc_error:
                print(f"DEBUG: cc module import failed: {cc_error}")
                return False

            return True

        except Exception as e:
            print(f"DEBUG: Test failed with error: {e}")
            return False
            return False
