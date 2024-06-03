import time
from datetime import datetime
from datetime import time as time_module
from datetime import timedelta

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
    for short in shorts:
        # short = {"optionSymbol": "SPX   240606C05315000", "expiration": "2024-06-03", "strike": "5315", "count": 1.0, "stockSymbol": "$SPX", "receivedPremium": 72.4897}
        # short = {'stockSymbol': 'MSFT', 'optionSymbol': 'MSFT  240531C00350000', 'expiration': '2024-05-31', 'count': 1.0, 'strike': '350', 'receivedPremium': 72.4897}
        dte = (
            datetime.strptime(short["expiration"], "%Y-%m-%d").date()
            - datetime.now(pytz.UTC).date()
        ).days
        if dte <= 7:
            if dte == 0:
                print(
                    f"{short['count']} {short['stockSymbol']} expiring {Fore.RED}TODAY{Style.RESET_ALL}: {short['optionSymbol']}"
                )
            else:
                print(
                    f"{short['count']} {short['stockSymbol']} expiring in {Fore.GREEN}{dte} day(s){Style.RESET_ALL}: {short['optionSymbol']}"
                )
            roll_function = RollSPX if short["stockSymbol"] == "$SPX" else RollCalls
            roll_function(api, short)
        else:
            print("No options expiring within 7 days.")


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
        "5": "Exit"
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


def execute_option(api, option, execWindow, shorts=None):
    if not execWindow["open"]:
        print("Market is closed, but the program will work in debug mode.")
    else:
        print("Market open, running the program now ...")

    if option == "1":
        roll_short_positions(api, shorts)
    elif option == "2":
        BoxSpread(api, "$SPX")
    elif option == "3":
        find_spreads(api)
    elif option == "4":
        find_spreads(api, synthetic=True)
    sleep_time = (
        5
        if execWindow["open"]
        and datetime.now(get_localzone()).time() >= time_module(15, 30)
        else 30
    )
    print(f"Sleeping for {sleep_time} seconds...")
    time.sleep(sleep_time)


def main():
    while True:
        try:
            option = present_menu()
            if option == "5":  # Assuming 4 is the option to exit
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
