import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Optional, List, Dict
from configuration import apiKey, apiRedirectUri, appSecret

import schwab
from schwab.client import AsyncClient
from schwab.streaming import StreamClient

logging.basicConfig(level=logging.DEBUG)

API_KEY = apiKey
CLIENT_SECRET = appSecret
CALLBACK_URL = apiRedirectUri


async def get_chains(client: AsyncClient, instruments: List[str]) -> Dict:
    chains = {}
    from_date = datetime.today().date()
    to_date = from_date + timedelta(days=3)

    for instrument in instruments:
        chain = client.get_option_chain(instrument, from_date=from_date, to_date=to_date)
        if chain.status_code == 200:
            chains[instrument] = chain.json()
        else:
            logging.error(f"Failed to get option chain for {instrument}: {chain.status_code}")

    return chains


def get_contracts_names(contracts: Dict) -> List[str]:
    names = []
    for instrument in contracts:
        names += [contract["symbol"] for contract in contracts[instrument]]
    return names


def get_contracts_from_chain(chain, days=1) -> List[str]:
    contracts = []
    for map_type in ["putExpDateMap", "callExpDateMap"]:
        counter = 0
        for idx, exp_date in enumerate(chain.get(map_type, {})):
            if counter == days:
                break

            days_to_expire = int(exp_date.split(":")[-1])
            if days_to_expire < 0:
                continue

            for strike in chain[map_type][exp_date]:
                contract = chain[map_type][exp_date][strike][0]
                contracts.append(contract)
            counter += 1

    sorted_array = sorted(contracts, key=lambda x: -x["openInterest"])
    return sorted_array


def get_contracts_from_chains(chains: Dict) -> Dict:
    contracts = {}
    for instrument in chains:
        contracts[instrument] = get_contracts_from_chain(chains[instrument], 2)
    return contracts


class OptionsDataStream:
    def __init__(self, instruments: List[str], api_key, client_secret, callback_url, token_path="./token.json"):
        self.api_key = api_key
        self.client_secret = client_secret
        self.callback_url = callback_url
        self.token_path = token_path

        self.account_id = None
        self.schwab_client = None
        self.stream_client = None
        self.instruments = instruments

        self.queue = asyncio.Queue()
        self.latest_quotes = {}

    async def initialize(self):
        self.schwab_client = schwab.auth.client_from_token_file(
            self.token_path, api_key=self.api_key, app_secret=self.client_secret
        )

        response = self.schwab_client.get_account_numbers()
        if response.status_code != 200:
            raise Exception(response.status_code)

        account_info = response.json()
        self.account_id = int(account_info[0]["accountNumber"])
        self.stream_client = StreamClient(self.schwab_client, account_id=self.account_id)
        self.stream_client.add_level_one_option_handler(self.handle_level_one_option)

    async def stream(self):
        await self.stream_client.login()

        chains = await get_chains(self.schwab_client, self.instruments)
        if len(chains) != len(self.instruments):
            raise Exception("Missing instruments")

        contracts = get_contracts_from_chains(chains)
        contracts_valid = {True if len(value) > 0 else False for key, value in contracts.items()}
        if contracts_valid != {True}:
            raise Exception("Contracts not valid")

        contracts = get_contracts_names(contracts)
        logging.debug(f"Subscribing to contracts: {contracts}")
        await self.stream_client.level_one_option_subs(contracts)

        asyncio.ensure_future(self.handle_queue())
        while True:
            try:
                await self.stream_client.handle_message()
            except:
                logging.exception("Error occurred")

    async def handle_level_one_option(self, msg):
        logging.debug(f"Received message: {msg}")
        if self.queue.full():
            await self.queue.get()
        await self.queue.put(msg)

    async def handle_queue(self):
        while True:
            msg = await self.queue.get()
            self.update_quotes(msg)

    def update_quotes(self, msg: Dict):
        symbol = msg.get("key")
        if symbol:
            logging.debug(f"Updating quote for {symbol}: {msg}")
            self.latest_quotes[symbol] = msg

    def get_latest_quotes(self) -> Dict:
        return self.latest_quotes


async def test_data_stream():
    data_stream = OptionsDataStream(
        instruments=["$SPX"],
        api_key=API_KEY,
        client_secret=CLIENT_SECRET,
        callback_url=CALLBACK_URL,
    )

    await data_stream.initialize()
    asyncio.create_task(data_stream.stream())

    while True:
        quotes = data_stream.get_latest_quotes()
        with open('quotes_output.txt', 'w') as file:
            # Write the quotes to the file
            file.write(str(quotes))
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(test_data_stream())
