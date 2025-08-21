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
from order_utils import monitor_order, handle_cancel, cancel_order, reset_cancel_flag

__all__ = ['monitor_order']

def calculate_box_spread_wrapper(spread, calls, puts):
    # Calculate both buy and sell box spreads for the given spread width
    buy_result = calculate_box_spread(spread, json.dumps(calls), json.dumps(puts), trade="buy")
    sell_result = calculate_box_spread(spread, json.dumps(calls), json.dumps(puts), trade="sell")
    return [
        (buy_result, spread, "Buy"),
        (sell_result, spread, "Sell")
    ]


def calculate_box_spread(spread, calls, puts, trade="Sell", price="mid"):
    # Parse the JSON option chain
    calls_chain = json.loads(calls)
    puts_chain = json.loads(puts)
    highest_cagr = None

    if trade.lower() == "buy":
        highest_cagr = 0
    elif trade.lower() == "sell":
        highest_cagr = float("-inf")
    best_spread = None

    for entry in zip(calls_chain, puts_chain):
        call_contracts = sorted(entry[0]["contracts"], key=lambda c: c["strike"])
        put_contracts = sorted(entry[1]["contracts"], key=lambda c: c["strike"])
        for i in range(len(call_contracts)):
            for j in range(i + 1, len(call_contracts)):
                if call_contracts[j]["strike"] - call_contracts[i]["strike"] == spread:
                    # Bid/Ask for all legs
                    low_call_bid = call_contracts[i]["bid"]
                    low_call_ask = call_contracts[i]["ask"]
                    high_call_bid = call_contracts[j]["bid"]
                    high_call_ask = call_contracts[j]["ask"]
                    low_put_bid = put_contracts[i]["bid"]
                    low_put_ask = put_contracts[i]["ask"]
                    high_put_bid = put_contracts[j]["bid"]
                    high_put_ask = put_contracts[j]["ask"]

                    # Calculate net price for buy/sell
                    if price.lower() in ["mid", "market"]:
                        low_call = statistics.median([low_call_bid, low_call_ask])
                        low_put = statistics.median([low_put_bid, low_put_ask])
                        high_call = statistics.median([high_call_bid, high_call_ask])
                        high_put = statistics.median([high_put_bid, high_put_ask])
                    else:  # natural
                        if trade.lower() == "buy":
                            low_call = low_call_ask
                            low_put = low_put_bid
                            high_call = high_call_bid
                            high_put = high_put_ask
                        elif trade.lower() == "sell":
                            low_call = low_call_bid
                            low_put = low_put_ask
                            high_call = high_call_ask
                            high_put = high_put_bid

                    if None not in [low_call, high_put, high_call, low_put]:
                        if trade.lower() == "buy":
                            trade_price = low_put + high_call - high_put - low_call
                            trade_price = -trade_price
                        elif trade.lower() == "sell":
                            trade_price = low_call + high_put - high_call - low_put
                    else:
                        continue

                    low_strike = call_contracts[i]["strike"]
                    high_strike = call_contracts[j]["strike"]
                    days = (datetime.strptime(entry[0]["date"], "%Y-%m-%d").date() - datetime.today().date()).days

                    if days > 1 and trade_price > 0:
                        if trade.lower() == "buy":
                            # For buying a box: pay net price now, receive spread at expiry
                            cagr, cagr_percentage = calculate_cagr(trade_price, spread, days)
                            investment = round(trade_price * 100, 2)
                            repayment = round(spread * 100, 2)
                        else:
                            # For selling a box: receive net price now, pay spread at expiry
                            cagr, cagr_percentage = calculate_cagr(spread, trade_price, days)
                            borrowed = round(trade_price * 100, 2)
                            repayment_sell = round(spread * 100, 2)

                        # Margin requirement and ROM
                        margin_req = calculate_margin_requirement(
                            entry[0].get("underlying", "$SPX"),
                            'credit_spread',
                            strike_diff=high_strike - low_strike,
                            contracts=1
                        )
                        if trade.lower() == "buy":
                            profit = repayment - investment  # Receive more at expiry than paid upfront
                        else:
                            profit = borrowed - repayment_sell  # Receive more upfront than paid at expiry
                        rom = calculate_annualized_return_on_margin(profit, margin_req, days)

                        spread_dict = {
                            "date": entry[0]["date"],
                            "strike1": low_strike,
                            "strike2": high_strike,
                            "low_call_bid": low_call_bid,
                            "low_call_ask": low_call_ask,
                            "high_call_bid": high_call_bid,
                            "high_call_ask": high_call_ask,
                            "low_put_bid": low_put_bid,
                            "low_put_ask": low_put_ask,
                            "high_put_bid": high_put_bid,
                            "high_put_ask": high_put_ask,
                            "net_price": round(trade_price, 2),
                            "cagr": round(cagr, 2),
                            "cagr_percentage": round(cagr_percentage, 2),
                            "investment": investment if trade.lower() == "buy" else None,
                            "repayment": repayment if trade.lower() == "buy" else None,
                            "borrowed": borrowed if trade.lower() == "sell" else None,
                            "repayment_sell": repayment_sell if trade.lower() == "sell" else None,
                            "margin_req": margin_req,
                            "ann_rom": round(rom, 2),
                            "direction": trade.capitalize()
                        }
                        if (trade.lower() == "buy" and (highest_cagr is None or cagr > highest_cagr)) or \
                           (trade.lower() == "sell" and (highest_cagr is None or cagr > highest_cagr)):
                            best_spread = spread_dict
                            highest_cagr = round(cagr, 2)
    return best_spread


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

    # Calculate both buy and sell box spreads for each spread width
    spread_results = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(calculate_box_spread_wrapper, spread, calls, puts): spread
            for spread in range(100, 500, 50)
        }
        for future in as_completed(futures):
            results = future.result()
            for result, spread, direction in results:
                if result is not None:
                    spread_results.append(result)

    # Table columns
    table = PrettyTable()
    table.field_names = [
        "Direction",
        "Date",
        "Low Strike",
        "High Strike",
        "Low Call B/A",
        "High Call B/A",
        "Low Put B/A",
        "High Put B/A",
        "Net Price",
        "Investment",
        "Repayment",
        "Borrowed",
        "Repayment (Sell)",
        "Ann. Cost/Return %",
        "Margin Req",
        "Ann. ROM %"
    ]

    # Add rows for both buy and sell box spreads
    for spread in spread_results:
        # Use the ann_rom value directly but format appropriately for buy vs sell
        ann_cost_return_label = f"{spread['ann_rom']:.2f}%"

        table.add_row([
            spread["direction"],
            spread["date"],
            spread["strike1"],
            spread["strike2"],
            f"{spread['low_call_bid']}/{spread['low_call_ask']}",
            f"{spread['high_call_bid']}/{spread['high_call_ask']}",
            f"{spread['low_put_bid']}/{spread['low_put_ask']}",
            f"{spread['high_put_bid']}/{spread['high_put_ask']}",
            spread["net_price"],
            spread["investment"] if spread["direction"] == "Buy" else "",
            spread["repayment"] if spread["direction"] == "Buy" else "",
            spread["borrowed"] if spread["direction"] == "Sell" else "",
            spread["repayment_sell"] if spread["direction"] == "Sell" else "",
            ann_cost_return_label,
            spread["margin_req"],
            spread["ann_rom"]
        ])
    print(table)

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
                        print("Strategy: Synthetic Covered Call")
                        print(f"Leg 1: Buy Call @ {strike_low} for {selected_spread['ask1']}")
                        print(f"Leg 2: Sell Call @ {strike_high} for {selected_spread['bid2']}")
                        print(f"Leg 3: Buy Put @ {strike_low} for {selected_spread['put_ask']}")
                    else:
                        print("Strategy: Vertical Call Spread")
                        print(f"Leg 1: Buy Call @ {strike_low} for {selected_spread['ask1']}")
                        print(f"Leg 2: Sell Call @ {strike_high} for {selected_spread['bid2']}")

                    try:
                        # Reset cancel flag and clear keyboard hooks
                        reset_cancel_flag()
                        keyboard.unhook_all()
                        keyboard.on_press(handle_cancel)

                        print("\nPlacing order with automatic price improvements...")
                        # Try prices in sequence, starting with original price
                        initial_price = price
                        for i in range(0, 76):  # 0 = original price, 1-75 = improvements
                            if cancel_order:
                                print("\nOperation cancelled by user")
                                break

                            current_price = (
                                initial_price if i == 0
                                else round_to_nearest_five_cents(initial_price * (1 - (i/100)))
                            )

                            if i > 0:
                                print(f"\nTrying new price: ${current_price} (improvement #{i})")

                            # Place order with appropriate strategy
                            if synthetic:
                                order_id = api.synthetic_covered_call_order(
                                    selected_asset,
                                    selected_date,
                                    strike_low,
                                    strike_high,
                                     1,  # quantity
                                    price=current_price  # Explicitly pass price as keyword arg
                                )
                            else:
                                order_id = api.vertical_call_order(
                                    selected_asset,
                                    selected_date,
                                    strike_low,
                                    strike_high,
                                    1,  # quantity
                                    current_price - 5
                                )

                            # Monitor with 60s timeout
                            result = monitor_order(api, order_id, timeout=60)

                            if result is True:  # Order filled
                                break
                            elif result == "cancelled":  # User cancelled
                                break
                            elif result == "rejected":  # Order rejected
                                continue  # Try next price
                            # On timeout, continue to next price improvement

                            # Brief pause between attempts
                            if i > 0:
                                time.sleep(1)

                    finally:
                        keyboard.unhook_all()

                else:
                    print("Order not placed")
            else:
                print("Invalid index. Please enter a number between 1 and", len(rows))
        except ValueError:
            print("Invalid input. Please enter an integer.")
    except TimeoutOccurred:
        print("Timeout occurred. No selection made.")
