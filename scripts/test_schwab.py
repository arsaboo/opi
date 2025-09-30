#!/usr/bin/env python3
"""
Test script to explore account information available from the Schwab API.

Added: streaming index ticker probe. Usage examples:

  python scripts/test_schwab.py stream-indices --seconds 15

This will connect the streaming API and subscribe to several SPX/NDX
candidate symbols via level-one equities, then report which symbols
produced ticks.
"""

import json
import sys
import os
from dotenv import load_dotenv  # Add this import

# Load environment variables from .env file
load_dotenv()

# Add the parent directory of the project to the path so we can import the api module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from api import Api

async def probe_index_streams(api, seconds=15):
    """Subscribe to candidate index symbols and report which stream.

    Uses level_one_equity subscriptions. Prints received LAST_PRICE per symbol.
    """
    from schwab.streaming import StreamClient

    # Gather account id
    r = api.connectClient.get_account_numbers()
    r.raise_for_status()
    acct = int(r.json()[0]["accountNumber"])

    stream = StreamClient(api.connectClient, account_id=acct)
    seen = {}

    def _handle(msg):
        for c in msg.get("content") or []:
            key = c.get("key") or c.get("symbol")
            lp = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST") or c.get("last")
            if key is not None and lp is not None:
                try:
                    seen.setdefault(key, []).append(float(lp))
                except Exception:
                    pass

    stream.add_level_one_equity_handler(_handle)

    # Candidate symbols to try
    spx_candidates = ["$SPX", "$SPX.X", "SPX"]
    ndx_candidates = ["$NDX", "$NDX.X", "NDX"]
    symbols = list({*spx_candidates, *ndx_candidates})

    await stream.login()
    await stream.level_one_equity_subs(symbols)

    print(f"Subscribed to: {symbols}")
    print(f"Collecting for {seconds}s...")
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        await stream.handle_message()

    print("\nResults (symbols with received LAST):")
    if not seen:
        print("  No ticks received. Try running during market hours or extend --seconds.")
    else:
        for sym, vals in seen.items():
            try:
                sample = ", ".join(f"{v:.2f}" for v in vals[:3])
            except Exception:
                sample = str(vals[:3])
            print(f"  {sym}: {len(vals)} ticks; samples: {sample}")

    try:
        await stream.logout()
    except Exception:
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Schwab API test utility")
    parser.add_argument("mode", nargs="?", default="rest", choices=["rest", "stream-indices"], help="Test mode")
    parser.add_argument("--seconds", dest="seconds", type=int, default=15, help="Seconds to capture streaming data")
    args = parser.parse_args()

    print("Initializing API...")
    api = Api(
        os.getenv("SCHWAB_API_KEY"),
        os.getenv("SCHWAB_REDIRECT_URI"),
        os.getenv("SCHWAB_APP_SECRET")  # Updated initialization
    )

    try:
        # Setup the API connection
        api.setup()
        print("API initialized successfully!")

        if args.mode == "stream-indices":
            asyncio.run(probe_index_streams(api, seconds=args.seconds))
            return

        # Get account numbers
        print("\n1. Getting account numbers...")
        account_numbers_response = api.connectClient.get_account_numbers()
        account_numbers = account_numbers_response.json()
        print(f"Account numbers: {json.dumps(account_numbers, indent=2)}")

        if not account_numbers:
            print("No accounts found!")
            return

        # Get the first account hash
        account_hash = account_numbers[0]['hashValue']
        print(f"\nUsing account hash: {account_hash}")

        # Test different account field combinations
        print("\n2. Getting account data with POSITIONS only...")
        try:
            positions_response = api.connectClient.get_account(
                account_hash,
                fields=api.connectClient.Account.Fields.POSITIONS
            )
            positions_data = positions_response.json()
            print("Positions data structure:")
            print_structure(positions_data, max_depth=3)
        except Exception as e:
            print(f"Error getting positions: {e}")

        print("\n3. Getting account data with BALANCES only...")
        try:
            balances_response = api.connectClient.get_account(
                account_hash,
                fields=api.connectClient.Account.Fields.BALANCES
            )
            balances_data = balances_response.json()
            print("Balances data structure:")
            print_structure(balances_data, max_depth=3)

            # Look for buying power and related fields
            find_buying_power_fields(balances_data)
        except Exception as e:
            print(f"Error getting balances: {e}")

        print("\n4. Getting account data with both POSITIONS and BALANCES...")
        try:
            combined_response = api.connectClient.get_account(
                account_hash,
                fields=[
                    api.connectClient.Account.Fields.POSITIONS,
                    api.connectClient.Account.Fields.BALANCES
                ]
            )
            combined_data = combined_response.json()
            print("Combined data structure:")
            print_structure(combined_data, max_depth=3)

            # Look for buying power and related fields
            find_buying_power_fields(combined_data)
        except Exception as e:
            print(f"Error getting combined data: {e}")

        print("\n5. Getting account data with ORDERS...")
        try:
            orders_response = api.connectClient.get_account(
                account_hash,
                fields=api.connectClient.Account.Fields.ORDERS
            )
            orders_data = orders_response.json()
            print("Orders data structure:")
            print_structure(orders_data, max_depth=2)
        except Exception as e:
            print(f"Error getting orders: {e}")

        print("\n6. Getting account data with all fields...")
        try:
            all_response = api.connectClient.get_account(account_hash)
            all_data = all_response.json()
            print("All data structure:")
            print_structure(all_data, max_depth=3)

            # Look for buying power and related fields
            find_buying_power_fields(all_data)
        except Exception as e:
            print(f"Error getting all data: {e}")

    except Exception as e:
        print(f"Error during API setup or calls: {e}")
        print("Make sure you have a valid token.json file and internet connection.")

def print_structure(data, max_depth=2, current_depth=0, prefix=""):
    """Recursively print the structure of the data with values"""
    if current_depth > max_depth:
        return

    indent = "  " * current_depth

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)) and current_depth < max_depth:
                print(f"{prefix}{indent}{key}: {type(value).__name__}")
                if isinstance(value, dict):
                    print_structure(value, max_depth, current_depth + 1, prefix)
                elif isinstance(value, list) and value:
                    print(f"{prefix}{indent}  [0]: {value[0]}")
                    if isinstance(value[0], dict):
                        print_structure(value[0], max_depth, current_depth + 2, prefix)
            else:
                print(f"{prefix}{indent}{key}: {value}")
    elif isinstance(data, list) and data:
        print(f"{prefix}{indent}[list of {len(data)} items]")
        if current_depth < max_depth and data:
            print(f"{prefix}{indent}[0]: {data[0]}")
            if isinstance(data[0], dict):
                print_structure(data[0], max_depth, current_depth + 1, prefix)

def find_buying_power_fields(data, path=""):
    """Look for buying power and related fields in the data"""
    print("\nSearching for buying power related fields...")

    def search_recursive(obj, current_path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{current_path}.{key}" if current_path else key
                if any(bp_term in key.lower() for bp_term in ['buyingpower', 'buying_power', 'availablefunds', 'cashavailable', 'margin']):
                    print(f"Found potential buying power field: {new_path} = {value}")
                elif isinstance(value, (dict, list)):
                    search_recursive(value, new_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                new_path = f"{current_path}[{i}]"
                if isinstance(item, (dict, list)):
                    search_recursive(item, new_path)

    search_recursive(data)

if __name__ == "__main__":
    main()
