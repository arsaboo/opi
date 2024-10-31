apiKey = ''  # create an app on https://developer.schwab.com/ to get one
apiRedirectUri = 'https://localhost'
SchwabAccountID = ''
appSecret = ''

dbName = 'db.json'

# console, email ### where to alert regarding errors or order fills
botAlert = 'console'
loggingLevel = 'ERROR'
AutoTrade = False

configuration = {
    '$SPX': {
        # minumum rollup gap for rolling up the strike. We will try to roll up by this amount if possible, but if not, we will reduce the gap until we are able to fetch minPremium
        "minRollupGap": 50,
        # don't write cc's with strikes below this value (set this f.ex. to breakeven)
        "minStrike": 5000,
        # Max DTE for rolling the calls.
        "maxRollOutWindow": 30,
        # Min DTE for rolling the calls.
        "minRollOutWindow": 7,
        # Ideal premium desired for writing the cc's
        "idealPremium": 10,
        # minimum premium desired for writing the cc's
        "minPremium": 5,
        # If our short strike is below current asset price - this value, we consider it ITM and want to rollup for minPremium
        "ITMLimit": 75,
        # If our strike is below current asset price - this value, we consider it deep ITM and want to rollup without credit
        "deepITMLimit": 150,
        # If our strike is above current asset price + this value, we consider it deep OTM and don't want to rollup. Instead, we wait for the short option to expire worthless
        "deepOTMLimit": 10,
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
debugMarketOpen = False
# Can actually place orders. If set to False, the program will only print the orders that would be placed.
debugCanSendOrders = True
