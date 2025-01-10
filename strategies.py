import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from datetime import time as time_module

import keyboard
from inputimeout import TimeoutOccurred, inputimeout
from prettytable import PrettyTable
from tzlocal import get_localzone

from cc import round_to_nearest_five_cents
from configuration import spreads
from margin_utils import (
    calculate_annualized_return_on_margin,
    calculate_margin_requirement,
)
from optionChain import OptionChain
from support import calculate_cagr

# Global flag for order cancellation
cancel_order = False

def handle_cancel(e):
    global cancel_order
    if e.name == 'c':
        cancel_order = True
        print("\nCancelling order...")

def monitor_order(api, order_id, timeout=60):  # Default timeout changed to 60 seconds
    """Monitor order status and handle cancellation with dynamic display"""
    global cancel_order

    start_time = time.time()
    last_status_check = 0

    # Set check interval based on market time
    now = datetime.now(get_localzone())
    if now.time() >= time_module(15, 30):  # After 3:30 PM
        check_interval = 2  # Check more frequently near market close
    else:
        check_interval = 5  # Normal interval during regular hours

    print("\nMonitoring order execution... (Press 'c' to cancel)")

    while time.time() - start_time < timeout:
        current_time = time.time()
        elapsed_time = int(current_time - start_time)

        if cancel_order:
            try:
                api.cancelOrder(order_id)
                print("\nOrder cancelled by user.")
                return "cancelled"  # Special return value for user cancellation
            except Exception as e:
                print(f"\nError cancelling order: {e}")
                return False

        # Check order status
        try:
            if current_time - last_status_check >= check_interval:
                order_status = api.checkOrder(order_id)
                last_status_check = current_time

                remaining = int(timeout - elapsed_time)
                print(f"\rStatus: {order_status['status']} | Time remaining: {remaining}s | "
                      f"Price: {order_status.get('price', 'N/A')} | "
                      f"Filled: {order_status.get('filledQuantity', '0')}  ", end="", flush=True)

                if order_status["filled"]:
                    print(f"\nOrder filled successfully!")
                    print(f"Fill Price: {order_status['price']}")
                    print(f"Time to fill: {elapsed_time} seconds")
                    return True
                elif order_status["status"] == "CANCELED":
                    print(f"\nOrder was cancelled after {elapsed_time} seconds.")
                    return False

            time.sleep(0.1)  # Small sleep to prevent CPU thrashing

        except Exception as e:
            print(f"\nError checking order status: {e}")
            return False

    print("\nOrder timed out, attempting price improvement...")
    return "timeout"  # Special return value for timeout

__all__ = ['monitor_order']

def BoxSpread(api, asset="$SPX"):
    days = spreads[asset].get("days", 2000)
    minDays = spreads[asset].get("minDays", 0)
    strikes = spreads[asset].get("strikes", 500)
    toDate = datetime.today() + timedelta(days=days)
    fromDate = datetime.today() + timedelta(days=minDays)
    try:
        calls = api.getOptionChain(asset, strikes, toDate, days - 120)
        puts = api.getPutOptionChain(asset, strikes, toDate, days - 120)
    except Exception as e:
        print(f"Error fetching option chain: {e}")
        return None
    option_chain = OptionChain(api, asset, toDate, days)
    calls = option_chain.mapApiData(calls)
    puts = option_chain.mapApiData(puts, put=True)

    # Filter out options before minDays
    calls = [entry for entry in calls if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]
    puts = [entry for entry in puts if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]

    calls = sorted(
        calls,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )
    puts = sorted(
        puts,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )
    best_overall_spread = None
    best_overall_cagr = float("-inf")

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(calculate_box_spread_wrapper, spread, calls, puts): spread
            for spread in range(100, 500, 50)
        }

        for future in as_completed(futures):
            result, spread = future.result()
            if result is not None and result["cagr_percentage"] > best_overall_cagr:
                best_overall_spread = result
                best_overall_cagr = result["cagr_percentage"]

    if best_overall_spread is not None:
        # Calculate margin requirement
        margin_req = calculate_margin_requirement(
            asset,
            'credit_spread',
            strike_diff=best_overall_spread["strike2"] - best_overall_spread["strike1"],
            contracts=1
        )

        # Calculate return on margin
        profit = best_overall_spread["total_return"]
        days_to_expiry = (datetime.strptime(best_overall_spread["date"], "%Y-%m-%d") - datetime.today()).days
        rom = calculate_annualized_return_on_margin(profit, margin_req, days_to_expiry)

        best_overall_spread["margin_requirement"] = margin_req
        best_overall_spread["return_on_margin"] = rom

        # Create a dictionary mapping the original column names to the new labels
        labels = {
            "date": "Date",
            "strike1": "Low Strike",
            "strike2": "High Strike",
            "net_debit": "Net Price",
            "cagr_percentage": "% CAGR",
            "total_investment": "Investment",
            "total_return": "Total Return",
            "margin_requirement": "Margin Req",
            "return_on_margin": "Ann. ROM %"
        }

        # Create a new PrettyTable instance
        table = PrettyTable()

        # Set the field names to the labels
        table.field_names = list(labels.values())

        # Add a row with the values of the selected columns
        table.add_row(
            [
                (
                    f"{best_overall_spread[column]}%"
                    if column in ["cagr_percentage", "return_on_margin"]
                    else best_overall_spread[column]
                )
                for column in labels.keys()
            ]
        )
        print(table)
    else:
        print("No best spread found.")


