from datetime import datetime
import statistics
from typing import Optional, Dict

import re
import calendar
import datetime as _dt


def threshold_points(limit_value: float, underlying_price: float) -> float:
    """
    Interpret a threshold as percent of underlying if < 1, else as points.
    """
    try:
        if limit_value is None:
            return 0.0
        val = float(limit_value)
        return underlying_price * val if val < 1 else val
    except Exception:
        return 0.0


def classify_status(short_strike: float, underlying_price: float, *, itm_limit, deep_itm_limit, deep_otm_limit) -> str:
    """
    Classify covered-call moneyness using percent-aware thresholds.
    Returns one of: deep_OTM, OTM, just_ITM, ITM, deep_ITM
    """
    deep_otm_pts = threshold_points(deep_otm_limit, underlying_price)
    itm_pts = threshold_points(itm_limit, underlying_price)
    deep_itm_pts = threshold_points(deep_itm_limit, underlying_price)

    if short_strike > underlying_price + deep_otm_pts:
        return "deep_OTM"
    if short_strike > underlying_price:
        return "OTM"
    if short_strike + itm_pts > underlying_price:
        return "just_ITM"
    if short_strike + deep_itm_pts > underlying_price:
        return "ITM"
    return "deep_ITM"


def get_median_price(symbol: str, data) -> Optional[float]:
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                bid = contract["bid"]
                ask = contract["ask"]
                return (bid + ask) / 2
    return None


def get_option_delta(symbol: str, data) -> Optional[float]:
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                return contract.get("delta")
    return None


def parse_option_details(api, data, option_symbol):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == option_symbol:
                short_strike = float(contract["strike"])
                short_price = round(statistics.median([contract["bid"], contract["ask"]]), 2)
                short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                if contract["underlying"] == "SPX":
                    ticker = "$SPX"
                else:
                    ticker = contract["underlying"]
                underlying_price = api.getATMPrice(ticker)
                return short_strike, short_price, short_expiry, underlying_price
    return None, None, None, None


def is_same_underlying(option_root: str, short_option_symbol: str) -> bool:
    """
    Check if an option contract root belongs to the same underlying as the short.
    Special-cases SPX vs SPXW.
    """
    short_root = short_option_symbol.split()[0]
    if short_root == "SPX":
        return option_root in ("SPX", "SPXW")
    return option_root == short_root


def round_to_nearest_five_cents(n: float) -> float:
    import math
    return math.ceil(n * 20) / 20


# ---------- Moved from support.py ----------

DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")
STRIKE_PRICE_PATTERN = re.compile(r"\$\d+")


def extract_date(s: str) -> str:
    match = DATE_PATTERN.search(s)
    if match:
        date_str = match.group()
        date_obj = _dt.datetime.strptime(date_str, "%m/%d/%Y")
        return date_obj.strftime("%Y-%m-%d")
    return None


def validDateFormat(date: str) -> bool:
    try:
        _dt.datetime.strptime(date, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def extract_strike_price(s: str) -> str:
    match = STRIKE_PRICE_PATTERN.search(s)
    return match.group()[1:] if match else None


def getThirdFridayOfMonth(date: _dt.date) -> _dt.date:
    _, num_days = calendar.monthrange(date.year, date.month)
    return date.replace(day=min(15 + (4 - date.weekday()) % 7, num_days))


def getNewCcExpirationDate() -> _dt.date:
    """Get the third Friday of the current month or next month."""
    now = _dt.datetime.now().astimezone(_dt.timezone.utc)
    third_friday = getThirdFridayOfMonth(now)
    if now.day > third_friday.day - 7:
        next_month = now + _dt.timedelta(days=30)
        third_friday = getThirdFridayOfMonth(next_month)
    return third_friday


def calculate_cagr(total_investment: float, returns: float, days: int) -> tuple:
    try:
        if total_investment <= 0 or returns <= 0 or days <= 0:
            return 0, 0
        ratio = min(returns / total_investment, 1e6)
        cagr = (ratio ** (365 / max(days, 1))) - 1
        if isinstance(cagr, complex) or cagr > 1e6:
            return 0, 0
        cagr_percentage = round(cagr * 100, 2)
        if cagr_percentage > 1000:
            return 10, 1000
        return cagr, cagr_percentage
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0, 0
