import math
import statistics
import time
from datetime import datetime, timedelta

from colorama import Fore, Style
from inputimeout import TimeoutOccurred, inputimeout

import alert
from configuration import configuration
from optionChain import OptionChain


class Cc:
    def __init__(self, asset):
        self.asset = asset

    def find_new_contract(self, api, existing):
        days = configuration[self.asset]["maxRollOutWindow"]
        toDate = datetime.today() + timedelta(days=days)
        option_chain = OptionChain(api, self.asset, toDate, days)
        chain = option_chain.get()
        roll = find_best_rollover(api, chain, existing)
        if roll is None:
            alert.botFailed(self.asset, "No rollover contract found")
            return None
        return roll

def vertical_contract(
    api, symbol, expiration, strike_low, strike_high, price, amount=1
):
    maxRetries = 75
    checkFillXTimes = 12

    order_id = api.vertical_call_order(
        symbol, expiration, strike_low, strike_high, price, amount
    )

    for retry in range(maxRetries):
        for x in range(checkFillXTimes):
            print("Waiting for order to be filled ...")
            time.sleep(1)
            checkedOrder = api.checkOrder(order_id)
            if checkedOrder["filled"]:
                print(
                    f"Order filled: {order_id}\n Order details: {api.checkOrder(order_id)}"
                )
                return
        api.cancelOrder(order_id)
        print("Can't fill order, retrying with lower price ...")
        new_price = price * (100 - retry) / 100
        rounded_price = round_to_nearest_five_cents(new_price)
        order_id = api.vertical_call_order(
            symbol, expiration, strike_low, strike_high, rounded_price, amount
        )

def roll_contract(api, short, roll, order_premium):
    maxRetries = 75
    checkFillXTimes = 12

    roll_order_id = api.rollOver(
        short["optionSymbol"], roll["symbol"], short["count"], order_premium
    )

    for retry in range(maxRetries):
        for x in range(checkFillXTimes):
            print("Waiting for order to be filled ...")
            time.sleep(1)
            checkedOrder = api.checkOrder(roll_order_id)
            if checkedOrder["filled"]:
                print(
                    f"Order filled: {roll_order_id}\n Order details: {api.checkOrder(roll_order_id)}"
                )
                return
        api.cancelOrder(roll_order_id)
        print("Can't fill order, retrying with lower price ...")
        new_premium = order_premium * (100 - retry) / 100
        rounded_premium = round_to_nearest_five_cents(new_premium)
        roll_order_id = api.rollOver(
            short["optionSymbol"], roll["symbol"], short["count"], rounded_premium
        )