def calculate_box_spread_wrapper(spread, calls, puts):
    return (
        calculate_box_spread(spread, json.dumps(calls), json.dumps(puts), trade="sell"),
        spread,
    )


def calculate_box_spread(spread, calls, puts, trade="Sell", price="natural"):
    # Parse the JSON option chain
    calls_chain = json.loads(calls)
    puts_chain = json.loads(puts)
    highest_cagr = None

    if trade == "buy":
        highest_cagr = 0
    elif trade == "sell":
        highest_cagr = float("-inf")
    best_spread = None

    # Iterate over the option chain
    for entry in zip(calls_chain, puts_chain):
        call_contracts = sorted(entry[0]["contracts"], key=lambda c: c["strike"])
        put_contracts = sorted(entry[1]["contracts"], key=lambda c: c["strike"])
        for i in range(len(call_contracts)):
            low_call = low_put = high_call = high_put = None
            # Find the next contract with a strike that is 'spread' above this one
            for j in range(i + 1, len(call_contracts)):
                if call_contracts[j]["strike"] - call_contracts[i]["strike"] == spread:
                    # Calculate net credit received by buying and selling options
                    if price.lower() in ["mid", "market"]:
                        # we need to calculate the median of the bid and ask prices for put and call options
                        low_call = statistics.median(
                            [call_contracts[i]["bid"], call_contracts[i]["ask"]]
                        )
                        low_put = statistics.median(
                            [put_contracts[i]["bid"], put_contracts[i]["ask"]]
                        )
                        high_call = statistics.median(
                            [call_contracts[j]["bid"], call_contracts[j]["ask"]]
                        )
                        high_put = statistics.median(
                            [put_contracts[j]["bid"], put_contracts[j]["ask"]]
                        )
                    else:  # assuming 'natural' price
                        if trade.lower() == "buy":
                            low_call = call_contracts[i]["ask"]
                            low_put = put_contracts[i]["bid"]
                            high_call = call_contracts[j]["bid"]
                            high_put = put_contracts[j]["ask"]
                        elif trade.lower() == "sell":
                            low_call = call_contracts[i]["bid"]
                            low_put = put_contracts[i]["ask"]
                            high_call = call_contracts[j]["ask"]
                            high_put = put_contracts[j]["bid"]
                    if None not in [low_call, high_put, high_call, low_put]:
                        if trade.lower() == "buy":  # debit
                            trade_price = low_put + high_call - high_put - low_call
                            trade_price = -trade_price
                        elif trade.lower() == "sell":  # credit
                            trade_price = low_call + high_put - high_call - low_put
                    else:
                        continue

                    low_strike = call_contracts[i]["strike"]
                    high_strike = call_contracts[j]["strike"]

                    days = (
                        datetime.strptime(entry[0]["date"], "%Y-%m-%d").date()
                        - datetime.today().date()
                    ).days
                    if days > 1 and trade_price > 0:
                        if trade.lower() == "buy":
                            cagr, cagr_percentage = calculate_cagr(
                                trade_price, spread, days
                            )
                        else:
                            cagr, cagr_percentage = calculate_cagr(
                                spread, trade_price, days
                            )
                        if trade.lower() == "buy" and (
                            highest_cagr is None or cagr > highest_cagr
                        ):
                            best_spread = {
                                "date": entry[0]["date"],
                                "strike1": low_strike,
                                "strike2": high_strike,
                                "net_debit": round(trade_price, 2),
                                "cagr": round(cagr, 2),
                                "cagr_percentage": round(cagr_percentage, 2),
                                "total_investment": round(trade_price * 100, 2),
                                "total_return": round((spread) * 100, 2),
                            }
                            highest_cagr = round(cagr, 2)
                        elif trade.lower() == "sell" and (
                            highest_cagr is None or cagr > highest_cagr
                        ):
                            best_spread = {
                                "date": entry[0]["date"],
                                "strike1": low_strike,
                                "strike2": high_strike,
                                "low_call_bid": call_contracts[i]["bid"],
                                "high_put_bid": put_contracts[j]["bid"],
                                "high_call_ask": call_contracts[j]["ask"],
                                "low_put_ask": put_contracts[i]["ask"],
                                "low_call_ask": call_contracts[i]["ask"],
                                "high_call_bid": call_contracts[j]["bid"],
                                "low_put_bid": put_contracts[i]["bid"],
                                "high_put_ask": put_contracts[j]["ask"],
                                "net_debit": round(trade_price, 2),
                                "cagr": round(cagr, 2),
                                "cagr_percentage": round(cagr_percentage, 2),
                                "total_investment": round(spread * 100, 2),
                                "total_return": round((trade_price) * 100, 2),
                            }
                            highest_cagr = round(cagr, 2)
    if best_spread is not None:
        return best_spread
    else:
        return None


