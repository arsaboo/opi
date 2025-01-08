# Options Trading Bot

This bot helps manage options positions, including rolling options and analyzing spreads. It uses Schwab API for options trading operations.

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
- `main.py`: Coordinates the application flow

## Usage

Run the main script:
```bash
python main.py
```

## Features

- Roll short options positions
- Check box spreads
- Analyze vertical spreads
- Check synthetic covered calls
- View margin requirements

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
