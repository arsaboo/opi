# Options Trading Bot (OPI)

## Project Overview

This is a Python-based bot designed to assist with managing options trading positions, particularly focusing on rolling short options and analyzing various spread strategies. It integrates with the Schwab API to fetch market data and place trades.

### Core Functionality

- **Roll Short Options**: Automatically identifies and executes rolls for expiring short call positions, optimizing for improved strike prices and premiums.
- **Analyze Spreads**: Evaluates potential Box Spreads, Bull Call Spreads (Verticals), and Synthetic Covered Calls to find high-yield opportunities.
- **Margin Calculations**: Provides detailed margin requirement analysis for different strategies and asset types.
- **Order Management**: Places complex multi-leg orders (rolls, spreads) with automatic price improvement mechanisms and real-time monitoring.
- **Market Timing**: Respects market hours and can operate in a debug mode for testing outside market hours.

### Technologies

- **Language**: Python 3
- **API**: Schwab Developer API (using the `schwab` Python library)
- **External Libraries**:
  - `pytz`, `tzlocal`: Timezone handling.
  - `keyboard`, `inputimeout`: User interaction and timeouts (CLI version).
  - `textual`: Terminal user interface (TUI) library.
  - `prettytable`: Formatted output display (CLI version).
  - `colorama`: Colored terminal output (CLI version).
  - `requests`: HTTP requests (used by Schwab library).
- **Configuration**: Centralized configuration via `configuration.py` and `configuration.example.py`.

## Project Architecture

The codebase is organized with clear separation of concerns:

- `main.py`: The entry point of the application (CLI version). It handles user interaction via a menu, initializes the API, manages the main execution loop, and coordinates calls to other modules.
- `api.py`: Handles all interactions with the Schwab API, including authentication, fetching quotes, option chains, account data, market hours, and placing/cancelling orders. It also contains logic for calculating margin requirements.
- `cc.py` (Call Control/Rolling): Contains the core logic for finding and executing rolls for short call positions (`RollCalls`, `RollSPX`). It uses data from `optionChain.py` and configuration from `configuration.py`.
- `optionChain.py`: Processes and standardizes raw option chain data fetched from the Schwab API.
- `strategies.py`: Implements the logic for analyzing and placing various spread strategies (Box Spreads, Bull Call Spreads, Synthetic Covered Calls).
- `margin_utils.py`: Dedicated module for calculating margin requirements and annualized returns for different strategies and assets.
- `order_utils.py`: Contains utilities for monitoring order status and handling user-initiated order cancellations.
- `alert.py`: Handles error reporting and notifications (currently console or email).
- `support.py` (not fully analyzed but implied): Contains helper functions.
- `configuration.py` (created by user): Stores API keys, account information, strategy parameters, and asset-specific settings.
- `logger_config.py`: Configures application logging.
- `ui/`: Contains the Textual-based Terminal User Interface (TUI) implementation.
  - `ui/main.py`: Entry point for the TUI application (`OpiApp`).
  - `ui/logic.py`: Asynchronous data fetching and processing logic for the UI widgets.
  - `ui/widgets/`: Contains individual UI components (screens/widgets) for different functionalities (e.g., Roll Short Options, Box Spreads).
  - `ui/screens/`: (Currently empty) Intended for full-screen dedicated views.

## Setup and Configuration

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Schwab API Setup**:
    - Create an app on [https://developer.schwab.com/](https://developer.schwab.com/) to get an API key and secret.
    - Configure your local callback/redirect URI (e.g., `https://localhost`).
3.  **Configure the Bot**:
    - Copy `configuration.example.py` to `configuration.py`.
    - Update `configuration.py` with your Schwab credentials (`apiKey`, `apiRedirectUri`, `SchwabAccountID`, `appSecret`).
    - Customize strategy parameters and asset configurations within `configuration.py`.

## Usage

### CLI Version

Run the main script:
```bash
python main.py
```

Upon first run, you will be directed to a Schwab authentication flow in your browser. After authentication, the bot will present a menu:

1.  **Roll Short Options**: Identifies expiring short calls and suggests/automates rolls.
2.  **Check Box Spreads**: Analyzes the market for profitable box spread opportunities.
3.  **Check Vertical Spreads**: Finds potential Bull Call Spread (Vertical) trades.
4.  **Check Synthetic Covered Calls**: Evaluates Synthetic Covered Call strategies.
5.  **View Margin Requirements**: Displays margin details for current short positions.
0.  **Exit**: Quits the application.

For automated actions (like placing orders), the bot often prompts for user confirmation before executing. During order placement, pressing 'c' can attempt to cancel the order.

### TUI Version

*(Details about how to run the TUI version would go here, likely `python -m ui.main` or similar, based on the structure. This part is inferred from the files present.)*

The TUI provides a more visual, interactive experience within the terminal, using the `textual` library. It presents data in tables and updates asynchronously.

## Development Conventions

- **Error Handling**: Functions that can fail often return `None` or `False`, or raise exceptions via `alert.botFailed()`. Robust retry logic (`handle_retry`) is used for API calls and order placement.
- **Configuration**: Strategy settings and asset parameters are externalized in `configuration.py` for easy adjustment without code changes.
- **Logging**: Uses `logger_config.py` for structured logging, primarily for debugging network/API issues.
- **Order Placement**: Employs automatic price improvement loops for better fills, with user cancellation support (CLI uses `keyboard`, TUI logic likely handles this differently or relies on API timeouts).
- **Margin Calculations**: Margin logic is centralized in `margin_utils.py` and `api.py`, supporting different asset types (indexes, ETFs, leveraged ETFs) and strategies.
- **UI (TUI)**: Uses the `textual` library. UI logic is separated into `ui/main.py` (app logic) and `ui/widgets/` (individual components). Data fetching for the UI is handled asynchronously in `ui/logic.py` to keep the interface responsive.
