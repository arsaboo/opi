from configuration import configuration, dbName, debugEverythingNeedsRolling, AutoTrade
from datetime import datetime, timedelta
from support import ccExpDaysOffset
from optionChain import OptionChain
from statistics import median
from tinydb import TinyDB, Query
import time
import alert
import support
import statistics


class Cc:

    def __init__(self, asset):
        self.asset = asset

    def findNew(self, api, existing, existingPremium):
        asset = self.asset

        newccExpDate = support.getNewCcExpirationDate()

        # get option chain of third thursday and friday of the month
        optionChain = OptionChain(api, asset, newccExpDate, 1)

        chain = optionChain.get()

        if not chain:
            return alert.botFailed(
                asset, "No chain found on the third thursday OR friday"
            )

        # get closest chain to days
        # it will get friday most of the time, but if a friday is a holiday f.ex. the chain will only return a thursday date chain
        closestChain = chain[-1]

        atmPrice = api.getATMPrice(asset)
        strikePrice = atmPrice + configuration[asset]["minGapToATM"]

        minStrike = configuration[asset]["minStrike"]

        if existing:
            maxDrawdownStrike = (
                existing["strike"] - configuration[asset]["maxDrawdownGap"]
            )
        else:
            maxDrawdownStrike = None

        if maxDrawdownStrike and maxDrawdownStrike > strikePrice:
            print("Applying max drawdown (" + str(maxDrawdownStrike) + ") ...")
            strikePrice = maxDrawdownStrike

        if minStrike > strikePrice:
            print("Min strike hit, applying (" + str(minStrike) + ") ...")
            strikePrice = minStrike

        #  get the best matching contract
        contract = optionChain.getContractFromDateChain(
            strikePrice, closestChain["contracts"]
        )

        if not contract:
            return alert.botFailed(asset, "No contract over minStrike found")

        # check minYield
        projectedPremium = median([contract["bid"], contract["ask"]])

        if projectedPremium < existingPremium:
            if existing:
                print(
                    "Failed to write contract for CREDIT with CC ("
                    + str(contract["strike"])
                    + "), now trying to get a lower strike ..."
                )

                # we need to get a lower strike instead to not pay debit
                contract = optionChain.getContractFromDateChainByMinYield(
                    existing["strike"],
                    strikePrice,
                    existingPremium,
                    closestChain["contracts"],
                )

                # edge case where this new contract fails:
                # - If even a calendar roll wouldn't result in a credit
                # - If we have a 301 f.ex. but the new chain only has 300 or 305 with less premium than the 301
                #   to prevent failing, we could f.ex. check maxRollupGap, ignoring deepITMLimit and if we can rollup for debit, then do that instead of failing
                if not contract:
                    return alert.botFailed(
                        asset,
                        "couldn't find contract for CREDIT above last strike price",
                    )

                deepItmLimitStrike = atmPrice - configuration[asset]["deepITMLimit"]

                #  allow to pay for roll up if we are too far itm
                if (
                    configuration[asset]["maxRollupGap"] > 0
                    and contract["strike"] < deepItmLimitStrike
                ):
                    maxRollupGapStrike = (
                        existing["strike"] + configuration[asset]["maxRollupGap"]
                    )

                    # rollup to deepITMLimit, with a max jump of maxRollupGap per month
                    rollUpStrike = (
                        maxRollupGapStrike
                        if maxRollupGapStrike < deepItmLimitStrike
                        else deepItmLimitStrike
                    )

                    if rollUpStrike > contract["strike"]:
                        print(
                            "Could roll to "
                            + str(contract["strike"])
                            + " for CREDIT, but its too far ITM ..."
                        )
                        print(
                            "Rolling towards deepITMLimit instead with this contract: "
                            + str(rollUpStrike)
                            + ", paying debit ..."
                        )
                        contract = optionChain.getContractFromDateChain(
                            rollUpStrike, closestChain["contracts"]
                        )
                        # todo should we check if the account has enough cash to rollup to this contract?

                projectedPremium = median([contract["bid"], contract["ask"]])
            else:
                return alert.botFailed(
                    asset,
                    "Api / code error: No existing contract and projected premium for "
                    + str(strikePrice)
                    + " is smaller than "
                    + str(existingPremium),
                )

        return {
            "date": closestChain["date"],
            "days": closestChain["days"],
            "contract": contract,
            "projectedPremium": projectedPremium,
        }


