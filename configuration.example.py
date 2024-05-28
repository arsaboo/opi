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
    'QQQ': {
        # how many cc's to write
        'amountOfHundreds': 1,

        # write cc's at or over current asset price + this value
        'minGapToATM': 1,

        # If our strike is below current asset price - this value, we consider it deep ITM and want to rollup for debit
        'deepITMLimit': 10,

        # How much do we want to rollup the strike from last month if we are Deep ITM?
        # (If this is set to 0 the bot will roll to the highest contract with credit, ignoring deepITMLimit)
        'maxRollupGap': 0,

        # How much are we allowed to reduce the strike from last month? (flash crash protection)
        # If the underlying f.ex. drops by 30 in value, this is the max we are gonna drop our cc strike
        'maxDrawdownGap': 10,

        # don't write cc's with strikes below this value (set this f.ex. to breakeven)
        'minStrike': 0
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
