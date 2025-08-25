import asyncio
import json
import math
from datetime import datetime, timedelta
from configuration import configuration, spreads
from cc import find_best_rollover, get_median_price
from optionChain import OptionChain
from strategies import calculate_box_spread_wrapper, calculate_spread
from margin_utils import calculate_margin_requirement, calculate_annualized_return_on_margin

async def get_expiring_shorts_data(api):
    """
    Fetches all short positions expiring within 30 days and finds the best rollover for each.
    """
    try:
        short_positions = await asyncio.to_thread(api.updateShortPosition)
        if not short_positions:
            return []

        today = datetime.now().date()
        expiring_shorts = [
            p for p in short_positions
            if (datetime.strptime(p["expiration"], "%Y-%m-%d").date() - today).days <= 30
        ]

        if not expiring_shorts:
            return []

        tasks = [process_short_position(api, short) for short in expiring_shorts]
        results = await asyncio.gather(*tasks)

        return [res for res in results if res]

    except Exception as e:
        print(f"Error in get_expiring_shorts_data: {e}")
        return []

async def process_short_position(api, short):
    """
    Processes a single short position to find rollover data.
    """
    try:
        stock_symbol = short["stockSymbol"]
        current_strike = float(short["strike"])
        short_expiration_date = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
        dte = (short_expiration_date - datetime.now().date()).days

        # Get underlying price
        underlying_price = await asyncio.to_thread(api.getATMPrice, stock_symbol)
        # Determine status
        value = round(current_strike - underlying_price, 2)
        ITMLimit = configuration.get(stock_symbol, {}).get("ITMLimit", 25)
        deepITMLimit = configuration.get(stock_symbol, {}).get("deepITMLimit", 50)
        deepOTMLimit = configuration.get(stock_symbol, {}).get("deepOTMLimit", 10)
        if value > 0:
            status = "OTM"
        elif value < 0:
            if abs(value) > deepITMLimit:
                status = "Deep ITM"
            elif abs(value) > ITMLimit:
                status = "ITM"
            else:
                status = "Just ITM"
        else:
            status = "ATM"

        new_strike = "N/A"
        new_expiration = "N/A"
        roll_out_days = "N/A"
        credit = "N/A"
        strike_delta = "N/A"
        config_status = "Configured"

        if stock_symbol not in configuration:
            config_status = "Not Configured"
        else:
            days = configuration[stock_symbol].get("maxRollOutWindow", 30)
            toDate = short_expiration_date + timedelta(days=days)

            option_chain_obj = await asyncio.to_thread(OptionChain, api, stock_symbol, toDate, days)
            chain = await asyncio.to_thread(option_chain_obj.get)

            if not chain:
                new_expiration = "No chain"
            else:
                roll_option = await asyncio.to_thread(find_best_rollover, api, chain, short)

                if roll_option:
                    new_strike = float(roll_option["strike"])
                    strike_delta = new_strike - current_strike

                    prem_short_contract = await asyncio.to_thread(get_median_price, short["optionSymbol"], chain)
                    roll_premium = await asyncio.to_thread(get_median_price, roll_option["symbol"], chain)

                    if prem_short_contract is not None and roll_premium is not None:
                        credit = round(roll_premium - prem_short_contract, 2)

                    if 'date' in roll_option:
                         new_expiration_date = datetime.strptime(roll_option['date'], "%Y-%m-%d").date()
                    else:
                        option_details = await asyncio.to_thread(api.getOptionDetails, roll_option['symbol'])
                        new_expiration_date = datetime.strptime(option_details['expiration'], "%Y-%m-%d").date()

                    new_expiration = str(new_expiration_date)
                    roll_out_days = (new_expiration_date - short_expiration_date).days

        return {
            "Ticker": stock_symbol,
            "Current Strike": current_strike,
            "Expiration": str(short_expiration_date),
            "DTE": dte,
            "Underlying Price": round(underlying_price, 2),
            "Status": status,
            "Quantity": int(short.get("count", 0)),
            "New Strike": new_strike,
            "New Expiration": new_expiration,
            "Roll Out (Days)": roll_out_days,
            "Credit": credit,
            "Strike Δ": strike_delta,
            "Config Status": config_status,
        }
    except Exception as e:
        print(f"Error processing position {short.get('optionSymbol', 'N/A')}: {e}")
        return None

