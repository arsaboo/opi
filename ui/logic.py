import asyncio
import json
from datetime import datetime, timedelta
from configuration import configuration, spreads
from status import notify_exception
from core.covered_calls import find_best_rollover
from core.common import get_median_price, classify_status
from api.option_chain import OptionChain
from core.box_spreads import calculate_box_spread as core_calc_box
from core.vertical_spreads import bull_call_spread as core_bull_call
from core.synthetic_covered_calls import synthetic_covered_call_spread as core_synth_cc
from core.margin import calculate_margin_requirement, calculate_annualized_return_on_margin


# Helpers for using core calculators from UI
def calculate_box_spread_wrapper(spread, calls, puts):
    buy_result = core_calc_box(spread, json.dumps(calls), json.dumps(puts), trade="buy")
    sell_result = core_calc_box(spread, json.dumps(calls), json.dumps(puts), trade="sell")
    return [
        (buy_result, spread, "Buy"),
        (sell_result, spread, "Sell"),
    ]

# Async wrappers for long-running API calls used by widgets
async def roll_over(api, old_symbol: str, new_symbol: str, amount: int, price: float):
    return await asyncio.to_thread(api.rollOver, old_symbol, new_symbol, amount, price)

async def cancel_order(api, order_id):
    return await asyncio.to_thread(api.cancelOrder, order_id)

async def check_order(api, order_id):
    return await asyncio.to_thread(api.checkOrder, order_id)

async def vertical_call_order(api, asset, expiration, strike_low, strike_high, quantity, price: float):
    return await asyncio.to_thread(
        api.vertical_call_order,
        asset,
        expiration,
        strike_low,
        strike_high,
        quantity,
        price=price,
    )

