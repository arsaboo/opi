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
        for short in shorts:
            # check if any option is expiring today
            dte = (
                datetime.strptime(short["expiration"], "%Y-%m-%d") - datetime.now()
            ).days
            #short = {'stockSymbol': 'WELL', 'optionSymbol': 'WELL  240528C05250000', 'expiration': '2024-05-28', 'count': 1.0, 'strike': '5250', 'receivedPremium': 72.4897}
            # short = {'stockSymbol': 'MSFT', 'optionSymbol': 'MSFT  240531C00400000', 'expiration': '2024-05-31', 'count': 1.0, 'strike': '400', 'receivedPremium': 72.4897}
            if dte <= 1:
                print("Option expiring today: ", short)
                if short["stockSymbol"] == "$SPX":
                    RollSPX(api, short)
                else:
                    RollCalls(api, short)
                    # end the program
                    continue

        if execWindow["openDate"]:

            break

        if rollDate1Am is not None and tomorrow1Am < rollDate1Am:
            # we don't need to do anything, but we are making a call every day to make sure the refresh token stays valid
            print("Token refreshed, waiting for roll date in %s" % rollDate1Am)

            time.sleep(tomorrow1Am.total_seconds())
        else:
            if debugMarketOpen or execWindow["open"]:
                print("Market open, running the program now ...")

                # writeCcs(api)

                nextRollDate = support.getDeltaDiffNowNextRollDate1Am()

                print("All done. The next roll date is in %s" % nextRollDate)

                # we are making a call every day to make sure the refresh token stays valid
                time.sleep(tomorrow1Am.total_seconds())
            else:
                if execWindow["openDate"]:
                    print("Waiting for execution window to open ...")

                    delta = execWindow["openDate"] - execWindow["nowDate"]

                    if delta > datetime.timedelta(0):
                        print("Window open in: %s. waiting ..." % delta)
                        time.sleep(delta.total_seconds())
                    else:
                        # we are past open date, but the market is not open
                        print(
                            "Market closed already. Rechecking tomorrow (in %s)"
                            % tomorrow1Am
                        )

                        time.sleep(tomorrow1Am.total_seconds())
                else:
                    print("The market is closed today, rechecking in 30 minutes ...")
                    time.sleep(support.defaultWaitTime)
except Exception as e:
    alert.botFailed(None, "Uncaught exception: " + str(e))
