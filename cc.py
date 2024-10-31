import json
import math
import statistics
import keyboard
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from datetime import time as time_module
from tzlocal import get_localzone

from colorama import Fore, Style
from inputimeout import TimeoutOccurred, inputimeout
from prettytable import PrettyTable

import alert
from configuration import spreads, configuration
from optionChain import OptionChain
from support import calculate_cagr
from logger_config import get_logger

logger = get_logger()

# Global flag for order cancellation
cancel_order = False

class Cc:
    def __init__(self, asset):
        self.asset = asset

    def find_new_contract(self, api, existing):
        # check if asset is in configuration
        if self.asset not in configuration:
            print(f"Configuration for {self.asset} not found")
            return None
        days = configuration[self.asset]["maxRollOutWindow"]
        toDate = datetime.today() + timedelta(days=days)
        option_chain = OptionChain(api, self.asset, toDate, days)
        chain = option_chain.get()
        roll = find_best_rollover(api, chain, existing)
        if roll is None:
            alert.botFailed(self.asset, "No rollover contract found")
            return None
        return roll

def handle_cancel(e):
    global cancel_order
    if e.name == 'c':
        cancel_order = True
        print("\nCancelling order...")

def monitor_order(api, order_id):
    """Monitor order status and handle cancellation"""
    global cancel_order

    while True:
        if cancel_order:
            try:
                api.cancelOrder(order_id)
                print("Order cancelled successfully.")
                return False
            except Exception as e:
                print(f"Error cancelling order: {e}")
                return False

        # Check order status
        try:
            order_status = api.checkOrder(order_id)
            if order_status["filled"]:
                print("Order filled successfully!")
                return True
            elif order_status["status"] == "CANCELED":
                print("Order was cancelled.")
                return False
            print("Waiting for order to be filled ...")
            time.sleep(2)  # Wait before checking again
        except Exception as e:
            print(f"Error checking order status: {e}")
            return False

