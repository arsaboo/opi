# Options Trading Bot (OPI)

## Project Overview

This is a Python-based bot designed to assist with managing options trading positions, particularly focusing on rolling short options and analyzing various spread strategies. It integrates with the Schwab API to fetch market data and place trades, and provides a modern terminal-based graphical user interface using the Textual library.

### Core Functionality

- **Roll Short Options**: Automatically identifies and executes rolls for expiring short call positions, optimizing for improved strike prices and premiums.
- **Analyze Spreads**: Evaluates potential Box Spreads, Bull Call Spreads (Verticals), and Synthetic Covered Calls to find high-yield opportunities.
- **Real-time Market Data**: Utilizes Schwab's streaming quotes API for live market data and option chain updates.
- **Margin Calculations**: Provides detailed margin requirement analysis for different strategies and asset types.
- **Order Management**: Places complex multi-leg orders (rolls, spreads) with automatic price improvement mechanisms and real-time monitoring.
- **Market Timing**: Respects market hours and can operate in a debug mode for testing outside market hours.

### Technologies

- **Language**: Python 3
- **API**: Schwab Developer API (using the `schwab` Python library) with streaming quotes support
- **External Libraries**:
  - `pytz`, `tzlocal`: Timezone handling.
  - `textual`: Terminal user interface (TUI) library.
  - `requests`: HTTP requests (used by Schwab library).
- **Configuration**: Centralized configuration via `configuration.py` and environment variables in `.env`.
- **Development Environment**: Optimized for Windows development in VSCode

## Project Architecture

The codebase is organized with clear separation of concerns:

### Core Modules
- `main.py`: The entry point of the application. It launches the Textual UI application.
- `api.py`: Handles all interactions with the Schwab API, including authentication, fetching quotes, option chains, account data, market hours, and placing/cancelling orders. It also contains logic for calculating margin requirements.
- `cc.py` (Call Control/Rolling): Contains the core logic for finding and executing rolls for short call positions (`RollCalls`, `RollSPX`). It uses data from `optionChain.py` and configuration from `configuration.py`.
- `optionChain.py`: Processes and standardizes raw option chain data fetched from the Schwab API.
- `strategies.py`: Implements the logic for analyzing and placing various spread strategies (Box Spreads, Bull Call Spreads, Synthetic Covered Calls).
- `margin_utils.py`: Dedicated module for calculating margin requirements and annualized returns for different strategies and assets.
- `order_utils.py`: Contains utilities for monitoring order status and handling user-initiated order cancellations.
- `alert.py`: Handles error reporting and notifications (console + Telegram).
- `support.py`: Contains helper functions and utilities.
- `logger_config.py`: Configures application logging.

### Configuration Files
- `configuration.py`: Stores strategy parameters, asset-specific settings, and other configuration options.
- `configuration.example.py`: Example configuration file template.
- `.env`: Environment variables for sensitive data (API keys, account info).
- `.env.example`: Example environment file template.

### User Interface
- `ui/`: Contains the Textual-based Terminal User Interface (TUI) implementation.
  - `ui/main.py`: Entry point for the TUI application (`OpiApp`).
  - `ui/logic.py`: Asynchronous data fetching and processing logic for the UI widgets.
  - `ui/widgets/`: Contains individual UI components for different functionalities:
    - `roll_short_options.py`: Widget for rolling short options positions.
    - `box_spreads.py`: Widget for analyzing box spread opportunities.
    - `bull_call_spreads.py`: Widget for bull call spread analysis.
    - `synthetic_covered_calls.py`: Widget for synthetic covered call strategies.
    - `accounts.py`: Widget for account information display.
    - `positions.py`: Widget for current positions overview.
    - `orders.py`: Widget for order management and monitoring.
  - `ui/screens/`: Full-screen dedicated views (currently minimal implementation).

## Setup and Configuration

### Prerequisites
- **Operating System**: Windows (developed and tested on Windows)
- **IDE**: VSCode (recommended for development)
- **Python**: Python 3.8 or higher
- **Brokerage Account**: A Schwab brokerage account
- **API Access**: Schwab Developer API access with streaming quotes enabled

### Installation Steps

1. **Clone the Repository**:
   ```powershell
   git clone <repository-url>
   cd opi_2
   ```

2. **Install Dependencies** (in VSCode terminal or PowerShell):
   ```powershell
   pip install -r requirements.txt
   ```

