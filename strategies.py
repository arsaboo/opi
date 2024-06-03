import json
import statistics
from datetime import datetime, timedelta

from inputimeout import TimeoutOccurred, inputimeout
from prettytable import PrettyTable

from configuration import spreads
from optionChain import OptionChain
from support import calculate_cagr


def BoxSpread(api, asset="$SPX"):
    days = 2000
    strikes = 500
    toDate = datetime.today() + timedelta(days=days)
    try:
        calls = api.getOptionChain(asset, strikes, toDate, days - 120)
        puts = api.getPutOptionChain(asset, strikes, toDate, days - 120)
    except Exception as e:
        print(f"Error fetching option chain: {e}")
        return None
    option_chain = OptionChain(api, asset, toDate, days)
    calls = option_chain.mapApiData(calls)
    puts = option_chain.mapApiData(puts, put=True)

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

    for spread in range(100, 500, 50):  # Adjust the range and step as needed
        best_spread = calculate_box_spread(
            spread, json.dumps(calls), json.dumps(puts), trade="sell"
        )
        if (
            best_spread is not None
            and best_spread["cagr_percentage"] > best_overall_cagr
        ):
            best_overall_spread = best_spread
            best_overall_cagr = best_spread["cagr_percentage"]

    if best_overall_spread is not None:
        # Create a dictionary mapping the original column names to the new labels
        labels = {
            "date": "Date",
            "strike1": "Low Strike",
            "strike2": "High Strike",
            "net_debit": "Net Price",
            "cagr_percentage": "% CAGR",
            "total_investment": "Investment",
            "total_return": "Total Return",
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
                    if column == "cagr_percentage"
                    else best_overall_spread[column]
                )
                for column in labels.keys()
            ]
        )
        print(table)
    else:
        print("No best spread found.")


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
        # print(f"Call Contracts: {call_contracts}")
        # print(f"Put Contracts: {put_contracts}")
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
                        # print(f"Low Call: {low_call}, Low Put: {low_put}, High Call: {high_call}, High Put: {high_put}")
                        if trade.lower() == "buy":  # debit
                            trade_price = low_put + high_call - high_put - low_call
                            trade_price = -trade_price
                        elif trade.lower() == "sell":  # credit
                            trade_price = low_call + high_put - high_call - low_put
                    else:
                        continue
                    # print(f"Trade Price: {trade_price}. Strike 1: {call_contracts[i]['strike']}, Strike 2: {call_contracts[j]['strike']}, date: {entry[0]['date']}")
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
                        # print(f"Trade Price: {trade_price}, CAGR: {cagr}, CAGR Percentage: {cagr_percentage}")
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

    toDate = datetime.today() + timedelta(days=days)
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
        for i in range(len(contracts)):
            # Find the next contract with a strike that is 'spread' above this one
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] == spread:
                    # Calculate net credit received by buying and selling options
                    #
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
                    else:
                        cagr = float("-inf")
                        cagr_percentage = round(cagr, 2)

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
    This function calculates the best bull call spread for a given asset
    :param api: the API object
    :param asset: the asset for which the spread is to be calculated
    :param spread: the spread between the two strikes
    :param days: the number of days to expiration
    :param downsideProtection: the minimum downside protection required
    :param price: the price to be used for the spread calculation; we can use Natural (which will use the bid/ask prices) or Market/mid (which will use the median price)
    :return: the best spread for the given asset
    """

    toDate = datetime.today() + timedelta(days=days)
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
    # Iterate over each date's options
    for entry in zip(entries, puts):
        contracts = sorted(entry[0]["contracts"], key=lambda c: c["strike"])
        put_contracts = sorted(entry[1]["contracts"], key=lambda c: c["strike"])

        for i in range(len(contracts)):
            # Find the next contract with a strike that is 'spread' above this one
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] == spread:
                    # Calculate net credit received by buying and selling options
                    #
                    if price.lower() in ["mid", "market"]:
                        net_debit = (
                            statistics.median(
                                [contracts[i]["bid"], contracts[i]["ask"]]
                            )
                            - statistics.median(
                                [contracts[j]["bid"], contracts[j]["ask"]]
                            )
                            - statistics.median(
                                [put_contracts[i]["bid"], put_contracts[i]["ask"]]
                            )
                        )
                    else:
                        net_debit = (
                            contracts[i]["ask"]
                            - contracts[j]["bid"]
                            - put_contracts[i]["bid"]
                        )
                    # calculate break even for this spread
                    break_even = contracts[i]["strike"] + net_debit
                    downside_protection = 1 - (break_even / underlying_price)
                    # Calculate CAGR for this spread
                    days = (
                        datetime.strptime(entry[0]["date"], "%Y-%m-%d")
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
                    else:
                        cagr = float("-inf")
                        cagr_percentage = round(cagr, 2)

                    # If this spread has a higher CAGR than the previous best, update our best spread
                    if cagr > highest_cagr:
                        best_spread = {
                            "asset": asset,
                            "date": entry[0]["date"],
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
                        }
                        highest_cagr = round(cagr, 2)
    if best_spread is not None:
        return best_spread
    else:
        return None


# let us use the bull_call_spread function to calculate the spreads for the indices in the list specified in spreads
def find_spreads(api, synthetic=False):
    spread_dict = {}
    for asset in spreads:
        spread = spreads[asset]["spread"]
        days = spreads[asset]["days"]
        downsideProtection = spreads[asset]["downsideProtection"]
        price_method = spreads[asset].get("price", "mid")
        if synthetic:
            spread_dict[asset] = synthetic_covered_call_spread(
                api, asset, spread, days, downsideProtection, price_method
            )
        else:
            spread_dict[asset] = bull_call_spread(
                api, asset, spread, days, downsideProtection, price_method
            )
    index = 1
    # Define the table
    table = PrettyTable()
    table.field_names = [
        "Index",
        "Asset",
        "Expiration Date",
        "Contract 1",
        "Contract 2",
        "Bid 1",
        "Ask 1",
        "Bid 2",
        "Ask 2",
        "Total Investment",
        "Return",
        "CAGR",
        "Protection",
    ]

    # Create a list to store the rows
    rows = []

    for asset, best_spread in spread_dict.items():
        if best_spread is not None:
            rows.append(
                [
                    asset,
                    best_spread["date"],
                    best_spread["strike1"],
                    best_spread["strike2"],
                    best_spread["bid1"],
                    best_spread["ask1"],
                    best_spread["bid2"],
                    best_spread["ask2"],
                    best_spread["total_investment"],
                    best_spread["total_return"],
                    str(round(best_spread["cagr_percentage"], 2)) + "%",
                    str(round(best_spread["downside_protection"], 2)) + "%",
                ]
            )

    # Sort the rows by CAGR
    rows.sort(key=lambda x: x[10], reverse=True)

    # Add the sorted rows to the table with their index
    for index, row in enumerate(rows, start=1):
        table.add_row([index] + row)

    print(table)
    index = None

    try:
        index = inputimeout(
            prompt="Enter the index of the row you're interested in: ",
            timeout=30,
        )
        index = int(index)
    except ValueError:
        print("Invalid input. Please enter an integer.")
    except TimeoutOccurred:
        index = 0
    if index >= 1 and index <= len(rows):
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
            api.place_order(
                api.vertical_call_order,
                [selected_asset, selected_date, strike_low, strike_high, 1],
                price - 25,
            )
        else:
            print("Order not placed")
