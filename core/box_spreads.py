import json
import statistics
from datetime import datetime
from core.spreads_common import mid_price, days_to_expiry, face_value as face_val, valid_ba


def calculate_box_spread(spread, calls_json, puts_json, trade="Sell"):
    calls_chain = json.loads(calls_json)
    puts_chain = json.loads(puts_json)
    highest_cagr = 0 if trade.lower() == "buy" else float("-inf")
    best_spread = None

    for entry in zip(calls_chain, puts_chain):
        call_contracts = sorted(entry[0]["contracts"], key=lambda c: c["strike"])
        put_contracts = sorted(entry[1]["contracts"], key=lambda c: c["strike"])
        for i in range(len(call_contracts)):
            for j in range(i + 1, len(call_contracts)):
                if call_contracts[j]["strike"] - call_contracts[i]["strike"] != spread:
                    continue

                low_call_bid = call_contracts[i]["bid"]
                low_call_ask = call_contracts[i]["ask"]
                high_call_bid = call_contracts[j]["bid"]
                high_call_ask = call_contracts[j]["ask"]
                low_put_bid = put_contracts[i]["bid"]
                low_put_ask = put_contracts[i]["ask"]
                high_put_bid = put_contracts[j]["bid"]
                high_put_ask = put_contracts[j]["ask"]

                # Mid price
                if valid_ba(low_call_bid, low_call_ask, high_call_bid, high_call_ask, low_put_bid, low_put_ask, high_put_bid, high_put_ask):
                    low_call_mid = mid_price(low_call_bid, low_call_ask)
                    low_put_mid = mid_price(low_put_bid, low_put_ask)
                    high_call_mid = mid_price(high_call_bid, high_call_ask)
                    high_put_mid = mid_price(high_put_bid, high_put_ask)
                    if trade.lower() == "buy":
                        mid_trade_price = -(low_put_mid + high_call_mid - high_put_mid - low_call_mid)
                    else:
                        mid_trade_price = low_call_mid + high_put_mid - high_call_mid - low_put_mid
                else:
                    mid_trade_price = None

                # Natural/executable
                if trade.lower() == "buy":
                    low_call_nat = low_call_ask
                    low_put_nat = low_put_bid
                    high_call_nat = high_call_bid
                    high_put_nat = high_put_ask
                else:
                    low_call_nat = low_call_bid
                    low_put_nat = low_put_ask
                    high_call_nat = high_call_ask
                    high_put_nat = high_put_bid

                if None not in [low_call_nat, high_put_nat, high_call_nat, low_put_nat]:
                    if trade.lower() == "buy":
                        nat_trade_price = -(low_put_nat + high_call_nat - high_put_nat - low_call_nat)
                    else:
                        nat_trade_price = low_call_nat + high_put_nat - high_call_nat - low_put_nat
                else:
                    nat_trade_price = None

                low_strike = call_contracts[i]["strike"]
                high_strike = call_contracts[j]["strike"]
                days = days_to_expiry(entry[0]["date"])
                face_value = face_val(low_strike, high_strike)

                mid_metrics = {"net_price": None, "upfront_amount": None, "annualized_return": None}
                if mid_trade_price is not None:
                    if trade.lower() == "buy":
                        upfront_amount = face_value - mid_trade_price
                        effective_days = max(days, 1)
                        annualized_return = ((face_value - upfront_amount) / upfront_amount) * (365 / effective_days)
                    else:
                        upfront_amount = mid_trade_price
                        effective_days = max(days, 1)
                        annualized_return = ((upfront_amount - face_value) / face_value) * (365 / effective_days)
                    mid_metrics = {
                        "net_price": round(mid_trade_price, 2),
                        "upfront_amount": round(upfront_amount, 2),
                        "annualized_return": round(annualized_return * 100, 2),
                    }

                nat_metrics = {"net_price": None, "upfront_amount": None, "annualized_return": None}
                if nat_trade_price is not None:
                    if trade.lower() == "buy":
                        upfront_amount = face_value - nat_trade_price
                        effective_days = max(days, 1)
                        annualized_return = ((face_value - upfront_amount) / upfront_amount) * (365 / effective_days)
                    else:
                        upfront_amount = nat_trade_price
                        effective_days = max(days, 1)
                        annualized_return = ((upfront_amount - face_value) / face_value) * (365 / effective_days)
                    nat_metrics = {
                        "net_price": round(nat_trade_price, 2),
                        "upfront_amount": round(upfront_amount, 2),
                        "annualized_return": round(annualized_return * 100, 2),
                    }

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
                    "low_call_symbol": call_contracts[i]["symbol"],
                    "high_call_symbol": call_contracts[j]["symbol"],
                    "low_put_symbol": put_contracts[i]["symbol"],
                    "high_put_symbol": put_contracts[j]["symbol"],
                    "face_value": face_value,
                    "mid_net_price": mid_metrics.get("net_price"),
                    "mid_upfront_amount": mid_metrics.get("upfront_amount"),
                    "mid_annualized_return": mid_metrics.get("annualized_return"),
                    "nat_net_price": nat_metrics.get("net_price"),
                    "nat_upfront_amount": nat_metrics.get("upfront_amount"),
                    "nat_annualized_return": nat_metrics.get("annualized_return"),
                    "net_price": mid_metrics.get("net_price", nat_metrics.get("net_price")),
                    "investment": mid_metrics.get("upfront_amount") if trade.lower() == "buy" else None,
                    "borrowed": mid_metrics.get("upfront_amount") if trade.lower() == "sell" else None,
                    "repayment": face_value if trade.lower() == "buy" else None,
                    "repayment_sell": face_value if trade.lower() == "sell" else None,
                    "ann_rom": mid_metrics.get("annualized_return", nat_metrics.get("annualized_return")),
                    "direction": trade.capitalize(),
                    "days_to_expiry": days,
                }

                ranking_ann_return = spread_dict["ann_rom"]
                if ranking_ann_return is None:
                    continue
                if (trade.lower() == "buy" and ranking_ann_return > highest_cagr) or (
                    trade.lower() == "sell" and ranking_ann_return > highest_cagr
                ):
                    best_spread = spread_dict
                    highest_cagr = ranking_ann_return

    return best_spread
