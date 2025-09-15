from datetime import datetime, timedelta
from core.spreads_common import mid_price, days_to_expiry

from configuration import spreads
from api.option_chain import OptionChain
from core.common import calculate_cagr
from core.margin import calculate_margin_requirement, calculate_annualized_return_on_margin


def bull_call_spread(api, asset, spread=100, days=90, downsideProtection=0.25, price="mid"):
    minDays = spreads[asset].get("minDays", 0)
    toDate = datetime.today() + timedelta(days=days)
    fromDate = datetime.today() + timedelta(days=minDays)
    optionChain = OptionChain(api, asset, toDate, days)
    underlying_price = api.get_price(asset)
    if underlying_price is None:
        return None
    chain = optionChain.get()

    chain = [entry for entry in chain if datetime.strptime(entry["date"], "%Y-%m-%d") >= fromDate]
    entries = sorted(
        chain,
        key=lambda entry: (
            datetime.strptime(entry["date"], "%Y-%m-%d"),
            -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract),
        ),
    )

    best_spread = None
    highest_cagr = float("-inf")
    for entry in entries:
        contracts = sorted(entry["contracts"], key=lambda c: c["strike"]) if entry.get("contracts") else []
        if not contracts or contracts[0].get("underlying") != asset:
            continue
        for i in range(len(contracts)):
            for j in range(i + 1, len(contracts)):
                if contracts[j]["strike"] - contracts[i]["strike"] != spread:
                    continue
                if price.lower() in ["mid", "market"]:
                    net_debit = (
                        mid_price(contracts[i]["bid"], contracts[i]["ask"]) -
                        mid_price(contracts[j]["bid"], contracts[j]["ask"])
                    )
                else:
                    net_debit = contracts[i]["ask"] - contracts[j]["bid"]

                break_even = contracts[i]["strike"] + net_debit
                downside_protection = 1 - (break_even / underlying_price)
                days_to_exp = days_to_expiry(entry["date"])
                if days_to_exp > 1 and net_debit > 0 and net_debit < spread and downside_protection > downsideProtection:
                    # Use per-contract dollars for both investment and max profit to be consistent
                    width = abs(contracts[j]["strike"] - contracts[i]["strike"])  # points
                    invest_total = float(net_debit) * 100.0
                    profit_total = (width - float(net_debit)) * 100.0
                    if profit_total > 0 and invest_total > 0:
                        cagr, cagr_percentage = calculate_cagr(invest_total, profit_total, days_to_exp)
                    else:
                        cagr, cagr_percentage = 0, 0

                    margin_req = calculate_margin_requirement(
                        asset,
                        'spread_call',
                        strike_diff=contracts[j]["strike"] - contracts[i]["strike"],
                        contracts_count=1
                    ) if False else 0  # keep compatibility minimal; existing UI uses margin later

                    profit = (spread - net_debit) * 100
                    rom = calculate_annualized_return_on_margin(profit, margin_req, days_to_exp) if margin_req else 0
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
                        "strike2": contracts[j]["strike"],
                        "net_debit": round(net_debit, 2),
                        "cagr": round(cagr, 2),
                        "cagr_percentage": round(cagr_percentage, 2),
                        "downside_protection": round(downside_protection * 100, 2),
                        "total_investment": round(invest_total, 2),
                        "total_return": round(profit_total, 2),
                        "margin_requirement": round(margin_req, 2),
                        "return_on_margin": round(rom, 2),
                    }
                    highest_cagr = round(cagr, 2)

    return best_spread
