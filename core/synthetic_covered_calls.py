import statistics
from datetime import datetime, timedelta
from core.spreads_common import mid_price, days_to_expiry

from configuration import spreads
from api.option_chain import OptionChain
from core.common import calculate_cagr
from core.margin import calculate_margin_requirement, calculate_annualized_return_on_margin


def synthetic_covered_call_spread(api, asset, spread=100, days=90, downsideProtection=0.25, price="mid"):
    minDays = spreads[asset].get("minDays", 0)
    toDate = datetime.today() + timedelta(days=days)
    fromDate = datetime.today() + timedelta(days=minDays)

    optionChain = OptionChain(api, asset, toDate, days)
    quote = api.get_quote(asset)
    if not (quote and asset in quote and quote[asset] and "quote" in quote[asset]):
        return None
    underlying_price = quote[asset]["quote"].get("lastPrice")

    calls = optionChain.get()
    # Use a reasonable strike count similar to calls path (OptionChain.get uses 150)
    puts_raw = api.getPutOptionChain(asset, 150, toDate, days - 120)
    puts = optionChain.mapApiData(puts_raw, put=True)

    calls = [entry for entry in calls if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]
    puts = [entry for entry in puts if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]

    entries = sorted(
        calls,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract),
        ),
    )

    best_spread = None
    highest_cagr = float("-inf")

    puts_by_date = {e["date"]: e for e in puts}

    for entry in entries:
        contracts = sorted(entry["contracts"], key=lambda c: c["strike"]) if entry.get("contracts") else []
        if not contracts or contracts[0].get("underlying") != asset:
            continue

        put_entry = puts_by_date.get(entry["date"]) or {"contracts": []}
        put_contracts_map = {pc["strike"]: pc for pc in put_entry.get("contracts", [])}

        if not put_contracts_map:
            continue

        for i in range(len(contracts)):
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] != spread:
                    continue
                put_contract = put_contracts_map.get(contracts[i]["strike"])
                if not put_contract:
                    continue

                if price.lower() in ["mid", "market"]:
                    net_debit = (
                        mid_price(contracts[i]["bid"], contracts[i]["ask"]) -
                        mid_price(contracts[j]["bid"], contracts[j]["ask"]) -
                        mid_price(put_contract["bid"], put_contract["ask"])
                    )
                else:
                    net_debit = contracts[i]["ask"] - contracts[j]["bid"] - put_contract["bid"]

                break_even = contracts[i]["strike"] + net_debit
                downside_protection = 1 - (break_even / underlying_price)
                days_to_exp = days_to_expiry(entry["date"])
                if days_to_exp > 1 and 0 < net_debit < spread and downside_protection > downsideProtection:
                    total_investment = net_debit
                    returns = abs(contracts[j]["strike"] - contracts[i]["strike"])
                    cagr, cagr_percentage = calculate_cagr(total_investment, returns, days_to_exp)

                    margin_req = calculate_margin_requirement(
                        asset,
                        'synthetic_covered_call',
                        put_strike=contracts[i]["strike"],
                        underlying_value=underlying_price,
                        put_premium=put_contract["bid"],
                        max_loss=contracts[i]["strike"] * 100,
                    )

                    profit = (spread - net_debit) * 100
                    rom = calculate_annualized_return_on_margin(profit, margin_req, days_to_exp)
                else:
                    cagr = float("-inf")
                    cagr_percentage = round(cagr, 2)
                    margin_req = 0
                    rom = 0

                if cagr > highest_cagr:
                    best_spread = {
                        "asset": asset,
                        "date": entry["date"],
                        "strike1": contracts[i]["strike"],
                        "bid1": contracts[i]["bid"],
                        "ask1": contracts[i]["ask"],
                        "symbol1": contracts[i]["symbol"],
                        "bid2": contracts[j]["bid"],
                        "ask2": contracts[j]["ask"],
                        "symbol2": contracts[j]["symbol"],
                        "put_bid": put_contract["bid"],
                        "put_ask": put_contract["ask"],
                        "put_symbol": put_contract["symbol"],
                        "strike2": contracts[j]["strike"],
                        "net_debit": round(net_debit, 2),
                        "cagr": round(cagr, 2),
                        "cagr_percentage": round(cagr_percentage, 2),
                        "downside_protection": round(downside_protection * 100, 2),
                        "total_investment": round(net_debit * 100, 2),
                        "total_return": round((spread - net_debit) * 100, 2),
                        "margin_requirement": round(margin_req, 2),
                        "return_on_margin": round(rom, 2),
                    }
                    highest_cagr = round(cagr, 2)

    return best_spread
