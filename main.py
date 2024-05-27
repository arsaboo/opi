from cc import RollSPX, RollCalls
import time
from configuration import (
    apiKey,
    apiRedirectUri,
    appSecret,
    debugMarketOpen,
    loggingLevel,
)
from api import Api
from datetime import datetime
import alert
import support
import logging
from optionChain import OptionChain

logger = logging.getLogger(__name__)
stream_handler = logging.StreamHandler()

# Set the level of the StreamHandler to INFO
stream_handler.setLevel(getattr(logging, loggingLevel.upper()))

# Get the root logger and add the StreamHandler to it
root_logger = logging.getLogger()
root_logger.addHandler(stream_handler)
root_logger.setLevel(getattr(logging, loggingLevel.upper()))

api = Api(apiKey, apiRedirectUri, appSecret)

try:
    while True:
        api.setup()
        logger.info("Account Hash: " + api.getAccountHash())
        execWindow = api.getOptionExecutionWindow()
        rollDate1Am = support.getDeltaDiffNowNextRollDate1Am()
        tomorrow1Am = support.getDeltaDiffNowTomorrow1Am()
        shorts = api.updateShortPosition()
        logger.info(
            f"Execution Window: {execWindow}, Roll Date: {rollDate1Am}, Tomorrow: {tomorrow1Am}"
        )
        if debugMarketOpen or execWindow["open"]:
            if not execWindow["open"]:
                print("Market is closed, but the program will work in debug mode.")
            else:
                print("Market open, running the program now ...")
            for short in shorts:
                # check if any option is expiring today
                dte = (
                    datetime.strptime(short["expiration"], "%Y-%m-%d") - datetime.now()
                ).days
                #short = {'stockSymbol': 'WELL', 'optionSymbol': 'WELL  240528C05250000', 'expiration': '2024-05-28', 'count': 1.0, 'strike': '5250', 'receivedPremium': 72.4897}
                #short = {'stockSymbol': 'MSFT', 'optionSymbol': 'MSFT  240531C00250000', 'expiration': '2024-05-31', 'count': 1.0, 'strike': '250', 'receivedPremium': 72.4897}
                if dte <= 1:
                    print(f"{short['count']} {short['stockSymbol']} expiring today: {short['optionSymbol']}")
                    if short["stockSymbol"] == "$SPX":
                        RollSPX(api, short)
                    else:
                        RollCalls(api, short)
        else:
            if execWindow["openDate"]:
                print("Waiting for execution window to open ...")
                delta = execWindow["openDate"] - execWindow["nowDate"]
                if delta > datetime.timedelta(0):
                    print("Window open in: %s. waiting ..." % delta)
                    time.sleep(delta.total_seconds())
                else:
                    print(
                        "Market closed already. Rechecking tomorrow (in %s)" % tomorrow1Am
                    )
                    time.sleep(tomorrow1Am.total_seconds())
            else:
                print("The market is closed today, rechecking in 30 minutes ...")
                time.sleep(support.defaultWaitTime)
                execWindow = api.getOptionExecutionWindow()
        print("Sleeping for 60 seconds...")
        time.sleep(60)
except Exception as e:
    alert.botFailed(None, "Uncaught exception: " + str(e))