def RollSPX(api, short):
    toDate = datetime.today() + timedelta(days=90)
    # chain = api.getOptionChain("$SPX", strikes=150, date=toDate, daysLessAllowed=90)
    optionChain = OptionChain(api, "$SPX", toDate, 90)
    chain = optionChain.get()
    # print(chain)
    print("Rolling SPX contract: ", short["optionSymbol"])

    prem_short_contract = get_median_price(short["optionSymbol"], chain)
    print("Premium of short contract: ", prem_short_contract)
    roll = find_best_rollover(chain, short["optionSymbol"])
    print("Best rollover contract: ", roll)
    roll_premium = get_median_price(roll["symbol"], chain)
    increase = roll_premium - prem_short_contract
    print(
        f"Best rollover contract: {roll['symbol']} with premium: {roll_premium} and increase: {increase}"
    )


def get_median_price(symbol, data):
    # Traversing through each contract in the JSON data
    for entry in data:
        print(entry["date"])
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                # Calculate the median of the bid and ask
                bid = contract["bid"]
                ask = contract["ask"]
                median = (bid + ask) / 2
                return median

    # If the symbol is not found, return None
    return None


def find_best_rollover(data, short_option):
    short_strike = None
    short_median = None
    short_expiry = None

    # Find the details of the short option
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == short_option:
                short_strike = contract["strike"]
                short_median = statistics.median([contract["bid"], contract["ask"]])
                short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                break
        if short_strike and short_median and short_expiry:
            break

    if short_strike is None or short_median is None or short_expiry is None:
        return None

    # Sort the entries by their dates
    entries = sorted(
        data, key=lambda entry: datetime.strptime(entry["date"], "%Y-%m-%d")
    )

    # Find the first option that gives a $15 premium and rolls up the strike price by $50
    best_option = None
    closest_days_diff = None
    for entry in entries:
        expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        days_diff = (expiry_date - short_expiry).days
        if days_diff > 30:
            continue

        for contract in entry["contracts"]:
            contract_median = statistics.median([contract["bid"], contract["ask"]])
            if (
                contract["strike"] > short_strike + 50
                and contract_median - short_median >= 15
                and contract["optionRoot"] == "SPXW"
            ):
                if best_option is None or abs(30 - days_diff) < closest_days_diff:
                    best_option = contract
                    closest_days_diff = abs(30 - days_diff)

            # If we haven't found an option yet, keep track of the option that gives at least $10 premium and has the highest strike price
            elif (
                contract["strike"] > short_strike
                and contract_median - short_median >= 10
            ):
                if (
                    best_option is None
                    or abs(30 - days_diff) < closest_days_diff
                    or contract["strike"] > best_option["strike"]
                ):
                    best_option = contract
                    closest_days_diff = abs(30 - days_diff)

    return best_option


def writeCcs(api):
    for asset in configuration:
        asset = asset.upper()
        cc = Cc(asset)

        try:
            existing = cc.existing()[0]
        except IndexError:
            existing = None

        if (existing and needsRolling(existing)) or not existing:
            amountToSell = configuration[asset]["amountOfHundreds"]

            if existing:
                existingSymbol = existing["optionSymbol"]
                amountToBuyBack = existing["count"]
                existingPremium = api.getATMPrice(existing["optionSymbol"])
            else:
                existingSymbol = None
                amountToBuyBack = 0
                existingPremium = 0

            new = cc.findNew(api, existing, existingPremium)

            print("The bot wants to write the following contract:")
            print(new)

            if not api.checkAccountHasEnoughToCover(
                asset,
                existingSymbol,
                amountToBuyBack,
                amountToSell,
                new["contract"]["strike"],
                new["date"],
            ):
                return alert.botFailed(
                    asset,
                    "The account doesn't have enough shares or options to cover selling "
                    + str(amountToSell)
                    + " cc('s)",
                )
            writeCc(
                api,
                asset,
                new,
                existing,
                existingPremium,
                amountToBuyBack,
                amountToSell,
                autoTrade=AutoTrade,
            )
        else:
            print("Nothing to write ...")


def needsRolling(cc):
    if debugEverythingNeedsRolling:
        return True

    # needs rolling on date BEFORE expiration (if the market is closed, it will trigger ON expiration date)
    nowPlusOffset = (
        datetime.datetime() + datetime.timedelta(days=ccExpDaysOffset)
    ).strftime("%Y-%m-%d")

    return nowPlusOffset >= cc["expiration"]


