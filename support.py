import re
import datetime
from dateutil.relativedelta import relativedelta
from tinydb import TinyDB
from configuration import debugEverythingNeedsRolling

import alert
from configuration import dbName

# how many days before expiration we close the contracts
ccExpDaysOffset = 0

defaultWaitTime = 3600


def extract_date(s):
    match = re.search(r'\d{2}/\d{2}/\d{4}', s)
    if match:
        date = datetime.datetime.strptime(match.group(), '%m/%d/%Y')
        return date.strftime('%Y-%m-%d')
    else:
        return None

def validDateFormat(date):
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")

        return True
    except ValueError:
        return False

def extract_strike_price(s):
    match = re.search(r'\$\d+', s)
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


def getDeltaDiffNowTomorrow1Am():
    now = datetime.datetime.now()

    tomorrow = datetime.datetime.combine(
        now.date(), datetime.time(1, 0)
    ) + datetime.timedelta(days=1)

    delta = tomorrow - now

    return delta


def getDeltaDiffNowNextRollDate1Am():
    db = TinyDB(dbName)
    soldCalls = db.all()
    db.close()

    if not soldCalls:
        return None

    soldCalls = sorted(soldCalls, key=lambda d: d["expiration"])

    now = datetime.datetime()

    if now.strftime("%Y-%m-%d") >= soldCalls[0]["expiration"]:
        # This call should've been rolled (this should never happen)
        return alert.botFailed(
            None, "Unrolled cc found in database, manual review required."
        )

    expDate = (
        datetime.datetime.strptime(soldCalls[0]["expiration"], "%Y-%m-%d")
        - datetime.timedelta(days=ccExpDaysOffset)
        + datetime.timedelta(hours=1)
    )

    delta = expDate - now

    if debugEverythingNeedsRolling:
        return datetime.timedelta(0)

    return delta