def bull_call_spread(
    api, asset, spread=100, days=90, downsideProtection=0.25, price="mid"
):
    """
    This function calculates the best bull call spread for a given asset
    :param api: the API object
    :param asset: the asset for which the spread is to be calculated
    :param spread: the spread between the two strikes
    :param days: the number of days to expiration
    :param downsideProtection: the minimum downside protection required
    :param price: the price to be used for the spread calculation; we can use Natural (which will use the bid/ask prices) or Market/mid (which will use the median price)
    :return: the best spread for the given asset
    """

    minDays = spreads[asset].get("minDays", 0)
    toDate = datetime.today() + timedelta(days=days)
    fromDate = datetime.today() + timedelta(days=minDays)
    optionChain = OptionChain(api, asset, toDate, days)
    quote = api.get_quote(asset)
    if quote is not None and asset in quote:
        asset_quote = quote[asset]
        if asset_quote is not None and "quote" in asset_quote:
            underlying_price = asset_quote["quote"].get("lastPrice")
    else:
        print("Error: Unable to get quote for asset")
        return None
    chain = optionChain.get()

    # Filter out options before minDays
    chain = [entry for entry in chain if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]

    entries = sorted(
        chain,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )

    best_spread = None
    highest_cagr = float("-inf")
    # Iterate over each date's options
    for entry in entries:
        contracts = sorted(entry["contracts"], key=lambda c: c["strike"])

        # Verify the underlying symbol matches
        if not contracts or contracts[0]["underlying"] != asset:
            continue

        for i in range(len(contracts)):
            # Find the next contract with a strike that is 'spread' above this one
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] == spread:
                    # Calculate net credit received by buying and selling options
                    if price.lower() in ["mid", "market"]:
                        net_debit = statistics.median(
                            [contracts[i]["bid"], contracts[i]["ask"]]
                        ) - statistics.median(
                            [contracts[j]["bid"], contracts[j]["ask"]]
                        )
                    else:
                        net_debit = contracts[i]["ask"] - contracts[j]["bid"]
                    # calculate break even for this spread
                    break_even = contracts[i]["strike"] + net_debit
                    downside_protection = 1 - (break_even / underlying_price)
                    # Calculate CAGR for this spread
                    days = (
                        datetime.strptime(entry["date"], "%Y-%m-%d") - datetime.today()
                    ).days
                    if (
                        days > 1
                        and net_debit > 0
                        and net_debit < spread
                        and downside_protection > downsideProtection
                    ):
                        total_investment = net_debit
                        returns = abs(contracts[j]["strike"] - contracts[i]["strike"])
                        cagr, cagr_percentage = calculate_cagr(
                            total_investment, returns, days
                        )

                        # Calculate margin requirement
                        margin_req = calculate_margin_requirement(
                            asset,
                            'debit_spread',
                            cost=net_debit * 100
                        )

                        # Calculate return on margin
                        profit = (spread - net_debit) * 100
                        rom = calculate_annualized_return_on_margin(profit, margin_req, days)

                    else:
                        cagr = float("-inf")
                        cagr_percentage = round(cagr, 2)
                        margin_req = 0
                        rom = 0

                    # If this spread has a higher CAGR than the previous best, update our best spread
                    if cagr > highest_cagr:
                        best_spread = {
                            "asset": asset,
                            "date": entry["date"],
                            "strike1": contracts[i]["strike"],
                            "bid1": contracts[i]["bid"],
                            "ask1": contracts[i]["ask"],
                            "bid2": contracts[j]["bid"],
                            "ask2": contracts[j]["ask"],
                            "strike2": contracts[j]["strike"],
                            "net_debit": round(net_debit, 2),
                            "cagr": round(cagr, 2),
                            "cagr_percentage": round(cagr_percentage, 2),
                            "downside_protection": round(downside_protection * 100, 2),
                            "total_investment": round(net_debit * 100, 2),
                            "total_return": round((spread - net_debit) * 100, 2),
                            "margin_requirement": round(margin_req, 2),
                            "return_on_margin": round(rom, 2)
                        }
                        highest_cagr = round(cagr, 2)
    if best_spread is not None:
        return best_spread
    else:
        return None