def writeCc(
    api,
    asset,
    new,
    existing,
    existingPremium,
    amountToBuyBack,
    amountToSell,
    retry=0,
    partialContractsSold=0,
    autoTrade=True,
):
    maxRetries = 75
    # lower the price by 1% for each retry if we couldn't get filled
    orderPricePercentage = 100 - retry
    if not autoTrade:
        confirmation = input("Do you want to place the trade? (yes/no): ")
        if confirmation.lower() != "yes":
            print("Trade cancelled.")
            return

    if retry > maxRetries:
        return alert.botFailed(
            asset,
            "Order cant be filled, tried with "
            + str(orderPricePercentage + 1)
            + "% of the price.",
        )

    if existing and existingPremium:
        orderId = api.writeNewContracts(
            existing["optionSymbol"],
            amountToBuyBack,
            existingPremium,
            new["contract"]["symbol"],
            amountToSell,
            new["projectedPremium"],
            orderPricePercentage,
        )
    else:
        orderId = api.writeNewContracts(
            None,
            0,
            0,
            new["contract"]["symbol"],
            amountToSell,
            new["projectedPremium"],
            orderPricePercentage,
        )

    checkFillXTimes = 12

    if retry > 0:
        # go faster through it
        checkFillXTimes = 6

    for x in range(checkFillXTimes):
        # try to fill it for x * 5 seconds
        print("Waiting for order to be filled ...")

        time.sleep(5)

        checkedOrder = api.checkOrder(orderId)

        if checkedOrder["filled"]:
            print("Order has been filled!")
            break

    if not checkedOrder["filled"]:
        api.cancelOrder(orderId)

        print("Cant fill order, retrying with lower price ...")

        if checkedOrder["partialFills"] > 0:
            if checkedOrder["complexOrderStrategyType"] is None or (
                checkedOrder["complexOrderStrategyType"]
                and checkedOrder["complexOrderStrategyType"] != "DIAGONAL"
            ):
                # partial fills are only possible on DIAGONAL orders, so this should never happen
                return alert.botFailed(
                    asset,
                    "Partial fill on custom order, manual review required: "
                    + str(checkedOrder["partialFills"]),
                )

            # on diagonal fill is per leg, 1 fill = 1 bought back and 1 sold

            # quick verification, this should never be true
            if not (
                amountToBuyBack == amountToSell
                and amountToBuyBack > checkedOrder["partialFills"]
            ):
                return alert.botFailed(
                    asset, "Partial fill amounts do not match, manual review required"
                )

            diagonalAmountBothWays = amountToBuyBack - checkedOrder["partialFills"]

            receivedPremium = (
                checkedOrder["typeAdjustedPrice"] * checkedOrder["partialFills"]
            )

            alert.alert(
                asset,
                "Partial fill: Bought back "
                + str(checkedOrder["partialFills"])
                + "x "
                + existing["optionSymbol"]
                + " and sold "
                + str(checkedOrder["partialFills"])
                + "x "
                + new["contract"]["symbol"]
                + " for "
                + str(receivedPremium),
            )

            return writeCc(
                api,
                asset,
                new,
                existing,
                existingPremium,
                diagonalAmountBothWays,
                diagonalAmountBothWays,
                retry + 1,
                partialContractsSold + checkedOrder["partialFills"],
            )

        return writeCc(
            api,
            asset,
            new,
            existing,
            existingPremium,
            amountToBuyBack,
            amountToSell,
            retry + 1,
            partialContractsSold,
        )

    receivedPremium = checkedOrder["typeAdjustedPrice"] * amountToSell

    if existing:
        if amountToBuyBack != amountToSell:
            # custom order, price is not per contract
            receivedPremium = checkedOrder["typeAdjustedPrice"]

        alert.alert(
            asset,
            "Bought back "
            + str(amountToBuyBack)
            + "x "
            + existing["optionSymbol"]
            + " and sold "
            + str(amountToSell)
            + "x "
            + new["contract"]["symbol"]
            + " for "
            + str(receivedPremium),
        )
    else:
        alert.alert(
            asset,
            "Sold "
            + str(amountToSell)
            + "x "
            + new["contract"]["symbol"]
            + " for "
            + str(receivedPremium),
        )

    if partialContractsSold > 0:
        amountHasSold = partialContractsSold + amountToSell
        receivedPremium = (
            receivedPremium + checkedOrder["typeAdjustedPrice"] * partialContractsSold
        )

        # shouldn't happen
        if amountHasSold != configuration[asset]["amountOfHundreds"]:
            return alert.botFailed(
                asset, "Unexpected amount of contracts sold: " + str(amountHasSold)
            )
    else:
        amountHasSold = amountToSell

    soldOption = {
        "stockSymbol": asset,
        "optionSymbol": new["contract"]["symbol"],
        "expiration": new["date"],
        "count": amountHasSold,
        "strike": new["contract"]["strike"],
        "receivedPremium": receivedPremium,
    }
    print("Sold option:" + str(soldOption))

    db = TinyDB(dbName)

    db.remove(Query().stockSymbol == asset)
    db.insert(soldOption)

    db.close()

    return soldOption
