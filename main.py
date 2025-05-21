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


def wait_for_execution_window(execWindow):
    if not execWindow["open"]:
        # find out how long before 9:30 am in the morning
        now = datetime.now(get_localzone())
        time_to_open = now.replace(hour=9, minute=30, second=0, microsecond=0) - now

        if time_to_open.total_seconds() < 0:
            # If we are past 9:30 AM, calculate the time to 9:30 AM the next day
            time_to_open += timedelta(days=1)

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


def execute_option(api, option, exec_window, shorts=None):
    # Reset cancel flag before executing any option
    reset_cancel_flag()

    # Show both debug mode and market status
    if exec_window["open"]:
        print("Market is open, running the program now...")
    else:
        print(
            "Market is closed"
            + (" but the program will work in debug mode" if debugMarketOpen else "")
            + "."
        )
        if not debugMarketOpen:
            return

    option_mapping = {
        "1": lambda: roll_short_positions(api, shorts),
        "2": lambda: BoxSpread(api, "$SPX"),
        "3": lambda: find_spreads(api),
        "4": lambda: find_spreads(api, synthetic=True),
        "5": lambda: Api.display_margin_requirements(api, shorts),
    }

    if option in option_mapping:
        func = option_mapping[option]
        if func:  # Only execute if the function exists (not None)
            option_error_retries = 0
            max_option_retries = 3

            while option_error_retries < max_option_retries:
                try:
                    func()
                    sleep_time = (
                        5
                        if exec_window["open"]
                        and datetime.now(get_localzone()).time() >= time_module(15, 30)
                        else 30
                    )
                    print(f"Sleeping for {sleep_time} seconds...")
                    time.sleep(sleep_time)
                    return  # Exit after successful execution
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"Error executing option {option}: {str(e)}")
                    logger.debug(f"Full traceback: {traceback.format_exc()}")

                    # Check if this is a recoverable error
                    if ("token_invalid" in error_str or
                        "connection was forcibly closed" in error_str or
                        "WinError 10054" in error_str or
                        "ConnectionRefusedError" in error_str or
                        "ConnectionResetError" in error_str or
                        "read operation timed out" in error_str or
                        "timed out" in error_str):

                        option_error_retries += 1
                        if option_error_retries >= max_option_retries:
                            # If we've reached max retries, alert and exit
                            alert.botFailed(None, f"Error in option {option} after {max_option_retries} attempts: {error_str}")
                            return False

                        # Wait with exponential backoff
                        retry_wait = 3 * option_error_retries
                        print(f"\nRecoverable error detected: {error_str}")
                        print(f"Attempting to retry option {option} (attempt {option_error_retries}/{max_option_retries})...")
                        print(f"Waiting {retry_wait} seconds before retry...")
                        time.sleep(retry_wait)
                        print(f"Retrying option {option}...")
                        continue

                    # Non-recoverable error
                    alert.botFailed(None, f"Error in option {option}: {error_str}")
                    return False
    else:
        logger.warning(f"Invalid option selected: {option}")
        print(f"Invalid option: {option}")


def main():
    try:
        # Initialize Schwab API with retry for token authentication errors
        setup_attempts = 0
        max_attempts = 3

        while setup_attempts < max_attempts:
            try:
                api.setup()
                break  # If setup is successful, exit the retry loop
            except Exception as e:
                setup_attempts += 1
                error_str = str(e)
                logger.error(f"Error while setting up the api: {error_str}")

                # Check for token authentication error
                if "refresh_token_authentication_error" in error_str and setup_attempts < max_attempts:
                    logger.info("Detected refresh token authentication error. Attempting to delete token and retry...")
                    print("Token authentication failed. Deleting existing token and retrying...")

                    # Reset/delete the token
                    api.delete_token()

                    if setup_attempts < max_attempts:
                        print(f"Retrying authentication (attempt {setup_attempts+1}/{max_attempts})...")
                        time.sleep(2)  # Brief pause before retry
                        continue

                # If we've reached max attempts or it's not a token error, raise the exception
                if setup_attempts >= max_attempts:
                    logger.error(f"Failed to initialize API after {max_attempts} attempts")
                    alert.botFailed(None, f"Failed to initialize API after {max_attempts} attempts: {error_str}")
                    return
                raise  # Re-raise the exception if it's not a token error

        while True:
            try:
                option = present_menu()
                if option == "0":
                    break

                # Counter for token invalid errors within this menu option execution
                token_error_retries = 0
                max_token_retries = 3

                while True:
                    try:
                        execWindow = api.getOptionExecutionWindow()
                        shorts = api.updateShortPosition()

                        logger.debug(f"Execution window: {execWindow}")
                        logger.debug(f"Short positions: {shorts}")

                        if debugMarketOpen or execWindow["open"]:
                            result = execute_option(api, option, execWindow, shorts)
                            if result:
                                break
                        else:
                            wait_for_execution_window(execWindow)

                        # Reset token error counter on successful execution
                        token_error_retries = 0

                    except Exception as e:
                        error_str = str(e)
                        logger.error(f"Error in main loop: {error_str}")
                        logger.debug(f"Full traceback: {traceback.format_exc()}")                        # Check for various errors that can be resolved with a simple retry
                        # Including token_invalid errors and network connection errors
                        if (("token_invalid" in error_str or
                            "connection was forcibly closed" in error_str or
                            "WinError 10054" in error_str or
                            "ConnectionRefusedError" in error_str or
                            "ConnectionResetError" in error_str or
                            "read operation timed out" in error_str or
                            "timed out" in error_str) and
                            token_error_retries < max_token_retries):

                            token_error_retries += 1
                            logger.info(f"Recoverable error detected. Attempting to retry operation (attempt {token_error_retries}/{max_token_retries})...")
                            print(f"\nRecoverable error detected: {error_str}")
                            print(f"Attempting to retry operation (attempt {token_error_retries}/{max_token_retries})...")

                            # Simple wait before retry with exponential backoff
                            retry_wait = 3 * token_error_retries  # Increase wait time with each retry
                            print(f"Waiting {retry_wait} seconds before retry...")
                            time.sleep(retry_wait)
                            print("Retrying operation...")
                            continue  # Skip to next iteration with a simple retry

                        alert.botFailed(None, f"Error in main loop: {error_str}")
                        break

            except KeyboardInterrupt:
                logger.info("Program interrupted by user. Going back to main menu.")
                print("\nInterrupted. Going back to the main menu...")
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