def synthetic_covered_call_spread(
    api, asset, spread=100, days=90, downsideProtection=0.25, price="mid"
):
    """
    This function calculates the best synthetic covered call spread for a given asset
    :param api: the API object
    :param asset: the asset for which the spread is to be calculated
    :param spread: the spread between the two strikes
    :param days: the number of days to expiration
    :param downsideProtection: the minimum downside protection required
    :param price: the price to be used for the spread calculation; we can use Natural (which will use the bid/ask prices) or Market/mid (which will use the median price)
    :return: the best spread for the given asset
    """

    minDays = spreads[asset].get("minDays", 0)
    toDate = datetime.today() + timedelta(days=days)
    fromDate = datetime.today() + timedelta(days=minDays)
    optionChain = OptionChain(api, asset, toDate, days)
    puts = api.getPutOptionChain(asset, strikes=150, date=toDate, daysLessAllowed=days)
    quote = api.get_quote(asset)
    if quote is not None and asset in quote:
        asset_quote = quote[asset]
        if asset_quote is not None and "quote" in asset_quote:
            underlying_price = asset_quote["quote"].get("lastPrice")
    else:
        print("Error: Unable to get quote for asset")
        return None
    chain = optionChain.get()
    puts = optionChain.mapApiData(puts, put=True)

    # Filter out options before minDays
    chain = [entry for entry in chain if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]
    puts = [entry for entry in puts if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]

    entries = sorted(
        chain,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )

    puts = sorted(
        puts,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(
                contract["strike"]
                for contract in entry["contracts"]
                if "strike" in contract
            ),
        ),
    )
    best_spread = None
    highest_cagr = float("-inf")

    # Create a dictionary to map dates to put contracts for easier lookup
    put_contracts_by_date = {}
    for put_entry in puts:
        put_contracts_by_date[put_entry["date"]] = {
            contract["strike"]: contract
            for contract in put_entry["contracts"]
        }

    # Iterate over each date's options
    for entry in entries:
        contracts = sorted(entry["contracts"], key=lambda c: c["strike"])

        # Verify the underlying symbol matches
        if not contracts or contracts[0]["underlying"] != asset:
            continue

        put_contracts_map = put_contracts_by_date.get(entry["date"], {})

        if not put_contracts_map:
            continue

        for i in range(len(contracts)):
            # Find the next contract with a strike that is 'spread' above this one
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] == spread:
                    # Get corresponding put contract for the lower strike
                    put_contract = put_contracts_map.get(contracts[i]["strike"])
                    if not put_contract:
                        continue

                    # Calculate net credit received by buying and selling options
                    if price.lower() in ["mid", "market"]:
                        net_debit = (
                            statistics.median(
                                [contracts[i]["bid"], contracts[i]["ask"]]
                            )
                            - statistics.median(
                                [contracts[j]["bid"], contracts[j]["ask"]]
                            )
                            - statistics.median(
                                [put_contract["bid"], put_contract["ask"]]
                            )
                        )
                    else:
                        net_debit = (
                            contracts[i]["ask"]
                            - contracts[j]["bid"]
                            - put_contract["bid"]
                        )
                    # calculate break even for this spread
                    break_even = contracts[i]["strike"] + net_debit
                    downside_protection = 1 - (break_even / underlying_price)
                    # Calculate CAGR for this spread
                    days = (
                        datetime.strptime(entry["date"], "%Y-%m-%d")
                        - datetime.today()
                    ).days
                    if (
                        days > 1
                        and net_debit > 0
                        and net_debit < spread
                        and downside_protection > downsideProtection
                    ):
                        total_investment = net_debit
                        returns = abs(contracts[j]["strike"] - contracts[i]["strike"])
                        cagr, cagr_percentage = calculate_cagr(
                            total_investment, returns, days
                        )

                        # Calculate margin requirement for the synthetic covered call
                        margin_req = calculate_margin_requirement(
                            asset,
                            'synthetic_covered_call',
                            put_strike=contracts[i]["strike"],
                            underlying_value=underlying_price,
                            put_premium=put_contract["bid"],
                            max_loss=contracts[i]["strike"] * 100
                        )

                        # Calculate return on margin
                        profit = (spread - net_debit) * 100
                        rom = calculate_annualized_return_on_margin(profit, margin_req, days)

                    else:
                        cagr = float("-inf")
                        cagr_percentage = round(cagr, 2)
                        margin_req = 0
                        rom = 0

                    # If this spread has a higher CAGR than the previous best, update our best spread
                    if cagr > highest_cagr:
                        best_spread = {
                            "asset": asset,
                            "date": entry["date"],
                            "strike1": contracts[i]["strike"],
                            "bid1": contracts[i]["bid"],
                            "ask1": contracts[i]["ask"],
                            "bid2": contracts[j]["bid"],
                            "ask2": contracts[j]["ask"],
                            "put_bid": put_contract["bid"],
                            "put_ask": put_contract["ask"],
                            "strike2": contracts[j]["strike"],
                            "net_debit": round(net_debit, 2),
                            "cagr": round(cagr, 2),
                            "cagr_percentage": round(cagr_percentage, 2),
                            "downside_protection": round(downside_protection * 100, 2),
                            "total_investment": round(net_debit * 100, 2),
                            "total_return": round((spread - net_debit) * 100, 2),
                            "margin_requirement": round(margin_req, 2),
                            "return_on_margin": round(rom, 2)
                        }
                        highest_cagr = round(cagr, 2)
    if best_spread is not None:
        return best_spread
    else:
        return None


