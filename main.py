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
from configuration import apiKey, apiRedirectUri, appSecret, debugMarketOpen
from logger_config import get_logger
from strategies import BoxSpread, find_spreads

logger = get_logger()  # use get_logger(True) to use the underlying logger
api = Api(apiKey, apiRedirectUri, appSecret)


def roll_short_positions(api, shorts):
    any_expiring = False  # flag to track if any options are expiring within 7 days
    today = datetime.now(pytz.UTC).date()

    for short in shorts:
        dte = (datetime.strptime(short["expiration"], "%Y-%m-%d").date() - today).days
        # short = {"optionSymbol": "SPXW  240622C05100000", "expiration": "2024-06-22", "strike": "5100", "count": 1.0, "stockSymbol": "$SPX", "receivedPremium": 72.4897}
        # short = {'stockSymbol': 'MSFT', 'optionSymbol': 'MSFT  240531C00350000', 'expiration': '2024-05-31', 'count': 1.0, 'strike': '350', 'receivedPremium': 72.4897}
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


def present_menu(default="1"):
    menu_options = {
        "1": "Roll Short Options",
        "2": "Check Box Spreads",
        "3": "Check Vertical Spreads",
        "4": "Check Synthetic Covered Calls",
        "0": "Exit",
    }

    while True:
        print("--- Welcome to Options Trading ---")
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
    if not exec_window["open"]:
        print("Market is closed, but the program will work in debug mode.")
    else:
        print("Market open, running the program now ...")

    option_mapping = {
        "1": lambda: roll_short_positions(api, shorts),
        "2": lambda: BoxSpread(api, "$SPX"),
        "3": lambda: find_spreads(api),
        "4": lambda: find_spreads(api, synthetic=True),
    }

    if option in option_mapping:
        option_mapping[option]()
    else:
        print(f"Invalid option: {option}")

    sleep_time = (
        5
        if exec_window["open"]
        and datetime.now(get_localzone()).time() >= time_module(15, 30)
        else 30
    )
    print(f"Sleeping for {sleep_time} seconds...")
    time.sleep(sleep_time)


def main():
    while True:
        try:
            option = present_menu()
            if option == "0":
                break
            while True:
                try:
                    api.setup()
                except Exception as e:
                    alert.botFailed(None, "Failed to setup the API: " + str(e))
                    return

                execWindow = api.getOptionExecutionWindow()
                shorts = api.updateShortPosition()

                logger.debug(f"Execution: {execWindow}")

                if debugMarketOpen or execWindow["open"]:
                    execute_option(api, option, execWindow, shorts)
                else:
                    wait_for_execution_window(execWindow)

        except KeyboardInterrupt:
            print("\nInterrupted. Going back to the main menu...")
        except Exception as e:
            alert.botFailed(None, "Uncaught exception: " + str(e))
            break  # Exit the program if an unhandled exception occurs


if __name__ == "__main__":
    main()
