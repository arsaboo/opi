import statistics
from datetime import datetime


def days_to_expiry(expiry_date_str: str) -> int:
    return (datetime.strptime(expiry_date_str, "%Y-%m-%d").date() - datetime.today().date()).days


def face_value(low_strike: float, high_strike: float) -> float:
    return (high_strike - low_strike) * 100


def mid_price(bid: float, ask: float):
    if bid is None or ask is None:
        return None
    return statistics.median([bid, ask])


def crossed_quote(bid: float, ask: float) -> bool:
    try:
        return bid is not None and ask is not None and bid > ask
    except Exception:
        return False


def valid_ba(*vals) -> bool:
    return all(v is not None for v in vals)

