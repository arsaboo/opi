from textual.app import App
from textual.containers import Container, Vertical
from textual.widgets import Button, Header, Footer, Static, DataTable
from textual.screen import Screen


class SpreadsTableScreen(Screen):
    """Screen to display spreads data in a table"""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "pop_screen", "Back"),
    ]

    def __init__(self, spreads_data, title="Spreads Analysis", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spreads_data = spreads_data or []
        self.title = title

    def compose(self):
        """Create the table layout"""
        yield Header(show_clock=True)

        with Container(id="table-container"):
            yield Static(f"{self.title} - {len(self.spreads_data)} items found", id="table-title")
            yield DataTable(id="spreads-table")
            yield Button("Back to Main Menu", id="back-button", variant="primary")

        yield Footer()

    def on_mount(self):
        """Initialize the table when mounted"""
        table = self.query_one("#spreads-table", DataTable)

        if not self.spreads_data:
            table.add_column("Message")
            table.add_row("No spreads data available")
            return

        # Add columns based on the first data item
        first_item = self.spreads_data[0]
        columns = list(first_item.keys())

        for column in columns:
            table.add_column(column.replace('_', ' ').title())

        # Add rows
        for item in self.spreads_data:
            row_data = []
            for column in columns:
                value = item.get(column, "")
                # Format numeric values
                if isinstance(value, float):
                    if column in ['cagr', 'protection', 'ann_rom']:
                        row_data.append(f"{value:.2f}%")
                    elif column in ['investment', 'max_profit', 'margin_req']:
                        row_data.append(f"${value:,.0f}")
                    else:
                        row_data.append(f"{value:.2f}")
                else:
                    row_data.append(str(value))

            table.add_row(*row_data)

        # Configure table appearance
        table.set_alternating_row_colors(True)
        table.set_show_grid(True)
        table.vertical_header().set_visible(False)

        # Set monospace font for consistent character width
        font = "Courier New"
        table.set_font_size(11)
        table.set_font_family(font)

        # Configure column behavior for consistent alignment
        header = table.horizontal_header()
        for i in range(len(columns)):
            header.set_section_resize_mode(i, "fixed")
            table.set_column_width(i, 120)  # Fixed width for all columns

        # Set minimum row height for better spacing
        table.vertical_header().set_default_section_size(30)

        # Style the headers
        header_style = """
            QHeaderView::section {
                background-color: #2b2b2b;
                color: white;
                padding: 8px;
                border: 1px solid #555;
                font-weight: bold;
            }
        """
        table.set_style_sheet(header_style)

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button press events"""
        if event.button.id == "back-button":
            self.app.pop_screen()

    def action_pop_screen(self):
        """Go back to the previous screen"""
        self.app.pop_screen()
