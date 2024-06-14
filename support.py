import datetime
import re

from dateutil.relativedelta import relativedelta

import alert

# how many days before expiration we close the contracts
ccExpDaysOffset = 0

defaultWaitTime = 1799


def extract_date(s):
    match = re.search(r"\d{2}/\d{2}/\d{4}", s)
    if match:
        date = datetime.datetime.strptime(match.group(), "%m/%d/%Y")
        return date.strftime("%Y-%m-%d")
    else:
        return None


def validDateFormat(date):
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")

        return True
    except ValueError:
        return False



def extract_strike_price(s):
    match = re.search(r"\$\d+", s)
    return match.group()[1:] if match else None


def getNewCcExpirationDate():
    now = datetime.datetime.now()
    now = now.replace(tzinfo=datetime.timezone.utc)

    third = getThirdFridayOfMonth(now)

    # if we are within 7 days or past, get the same day next month
    if now.day > third.day - 7:
        nextMonth = now + relativedelta(months=1)

        third = getThirdFridayOfMonth(nextMonth)

    return third


def getThirdFridayOfMonth(monthDate):
    # the third friday will be the 15 - 21 day, check lowest
    third = datetime.date(monthDate.year, monthDate.month, 15)

    w = third.weekday()
    if w != 4:
        # replace the day
        third = third.replace(day=(15 + (4 - w) % 7))

    return third


def calculate_cagr(total_investment, returns, days):
    """
    Calculate Compound Annual Growth Rate (CAGR) based on total investment, returns, and number of days.

    Args:
        total_investment (float): Total investment amount.
        returns (float): Total returns (this is the total inflow not just the profit).
        days (int): Number of days.

    Returns:
        tuple: A tuple containing the CAGR and CAGR percentage.

    Raises:
        ValueError: If CAGR calculation results in a complex number.

    """
    try:
        cagr = ((returns / total_investment) ** (365 / days)) - 1
        if isinstance(cagr, complex):
            raise ValueError("CAGR calculation resulted in a complex number")
        cagr_percentage = round(cagr * 100, 2)  # Convert CAGR to percentage
    except OverflowError:
        cagr = 0
        cagr_percentage = round(cagr, 2)
    except ValueError as e:
        print(e)
        cagr = None
        cagr_percentage = None
    return cagr, cagr_percentage