async def get_box_spreads_data(api, asset="$SPX"):
    """
    Fetches both buy and sell box spread data, showing only the best buy (lowest cost) and best sell (highest return) per expiry.
    """
    try:
        days = spreads[asset].get("days", 2000)
        minDays = spreads[asset].get("minDays", 0)
        strikes = spreads[asset].get("strikes", 500)
        toDate = datetime.today() + timedelta(days=days)
        fromDate = datetime.today() + timedelta(days=minDays)

        calls_chain_raw = await asyncio.to_thread(api.getOptionChain, asset, strikes, toDate, days - 120)
        puts_chain_raw = await asyncio.to_thread(api.getPutOptionChain, asset, strikes, toDate, days - 120)

        option_chain_obj = OptionChain(api, asset, toDate, days)
        calls = await asyncio.to_thread(option_chain_obj.mapApiData, calls_chain_raw)
        puts = await asyncio.to_thread(option_chain_obj.mapApiData, puts_chain_raw, put=True)

        calls = [entry for entry in calls if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]
        puts = [entry for entry in puts if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]

        calls = sorted(calls, key=lambda entry: (datetime.strptime(entry["date"], "%Y-%m-%d"), -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract)))
        puts = sorted(puts, key=lambda entry: (datetime.strptime(entry["date"], "%Y-%m-%d"), -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract)))

        spread_ranges = range(100, 500, 50)
        results = []
        for spread in spread_ranges:
            buy_result = await asyncio.to_thread(calculate_box_spread_wrapper, spread, calls, puts)
            for result, _, direction in buy_result:
                if result is not None:
                    results.append(result)

        # Group by expiry date and direction, keep only best buy (lowest cost) and best sell (highest return)
        best_spreads = {}
        for spread in results:
            key = (spread["date"], spread["direction"])
            ann_cost_return_val = float(spread["ann_rom"])
            if spread["direction"] == "Buy":
                # For buy, keep the lowest (most negative) annualized cost
                if key not in best_spreads or ann_cost_return_val < float(best_spreads[key]["ann_rom"]):
                    best_spreads[key] = spread
            else:
                # For sell, keep the highest annualized return
                if key not in best_spreads or ann_cost_return_val > float(best_spreads[key]["ann_rom"]):
                    best_spreads[key] = spread

        box_spreads = []
        for spread in best_spreads.values():
            try:
                start_date = datetime.today()
                end_date = datetime.strptime(spread["date"], "%Y-%m-%d")
                days = (end_date - start_date).days
                spread_amount = abs(float(spread["high_strike"]) - float(spread["low_strike"])) * 100

                # For buying a box: pay upfront (investment), get more at expiry (repayment)
                # For selling a box: receive upfront (borrowed), pay more at expiry (repayment_sell)
                if spread["direction"] == "Buy":
                    investment = float(spread.get("investment", 0))
                    repayment = float(spread.get("repayment", 0))
                    # Pay investment now, receive repayment at expiry
                    # Annualized return = ((repayment - investment) / investment) * (365 / days)
                    if investment > 0 and repayment > 0 and days > 0:
                        ann_return = ((repayment - investment) / investment) * (365 / days) * 100
                        ann_cost_return = f"{ann_return:.2f}%"
                    else:
                        ann_cost_return = ""
                else:
                    borrowed = float(spread.get("borrowed", 0))
                    repayment_sell = float(spread.get("repayment_sell", 0))
                    # Receive borrowed now, pay repayment_sell at expiry
                    # Annualized cost = ((repayment_sell - borrowed) / borrowed) * (365 / days)
                    # Note: This is a cost to us (negative return) since we pay more than we receive
                    if borrowed > 0 and repayment_sell > 0 and days > 0:
                        ann_cost = ((repayment_sell - borrowed) / borrowed) * (365 / days) * 100
                        ann_cost_return = f"-{ann_cost:.2f}%"  # Negative because it's a cost
                    else:
                        ann_cost_return = ""
            except Exception:
                ann_cost_return = spread["ann_rom"]

            box_spreads.append({
                "direction": spread["direction"],
                "date": spread["date"],
                "low_strike": spread["strike1"],
                "high_strike": spread["strike2"],
                "low_call_ba": f"{spread['low_call_bid']}/{spread['low_call_ask']}",
                "high_call_ba": f"{spread['high_call_bid']}/{spread['high_call_ask']}",
                "low_put_ba": f"{spread['low_put_bid']}/{spread['low_put_ask']}",
                "high_put_ba": f"{spread['high_put_bid']}/{spread['high_put_ask']}",
                "net_price": spread["net_price"],
                "investment": spread.get("investment", ""),
                "repayment": spread.get("repayment", ""),
                "borrowed": spread.get("borrowed", ""),
                "repayment_sell": spread.get("repayment_sell", ""),
                "ann_cost_return": ann_cost_return,
                "margin_req": spread["margin_req"],
            })
        # Sort by expiration date ascending
        box_spreads.sort(key=lambda x: x["date"])
        return box_spreads

    except Exception as e:
        print(f"Error in get_box_spreads_data: {e}")
        return []