def RollSPX(api, short):
    days = configuration[short["stockSymbol"]]["maxRollOutWindow"]
    toDate = datetime.today() + timedelta(days=days)
    optionChain = OptionChain(api, short["stockSymbol"], toDate, days)
    chain = optionChain.get()
    prem_short_contract = get_median_price(short["optionSymbol"], chain)

    if prem_short_contract is None:
        print("Short contract not found in chain")
        return

    print("Premium of short contract: ", prem_short_contract)
    roll = find_best_rollover(api, chain, short)
    if roll is None:
        print("No rollover contract found")
        return

    roll_premium = get_median_price(roll["symbol"], chain)
    credit = round(roll_premium - prem_short_contract, 2)
    ret = api.getOptionDetails(roll["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d")
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d")
    roll_out_time = ret_expiration - short_expiration
    short_delta = get_option_delta(short["optionSymbol"], chain)
    print(
        f"{'Roll:':<12} {short['optionSymbol']} -> {roll['symbol']}\n"
        f"{'Credit:':<12} ${credit}\n"
        f"{'Roll-up:':<12} ${float(roll['strike']) - float(short['strike'])}\n"
        f"{'Roll-out:':<12} {roll_out_time.days} days\n"
        f"{'Expiration:':<12} {ret['expiration']}\n"
        f"{'Short Delta:':<12} {round(short_delta,3)} {'New Delta:':<10} {round(ret['delta'],3)}\n"
        f"{'Trade Delta:':<12} {round(short_delta - ret['delta'],3)}"
    )

    try:
        user_input = inputimeout(
            prompt="Do you want to place the trade? (yes/no): ", timeout=30
        ).lower()
    except TimeoutOccurred:
        user_input = "no"

    if user_input == "yes":
        roll_contract(api, short, roll, round(credit, 2))
    else:
        print("Roll over cancelled")


def RollCalls(api, short):
    cc = Cc(short["stockSymbol"])

    existingSymbol = short["optionSymbol"]
    amountToBuyBack = short["count"]
    existingPremium = api.getATMPrice(short["optionSymbol"])
    short["delta"] = api.getOptionDetails(short["optionSymbol"])["delta"]
    print(
        f"Existing symbol: {existingSymbol} "
        f"Amount to buy back: {amountToBuyBack} "
        f"Existing premium: {existingPremium}"
    )

    new = cc.find_new_contract(api, short)
    if new is None:
        return

    print("The bot wants to write the following contract:")
    roll_premium = statistics.median([new["bid"], new["ask"]])
    credit = round(roll_premium - existingPremium, 2)

    ret = api.getOptionDetails(new["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d")
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d")
    roll_out_time = ret_expiration - short_expiration
    print(
        f"{'Roll:':<12} {existingSymbol} -> {new['symbol']}\n"
        f"{'Credit:':<12} ${credit}\n"
        f"{'Roll-up:':<12} ${float(new['strike']) - float(short['strike'])}\n"
        f"{'Roll-out:':<12} {roll_out_time.days} days\n"
        f"{'Expiration:':<12} {ret['expiration']}\n"
        f"{'Short Delta:':<12} {round(short['delta'],3)} {'New Delta:':<10} {round(ret['delta'],3)}\n"
        f"{'Trade Delta:':<12} {round(short['delta'] - ret['delta'],3)}"
    )

    try:
        user_input = inputimeout(
            prompt="Do you want to place the trade? (yes/no): ", timeout=30
        ).lower()
    except TimeoutOccurred:
        user_input = "no"

    if user_input == "yes":
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
        roll_contract(api, short, new, round(credit + 0.5, 2))
    else:
        print("Roll over cancelled")


def find_best_rollover(api, data, short_option):

    short_strike, short_price, short_expiry, underlying_price = parse_option_details(
        api, data, short_option["optionSymbol"]
    )
    if short_strike is None or short_price is None or short_expiry is None:
        return None

    # Configuration variables
    ITMLimit = configuration[short_option["stockSymbol"]].get("ITMLimit", 10)
    deepITMLimit = configuration[short_option["stockSymbol"]].get("deepITMLimit", 25)
    deepOTMLimit = configuration[short_option["stockSymbol"]].get("deepOTMLimit", 10)
    minPremium = configuration[short_option["stockSymbol"]].get("minPremium", 1)
    idealPremium = configuration[short_option["stockSymbol"]].get("idealPremium", 2.5)
    minRollupGap = configuration[short_option["stockSymbol"]].get("minRollupGap", 5)
    maxRollOutWindow = configuration[short_option["stockSymbol"]].get(
        "maxRollOutWindow", 30
    )
    minRollOutWindow = configuration[short_option["stockSymbol"]].get(
        "minRollOutWindow", 7
    )
    # desiredDelta = configuration[short_option["stockSymbol"]].get("desiredDelta", 0.3)

    # Determine the short status
    short_status = None
    if short_strike > underlying_price + deepOTMLimit:
        short_status = "deep_OTM"
    elif short_strike > underlying_price:
        short_status = "OTM"
    elif short_strike + ITMLimit > underlying_price:
        short_status = "just_ITM"
    elif short_strike + deepITMLimit > underlying_price:
        short_status = "ITM"
    else:
        short_status = "deep_ITM"

    value = round(short_strike - underlying_price, 2)

    if value > 0:
        print(
            f"Short status: {Fore.GREEN}{short_status}{Style.RESET_ALL}. Strike - Underlying: {Fore.GREEN}{value}{Style.RESET_ALL}"
        )
    elif value < 0:
        print(
            f"Short status: {Fore.RED}{short_status}{Style.RESET_ALL}. Strike - Underlying: {Fore.RED}{value}{Style.RESET_ALL}"
        )
    else:
        print(f"Short status: {short_status}. Strike - Underlying: {value}")

    # Sort entries
    entries = sorted(
        data,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )

    # Initialize best option
    best_option = None
    closest_days_diff = float("inf")
    highest_strike = float("-inf")

    # Iterate to find the best rollover option
    while short_status and best_option is None:

        for entry in entries:
            expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            days_diff = (expiry_date - short_expiry).days
            if days_diff > maxRollOutWindow or days_diff < minRollOutWindow:
                continue
            for contract in entry["contracts"]:
                if (
                    contract["strike"] <= short_strike
                    or contract["optionRoot"] != contract["symbol"].split()[0]
                ):
                    continue
                contract_price = round(
                    statistics.median([contract["bid"], contract["ask"]]), 2
                )
                premium_diff = contract_price - short_price
                if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                    if (
                        contract["strike"] >= short_strike + minRollupGap
                        and premium_diff >= idealPremium
                    ):
                        if days_diff < closest_days_diff:
                            closest_days_diff = days_diff
                            best_option = contract

                elif short_status == "ITM":
                    if premium_diff >= minPremium and (
                        contract["strike"] > highest_strike
                        or (
                            contract["strike"] == highest_strike
                            and days_diff < closest_days_diff
                        )
                    ):
                        highest_strike = contract["strike"]
                        closest_days_diff = days_diff
                        best_option = contract

                elif short_status == "deep_ITM":
                    # Roll to the highest strike without paying a premium
                    if premium_diff >= 0.1 and contract["strike"] > highest_strike:
                        highest_strike = contract["strike"]
                        closest_days_diff = days_diff
                        best_option = contract

        # Adjust criteria if no best option found
        if best_option is None and short_status in ["deep_OTM", "OTM", "just_ITM"]:
            while idealPremium > minPremium or minRollupGap > 0:
                if idealPremium > minPremium:
                    idealPremium -= 0.5
                    if idealPremium < minPremium:
                        idealPremium = minPremium
                elif minRollupGap > 0:
                    minRollupGap -= 5
                    if minRollupGap < 0:
                        minRollupGap = 0
        if best_option is None and short_status in ["ITM", "deep_ITM"]:
            minPremium -= 0.25
            if minPremium < 0:
                break  # Avoid going negative on the premium

    return best_option


# This function can be used to parse the option chain returned from the optionchain.get() function.
# data is the chain returned from that function and option_symbol is the symbol of the option you want to parse.
def parse_option_details(api, data, option_symbol):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == option_symbol:
                short_strike = contract["strike"]
                short_price = round(
                    statistics.median([contract["bid"], contract["ask"]]), 2
                )
                short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                underlying_price = api.getATMPrice(contract["underlying"])
                return short_strike, short_price, short_expiry, underlying_price
    return None, None, None, None


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


def get_option_delta(symbol, data):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                return contract["delta"]
    return None
