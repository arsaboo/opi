# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Codebase Overview

This repository contains an Options Trading Bot that uses the Schwab API for automated options trading operations. The system provides functionality for rolling short options positions, analyzing spreads, and managing margin requirements through both a command-line interface and a modern Textual-based terminal UI.

## Architecture

The codebase is organized with clear separation of concerns:

- `api.py`: Handles all Schwab API interactions for options trading operations
- `optionChain.py`: Processes option chain data from Schwab API
- `cc.py`: Implements options rolling logic and calculations
- `main.py`: Main application entry point with retry logic and UI coordination
- `configuration.py`: Central configuration including API keys, trading parameters, and asset-specific settings
- `ui/`: Contains Textual-based terminal user interface components

## Common Development Tasks

### Starting the Application

Run the main application with:
```bash
python main.py
```

### Installing Dependencies

Install all required packages:
```bash
pip install -r requirements.txt
```

### Configuration Setup

1. Copy the example configuration:
```bash
cp configuration.example.py configuration.py
```

2. Update `configuration.py` with your Schwab API credentials:
   - `apiKey`: Your Schwab API key
   - `apiRedirectUri`: Your redirect URI (typically https://127.0.0.1)
   - `SchwabAccountID`: Your Schwab account ID
   - `appSecret`: Your Schwab app secret

### Testing Order Functionality

To test order placement without actually sending orders to Schwab, set:
```python
debugCanSendOrders = False
```
in `configuration.py`

## Key Components

1. **Options Rolling**: The core functionality in `cc.py` handles automatic rolling of short call positions based on configurable parameters in `configuration.py`.

2. **Spread Analysis**: The system can analyze vertical spreads, box spreads, and synthetic covered calls with profitability calculations.

3. **Margin Calculations**: Complex margin requirement calculations are handled in `margin_utils.py` following Schwab's margin rules.

4. **Textual UI**: Modern terminal interface in the `ui/` directory with keyboard navigation and real-time updates.

## Adding New Assets

To add support for a new stock/index:
1. Add configuration entry in the `configuration` dictionary in `configuration.py`
2. (Optional) Add spread configuration in the `spreads` dictionary for vertical spread analysis

## Debugging

Key debug settings in `configuration.py`:
- `debugMarketOpen = True`: Run even when market is closed
- `debugCanSendOrders = False`: Prevent actual order placement
- `loggingLevel = "DEBUG"`: Enable detailed logging

## Common Issues

1. **Authentication Errors**: If you see "token invalid" errors, delete the `token.json` file and re-authenticate
2. **Market Hours**: Some operations are restricted to market hours unless `debugMarketOpen = True`