# Schwab API settings
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
loggingLevel = 'ERROR'  # DEBUG, INFO, WARNING, ERROR, CRITICAL
AutoTrade = False

spreads = {
    "$SPX": {
        "spread": 200,  # spread between the strikes
        "days": 2500,  # no of days to look out for the highest yield
        "minDays": 120,  # minimum days to start looking from
        "downsideProtection": 0.30,  # downside protection %
        'price': 'mid',  # can be mid/market for the median price
        'type': 'broad_based_index'  # Used for margin calculations
    },
    "SPY": {
        "spread": 100,
        "days": 2000,
        "minDays": 90,
        "downsideProtection": 0.25,
        'price': 'mid',
        'type': 'etf'  # Standard ETF margin rules
    },
    "QQQ": {
        "spread": 100,
        "days": 2000,
        "minDays": 90,
        "downsideProtection": 0.30,
        'price': 'mid',
        'type': 'etf'
    },
    "TQQQ": {  # Example of leveraged ETF
        "spread": 50,
        "days": 1000,
        "minDays": 60,
        "downsideProtection": 0.35,
        'price': 'mid',
        'type': 'leveraged_etf'
    }
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
debugMarketOpen = True
debugCanSendOrders = True

# Margin calculation rules
margin_rules = {
    "spreads": {
        "credit": lambda strike_diff, contracts: strike_diff * 100 * contracts,
        "debit": lambda cost: cost  # 100% of cost
    },
    "naked_calls": {
        "broad_based_index": {
            "min_equity": 5000,
            "initial_req": lambda underlying_value, otm_amount, premium: max(
                0.15 * underlying_value - otm_amount + premium * 100,  # 15% method
                0.10 * underlying_value + premium * 100,  # 10% method
                100  # Minimum per contract
            )
        },
        "leveraged_etf": {
            "2x": {
                "initial_req": lambda underlying_value, otm_amount, premium: max(
                    0.30 * underlying_value - otm_amount + premium * 100,
                    0.20 * underlying_value + premium * 100
                )
            },
            "3x": {
                "initial_req": lambda underlying_value, otm_amount, premium: max(
                    0.45 * underlying_value - otm_amount + premium * 100,
                    0.30 * underlying_value + premium * 100
                )
            }
        }
    },
    "naked_puts": {
        "broad_based_index": {
            "min_equity": lambda max_loss: min(5000, max_loss),
            "initial_req": lambda underlying_value, otm_amount, premium, max_loss: max(
                0.15 * underlying_value - otm_amount + premium * 100,
                0.10 * underlying_value + premium * 100,
                100,  # Minimum per contract
                max_loss
            )
        }
    }
}
