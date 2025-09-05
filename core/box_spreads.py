import json
from core.spreads_common import mid_price, days_to_expiry, face_value as face_val, valid_ba


def calculate_box_spread(spread, calls_json, puts_json):
    """
    Calculate the best SELL box spread (borrow now, repay at expiry).

    Simplified to only evaluate sell-direction box spreads. Returns the
    best result (highest annualized return value; for borrowing cost this
    will typically be the least negative value).
    """
    calls_chain = json.loads(calls_json)
    puts_chain = json.loads(puts_json)
    highest_cagr = float("-inf")
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

                # Mid price (sell-only)
                if valid_ba(
                    low_call_bid,
                    low_call_ask,
                    high_call_bid,
                    high_call_ask,
                    low_put_bid,
                    low_put_ask,
                    high_put_bid,
                    high_put_ask,
                ):
                    low_call_mid = mid_price(low_call_bid, low_call_ask)
                    low_put_mid = mid_price(low_put_bid, low_put_ask)
                    high_call_mid = mid_price(high_call_bid, high_call_ask)
                    high_put_mid = mid_price(high_put_bid, high_put_ask)
                    mid_trade_price = low_call_mid + high_put_mid - high_call_mid - low_put_mid
                else:
                    mid_trade_price = None

                # Natural/executable (sell-only)
                low_call_nat = low_call_bid
                low_put_nat = low_put_ask
                high_call_nat = high_call_ask
                high_put_nat = high_put_bid

                if None not in [low_call_nat, high_put_nat, high_call_nat, low_put_nat]:
                    nat_trade_price = low_call_nat + high_put_nat - high_call_nat - low_put_nat
                else:
                    nat_trade_price = None

                low_strike = call_contracts[i]["strike"]
                high_strike = call_contracts[j]["strike"]
                days = days_to_expiry(entry[0]["date"])
                face_value = face_val(low_strike, high_strike)

                mid_metrics = {"net_price": None, "upfront_amount": None, "annualized_return": None}
                if mid_trade_price is not None:
                    # For sell box, we borrow upfront; that's the credit received now
                    upfront_amount = mid_trade_price * 100
                    effective_days = max(days, 1)
                    # Only valid if 0 < upfront < face
                    if upfront_amount > 0 and upfront_amount < face_value:
                        # Positive borrowing cost rate: (repayment - borrowed) / borrowed annualized
                        # i.e., (face - upfront) / upfront
                        annualized_cost = ((face_value - upfront_amount) / upfront_amount) * (
                            365 / effective_days
                        )
                    else:
                        annualized_cost = None
                    mid_metrics = {
                        "net_price": round(mid_trade_price, 2) if annualized_cost is not None else None,
                        "upfront_amount": round(upfront_amount, 2) if annualized_cost is not None else None,
                        "annualized_return": round(annualized_cost * 100, 2) if annualized_cost is not None else None,
                    }

                nat_metrics = {"net_price": None, "upfront_amount": None, "annualized_return": None}
                if nat_trade_price is not None:
                    upfront_amount = nat_trade_price * 100
                    effective_days = max(days, 1)
                    # Only valid if 0 < upfront < face
                    if upfront_amount > 0 and upfront_amount < face_value:
                        annualized_cost = ((face_value - upfront_amount) / upfront_amount) * (
                            365 / effective_days
                        )
                    else:
                        annualized_cost = None
                    nat_metrics = {
                        "net_price": round(nat_trade_price, 2) if annualized_cost is not None else None,
                        "upfront_amount": round(upfront_amount, 2) if annualized_cost is not None else None,
                        "annualized_return": round(annualized_cost * 100, 2) if annualized_cost is not None else None,
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
                    "investment": None,
                    "borrowed": mid_metrics.get("upfront_amount"),
                    "repayment": None,
                    "repayment_sell": face_value,
                    "ann_rom": mid_metrics.get("annualized_return", nat_metrics.get("annualized_return")),
                    "direction": "Sell",
                    "days_to_expiry": days,
                }

                ranking_ann_return = spread_dict["ann_rom"]
                if ranking_ann_return is None:
                    continue
                # Now ranking_ann_return is a POSITIVE cost percentage. Choose the lowest.
                if highest_cagr == float("-inf") or ranking_ann_return < highest_cagr:
                    best_spread = spread_dict
                    highest_cagr = ranking_ann_return

    return best_spread
