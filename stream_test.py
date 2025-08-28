"""
Simple streaming quotes smoke test for Schwab.

Usage examples:
  - Equities only (SPY, AAPL), print 10 messages or stop after 30s:
      python stream_test.py --equity SPY AAPL --count 10 --timeout 30

  - Options only (exact option symbols):
      python stream_test.py --option "SPXW  251003C06450000" --count 10

  - Mixed:
      python stream_test.py --equity SPY --option "SPXW  251003C06450000" --count 20

Notes:
  - Uses existing token.json. If auth fails, run the main app to re‑authenticate.
  - Prints BID/ASK/LAST when available.
"""

import argparse
import asyncio
import sys
from typing import List

import schwab
from schwab.streaming import StreamClient

from configuration import apiKey, appSecret


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Schwab streaming quotes smoke test")
    p.add_argument("--equity", nargs="*", default=[], help="Equity symbols (e.g., SPY AAPL)")
    p.add_argument("--option", nargs="*", default=[], help="Option symbols (exact) to stream")
    p.add_argument("--count", type=int, default=10, help="Number of messages to print before exiting")
    p.add_argument("--timeout", type=int, default=60, help="Max seconds to run before exiting")
    return p.parse_args()


async def main(equities: List[str], options: List[str], count: int, timeout: int) -> int:
    try:
        client = schwab.auth.client_from_token_file(
            "token.json", api_key=apiKey, app_secret=appSecret
        )
    except Exception as e:
        print(f"Auth error loading token.json: {e}\nRun the main app to re-authenticate.")
        return 2

    try:
        acc = int(client.get_account_numbers().json()[0]["accountNumber"])
    except Exception as e:
        print(f"Error fetching account number: {e}")
        return 2

    stream = StreamClient(client, account_id=acc)

    received = {"n": 0}

    async def on_equity(msg):
        for c in (msg.get("content") or []):
            sym = c.get("key")
            bid = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID")
            ask = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK")
            last = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST")
            print(f"EQ  {sym:>16}  BID {bid}  ASK {ask}  LAST {last}")
            received["n"] += 1

    async def on_option(msg):
        for c in (msg.get("content") or []):
            sym = c.get("key")
            bid = c.get("BID_PRICE") or c.get("bidPrice") or c.get("BID")
            ask = c.get("ASK_PRICE") or c.get("askPrice") or c.get("ASK")
            last = c.get("LAST_PRICE") or c.get("lastPrice") or c.get("LAST")
            print(f"OPT {sym:>16}  BID {bid}  ASK {ask}  LAST {last}")
            received["n"] += 1

    stream.add_level_one_equity_handler(on_equity)
    stream.add_level_one_option_handler(on_option)

    await stream.login()

    # Subscriptions
    if equities:
        await stream.level_one_equity_subs(equities)
    if options:
        await stream.level_one_option_subs(options)

    # Pump until count or timeout
    async def pump():
        while received["n"] < count:
            await stream.handle_message()

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"Timed out after {timeout}s with {received['n']} messages.")
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    ns = parse_args()
    rc = asyncio.run(main(ns.equity, ns.option, ns.count, ns.timeout))
    sys.exit(rc)