3. **Schwab API Setup**:
   - Create an app on [https://developer.schwab.com/](https://developer.schwab.com/) to get an API key and secret.
   - **Important**: Ensure your application has streaming quotes access enabled (required for real-time data).
   - Configure your local callback/redirect URI (typically `https://localhost` for local development).

4. **Environment Configuration**:
   - In VSCode, copy `.env.example` to `.env` and update it with your Schwab credentials:
     ```
     SCHWAB_API_KEY=your_api_key_here
     SCHWAB_APP_SECRET=your_app_secret_here
     SCHWAB_REDIRECT_URI=https://localhost
     SCHWAB_ACCOUNT_ID=your_account_id_here
     ```
   - **Note**: Use VSCode's file explorer or PowerShell commands instead of Unix commands like `sed` or `cp`.

5. **Strategy Configuration**:
   - Copy `configuration.example.py` to `configuration.py` using VSCode or PowerShell:
     ```powershell
     Copy-Item configuration.example.py configuration.py
     ```
   - Customize strategy parameters, asset configurations, and trading preferences within `configuration.py`.

## Usage

### Running the Application

Run the main script from VSCode terminal or PowerShell:
```powershell
python main.py
```

**Note**: When developing in VSCode, you can use the integrated terminal (Ctrl+`) for all commands. The application is designed to work seamlessly in the Windows environment.

### First-Time Authentication
Upon first run, you will be directed to a Schwab authentication flow in your browser. The process involves:
1. A browser window will open for Schwab OAuth authentication
2. Log in to your Schwab account and authorize the application
3. You'll be redirected to your callback URI (localhost)
4. Copy the authorization code from the URL and paste it back into the terminal
5. The bot will then obtain and store authentication tokens

**Note**: The initial token refresh process occurs in the regular terminal before loading the Textual UI. You may see authentication-related output during this process.

### Using the TUI
The TUI provides a visual, interactive experience within the terminal using the `textual` library. Features include:
- **Tab Navigation**: Switch between different strategy widgets using keyboard shortcuts
- **Real-time Data**: Asynchronously updated tables with live streaming market data from Schwab
- **Interactive Tables**: Select and execute trades directly from the interface
- **Status Logging**: All logs and status messages are displayed within the UI
- **Order Management**: Monitor and cancel orders from within the interface
- **Streaming Quotes**: Live price updates for options and underlying assets

Use the keyboard shortcuts shown in the footer to navigate between different features. All interaction occurs within the Textual UI after launch.

## Key Features by Widget

### Roll Short Options
- Automatically identifies expiring short call positions
- Calculates optimal roll targets based on configuration parameters
- Displays potential profit/loss and margin impact with live pricing
- One-click execution of roll orders

### Box Spreads
- Scans for arbitrage opportunities in box spread configurations using real-time quotes
- Calculates annualized returns and margin requirements
- Filters opportunities based on minimum return thresholds

### Bull Call Spreads
- Analyzes vertical spread opportunities with live market data
- Evaluates risk/reward ratios
- Provides detailed margin and profit/loss calculations

### Synthetic Covered Calls
- Identifies synthetic covered call opportunities using streaming quotes
- Compares synthetic vs. actual covered call strategies
- Analyzes dividend capture scenarios

## Development Conventions

### Windows Development Environment
- **IDE**: Developed and optimized for VSCode on Windows
- **Terminal**: Use PowerShell or VSCode integrated terminal (avoid Unix-specific commands)
- **File Operations**: Use VSCode file explorer or PowerShell commands (Copy-Item, Move-Item, etc.)
- **Path Handling**: Windows path separators are handled automatically by Python

### Real-time Data Integration
- **Streaming Quotes**: Utilizes Schwab's streaming API for live market data
- **Data Refresh**: Real-time updates for option chains, underlying prices, and Greeks
- **Connection Management**: Automatic reconnection and error handling for streaming connections
- **Rate Limiting**: Respects API rate limits while maintaining real-time data flow

### Error Handling
- Functions that can fail often return `None` or `False`, or raise exceptions via `alert.botFailed()`
- Robust retry logic is implemented for API calls and order placement
- All errors are logged and displayed in the UI status panel

### Configuration Management
- Strategy settings and asset parameters are externalized in `configuration.py`
- Sensitive data (API keys, account info) is stored in `.env` file
- Easy adjustment of parameters without code changes

### Logging
- Uses `logger_config.py` for structured logging
- Primarily used for debugging network/API issues
- All logs are displayed in the Textual UI status log panel
- No terminal output after UI initialization

### Order Placement
- Employs automatic price improvement loops for better fills
- Multi-leg order support for complex strategies
- Real-time order status monitoring
- Automatic retry mechanisms with exponential backoff

### Margin Calculations
- Margin logic is centralized in `margin_utils.py` and `api.py`
- Supports different asset types (indexes, ETFs, leveraged ETFs)
- Strategy-specific margin calculations
- Real-time margin impact analysis

### UI Architecture
- Uses the `textual` library for modern terminal interfaces (works excellently in VSCode terminal)
- Asynchronous data fetching in `ui/logic.py` keeps interface responsive
- Real-time streaming data integration for live updates
- Modular widget design for easy extension
- Separation of UI logic from business logic
- Event-driven architecture for real-time updates

### API Integration
- Centralized API handling in `api.py`
- **Streaming Integration**: Real-time quotes and market data streaming
- Token management and automatic refresh
- Rate limiting and error handling
- Market hours awareness
- Debug mode for testing outside market hours
- Windows-compatible authentication flow

## File Structure
```
opi_2/
├── main.py                     # Application entry point
├── api.py                      # Schwab API integration (includes streaming quotes)
├── cc.py                       # Call rolling logic
├── strategies.py               # Spread strategy implementations
├── optionChain.py             # Option chain data processing
├── margin_utils.py            # Margin calculation utilities
├── order_utils.py             # Order management utilities
├── alert.py                   # Error reporting and notifications
├── support.py                 # Helper functions
├── logger_config.py           # Logging configuration
├── configuration.py           # User configuration (created from example)
├── configuration.example.py   # Configuration template
├── .env                       # Environment variables (created from example)
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
└── ui/                       # User interface components
    ├── main.py               # TUI application entry
    ├── logic.py              # Async data processing (streaming integration)
    ├── widgets/              # UI components
    │   ├── roll_short_options.py
    │   ├── box_spreads.py
    │   ├── bull_call_spreads.py
    │   ├── synthetic_covered_calls.py
    │   ├── accounts.py
    │   ├── positions.py
    │   └── orders.py
    └── screens/              # Full-screen views
```

## VSCode Development Tips

- **Integrated Terminal**: Use Ctrl+` to open the integrated terminal for running the application
- **Python Extension**: Ensure the Python extension is installed for proper syntax highlighting and debugging
- **File Explorer**: Use the built-in file explorer for copying configuration files
- **Debugging**: The application can be debugged directly in VSCode using the Python debugger
- **Environment Variables**: VSCode can load `.env` files automatically with the Python extension
