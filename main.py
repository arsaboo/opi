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
    SPREADSHEET_ID,
    apiKey,
    apiRedirectUri,
    appSecret,
    debugMarketOpen,
    enableTaxTracking,
)
from logger_config import get_logger
from sheets_api import SheetsAPI
from strategies import BoxSpread, find_spreads
from tax_tracker import TaxTracker

logger = get_logger()  # use get_logger(True) to use the underlying logger

# Initialize APIs
api = Api(apiKey, apiRedirectUri, appSecret)

# Lazy initialization of tax tracking components
_sheets_api = None
_tax_tracker = None


def get_tax_tracker():
    """Lazy initialization of tax tracking components"""
    global _sheets_api, _tax_tracker
    if enableTaxTracking and _tax_tracker is None:
        _sheets_api = SheetsAPI(SPREADSHEET_ID)
        _sheets_api.authenticate()
        _tax_tracker = TaxTracker(_sheets_api)
    return _tax_tracker


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

def display_tax_menu():
    tax_tracker = get_tax_tracker()
    if not tax_tracker:
        print("Tax tracking is not enabled.")
        return True

    menu_options = {
        "1": "View Year-to-Date Summary",
        "2": "Analyze Tax Implications",
        "3": "Export Tax Report",
        "0": "Back to Main Menu",
    }

    while True:
        print("\n--- Tax Management ---")
        for key, value in menu_options.items():
            print(f"{key}. {value}")

        choice = input("Please choose an option: ")

        if choice == "0":
            break  # Exit the tax menu loop
        elif choice == "1":
            year = datetime.now().year
            summary = tax_tracker.get_year_summary(year)

            # Debug: Print raw category names from the data
            print("\nDEBUG - Available categories in data:", list(summary["transactions_by_type"].keys()))

            # Updated category mapping with all possible variations
            transaction_categories = {
                "Options": "Option Transactions",
                "Option": "Option Transactions",
                "Option Premium": "Option Transactions",
                "Stock": "Stock Transactions",
                "Stocks": "Stock Transactions",
                "Stock Sales": "Stock Transactions",
                "Dividend": "Dividend Income",
                "Dividends": "Dividend Income"
            }

            # Group transactions by display title
            grouped_transactions = {}
            for category, transactions in summary["transactions_by_type"].items():
                if category in transaction_categories:
                    title = transaction_categories[category]
                    if title not in grouped_transactions:
                        grouped_transactions[title] = []
                    grouped_transactions[title].extend(transactions)

            # Display tables in specific order
            display_order = ["Option Transactions", "Stock Transactions", "Dividend Income"]

            for title in display_order:
                if title in grouped_transactions:
                    print_transaction_table(
                        title,
                        grouped_transactions[title],
                        title
                    )

            # Print summary section
            print("\nYear-to-Date Summary:")
            print("-" * 50)
            print(f"{'Total Income:':<33} {format_amount(summary['total_income']):>15}")
            print(f"{'Option Income:':<33} {format_amount(summary['option_income']):>15}")
            print(f"{'Stock Gains:':<33} {format_amount(summary['stock_gains']):>15}")
            print(f"{'Dividends:':<33} {format_amount(summary['dividends']):>15}")
            print("-" * 50)

        elif choice == "2":
            year = datetime.now().year
            analysis = tax_tracker.analyze_tax_implications(year)
            print(f"\nTax Analysis for {year}:")
            print(f"\tTotal Taxable Income: ${analysis['total_taxable_income']:,.2f}")
            print("\nRecommendations:")
            for rec in analysis["recommendations"]:
                print(f"- {rec}")
        elif choice == "3":
            year = datetime.now().year
            filename = tax_tracker.export_tax_report(year)
            print(f"\nTax report exported to: {filename}")
        else:
            print("Invalid option. Please try again.")

    return True  # Indicate we're returning to main menu


def present_menu(default="1"):
    menu_options = {
        "1": "Roll Short Options",
        "2": "Check Box Spreads",
        "3": "Check Vertical Spreads",
        "4": "Check Synthetic Covered Calls",
        "5": "View Margin Requirements",
        "6": "Tax Management" if enableTaxTracking else None,
        "0": "Exit",
    }

    # Remove None values from menu_options
    menu_options = {k: v for k, v in menu_options.items() if v is not None}

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
        "6": lambda: display_tax_menu() if enableTaxTracking else None,
    }

    if option in option_mapping:
        func = option_mapping[option]
        if func:  # Only execute if the function exists (not None)
            result = func()
            if result:  # If a function returns True (like tax menu), break the loop
                return True
            # Only sleep if not returning from tax menu
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