def RollCalls(api, short):
    days = configuration[short["stockSymbol"]]["maxRollOutWindow"]
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
    toDate = short_expiration + timedelta(days=days)
    optionChain = OptionChain(api, short["stockSymbol"], toDate, days)
    chain = optionChain.get()

    # Get current position details
    prem_short_contract = get_median_price(short["optionSymbol"], chain)
    if prem_short_contract is None:
        print("Short contract not found in chain")
        return

    # Get underlying price and calculate position metrics
    underlying_price = api.getATMPrice(short["stockSymbol"])
    short_strike = float(short["strike"])
    moneyness = (underlying_price - short_strike) / underlying_price * 100
    days_to_expiry = (short_expiration - datetime.now().date()).days
    short_delta = api.getOptionDetails(short["optionSymbol"])["delta"]

    # Determine position status
    if moneyness > 5:
        position_status = f"{Fore.RED}Deep ITM{Style.RESET_ALL}"
    elif moneyness > 2:
        position_status = f"{Fore.YELLOW}Moderately ITM{Style.RESET_ALL}"
    elif moneyness > 0:
        position_status = f"{Fore.GREEN}Slightly ITM{Style.RESET_ALL}"
    else:
        position_status = f"{Fore.GREEN}OTM{Style.RESET_ALL}"

    # Find roll opportunity
    roll = find_best_rollover(api, chain, short)
    if roll is None:
        print("No rollover contract found")
        return

    # Calculate roll metrics
    roll_premium = get_median_price(roll["symbol"], chain)
    credit = round(roll_premium - prem_short_contract, 2)
    credit_percent = (credit / underlying_price) * 100
    ret = api.getOptionDetails(roll["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d").date()
    roll_out_time = ret_expiration - short_expiration
    new_strike = float(roll["strike"])
    strike_improvement = new_strike - short_strike
    strike_improvement_percent = (strike_improvement / short_strike) * 100

    # Calculate annualized return
    days_to_new_expiry = (ret_expiration - datetime.now().date()).days
    if days_to_new_expiry > 0:
        annualized_return = (credit / underlying_price) * (365 / days_to_new_expiry) * 100
    else:
        annualized_return = 0

    # Calculate break-even
    break_even = new_strike - credit

    # Create combined table
    table = PrettyTable()
    table.field_names = [
        "Current Strike",
        "Current DTE",
        "Current Delta",
        "Status",
        "New Strike",
        "Strike Improvement",
        "Credit",
        "Credit %",
        "Roll Duration",
        "New Delta",
        "Delta Change",
        "Break-even",
        "Ann. Return"
    ]
    table.add_row([
        short_strike,
        days_to_expiry,
        f"{short_delta:.3f}",
        position_status,
        new_strike,
        f"{strike_improvement:+.1f} ({strike_improvement_percent:+.1f}%)",
        f"${credit:+.2f}",
        f"{credit_percent:+.2f}%",
        f"{roll_out_time.days} days",
        f"{ret['delta']:.3f}",
        f"{ret['delta'] - short_delta:+.3f}",
        round(break_even, 2),
        f"{annualized_return:.1f}%"
    ])

    print(f"Underlying Price: {round(underlying_price, 2)}")
    print("\n" + str(table))

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

def RollSPX(api, short):
    days = configuration[short["stockSymbol"]]["maxRollOutWindow"]
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
    toDate = short_expiration + timedelta(days=days)
    optionChain = OptionChain(api, short["stockSymbol"], toDate, days)
    chain = optionChain.get()

    # Get current position details
    prem_short_contract = get_median_price(short["optionSymbol"], chain)
    if prem_short_contract is None:
        print("Short contract not found in chain")
        return

    # Get underlying price and calculate position metrics
    underlying_price = api.getATMPrice(short["stockSymbol"])
    short_strike = float(short["strike"])
    moneyness = (underlying_price - short_strike) / underlying_price * 100
    days_to_expiry = (short_expiration - datetime.now().date()).days
    short_delta = get_option_delta(short["optionSymbol"], chain)

    # Determine position status
    if moneyness > 5:
        position_status = f"{Fore.RED}Deep ITM{Style.RESET_ALL}"
    elif moneyness > 2:
        position_status = f"{Fore.YELLOW}Moderately ITM{Style.RESET_ALL}"
    elif moneyness > 0:
        position_status = f"{Fore.GREEN}Slightly ITM{Style.RESET_ALL}"
    else:
        position_status = f"{Fore.GREEN}OTM{Style.RESET_ALL}"

    # Find roll opportunity
    roll = find_best_rollover(api, chain, short)
    if roll is None:
        print("No rollover contract found")
        return

    # Calculate roll metrics
    roll_premium = get_median_price(roll["symbol"], chain)
    credit = round(roll_premium - prem_short_contract, 2)
    credit_percent = (credit / underlying_price) * 100
    ret = api.getOptionDetails(roll["symbol"])
    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d").date()
    roll_out_time = ret_expiration - short_expiration
    new_strike = float(roll["strike"])
    strike_improvement = new_strike - short_strike
    strike_improvement_percent = (strike_improvement / short_strike) * 100

    # Calculate annualized return
    days_to_new_expiry = (ret_expiration - datetime.now().date()).days
    if days_to_new_expiry > 0:
        annualized_return = (credit / underlying_price) * (365 / days_to_new_expiry) * 100
    else:
        annualized_return = 0

    # Calculate break-even
    break_even = new_strike - credit

    # Create combined table
    table = PrettyTable()
    table.field_names = [
        "Current Strike",
        "Current DTE",
        "Current Delta",
        "Status",
        "New Strike",
        "Strike Improvement",
        "Credit",
        "Credit %",
        "Roll Duration",
        "New Delta",
        "Delta Change",
        "Break-even",
        "Ann. Return"
    ]
    table.add_row([
        short_strike,
        days_to_expiry,
        f"{short_delta:.3f}",
        position_status,
        new_strike,
        f"{strike_improvement:+.1f} ({strike_improvement_percent:+.1f}%)",
        f"${credit:+.2f}",
        f"{credit_percent:+.2f}%",
        f"{roll_out_time.days} days",
        f"{ret['delta']:.3f}",
        f"{ret['delta'] - short_delta:+.3f}",
        round(break_even, 2),
        f"{annualized_return:.1f}%"
    ])

    print(f"Underlying Price: {round(underlying_price, 2)}")
    print("\n" + str(table))

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

def roll_contract(api, short, roll, order_premium):
    maxRetries = 75
    checkFillXTimes = 12

    roll_order_id = api.rollOver(
        short["optionSymbol"], roll["symbol"], short["count"], order_premium
    )

    for retry in range(maxRetries):
        for x in range(checkFillXTimes):
            print("Waiting for order to be filled ...")
            time.sleep(
                1
                if datetime.now(get_localzone()).time() >= time_module(15, 45)
                else (
                    5
                    if datetime.now(get_localzone()).time() >= time_module(15, 30)
                    else 30
                )
            )
            checkedOrder = api.checkOrder(roll_order_id)
            if checkedOrder["filled"]:
                print(f"Order filled: {roll_order_id}\n Order details: {checkedOrder}")
                return
        api.cancelOrder(roll_order_id)
        print("Can't fill order, retrying with lower price ...")
        new_premium = order_premium * (100 - retry) / 100
        rounded_premium = round_to_nearest_five_cents(new_premium)
        roll_order_id = api.rollOver(
            short["optionSymbol"], roll["symbol"], short["count"], rounded_premium
        )

def find_best_rollover(api, data, short_option):
    short_strike, short_price, short_expiry, underlying_price = parse_option_details(
        api, data, short_option["optionSymbol"]
    )
    logger.debug(
        f"Short Strike: {short_strike}, Short Price: {short_price}, Short Expiry: {short_expiry}, Underlying Price: {underlying_price}"
    )
    if short_strike is None or short_price is None or short_expiry is None:
        return None

    # Configuration variables
    ITMLimit = configuration[short_option["stockSymbol"]].get("ITMLimit", 10)
    deepITMLimit = configuration[short_option["stockSymbol"]].get("deepITMLimit", 25)
    deepOTMLimit = configuration[short_option["stockSymbol"]].get("deepOTMLimit", 10)
    minPremium = configuration[short_option["stockSymbol"]].get("minPremium", 1)
    idealPremium = configuration[short_option["stockSymbol"]].get("idealPremium", 15)
    minRollupGap = configuration[short_option["stockSymbol"]].get("minRollupGap", 5)
    maxRollOutWindow = configuration[short_option["stockSymbol"]].get(
        "maxRollOutWindow", 30
    )
    minRollOutWindow = configuration[short_option["stockSymbol"]].get(
        "minRollOutWindow", 7
    )

    logger.debug(f"Initial Ideal Premium: {idealPremium}")

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

    if short_status == "deep_ITM":
        # sorts data first by date in descending order (farthest first, earliest last) and then by strike price in descending order (highest strike first)
        entries = sorted(
            data,
            key=lambda entry: (
                -datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
                -max(
                    contract["strike"]
                    for contract in entry["contracts"]
                    if "strike" in contract
                ),
            ),
        )
    else:
        # sorts data first by date in ascending order (earliest first, farthest last) and then by strike price in descending order (highest strike first)
        entries = sorted(
            data,
            key=lambda entry: (
                datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
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
                if contract["strike"] <= short_strike:
                    continue
                if short_option["optionSymbol"].split()[0] == "SPX":
                    if contract["optionRoot"] not in ["SPX", "SPXW"]:
                        continue
                else:
                    if contract["optionRoot"] != short_option["optionSymbol"].split()[0]:
                        continue
                contract_price = round(
                    statistics.median([contract["bid"], contract["ask"]]), 2
                )
                premium_diff = contract_price - short_price
                logger.debug(
                    f"Contract: {contract['symbol']}, Premium: {contract_price}, Days: {days_diff}, Premium Diff: {premium_diff}, Ideal Premium: {idealPremium}, Strike: {contract['strike']}"
                )
                if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                    if (
                        contract["strike"] >= short_strike + minRollupGap
                        and premium_diff >= idealPremium
                    ):
                        if days_diff < closest_days_diff:
                            closest_days_diff = days_diff
                            best_option = contract

                elif short_status == "ITM":
                    if (
                        premium_diff >= minPremium
                        and contract["strike"] >= short_strike + minRollupGap
                    ):
                        if contract["strike"] > highest_strike or (
                            contract["strike"] == highest_strike
                            and days_diff < closest_days_diff
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
        if best_option is None:
            logger.debug(
                f"Before adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
            )
            if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                if idealPremium > minPremium:
                    idealPremium = max(idealPremium - 0.5, minPremium)
                elif minRollupGap > 0:
                    minRollupGap = max(minRollupGap - 5, 0)
            elif short_status == "ITM":
                if minRollupGap > 0:
                    minRollupGap = max(minRollupGap - 5, 0)
                elif minPremium > 0:
                    minPremium = max(minPremium - 0.25, 0)

            logger.debug(
                f"After adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
            )
    return best_option

def parse_option_details(api, data, option_symbol):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == option_symbol:
                short_strike = float(contract["strike"])
                short_price = round(
                    statistics.median([contract["bid"], contract["ask"]]), 2
                )
                short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                if contract["underlying"] == "SPX":
                    ticker = "$SPX"
                else:
                    ticker = contract["underlying"]
                underlying_price = api.getATMPrice(ticker)
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
