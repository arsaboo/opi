import time
from datetime import datetime, timedelta
from datetime import time as time_module

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

logger = get_logger()

# Initialize API
api = Api(apiKey, apiRedirectUri, appSecret)


def roll_short_positions(api, shorts):
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
            func()
            sleep_time = (
                5
                if exec_window["open"]
                and datetime.now(get_localzone()).time() >= time_module(15, 30)
                else 30
            )
            print(f"Sleeping for {sleep_time} seconds...")
            time.sleep(sleep_time)
    else:
        print(f"Invalid option: {option}")


def main():
    try:
        # Initialize Schwab API
        api.setup()

        while True:
            try:
                option = present_menu()
                if option == "0":
                    break
                while True:
                    execWindow = api.getOptionExecutionWindow()
                    shorts = api.updateShortPosition()

                    logger.debug(f"Execution: {execWindow}")

                    if debugMarketOpen or execWindow["open"]:
                        result = execute_option(api, option, execWindow, shorts)
                        if (
                            result
                        ):  # If a function returns True (like tax menu), break inner loop
                            break
                    else:
                        wait_for_execution_window(execWindow)

            except KeyboardInterrupt:
                print("\nInterrupted. Going back to the main menu...")
            except Exception as e:
                alert.botFailed(None, "Uncaught exception: " + str(e))
                break  # Exit the program if an unhandled exception occurs

    except Exception as e:
        alert.botFailed(None, "Failed to initialize APIs: " + str(e))


if __name__ == "__main__":
    main()
