import time
from datetime import datetime, timedelta

import pytz
from colorama import Fore, Style
from tzlocal import get_localzone

import alert
from api import Api
from cc import RollCalls, RollSPX
from configuration import (
    apiKey,
    apiRedirectUri,
    appSecret,
)
from logger_config_quiet import get_logger
import traceback

# Import log cleanup function
from log_cleanup import cleanup_old_logs

logger = get_logger()

# Initialize API
api = Api(apiKey, apiRedirectUri, appSecret)


def handle_retry(func, max_retries=3, backoff_factor=3, recoverable_errors=None):
    """
    Execute a function with retry logic for recoverable errors.

    Args:
        func: Function to execute
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for wait time between retries
        recoverable_errors: List of error message substrings that are considered recoverable

    Returns:
        The result of the function if successful, True if completed without errors even if result is None
        The result of the function if successful, True if completed without errors even if result is None
    """
    # Define default recoverable errors if none provided
    if recoverable_errors is None:
        recoverable_errors = [
            "token_invalid",
            "connection was forcibly closed",
            "WinError 10054",
            "ConnectionRefusedError",
            "ConnectionResetError",
            "read operation timed out",
            "timed out",
            "Expecting value: line 1 column 1 (char 0)",
            "JSONDecodeError",
            "Invalid JSON",
            "Unterminated string",
            "Extra data"
        ]

    for retry_count in range(max_retries):
        try:
            # Attempt to execute the function
            result = func()
            # Return True if function completed successfully, regardless of its return value
            return True if result is None else result
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error during execution: {error_str}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")

            # Check if this is a recoverable error
            is_recoverable = any(err in error_str for err in recoverable_errors)

            # If error is recoverable and we have retries left
            if is_recoverable and retry_count < max_retries - 1:
                # Special handling for JSON parsing errors - use shorter wait time
                if any(json_err in error_str for json_err in ["Expecting value", "JSONDecodeError", "Invalid JSON"]):
                    retry_wait = 2  # Shorter wait for JSON errors
                    print(f"\nAPI response error detected (likely temporary): {error_str}")
                    print(f"This usually resolves quickly. Retrying in {retry_wait} seconds... (attempt {retry_count + 1}/{max_retries})")
                else:
                    # Calculate wait time with exponential backoff for other errors
                    retry_wait = backoff_factor * (retry_count + 1)
                    print(f"\nRecoverable error detected: {error_str}")
                    print(f"Attempting to retry (attempt {retry_count + 1}/{max_retries})...")
                    print(f"Waiting {retry_wait} seconds before retry...")

                try:
                    time.sleep(retry_wait)
                except KeyboardInterrupt:
                    # Let KeyboardInterrupts during sleep propagate up
                    raise
                print("Retrying...")
                continue

            # Non-recoverable error or max retries reached
            alert.botFailed(None, f"Error: {error_str}")
            return False

    # This should not be reached but added as a fallback
    return False


