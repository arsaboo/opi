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

margin_rules = {
    "long_options": {
        "min_equity": lambda market_value: min(2000, market_value),
        "initial_req": lambda cost: cost,  # 100% of cost
        "maintenance_req": lambda cost: cost  # Same as initial
    },
    "naked_calls": {
        "broad_based_index": {
            "min_equity": 5000,
            "initial_req": lambda underlying_value, otm_amount, premium: max(
                0.15 * underlying_value - otm_amount + premium * 100,  # 15% - OTM + premium
                0.10 * underlying_value + premium * 100,  # 10% + premium
                100  # Minimum per contract
            )
        },
        "narrow_based_index": {
            "min_equity": 5000,
            "initial_req": lambda underlying_value, otm_amount, premium: max(
                0.20 * underlying_value - otm_amount + premium * 100,
                0.10 * underlying_value + premium * 100,
                100
            )
        },
        "equity": {  # For stocks and ETFs
            "min_equity": 5000,
            "initial_req": lambda underlying_value, otm_amount, premium: max(
                0.20 * underlying_value - otm_amount + premium * 100,
                0.10 * underlying_value + premium * 100,
                100
            )
        },
        "leveraged_etf": {
            "2x": {
                "initial_req": lambda underlying_value, otm_amount, premium: max(
                    0.30 * underlying_value - otm_amount + premium,
                    0.20 * underlying_value + premium
                )
            },
            "3x": {
                "initial_req": lambda underlying_value, otm_amount, premium: max(
                    0.45 * underlying_value - otm_amount + premium,
                    0.30 * underlying_value + premium
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
        },
        "equity": {  # For stocks and ETFs
            "min_equity": lambda max_loss: min(5000, max_loss),
            "initial_req": lambda underlying_value, otm_amount, premium, max_loss: max(
                0.20 * underlying_value - otm_amount + premium * 100,
                0.10 * underlying_value + premium * 100,
                100,
                max_loss
            )
        },
        "etf_index": {  # Add new category for SPY
            "min_equity": lambda max_loss: min(2500, max_loss),
            "initial_req": lambda underlying_value, otm_amount, premium, max_loss: max(
                0.10 * underlying_value,  # 10% of underlying value
                2500,  # Minimum requirement
                max_loss
            )
        }
    },
    "spreads": {
        "credit": lambda strike_diff, contracts: strike_diff * 100 * contracts,
        "debit": lambda cost: cost  # 100% of cost
    },
    "complex_spreads": {
        "min_equity": {
            "box": 0,
            "butterfly": 0,
            "condor": 0,
            "iron_butterfly": 5000,
            "iron_condor": 5000
        },
        "initial_req": lambda naked_reqs, max_loss: min(sum(naked_reqs), max_loss)
    }
}

spreads = {
    "$SPX": {
        "spread": 100, # spread between the strikes
        "days": 2000, #no of days to look out for the highest yield
        "minDays": 120, # minimum days to start looking from (default 0 for today)
        "downsideProtection": 0.45, # downside protection is the % difference between the breakeven price adn current underlying price. We won't look for spreads with downside protection below this value.
        'price': 'mid', # can be mid/market for the median price. Mid is recommended
        'type': 'broad_based_index'  # Used for margin calculations
    },
    "VOO": {
        "spread": 100,
        "days": 2000,
        "minDays": 90,
        "downsideProtection": 0.15,
        'price': 'mid',
        'type': 'equity'  # Changed from etf_index to equity
    },
    "SPY": {
        "spread": 100,
        "days": 2000,
        "minDays": 90,
        "downsideProtection": 0.20,
        'price': 'mid',
        'type': 'equity'  # Changed from etf_index to equity
    },
    "QQQ": {
        "spread": 100,
        "days": 2000,
        "minDays": 90,
        "downsideProtection": 0.20,
        'price': 'mid',
        'type': 'equity'  # Changed from etf_index to equity
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
