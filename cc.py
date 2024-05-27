from inputimeout import inputimeout, TimeoutOccurred
from configuration import configuration
from datetime import datetime, timedelta
from optionChain import OptionChain
import math
import time
import alert
import statistics


class Cc:
    def __init__(self, asset):
        self.asset = asset

    def find_new_contract(self, api, existing):
        days = configuration[self.asset]["maxRollOutWindow"]
        print(f"Finding new contract for {self.asset} with {days} days to expiry")
        toDate = datetime.today() + timedelta(days=days)
        option_chain = OptionChain(api, self.asset, toDate, days)
        chain = option_chain.get()
        roll = find_best_rollover(chain, existing)
        if roll is None:
            alert.botFailed(self.asset, "No rollover contract found")
            return None
        return roll


def roll_contract(api, short, roll, order_premium):
    maxRetries = 75
    checkFillXTimes = 12

    roll_order_id = api.rollOver(
        short["optionSymbol"], roll["symbol"], short["count"], order_premium
    )

    for retry in range(maxRetries):
        for x in range(checkFillXTimes):
            print("Waiting for order to be filled ...")
            time.sleep(5)
            checkedOrder = api.checkOrder(roll_order_id)
            if checkedOrder["filled"]:
                print("Order has been filled!")
                return
        api.cancelOrder(roll_order_id)
        print("Can't fill order, retrying with lower price ...")
        new_premium = order_premium * (100 - retry) / 100
        rounded_premium = round_to_nearest_five_cents(new_premium)
        roll_order_id = api.rollOver(
            short["optionSymbol"], roll["symbol"], short["count"], rounded_premium
        )


def RollSPX(api, short):
    toDate = datetime.today() + timedelta(days=90)
    optionChain = OptionChain(api, short["stockSymbol"], toDate, 90)
    chain = optionChain.get()
    prem_short_contract = get_median_price(short["optionSymbol"], chain)

    if prem_short_contract is None:
        print("Short contract not found in chain")
        return

    print("Premium of short contract: ", prem_short_contract)
    roll = find_best_rollover(chain, short)
    if roll is None:
        print("No rollover contract found")
        return

    roll_premium = get_median_price(roll["symbol"], chain)
    increase = round(roll_premium - prem_short_contract, 2)
    ret = api.getOptionExpirationDateAndStrike(roll["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d")
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d")
    roll_out_time = ret_expiration - short_expiration
    print(
        f"Roll: {short['optionSymbol']} -> {roll['symbol']}"
        f"\n Credit: ${increase}\n Roll-up: ${float(roll['strike']) - float(short['strike'])}"
        f"\n Roll-out: {roll_out_time.days} days\n Expiration: {ret['expiration']}"
    )

    try:
        user_input = inputimeout(
            prompt="Do you want to place the trade? (yes/no): ", timeout=60
        ).lower()
    except TimeoutOccurred:
        user_input = "no"

    if user_input == "yes":
        roll_contract(api, short, roll, round(increase + 5, 2))
    else:
        print("Roll over cancelled")


def RollCalls(api, short):
    cc = Cc(short["stockSymbol"])

    existingSymbol = short["optionSymbol"]
    amountToBuyBack = short["count"]
    existingPremium = api.getATMPrice(short["optionSymbol"])
    print(
        f"Existing symbol: {existingSymbol} Amount to buy back: {amountToBuyBack} Existing premium: {existingPremium}"
    )

    new = cc.find_new_contract(api, short)
    if new is None:
        return

    print("The bot wants to write the following contract:")
    roll_premium = statistics.median([new["bid"], new["ask"]])
    increase = round(roll_premium - existingPremium, 2)

    ret = api.getOptionExpirationDateAndStrike(new["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d")
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d")
    roll_out_time = ret_expiration - short_expiration
    print(
        f"Roll: {existingSymbol} -> {new['symbol']}"
        f"\n Credit: ${increase}\n Roll-up: ${float(new['strike']) - float(short['strike'])}"
        f"\n Roll-out: {roll_out_time.days} days\n Expiration: {ret['expiration']}"
    )

    if not api.checkAccountHasEnoughToCover(
        short["stockSymbol"],
        existingSymbol,
        amountToBuyBack,
        amountToBuyBack,
        new["strike"],
        ret["expiration"],
    ):
        return alert.botFailed(
            short["stockSymbol"],
            f"The account doesn't have enough shares or options to cover selling {amountToBuyBack} cc(s)",
        )

    try:
        user_input = inputimeout(
            prompt="Do you want to place the trade? (yes/no): ", timeout=60
        ).lower()
    except TimeoutOccurred:
        user_input = "no"

    if user_input == "yes":
        roll_contract(api, short, new, round(increase + 5, 2))
    else:
        print("Roll over cancelled")


def find_best_rollover(data, short_option):
    def get_option_details(data, short_option):
        for entry in data:
            for contract in entry["contracts"]:
                if contract["symbol"] == short_option:
                    short_strike = contract["strike"]
                    short_median = round(
                        statistics.median([contract["bid"], contract["ask"]]), 2
                    )
                    short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                    return short_strike, short_median, short_expiry
        return None, None, None

    short_strike, short_median, short_expiry = get_option_details(
        data, short_option["optionSymbol"]
    )
    if short_strike is None or short_median is None or short_expiry is None:
        return None

    entries = sorted(
        data, key=lambda entry: datetime.strptime(entry["date"], "%Y-%m-%d")
    )

    best_option = None
    closest_days_diff = float("inf")
    for entry in entries:
        expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        days_diff = (expiry_date - short_expiry).days
        if (
            days_diff > configuration[short_option["stockSymbol"]]["maxRollOutWindow"]
            or days_diff
            < configuration[short_option["stockSymbol"]]["minRollOutWindow"]
        ):
            continue
        for contract in entry["contracts"]:
            if (
                contract["strike"] <= short_strike
                or contract["optionRoot"] != contract["symbol"].split()[0]
            ):
                continue
            contract_median = round(
                statistics.median([contract["bid"], contract["ask"]]), 2
            )
            premium_diff = contract_median - short_median
            if (
                contract["strike"]
                >= short_strike
                + configuration[short_option["stockSymbol"]]["minRollupGap"]
                and premium_diff
                >= configuration[short_option["stockSymbol"]]["idealPremium"]
            ):
                if days_diff < closest_days_diff:
                    closest_days_diff = days_diff
                    best_option = contract
    if best_option:
        return best_option

    best_option = None
    highest_strike = float("-inf")
    for entry in entries:
        expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        days_diff = (expiry_date - short_expiry).days
        if (
            days_diff > configuration[short_option["stockSymbol"]]["maxRollOutWindow"]
            or days_diff
            < configuration[short_option["stockSymbol"]]["minRollOutWindow"]
        ):
            continue
        for contract in entry["contracts"]:
            if (
                contract["strike"] <= short_strike
                or contract["optionRoot"] != contract["symbol"].split()[0]
            ):
                continue
            contract_median = round(
                statistics.median([contract["bid"], contract["ask"]]), 2
            )
            premium_diff = contract_median - short_median
            if premium_diff >= configuration[short_option["stockSymbol"]]["minPremium"]:
                if contract["strike"] > highest_strike or (
                    contract["strike"] == highest_strike
                    and days_diff < closest_days_diff
                ):
                    highest_strike = contract["strike"]
                    closest_days_diff = days_diff
                    best_option = contract
    return best_option


def round_to_nearest_five_cents(n):
    return math.ceil(n * 20) / 20


def get_median_price(symbol, data):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                bid = contract["bid"]
                ask = contract["ask"]
                return (bid + ask) / 2
    return None