def calculate_spread(
    api, asset, spread, days, downsideProtection, price_method, synthetic
):
    if synthetic:
        return asset, synthetic_covered_call_spread(
            api, asset, spread, days, downsideProtection, price_method
        )
    else:
        return asset, bull_call_spread(
            api, asset, spread, days, downsideProtection, price_method
        )


def find_spreads(api, synthetic=False):
    spread_dict = {}
    futures_to_asset = {}

    with ThreadPoolExecutor() as executor:
        for asset in spreads:
            spread = spreads[asset]["spread"]
            days = spreads[asset]["days"]
            downsideProtection = spreads[asset]["downsideProtection"]
            price_method = spreads[asset].get("price", "mid")
            future = executor.submit(
                calculate_spread,
                api,
                asset,
                spread,
                days,
                downsideProtection,
                price_method,
                synthetic,
            )
            futures_to_asset[future] = asset

        for future in as_completed(futures_to_asset):
            asset, result = future.result()
            spread_dict[asset] = result

    # Define the table
    table = PrettyTable()
    if synthetic:
        table.field_names = [
            "Index",
            "Asset",
            "Expiration",
            "Strike Low",
            "Strike High",
            "Call Low B/A",
            "Call High B/A",
            "Put Low B/A",
            "Investment",
            "Max Profit",
            "CAGR",
            "Protection",
            "Margin Req",
            "Ann. ROM %"
        ]
    else:
        table.field_names = [
            "Index",
            "Asset",
            "Expiration",
            "Strike Low",
            "Strike High",
            "Call Low B/A",
            "Call High B/A",
            "Investment",
            "Max Profit",
            "CAGR",
            "Protection",
            "Margin Req",
            "Ann. ROM %"
        ]

    # Create a list to store the rows
    rows = []

    for asset, best_spread in spread_dict.items():
        if best_spread is not None:
            row = [
                asset,
                best_spread["date"],
                best_spread["strike1"],
                best_spread["strike2"],
                f"{best_spread['bid1']}/{best_spread['ask1']}",
                f"{best_spread['bid2']}/{best_spread['ask2']}",
            ]
            if synthetic:
                row.append(f"{best_spread['put_bid']}/{best_spread['put_ask']}")
            row.extend([
                best_spread["total_investment"],
                best_spread["total_return"],
                round(best_spread["cagr_percentage"], 2),
                str(round(best_spread["downside_protection"], 2)) + "%",
                best_spread["margin_requirement"],
                str(round(best_spread["return_on_margin"], 2)) + "%"
            ])
            rows.append(row)

    # Sort the rows by return on margin
    rows.sort(key=lambda x: float(x[-2]), reverse=True)

    # Add the sorted rows to the table with their index
    for index, row in enumerate(rows, start=1):
        table.add_row([index] + row)

    print(table)

    try:
        index = inputimeout(
            prompt="Enter the index of the row you're interested in: ",
            timeout=30,
        )
        try:
            index = int(index)
            if 1 <= index <= len(rows):
                selected_row = table.get_string(start=index - 1, end=index)
                print("You selected the following row:")
                print(selected_row)
                # get the corresponding values from the spread_dict
                selected_asset = rows[index - 1][0]
                selected_date = rows[index - 1][1]
                selected_spread = spread_dict[selected_asset]
                price = selected_spread["net_debit"]
                strike_low = selected_spread["strike1"]
                strike_high = selected_spread["strike2"]
                try:
                    user_input = inputimeout(
                        prompt="Do you want to place the trade? (yes/no): ", timeout=30
                    ).lower()
                except TimeoutOccurred:
                    user_input = "no"
                if user_input == "yes":
                    selected_date = datetime.strptime(selected_date, "%Y-%m-%d")

                    # Print order details
                    print("\nOrder Details:")
                    print(f"Asset: {selected_asset}")
                    print(f"Expiration: {selected_date.strftime('%Y-%m-%d')}")
                    print(f"Low Strike: {strike_low}")
                    print(f"High Strike: {strike_high}")
                    print(f"Net Debit: {price}")
                    print(f"Margin Requirement: {selected_spread['margin_requirement']}")
                    print(f"Annualized Return on Margin: {selected_spread['return_on_margin']}%")
                    if synthetic:
                        print(f"Strategy: Synthetic Covered Call")
                        print(f"Leg 1: Buy Call @ {strike_low} for {selected_spread['ask1']}")
                        print(f"Leg 2: Sell Call @ {strike_high} for {selected_spread['bid2']}")
                        print(f"Leg 3: Buy Put @ {strike_low} for {selected_spread['put_ask']}")
                    else:
                        print(f"Strategy: Vertical Call Spread")
                        print(f"Leg 1: Buy Call @ {strike_low} for {selected_spread['ask1']}")
                        print(f"Leg 2: Sell Call @ {strike_high} for {selected_spread['bid2']}")

                    print("\nPlacing order with automatic price improvements...")

                    # Reset cancel flag
                    global cancel_order
                    cancel_order = False

                    # Setup keyboard listener
                    keyboard.on_press(handle_cancel)

                    try:
                        # Use place_order instead of direct order placement
                        if synthetic:
                            success = api.place_order(
                                api.synthetic_covered_call_order,
                                (selected_asset, selected_date, strike_low, strike_high, 1),
                                price
                            )
                        else:
                            success = api.place_order(
                                api.vertical_call_order,
                                (selected_asset, selected_date, strike_low, strike_high, 1),
                                price - 5
                            )

                        keyboard.unhook_all()

                        if not success:
                            print("Order was not completed.")
                    except Exception as e:
                        keyboard.unhook_all()
                        print(f"Failed to place order: {e}")

                else:
                    print("Order not placed")
            else:
                print("Invalid index. Please enter a number between 1 and", len(rows))
        except ValueError:
            print("Invalid input. Please enter an integer.")
    except TimeoutOccurred:
        print("Timeout occurred. No selection made.")
