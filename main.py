import time
from datetime import datetime, timedelta
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
        dte = (datetime.strptime(short["expiration"], "%Y-%m-%d") - datetime.now()).days
        if dte <= 1:
            print(
                f"{short['count']} {short['stockSymbol']} expiring today: {short['optionSymbol']}"
            )
            roll_function = RollSPX if short["stockSymbol"] == "$SPX" else RollCalls
            roll_function(api, short)


def wait_for_execution_window(execWindow, tomorrow1Am):
    if execWindow["openDate"]:
        delta = execWindow["openDate"] - execWindow["nowDate"]
        sleep_time = (
            delta.total_seconds()
            if delta > timedelta(0)
            else tomorrow1Am.total_seconds()
        )
        time.sleep(sleep_time)
    else:
        print("The market is closed today, rechecking in 30 minutes ...")
        time.sleep(support.defaultWaitTime)


def main():
    try:
        while True:
            try:
                api.setup()
            except Exception as e:
                alert.botFailed(None, "Failed to setup the API: " + str(e))
                return
            execWindow = api.getOptionExecutionWindow()
            tomorrow1Am = support.getDeltaDiffNowTomorrow1Am()
            shorts = api.updateShortPosition()

            logger.debug(f"Execution: {execWindow}")
            logger.debug(f"Tomorrow: {tomorrow1Am}")

            if debugMarketOpen or execWindow["open"]:
                if not execWindow["open"]:
                    print("Market is closed, but the program will work in debug mode.")
                else:
                    print("Market open, running the program now ...")

                check_short_positions(api, shorts)

            else:
                wait_for_execution_window(execWindow, tomorrow1Am)

            print("Sleeping for 60 seconds...")
            time.sleep(60)

    except KeyboardInterrupt:
        print("Exiting the program ...")
    except Exception as e:
        alert.botFailed(None, "Uncaught exception: " + str(e))


if __name__ == "__main__":
    main()
