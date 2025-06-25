import time
from datetime import datetime, timedelta, time as time_module

import pytz
from colorama import Fore, Style
from tzlocal import get_localzone

import alert
import support
from api import Api
from cc import RollCalls, RollSPX
from configuration import (
    apiKey,
    apiRedirectUri,
    appSecret,
    debugMarketOpen,
)
from logger_config import get_logger
from strategies import BoxSpread, find_spreads
import traceback
from order_utils import reset_cancel_flag

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
            "timed out"
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
                # Calculate wait time with exponential backoff
                retry_wait = backoff_factor * (retry_count + 1)

                # Inform user about retry
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


def wait_for_execution_window(execWindow):
    if not execWindow["open"]:
        time_to_open = calculate_time_to_market_open()

        sleep_time = time_to_open.total_seconds()
        if sleep_time < 0:
            return

        seconds = int(sleep_time)
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60

        if sleep_time > support.defaultWaitTime:
            print("\rMarket is closed, rechecking in 30 minutes...", end="")
            time.sleep(support.defaultWaitTime)
        else:
            print(f"Market will open in {minutes} minutes and {seconds} seconds.")
            time.sleep(sleep_time)


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


def present_menu(default="1"):
    """Display menu options and get user selection"""
    # Reset cancel flag before showing menu
    reset_cancel_flag()

    menu_options = {
        "1": "Roll Short Options",
        "2": "Check Box Spreads",
        "3": "Check Vertical Spreads",
        "4": "Check Synthetic Covered Calls",
        "5": "View Margin Requirements",
        "0": "Exit",
    }

    while True:
        print("\n--- Welcome to Options Trading ---")
        for key, value in menu_options.items():
            print(f"{key}. {value}")

        choice = input(f"Please choose an option (default is {default}): ")
        if not choice:  # if user just presses enter, use the default value
            return default
        elif choice in menu_options.keys():  # replace with your valid options
            return choice
        else:
            print("Invalid option. Please enter a valid option.")


def get_option_function(option, api, shorts=None):
    """Map option numbers to their corresponding functions"""
    option_mapping = {
        "1": lambda: roll_short_positions(api, shorts),
        "2": lambda: BoxSpread(api, "$SPX"),
        "3": lambda: find_spreads(api),
        "4": lambda: find_spreads(api, synthetic=True),
        "5": lambda: Api.display_margin_requirements(api, shorts),
    }

    return option_mapping.get(option)


def execute_option(api, option, exec_window, shorts=None):
    """Execute the selected option with error handling and retries"""
    # Reset cancel flag before executing any option
    reset_cancel_flag()

    # Display market status information
    display_market_status(exec_window)

    # Don't proceed if market is closed and we're not in debug mode
    if not exec_window["open"] and not debugMarketOpen:
        return False

    # Get and execute the function corresponding to the selected option
    func = get_option_function(option, api, shorts)
    if not func:
        logger.warning(f"Invalid option selected: {option}")
        print(f"Invalid option: {option}")
        return False

    # Execute the function with retry logic
    result = handle_retry(func, max_retries=3)

    # Only sleep if the function executed successfully
    if result is not False:
        sleep_time = get_sleep_time(exec_window)
        print(f"Sleeping for {sleep_time} seconds...")
        time.sleep(sleep_time)

    return result


def display_market_status(exec_window):
    """Display information about the current market status"""
    if exec_window["open"]:
        print("Market is open, running the program now...")
    else:
        message = "Market is closed"
        if debugMarketOpen:
            message += " but the program will work in debug mode"
        print(message + ".")


def get_sleep_time(exec_window):
    """Determine how long to sleep after executing an option"""
    now = datetime.now(get_localzone())
    current_time = now.time()

    # If market is open and it's after 3:30 PM, use short sleep time
    if exec_window["open"] and current_time >= time_module(15, 30):
        return 5

    # Otherwise use longer sleep time
    return 30


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


def get_execution_context(api):
    """Get the current execution context (window and short positions)"""
    execWindow = api.getOptionExecutionWindow()
    shorts = api.updateShortPosition()

    logger.debug(f"Execution window: {execWindow}")
    logger.debug(f"Short positions: {shorts}")

    return execWindow, shorts

def process_menu_option(api, option):
    """Process a single menu option execution with error handling"""
    def run_option():
        execWindow, shorts = get_execution_context(api)

        if debugMarketOpen or execWindow["open"]:
            return execute_option(api, option, execWindow, shorts)
        else:
            wait_for_execution_window(execWindow)
            return None  # Continue the loop after waiting

        result = handle_retry(run_option)
        return result  # Return the result to main loop

    except KeyboardInterrupt:
        logger.info("Operation interrupted by user.")
        print("\nInterrupted. Going back to main menu...")
        raise  # Re-raise so main() can handle and break the loop

def main():
    try:
        # Initialize Schwab API with retry for token authentication errors
        if not setup_api_with_retry(api):
            return

        while True:  # Outer loop for main menu
            option = present_menu()
            if option == "0":
                return
            try:
                while True:  # Inner loop for auto-repeat
                    process_menu_option(api, option)
            except KeyboardInterrupt:
                logger.info("Program interrupted by user. Exiting to main menu.")
                print("\nInterrupted. Exiting to main menu...")
                continue  # Go back to main menu
            except Exception as e:
                logger.error(f"Unhandled error: {str(e)}")
                logger.debug(f"Full traceback: {traceback.format_exc()}")
                alert.botFailed(None, f"Unhandled error: {str(e)}")
                break

    except Exception as e:
        logger.error(f"Failed to initialize API: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        alert.botFailed(None, f"Failed to initialize API: {str(e)}")


if __name__ == "__main__":
    main()
