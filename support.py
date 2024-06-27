import datetime
import re
from dateutil.relativedelta import relativedelta
import calendar

ccExpDaysOffset = 0
defaultWaitTime = 1799

DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")
STRIKE_PRICE_PATTERN = re.compile(r"\$\d+")


def extract_date(s: str) -> str:
    """Extract date from string in MM/DD/YYYY format."""
    match = DATE_PATTERN.search(s)
    if match:
        date_str = match.group()
        date_obj = datetime.datetime.strptime(date_str, "%m/%d/%Y")
        return date_obj.strftime("%Y-%m-%d")
    else:
        return None


def validDateFormat(date: str) -> bool:
    """Validate date format as YYYY-MM-DD."""
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def extract_strike_price(s: str) -> str:
    """Extract strike price from string in $XXX format."""
    match = STRIKE_PRICE_PATTERN.search(s)
    return match.group()[1:] if match else None


def getNewCcExpirationDate() -> datetime.date:
    """Get the third Friday of the current month or next month."""
    now = datetime.datetime.now().astimezone(datetime.timezone.utc)
    third_friday = getThirdFridayOfMonth(now)

    if now.day > third_friday.day - 7:
        next_month = now + relativedelta(months=1)
        third_friday = getThirdFridayOfMonth(next_month)

    return third_friday


def getThirdFridayOfMonth(date: datetime.date) -> datetime.date:
    """Get the third Friday of a given month."""
    _, num_days = calendar.monthrange(date.year, date.month)
    third_friday = date.replace(day=min(15 + (4 - date.weekday()) % 7, num_days))
    return third_friday


def calculate_cagr(total_investment: float, returns: float, days: int) -> tuple:
    """
    Calculate Compound Annual Growth Rate (CAGR) based on total investment, returns, and number of days.

    Args:
        total_investment (float): Total investment amount.
        returns (float): Total returns (this is the total inflow not just the profit).
        days (int): Number of days.

    Returns:
        tuple: A tuple containing the CAGR and CAGR percentage.
    """
    try:
        cagr = ((returns / total_investment) ** (365 / days)) - 1
        if isinstance(cagr, complex):
            raise ValueError("CAGR calculation resulted in a complex number")
        cagr_percentage = round(cagr * 100, 2)  # Convert CAGR to percentage
    except OverflowError:
        cagr = 0
        cagr_percentage = round(cagr, 2)
    return cagr, cagr_percentage