async def get_vertical_spreads_data(api, synthetic=False):
    """
    Fetches vertical spread data for all configured assets.
    """
    try:
        spread_results = []
        tasks = []
        for asset in spreads:
            spread = spreads[asset]["spread"]
            days = spreads[asset]["days"]
            downsideProtection = spreads[asset]["downsideProtection"]
            price_method = spreads[asset].get("price", "mid")
            tasks.append(
                asyncio.to_thread(
                    calculate_spread,
                    api,
                    asset,
                    spread,
                    days,
                    downsideProtection,
                    price_method,
                    synthetic,
                )
            )

        results = await asyncio.gather(*tasks)

        for asset, best_spread in results:
            if best_spread:
                row = {
                    "asset": asset,
                    "expiration": best_spread["date"],
                    "strike_low": best_spread["strike1"],
                    "strike_high": best_spread["strike2"],
                    "bid1": best_spread["bid1"],
                    "ask1": best_spread["ask1"],
                    "bid2": best_spread["bid2"],
                    "ask2": best_spread["ask2"],
                    # Ensure these are floats for UI logic
                    "investment": float(best_spread['total_investment']),
                    "max_profit": float(best_spread['total_return']),
                    "cagr": float(best_spread['cagr_percentage']) / 100.0,
                    "protection": float(best_spread['downside_protection']) / 100.0,
                    "margin_req": float(best_spread['margin_requirement']),
                    "ann_rom": float(best_spread['return_on_margin']) / 100.0,
                }
                if synthetic:
                    row["put_bid"] = best_spread["put_bid"]
                    row["put_ask"] = best_spread["put_ask"]

                spread_results.append(row)

        spread_results.sort(key=lambda x: x["ann_rom"], reverse=True)
        return spread_results

    except Exception as e:
        print(f"Error in get_vertical_spreads_data: {e}")
        return []

async def get_margin_requirements_data(api):
    """
    Fetches margin requirements for all short positions.
    """
    try:
        shorts = await asyncio.to_thread(api.updateShortPosition)
        if not shorts:
            return [], 0

        account_data = await asyncio.to_thread(api.connectClient.get_account, api.getAccountHash(), fields=api.connectClient.Account.Fields.POSITIONS)
        account_data = account_data.json()

        margin_data = []
        total_margin = 0

        for short in shorts:
            margin = 0
            option_type = "Call" if "C" in short["optionSymbol"] else "Put"

            for position in account_data["securitiesAccount"]["positions"]:
                if position["instrument"]["symbol"] == short["optionSymbol"]:
                    if "maintenanceRequirement" in position:
                        margin = position["maintenanceRequirement"]
                    break

            if margin > 0:
                total_margin += margin
                margin_data.append({
                    "symbol": short["stockSymbol"],
                    "type": f"Short {option_type}",
                    "strike": short["strike"],
                    "expiration": short["expiration"],
                    "count": int(short["count"]),
                    "margin": f"${margin:,.2f}"
                })

        margin_data.sort(key=lambda x: float(x["margin"].strip('$').replace(',', '')), reverse=True)
        return margin_data, total_margin

    except Exception as e:
        print(f"Error in get_margin_requirements_data: {e}")
        return [], 0