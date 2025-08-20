import asyncio
import json
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
    Fetches box spread data.
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

        best_overall_spread = None
        best_overall_cagr = float("-inf")

        spread_ranges = range(100, 500, 50)
        tasks = [
            asyncio.to_thread(calculate_box_spread_wrapper, spread, calls, puts)
            for spread in spread_ranges
        ]
        results = await asyncio.gather(*tasks)

        for result, spread, trade_direction in results:
            if result is not None and result["cagr_percentage"] > best_overall_cagr:
                best_overall_spread = result
                best_overall_cagr = result["cagr_percentage"]
                best_overall_spread["trade_direction"] = trade_direction.capitalize()

        if best_overall_spread is not None:
            margin_req = calculate_margin_requirement(
                asset,
                'credit_spread',
                strike_diff=best_overall_spread["strike2"] - best_overall_spread["strike1"],
                contracts=1
            )
            if best_overall_spread["trade_direction"].lower() == "sell":
                profit = best_overall_spread["total_investment"] - best_overall_spread["total_return"]
            else:
                profit = best_overall_spread["total_return"] - best_overall_spread["total_investment"]
            days_to_expiry = (datetime.strptime(best_overall_spread["date"], "%Y-%m-%d") - datetime.today()).days
            rom = calculate_annualized_return_on_margin(profit, margin_req, days_to_expiry)

            best_overall_spread["margin_requirement"] = margin_req
            best_overall_spread["return_on_margin"] = rom
            
            return [{
                "date": best_overall_spread["date"],
                "low_strike": best_overall_spread["strike1"],
                "high_strike": best_overall_spread["strike2"],
                "net_price": best_overall_spread["net_debit"],
                "cagr": f"{best_overall_spread['cagr_percentage']:.2f}%",
                "direction": best_overall_spread["trade_direction"],
                "borrowed": best_overall_spread.get("total_investment", "N/A"),
                "repayment": best_overall_spread.get("total_return", "N/A"),
                "margin_req": best_overall_spread["margin_requirement"],
                "ann_rom": f"{best_overall_spread['return_on_margin']:.2f}%",
            }]
        else:
            return []

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
                    "low_call_ba": f"{best_spread['bid1']:.2f}/{best_spread['ask1']:.2f}",
                    "high_call_ba": f"{best_spread['bid2']:.2f}/{best_spread['ask2']:.2f}",
                    "investment": f"{best_spread['total_investment']:.2f}",
                    "max_profit": f"{best_spread['total_return']:.2f}",
                    "cagr": f"{best_spread['cagr_percentage']:.2f}%",
                    "protection": f"{best_spread['downside_protection']:.2f}%",
                    "margin_req": f"{best_spread['margin_requirement']:.2f}",
                    "ann_rom": f"{best_spread['return_on_margin']:.2f}%",
                }
                if synthetic:
                    row["low_put_ba"] = f"{best_spread['put_bid']:.2f}/{best_spread['put_ask']:.2f}"
                
                spread_results.append(row)
        
        spread_results.sort(key=lambda x: float(x["ann_rom"].strip('%')), reverse=True)
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