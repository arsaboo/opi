import asyncio

async def get_expiring_shorts_data(api):
    """
    Fetches all short positions expiring within 30 days and finds the best rollover for each.
    """
    # Placeholder data
    await asyncio.sleep(2) # Simulate network latency
    return [
        {"Ticker": "SPY", "Expiring Option": "SPY_12345C678", "DTE": 10, "Roll To": "SPY_23456C789", "Config Status": "Configured"},
        {"Ticker": "QQQ", "Expiring Option": "QQQ_12345C678", "DTE": 5, "Roll To": "N/A", "Config Status": "Configured"},
        {"Ticker": "IWM", "Expiring Option": "IWM_12345C678", "DTE": 20, "Roll To": "N/A", "Config Status": "Not Configured"},
    ]
