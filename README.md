# Options Trading Bot (Textual UI)

This bot helps manage options positions, including rolling options and analyzing spreads. 
It uses Schwab API for options trading operations and provides a modern terminal-based 
graphical user interface using the Textual library.

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

### Schwab API Setup
1. Create an app on https://developer.schwab.com/
2. Get your API key and secret
3. Copy the .env file and update it with your Schwab credentials:
```bash
cp .env.example .env
```
Then edit the `.env` file with your credentials:
```env
SCHWAB_API_KEY=your_api_key_here
SCHWAB_APP_SECRET=your_app_secret_here
SCHWAB_REDIRECT_URI=your_redirect_uri_here
SCHWAB_ACCOUNT_ID=your_account_id_here
```

## Architecture

The codebase is organized with clear separation of concerns:
- `api/`: SDK-facing logic
  - `api/client.py` (`Api`): token setup, quotes, option chains, account lookup
  - `api/option_chain.py` (`OptionChain`): maps Schwab option chain JSON to internal format
  - `api/order_manager.py` (`OrderManager`): builds and sends orders, monitoring/cancel/edit
  - `api/streaming/`: live quote provider and subscription coordination for UI
- `core/`: computation utilities (spreads, pricing, date helpers)
  - `core/box_spreads.py`: box spread evaluation
  - `core/spreads_common.py`: common helpers for spreads
  - `core/common.py`: shared utils (dates, moneyness, rounding)
- `ui/`: Textual TUI (widgets, views, layout)
  - `ui/main.py`: application shell and navigation
  - `ui/widgets/`, `ui/views/`: feature screens and components
- `status.py`: UI-aware status/exception publishing
- `state_manager.py`: persistence of tracked symbols between runs
- `main.py`: CLI entry point to launch the TUI

## Usage

Run the main script to launch the Textual UI:
```bash
python main.py
```

**Note on Authentication**: The initial token refresh process still occurs in the regular terminal before loading the Textual UI. You may see some output in the terminal during this process.

The application will start with a terminal-based graphical user interface.
Use the keyboard shortcuts shown in the footer to navigate between different features.

For help information:
```bash
python main.py --help
```

All logs and status messages are displayed within the Textual UI status log panel, as the terminal is no longer available after the UI loads.

## Features

- Interactive Textual UI for all operations
- Roll short options positions with real-time data
- Check sell box spreads with annualized cost view
- Analyze vertical spreads with sorting and filtering
- Check synthetic covered calls with detailed views
- View margin requirements with comprehensive breakdowns
- Real-time status updates and logging
- Keyboard shortcuts for quick navigation
- Color-coded data for better visualization
- Automatic data refresh for live updates

## Configuration

Edit configuration.py to customize:
- Option rolling parameters
- Spread analysis settings
- Market timing preferences
- Debug modes

Note: API credentials are now stored in the `.env` file for better security.

## Troubleshooting

Common issues:

1. Authentication Errors:
   - Error: "Invalid credentials"
   - Solution: Verify API key and secret

2. Permission Errors:
   - Error: "Permission denied"
   - Solution: Check account permissions

3. Market Hours:
   - Error: "Market is closed"
   - Solution: Run during market hours or enable debug mode
