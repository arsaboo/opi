# Options Trading Bot

This bot helps manage options positions, including rolling options and analyzing spreads. It uses Schwab API for options trading operations and optionally Google Sheets for tax tracking.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy configuration:
```bash
cp configuration.example.py configuration.py
```

3. Configure your setup:

### Required: Schwab API Setup
1. Create an app on https://developer.schwab.com/
2. Get your API key and secret
3. Update configuration.py with your Schwab credentials:
```python
apiKey = 'your_api_key'
apiRedirectUri = 'https://localhost'
SchwabAccountID = 'your_account_id'
appSecret = 'your_app_secret'
```

### Optional: Google Sheets Setup (for Tax Tracking)
1. Create a Google Cloud Project:
   - Go to https://console.cloud.google.com/
   - Create a new project
   - Enable Google Sheets API

2. Create credentials:
   - Go to APIs & Services > Credentials
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app"
   - Download the credentials and save as `credentials.json` in project directory

3. Get your spreadsheet ID:
   - Open your "Stock Portfolio Tracker" spreadsheet
   - The ID is in the URL: https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit

4. Update configuration.py to enable tax tracking:
```python
enableTaxTracking = True
SPREADSHEET_ID = 'your_spreadsheet_id'
```

## Architecture

The codebase is organized with clear separation of concerns:
- `api.py`: Handles all Schwab API interactions for options trading
- `sheets_api.py`: Handles Google Sheets interactions (used only for tax tracking)
- `tax_tracker.py`: Manages tax-related functionality using Google Sheets
- `optionChain.py`: Processes option chain data from Schwab API
- `cc.py`: Implements options rolling logic
- `main.py`: Coordinates the application flow

## Spreadsheet Format

If using tax tracking with Google Sheets, the integration expects a specific format:

### "Stocks" Sheet
Summary of current positions with columns:
- Category
- Stock Name
- Google Quote
- Change
- Chart
- Google Price
- Units
- Cost
- Cost (Per Unit)
- Unrealised Gain/Loss
- Unrealised Gain/Loss (%)
- Realised Gain/Loss
- Dividends Collected
- Total Gain/Loss
- Mkt Value
- Returns
- 52 Wk Low
- 52 Wk High
- Additional Deltas
- Recom
- Remarks (used to filter for "Schwab" positions)

### "Transactions" Sheet
Detailed transaction history with columns:
- Date (in YYYY-MM-DD format, e.g., 2024-01-31)
- Type
- Stock
- Units
- Price (per unit)
- Fees
- Split Ratio
- Prev Row
- Previous Units
- Cumulative Units
- Transacted Value
- Previous Cost
- Cost of Transaction
- Cost of Transaction (per unit)
- Cumulative Cost
- Gains/Losses
- Yield
- Cash Flow
- TIC
- Remarks
- Account (used to filter for "Schwab" transactions)

Transaction Types:
- Buy: Stock purchase
- Div: Dividend received
- Sell: Stock sale
- SPO: Sell put option to open
- Fees: Fees charged
- SCO: Sell call option to open
- BCC: Buy call option to close
- BCO-VC: Buy call option to open
- SCO-VC: Sell call option to open
- BCO: Buy call option to open
- BCC-VC-F: Buy call option to close
- BCO-COM: Buy call option to open
- SPO-COM: Sell put option to open
- SCC-VC-F: Sell call option to close
- BPC: Buy put option to close
- BPC-COM: Buy put option to close
- SCC-VC: Sell call option to close
- BCC-VC: Buy call option to close

### Data Format Requirements

1. Dates:
   - Must be in YYYY-MM-DD format (e.g., 2024-01-31)
   - Invalid formats like MM/DD/YYYY will cause errors

2. Numbers:
   - Can include currency symbols (e.g., $123.45)
   - Can include commas (e.g., 1,234.56)
   - Negative values should use minus sign (e.g., -123.45)
   - Empty cells or '-' are treated as zero

3. Percentages:
   - Can include % symbol (e.g., 12.34%)
   - Can be negative (e.g., -12.34%)
   - Empty cells or '-' are treated as zero

4. Text Fields:
   - Case sensitive for Type and Account columns
   - Empty cells are treated as empty strings
   - Leading/trailing spaces are trimmed

5. Required Fields:
   - Date, Type, Stock, and Account are required
   - Other numeric fields can be empty or '-'
   - TIC field is required for option transactions

## Usage

Run the main script:
```bash
python main.py
```

If tax tracking is enabled with Google Sheets, the first time you run it will:
1. Open your browser for OAuth authentication
2. Ask you to authorize the application
3. Save the token for future use

## Features

- Roll short options positions
- Check box spreads
- Analyze vertical spreads
- Check synthetic covered calls
- View margin requirements
- Tax management (if enabled)

## Configuration

Edit configuration.py to customize:
- Option rolling parameters
- Spread analysis settings
- Market timing preferences
- Debug modes
- Tax tracking settings

## Troubleshooting

Common issues:

1. Date Format Errors:
   - Error: "time data '12/31/2024' does not match format '%Y-%m-%d'"
   - Solution: Change dates to YYYY-MM-DD format

2. Number Format Errors:
   - Error: "could not convert string to float"
   - Solution: Check for invalid characters in number fields
   - Valid: "$1,234.56", "-123.45", empty cell, or "-"
   - Invalid: "N/A", "TBD", or other text

3. Authentication Errors:
   - Error: "credentials.json not found"
   - Solution: Download OAuth credentials from Google Cloud Console

4. Permission Errors:
   - Error: "Permission denied"
   - Solution: Share spreadsheet with your Google account

5. Missing Data:
   - Error: "Missing required column"
   - Solution: Verify all required columns exist with exact names

6. Sheet Names:
   - Error: "Sheet not found"
   - Solution: Ensure sheets are named exactly "Stocks" and "Transactions"