def _compute_spread(api, asset, spread, days, downsideProtection, price_method, synthetic):
    if synthetic:
        return asset, core_synth_cc(api, asset, spread, days, downsideProtection, price_method)
    else:
        return asset, core_bull_call(api, asset, spread, days, downsideProtection, price_method)

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
        notify_exception(e, prefix="get_expiring_shorts_data")
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
        # Determine status (centralized)
        ITMLimit = configuration.get(stock_symbol, {}).get("ITMLimit", 25)
        deepITMLimit = configuration.get(stock_symbol, {}).get("deepITMLimit", 50)
        deepOTMLimit = configuration.get(stock_symbol, {}).get("deepOTMLimit", 10)
        status_map = {
            "deep_OTM": "OTM",
            "OTM": "OTM",
            "just_ITM": "Just ITM",
            "ITM": "ITM",
            "deep_ITM": "Deep ITM",
        }
        status_key = classify_status(current_strike, underlying_price,
                                     itm_limit=ITMLimit,
                                     deep_itm_limit=deepITMLimit,
                                     deep_otm_limit=deepOTMLimit)
        status = status_map.get(status_key, "ATM")

        new_strike = "N/A"
        new_expiration = "N/A"
        roll_out_days = "N/A"
        credit = "N/A"
        strike_delta = "N/A"
        config_status = "Configured"
        new_option_symbol = "N/A"  # Add this for rollOver

        # Always try to calculate current short premium for extrinsic_left
        prem_short_contract = None
        days = configuration.get(stock_symbol, {}).get("maxRollOutWindow", 30)  # Use default if not configured
        toDate = short_expiration_date + timedelta(days=days)
        option_chain_obj = await asyncio.to_thread(OptionChain, api, stock_symbol, toDate, days)
        chain = await asyncio.to_thread(option_chain_obj.get)
        if chain:
            prem_short_contract = await asyncio.to_thread(get_median_price, short["optionSymbol"], chain)

        if stock_symbol not in configuration:
            config_status = "Not Configured"
        else:
            if not chain:
                new_expiration = "No chain"
            else:
                roll_option = await asyncio.to_thread(find_best_rollover, api, chain, short)

                if roll_option:
                    new_strike = float(roll_option["strike"])
                    strike_delta = new_strike - current_strike
                    new_option_symbol = roll_option["symbol"]  # Store for rollOver

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

        # Calculate new fields
        cr_day = "N/A"
        extrinsic_left = "N/A"
        cr_day_per_pt = "N/A"
        if credit != "N/A" and roll_out_days != "N/A" and roll_out_days > 0:
            cr_day = round(credit / roll_out_days, 2)
            # Calculate CrDayPerPt (normalized per point of roll-up, in cash dollars)
            try:
                delta_k = float(new_strike) - float(current_strike)
                denom = roll_out_days * max(abs(delta_k), 1e-6)
                cr_day_per_pt = round((credit * 100) / denom, 2)
            except Exception:
                cr_day_per_pt = "N/A"
        if prem_short_contract is not None:
            intrinsic_value = max(0, underlying_price - current_strike)
            extrinsic_left = round(prem_short_contract - intrinsic_value, 2)

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
            "Cr/Day": cr_day,
            "CrDayPerPt": cr_day_per_pt,
            "Extrinsic": extrinsic_left,
            "Strike Δ": strike_delta,
            "Config Status": config_status,
            "optionSymbol": short["optionSymbol"],  # Add for rollOver
            "New Option Symbol": new_option_symbol,  # Add for rollOver
        }
    except Exception as e:
        prefix = f"process_short_position {short.get('optionSymbol', 'N/A')}"
        notify_exception(e, prefix=prefix)
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
            ann_return_val = float(spread["ann_rom"]) if spread["ann_rom"] is not None else 0
            if spread["direction"] == "Buy":
                # For buy, keep the highest annualized return
                if key not in best_spreads or ann_return_val > float(best_spreads[key]["ann_rom"] or 0):
                    best_spreads[key] = spread
            else:
                # For sell, keep the highest annualized return (most negative is worst, least negative is best)
                if key not in best_spreads or ann_return_val > float(best_spreads[key]["ann_rom"] or 0):
                    best_spreads[key] = spread

        box_spreads = []
        for spread in best_spreads.values():
            try:
                start_date = datetime.today()
                end_date = datetime.strptime(spread["date"], "%Y-%m-%d")
                days = (end_date - start_date).days

                # Check for impossible mids or suspect quotes
                flags = []

                # Check if mid prices are valid (not crossed)
                low_call_bid = spread.get("low_call_bid")
                low_call_ask = spread.get("low_call_ask")
                high_call_bid = spread.get("high_call_bid")
                high_call_ask = spread.get("high_call_ask")
                low_put_bid = spread.get("low_put_bid")
                low_put_ask = spread.get("low_put_ask")
                high_put_bid = spread.get("high_put_bid")
                high_put_ask = spread.get("high_put_ask")

                if all(x is not None for x in [low_call_bid, low_call_ask, high_call_bid, high_call_ask,
                                               low_put_bid, low_put_ask, high_put_bid, high_put_ask]):
                    # Check for crossed quotes (bid > ask)
                    if low_call_bid > low_call_ask:
                        flags.append("Low Call Crossed")
                    if high_call_bid > high_call_ask:
                        flags.append("High Call Crossed")
                    if low_put_bid > low_put_ask:
                        flags.append("Low Put Crossed")
                    if high_put_bid > high_put_ask:
                        flags.append("High Put Crossed")

                    # Check for negative spreads (ask < bid for the same leg)
                    if low_call_ask < low_call_bid:
                        flags.append("Low Call Negative Spread")
                    if high_call_ask < high_call_bid:
                        flags.append("High Call Negative Spread")
                    if low_put_ask < low_put_bid:
                        flags.append("Low Put Negative Spread")
                    if high_put_ask < high_put_bid:
                        flags.append("High Put Negative Spread")

                box_spreads.append({
                    "direction": spread["direction"],
                    "date": spread["date"],
                    "low_strike": spread["strike1"],
                    "high_strike": spread["strike2"],
                    "low_call_ba": f"{spread['low_call_bid']}/{spread['low_call_ask']}",
                    "high_call_ba": f"{spread['high_call_bid']}/{spread['high_call_ask']}",
                    "low_put_ba": f"{spread['low_put_bid']}/{spread['low_put_ask']}",
                    "high_put_ba": f"{spread['high_put_bid']}/{spread['high_put_ask']}",
                    "low_call_symbol": spread.get("low_call_symbol"),
                    "high_call_symbol": spread.get("high_call_symbol"),
                    "low_put_symbol": spread.get("low_put_symbol"),
                    "high_put_symbol": spread.get("high_put_symbol"),
                    # Mid-based prices and metrics
                    "mid_net_price": spread.get("mid_net_price", ""),
                    "mid_upfront_amount": spread.get("mid_upfront_amount", ""),
                    "mid_annualized_return": spread.get("mid_annualized_return", ""),
                    # Natural/executable prices and metrics
                    "nat_net_price": spread.get("nat_net_price", ""),
                    "nat_upfront_amount": spread.get("nat_upfront_amount", ""),
                    "nat_annualized_return": spread.get("nat_annualized_return", ""),
                    # Face value
                    "face_value": spread.get("face_value", ""),
                    # Backward compatibility fields (using mid-based values)
                    "net_price": spread.get("net_price", ""),
                    "investment": spread.get("investment", ""),
                    "borrowed": spread.get("borrowed", ""),
                    "repayment": spread.get("repayment", ""),
                    "repayment_sell": spread.get("repayment_sell", ""),
                    "ann_cost_return": spread.get("ann_rom", ""),
                    "days_to_expiry": spread.get("days_to_expiry", ""),
                    # Flags for suspect quotes
                    "flags": ", ".join(flags) if flags else ""
                })
            except Exception as e:
                notify_exception(e, prefix="process box spread row")
                # Add a basic entry even if there's an error
                box_spreads.append({
                    "direction": spread.get("direction", ""),
                    "date": spread.get("date", ""),
                    "low_strike": spread.get("strike1", ""),
                    "high_strike": spread.get("strike2", ""),
                    "low_call_ba": f"{spread.get('low_call_bid', '')}/{spread.get('low_call_ask', '')}",
                    "high_call_ba": f"{spread.get('high_call_bid', '')}/{spread.get('high_call_ask', '')}",
                    "low_put_ba": f"{spread.get('low_put_bid', '')}/{spread.get('low_put_ask', '')}",
                    "high_put_ba": f"{spread.get('high_put_bid', '')}/{spread.get('high_put_ask', '')}",
                    "mid_net_price": spread.get("mid_net_price", ""),
                    "mid_upfront_amount": spread.get("mid_upfront_amount", ""),
                    "mid_annualized_return": spread.get("mid_annualized_return", ""),
                    "nat_net_price": spread.get("nat_net_price", ""),
                    "nat_upfront_amount": spread.get("nat_upfront_amount", ""),
                    "nat_annualized_return": spread.get("nat_annualized_return", ""),
                    "face_value": spread.get("face_value", ""),
                    "net_price": spread.get("net_price", ""),
                    "investment": spread.get("investment", ""),
                    "borrowed": spread.get("borrowed", ""),
                    "repayment": spread.get("repayment", ""),
                    "repayment_sell": spread.get("repayment_sell", ""),
                    "ann_cost_return": spread.get("ann_rom", ""),
                    "days_to_expiry": spread.get("days_to_expiry", ""),
                    "flags": "Error processing data"
                })

        # Sort by expiration date ascending
        box_spreads.sort(key=lambda x: x["date"])
        return box_spreads

    except Exception as e:
        notify_exception(e, prefix="get_box_spreads_data")
        return []

async def get_vertical_spreads_data(api, synthetic=False):
    """
    Fetches vertical spread data for all configured assets.
    """
    try:
        spread_results = []
        tasks = []
        for asset in spreads:
            spread_w = spreads[asset]["spread"]
            days = spreads[asset]["days"]
            downsideProtection = spreads[asset]["downsideProtection"]
            price_method = spreads[asset].get("price", "mid")
            tasks.append(
                asyncio.to_thread(
                    _compute_spread,
                    api,
                    asset,
                    spread_w,
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
                    "symbol1": best_spread.get("symbol1"),
                    "symbol2": best_spread.get("symbol2"),
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
                    row["put_symbol"] = best_spread.get("put_symbol")

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
        notify_exception(e, prefix="get_margin_requirements_data")
        return [], 0
