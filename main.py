import time
from datetime import datetime, timedelta

import pytz

import alert
import support
from api import Api
from cc import RollCalls, RollSPX
from configuration import apiKey, apiRedirectUri, appSecret, debugMarketOpen
from logger_config import get_logger

logger = get_logger()  # use get_logger(True) to use the underlying logger
api = Api(apiKey, apiRedirectUri, appSecret)


def check_short_positions(api, shorts):
    for short in shorts:
        short = {'stockSymbol': '$SPX', 'optionSymbol': 'SPXW  240529C05400000', 'expiration': '2024-05-29', 'count': 1.0, 'strike': '5400', 'receivedPremium': 72.4897}
        # short = {'stockSymbol': 'MSFT', 'optionSymbol': 'MSFT  240531C00250000', 'expiration': '2024-05-31', 'count': 1.0, 'strike': '250', 'receivedPremium': 72.4897}
        dte = (
            datetime.strptime(short["expiration"], "%Y-%m-%d").date()
            - datetime.now(pytz.UTC).date()
        ).days
        if dte <= 1:
            print(
                f"{short['count']} {short['stockSymbol']} expiring today: {short['optionSymbol']}"
            )
            roll_function = RollSPX if short["stockSymbol"] == "$SPX" else RollCalls
            roll_function(api, short)


def wait_for_execution_window(execWindow):
    if not execWindow["open"]:
        #find out how long before 9:30 am in the morning
        now = datetime.now(pytz.UTC)
        time_to_open = now.replace(hour=9, minute=30, second=0, microsecond=0) - now

        if time_to_open.total_seconds() < 0:
            # If we are past 9:30 AM, calculate the time to 9:30 AM the next day
            time_to_open += timedelta(days=1)

        sleep_time = time_to_open.total_seconds()
        if sleep_time < 0:
            return
        seconds = int(sleep_time)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        logger.debug(
            f"Market open in {hours} hours, {minutes} minutes, and {seconds} seconds. We will keep rechecking every 30 minutes."
        )
        if sleep_time > support.defaultWaitTime:
            time.sleep(support.defaultWaitTime)
        else:
            time.sleep(sleep_time)


def main():
    try:
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
                if not execWindow["open"] and not debugMarketOpen:
                    print("Market is closed, but the program will work in debug mode.")
                else:
                    print("Market open, running the program now ...")
                check_short_positions(api, shorts)
                print("Sleeping for 60 seconds...")
                time.sleep(60)
            else:
                print("\rMarket is closed, rechecking in 30 minutes...", end="")
                #time.sleep(support.defaultWaitTime)
                wait_for_execution_window(execWindow)

    except KeyboardInterrupt:
        print("Exiting the program ...")
    except Exception as e:
        alert.botFailed(None, "Uncaught exception: " + str(e))


if __name__ == "__main__":
    main()
