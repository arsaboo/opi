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
3. Update configuration.py with your Schwab credentials:
```python
apiKey = 'your_api_key'
apiRedirectUri = 'https://localhost'
SchwabAccountID = 'your_account_id'
appSecret = 'your_app_secret'
```

## Architecture

The codebase is organized with clear separation of concerns:
- `api.py`: Handles all Schwab API interactions for options trading
- `optionChain.py`: Processes option chain data from Schwab API
- `cc.py`: Implements options rolling logic
- `ui/`: Contains all Textual UI components and logic
- `main.py`: Entry point that launches the Textual UI application

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
- Check box spreads with visual analysis
- Analyze vertical spreads with sorting and filtering
- Check synthetic covered calls with detailed views
- View margin requirements with comprehensive breakdowns
- Real-time status updates and logging
- Keyboard shortcuts for quick navigation
- Color-coded data for better visualization
- Automatic data refresh for live updates
- Machine learning enhanced roll timing with technical indicators
- Advanced counterfactual analysis for optimal roll strategies

## Configuration

Edit configuration.py to customize:
- Option rolling parameters
- Spread analysis settings
- Market timing preferences
- Debug modes

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

## Features

- Interactive Textual UI for all operations
- Roll short options positions with real-time data
- Check box spreads with visual analysis
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
