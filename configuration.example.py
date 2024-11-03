# Schwab API settings (optional if using Google Sheets)
apiKey = ''  # create an app on https://developer.schwab.com/ to get one
apiRedirectUri = 'https://localhost'
SchwabAccountID = ''
appSecret = ''

# Google Sheets settings
SPREADSHEET_ID = ''  # ID from your Google Sheets URL
USE_SHEETS = True    # Set to True to use Google Sheets instead of Schwab API

# General settings
dbName = 'db.json'
botAlert = 'console'  # console, email
loggingLevel = 'ERROR'
AutoTrade = False
spreads = {
    "$SPX": {
        "spread": 200,  # spread between the strikes
        "days": 2500,  # no of days to look out for the highest yield
        "downsideProtection": 0.30,  # downside protection is the % difference between the breakeven price and current underlying price
        'price': 'mid'  # can be mid/market for the median price. Mid is recommended
    },
    "SPY": {
        "spread": 100,
        "days": 2000,
        "downsideProtection": 0.25,
        'price': 'mid'
    },
    "QQQ": {
        "spread": 100,
        "days": 2000,
        "downsideProtection": 0.30,
        'price': 'mid'
    },
}
configuration = {
    '$SPX': {
        # minimum rollup gap for rolling up the strike
        "minRollupGap": 50,
        # don't write cc's with strikes below this value (set this f.ex. to breakeven)
        "minStrike": 5000,
        # Max DTE for rolling the calls
        "maxRollOutWindow": 30,
        # Min DTE for rolling the calls
        "minRollOutWindow": 7,
        # Ideal premium desired for writing the cc's
        "idealPremium": 10,
        # minimum premium desired for writing the cc's
        "minPremium": 5,
        "desiredDelta": 0.25,
        # If our short strike is below current asset price - this value, we consider it ITM and want to rollup for minPremium
        "ITMLimit": 75,
        # If our strike is below current asset price - this value, we consider it deep ITM and want to rollup without credit
        "deepITMLimit": 150,
        # If our strike is above current asset price + this value, we consider it deep OTM and don't want to rollup
        "deepOTMLimit": 10,
    },
    'QQQ': {
        "minRollupGap": 25,
        "minStrike": 350,
        "maxRollOutWindow": 120,
        "minRollOutWindow": 30,
        "idealPremium": 5,
        "minPremium": 2.5,
        "ITMLimit": 25,
        "deepITMLimit": 50,
        "deepOTMLimit": 5,
    }
}

# Required for 'botAlert' email
mailConfig = {
    'smtp': None,
    'port': 587,
    'from': None,
    'to': None,
    'username': None,
    'password': None,
}

# DEBUG MODES

# To run the program in debug mode. If set to True, the program will run even if the market is closed.
debugMarketOpen = True
# Can actually place orders. If set to False, the program will only print the orders that would be placed.
debugCanSendOrders = True