def roll_short_positions(api, shorts):
    try:
        any_expiring = False  # flag to track if any options are expiring within 7 days
        today = datetime.now(pytz.UTC).date()

        for short in shorts:
            dte = (datetime.strptime(short["expiration"], "%Y-%m-%d").date() - today).days
            if -1 < dte < 7:
                any_expiring = True  # set the flag to True

                message_color = Fore.RED if dte == 0 else Fore.GREEN
                print(
                    f"{short['count']} {short['stockSymbol']} expiring in {message_color}{dte} day(s){Style.RESET_ALL}: {short['optionSymbol']}"
                )

                roll_function = RollSPX if short["stockSymbol"] == "$SPX" else RollCalls
                roll_function(api, short)

        if not any_expiring:  # if the flag is still False after the loop, print the message
            print("No options expiring soon.")

    except Exception as e:
        logger.error(f"Error in roll_short_positions: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        alert.botFailed(None, f"Error rolling positions: {str(e)}")
        return None


def calculate_time_to_market_open():
    """Calculate time until market opens at 9:30 AM"""
    now = datetime.now(get_localzone())
    time_to_open = now.replace(hour=9, minute=30, second=0, microsecond=0) - now

    if time_to_open.total_seconds() < 0:
        # If we are past 9:30 AM, calculate the time to 9:30 AM the next day
        time_to_open += timedelta(days=1)

    return time_to_open


def format_amount(amount):
    """Format currency amount with color coding based on value"""
    color = Fore.GREEN if amount >= 0 else Fore.RED
    return f"{color}${abs(amount):,.2f}{Style.RESET_ALL}"


def print_transaction_table(title, transactions, category):
    """Helper function to print transaction table with dynamic width"""
    if not transactions:
        return

    # Calculate maximum description length
    max_desc_len = max(len(t['description']) for t in transactions)
    desc_width = min(max(45, max_desc_len), 80)  # minimum 45, maximum 80 chars
    total_width = 12 + 20 + desc_width + 15 + 3  # Date + Type + Description + Amount + spacing

    print(f"\n{title}:")
    print("-" * total_width)
    print(f"{'Date':<12} {'Type':<20} {'Description':<{desc_width}} {'Amount':>15}")
    print("-" * total_width)

    for t in sorted(transactions, key=lambda x: x["date"]):
        if category == "Stock Sales" and t['amount'] == 0:
            continue
        print(
            f"{t['date']:<12} "
            f"{category[:20]:<20} "
            f"{t['description']:<{desc_width}} "
            f"{format_amount(t['amount']):>15}"
        )
    print("-" * total_width)


def run_textual_ui(api):
    """Run the modern Textual-based UI"""
    try:
        from ui.ui_main import run_textual_app
        run_textual_app(api)
    except ImportError as e:
        logger.error(f"Failed to import Textual UI: {e}")
        raise ImportError(
            "Textual UI dependencies are missing. Please install with: pip install -r requirements.txt"
        ) from e
    except Exception as e:
        logger.error(f"Error running Textual UI: {e}")
        # Check if it's an I/O operation error
        if "I/O operation on closed file" in str(e):
            logger.error("I/O operation error detected. This may be due to stdin/stdout not being available.")
            raise RuntimeError("UI initialization failed due to I/O access issues. Try running in a different terminal environment.") from e
        raise RuntimeError(f"Error starting UI: {e}") from e


def setup_api_with_retry(api, max_attempts=3):
    """Set up the API with retry logic specifically for authentication errors"""
    for attempt in range(1, max_attempts + 1):
        try:
            api.setup()
            return True  # If setup is successful, return True
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error while setting up the api: {error_str}")

            # Check if this is the last attempt
            is_last_attempt = attempt >= max_attempts

            # Handle token authentication error
            if "refresh_token_authentication_error" in error_str and not is_last_attempt:
                logger.info("Detected refresh token authentication error. Attempting to delete token and retry...")
                print("Token authentication failed. Deleting existing token and retrying...")
                api.delete_token()

            # Exit if max attempts reached
            if is_last_attempt:
                logger.error(f"Failed to initialize API after {max_attempts} attempts")
                alert.botFailed(None, f"Failed to initialize API after {max_attempts} attempts: {error_str}")
                return False

            # Retry with delay
            print(f"Retrying setup (attempt {attempt}/{max_attempts})...")
            time.sleep(2)  # Brief pause before retry

    return False  # Should not reach here, but added as a fallback


# Add timeout protection to API setup
import threading

def setup_api_with_timeout(api, timeout_seconds=30):
    """Setup API with timeout protection"""
    result = [None]
    exception = [None]

    def target():
        try:
            result[0] = api.setup()
        except Exception as e:
            exception[0] = e

    print(f"Setting up API connection with {timeout_seconds}s timeout...")
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        print(f"WARNING: API setup timed out after {timeout_seconds} seconds")
        print("This might be due to network issues or API server problems")
        print("Starting UI anyway - you can try reconnecting from the UI...")
        return False

    if exception[0]:
        print(f"API setup failed: {exception[0]}")
        return False

    print("API setup successful!")
    return True


def get_execution_context(api):
    """Get the current execution context (window and short positions)"""
    execWindow = api.getOptionExecutionWindow()
    shorts = api.updateShortPosition()

    logger.debug(f"Execution window: {execWindow}")
    logger.debug(f"Short positions: {shorts}")

    return execWindow, shorts


def main():
    try:
        # Initialize Schwab API with retry for token authentication errors
        if not setup_api_with_retry(api):
            return

        # Run the modern Textual UI
        print("Starting Options Trading System...")
        run_textual_ui(api)

    except Exception as e:
        logger.error(f"Failed to initialize API: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        alert.botFailed(None, f"Failed to initialize API: {str(e)}")


# Updated main function to prevent hanging on API setup
def main_with_timeout():
    """Main entry point with timeout protection"""
    print("=" * 60)
    print("OPTIONS TRADING INTERFACE")
    print("=" * 60)
    
    # Clean up old log files (keep last 2 days)
    cleanup_old_logs()

    # Use the existing global API instance
    global api

    # Try to setup API with timeout protection (don't block UI startup)
    print("Attempting to connect to Schwab API...")
    try:
        api.setup()  # <-- This will block for manual authentication if needed
        api_connected = True
    except Exception as e:
        print(f"API setup failed: {e}")
        api_connected = False

    # Token validation before UI
    if api_connected:
        if not is_token_valid(api):
            print("Authentication failed or token is invalid. Please try again.")
            return

    if not api_connected:
        print("API connection failed or timed out")
        print("Starting UI anyway - you can try to reconnect from the interface")
        print("Check your internet connection and API credentials")

    # Always start the UI - user can retry connection from within the app
    print("Starting Trading UI...")
    try:
        from ui.screen_main import OptionsTradingApp
        app = OptionsTradingApp(api)
        app.run()
    except KeyboardInterrupt:
        print("👋 Goodbye!")
    except Exception as e:
        print(f"❌ UI Error: {e}")
        import traceback
        traceback.print_exc()

def is_token_valid(api):
    """Check if the API token is valid (returns True if valid, False if expired/invalid)"""
    try:
        # Try a lightweight API call that requires authentication
        api.getAccountInfo()  # or any method that fails on invalid token
        return True
    except Exception as e:
        if "token" in str(e).lower() or "authentication" in str(e).lower():
            return False
        return True  # If error is not auth-related, assume token is valid

if __name__ == "__main__":
    main_with_timeout()  # Use the timeout-protected version
