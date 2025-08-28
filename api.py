import datetime
import json
import math
import os
import time
from datetime import datetime, timedelta, time as time_module
from operator import itemgetter
from statistics import median

import pytz
import requests
import schwab
from schwab import auth
from schwab.orders.options import OptionSymbol
from schwab.utils import Utils
from tzlocal import get_localzone

import alert
from cc import round_to_nearest_five_cents
from configuration import SchwabAccountID, debugCanSendOrders
from logger_config import get_logger
from strategies import monitor_order  # Import monitor_order from strategies
from support import extract_date, extract_strike_price, validDateFormat

logger = get_logger()


class Api:
    connectClient = None
    tokenPath = ""
    apiKey = ""
    apiRedirectUri = ""

    def __init__(self, apiKey, apiRedirectUri, appSecret):
        self.tokenPath = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "token.json"
        )
        self.apiKey = apiKey
        self.apiRedirectUri = apiRedirectUri
        self.appSecret = appSecret
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.tokenPath), exist_ok=True)

    def setup(self, retries=3, delay=5):
        attempt = 0
        while attempt < retries:
            try:
                self.connectClient = auth.client_from_token_file(
                    api_key=self.apiKey,
                    app_secret=self.appSecret,
                    token_path=self.tokenPath,
                )
                response = self.connectClient.get_account_numbers()
                response.raise_for_status()
                return  # Exit if successful
            except requests.exceptions.HTTPError as http_err:
                logger.error(f"HTTP error occurred: {http_err}")
                if http_err.response.status_code == 401:  # 401 Unauthorized
                    self._handle_auth_error()
                    return
            except FileNotFoundError as fnf_err:
                logger.error(f"Token file not found: {fnf_err}")
                self._handle_auth_error()
                return
            except Exception as e:
                logger.error(f"Error while setting up the api: {e}")
                if "refresh token invalid" in str(e):
                    self._handle_auth_error()
                    return
                attempt += 1
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise

    def _handle_auth_error(self):
        """Helper method to handle authentication errors"""
        if os.path.exists(self.tokenPath):
            os.remove(self.tokenPath)
        try:
            self.connectClient = auth.client_from_manual_flow(
                api_key=self.apiKey,
                app_secret=self.appSecret,
                callback_url=self.apiRedirectUri,
                token_path=self.tokenPath,
            )
        except requests.exceptions.HTTPError as http_err:
            if "AuthorizationCode has expired" in str(http_err):
                logger.error("Authorization code has expired. Please re-authenticate.")
                # Prompt user to re-authenticate
                print("Authorization code has expired. Please re-authenticate.")
                # Retry authentication
                self.connectClient = auth.client_from_manual_flow(
                    api_key=self.apiKey,
                    app_secret=self.appSecret,
                    callback_url=self.apiRedirectUri,
                    token_path=self.tokenPath,
                )
            else:
                raise

    def delete_token(self):
        """
        Delete the stored token files to force re-authentication.
        This is useful when token authentication errors occur.
        """
        import os
        from logger_config import get_logger

        logger = get_logger()

        try:
            # Path to token file - assuming it's stored in the same directory in a 'token.json' file
            token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')

            # Check if token file exists before attempting to delete
            if os.path.exists(token_path):
                os.remove(token_path)
                logger.info(f"Successfully deleted token file at {token_path}")
                print("Token file deleted successfully.")
            else:
                logger.info("No token file found to delete.")
                print("No existing token file found.")

            # Also check for any other potential token-related files in the directory
            directory = os.path.dirname(os.path.abspath(__file__))
            for filename in os.listdir(directory):
                if filename.endswith('.token') or 'token' in filename.lower():
                    file_path = os.path.join(directory, filename)
                    os.remove(file_path)
                    logger.info(f"Deleted additional token file: {file_path}")
                    print(f"Deleted additional token file: {filename}")

            return True
        except Exception as e:
            logger.error(f"Error while deleting token: {str(e)}")
            print(f"Error while deleting token: {str(e)}")
            return False

    def get_hash_value(self, account_number, data):
        for item in data:
            if item["accountNumber"] == account_number:
                return item["hashValue"]
        return None

    def getAccountHash(self):
        r = self.connectClient.get_account_numbers()

        assert r.status_code == 200, r.raise_for_status()

        data = r.json()
        try:
            return self.get_hash_value(SchwabAccountID, data)
        except KeyError:
            return alert.botFailed(None, "Error while getting account hash value")

    def getATMPrice(self, asset):
        # client can be None
        r = self.connectClient.get_quote(asset)
        assert r.status_code == 200, r.raise_for_status()

        data = r.json()
        lastPrice = 0

        try:
            if data[asset]["assetMainType"] == "OPTION":
                lastPrice = median(
                    [data[asset]["quote"]["bidPrice"], data[asset]["quote"]["askPrice"]]
                )
            else:
                lastPrice = data[asset]["quote"]["lastPrice"]
        except KeyError:
            return alert.botFailed(asset, "Wrong data from api when getting ATM price")

        return lastPrice

    def getOptionChain(self, asset, strikes, date, daysLessAllowed):
        fromDate = date - timedelta(days=daysLessAllowed)
        toDate = date

        r = self.connectClient.get_option_chain(
            asset,
            contract_type=self.connectClient.Options.ContractType.CALL,
            strike_count=strikes,
            strategy=self.connectClient.Options.Strategy.SINGLE,
            interval=None,
            strike=None,
            strike_range=None,
            from_date=fromDate,
            to_date=toDate,
            volatility=None,
            underlying_price=None,
            interest_rate=None,
            days_to_expiration=None,
            exp_month=None,
            option_type=None,
        )

        assert r.status_code == 200, r.raise_for_status()

        return r.json()

    def getPutOptionChain(self, asset, strikes, date, daysLessAllowed):
        fromDate = date - timedelta(days=daysLessAllowed)
        toDate = date

        r = self.connectClient.get_option_chain(
            asset,
            contract_type=self.connectClient.Options.ContractType.PUT,
            strike_count=strikes,
            strategy=self.connectClient.Options.Strategy.SINGLE,
            interval=None,
            strike=None,
            strike_range=None,
            from_date=fromDate,
            to_date=toDate,
            volatility=None,
            underlying_price=None,
            interest_rate=None,
            days_to_expiration=None,
            exp_month=None,
            option_type=None,
        )

        assert r.status_code == 200, r.raise_for_status()

        return r.json()

    def getOptionExecutionWindow(self):
        now = datetime.now(pytz.UTC)

        try:
            r = self.connectClient.get_market_hours(
                self.connectClient.MarketHours.Market.OPTION
            )
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching market hours: {e}")
            return {"open": False, "openDate": None, "nowDate": now, "error": str(e)}

        data = r.json()

        try:
            market_data = data["option"]
            logger.debug("Market data: %s", market_data)
            if not market_data or not next(iter(market_data.values())).get("isOpen"):
                return {"open": False, "openDate": None, "nowDate": now}

            session_hours = next(iter(market_data.values())).get("sessionHours")
            if not session_hours:
                return {"open": False, "openDate": None, "nowDate": now}

            regular_market_hours = session_hours.get("regularMarket")
            if not regular_market_hours:
                return {"open": False, "openDate": None, "nowDate": now}

            start = datetime.fromisoformat(regular_market_hours[0]["start"])
            end = datetime.fromisoformat(regular_market_hours[0]["end"])

            window_start = start + timedelta(minutes=10)

            if window_start <= now <= end:
                return {"open": True, "openDate": window_start, "nowDate": now}
            else:
                return {"open": False, "openDate": window_start, "nowDate": now}
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Error processing market hours data: {e}")
            return {"open": False, "openDate": None, "nowDate": now, "error": str(e)}

    def display_margin_requirements(api, shorts):
        if not shorts:
            print("No short options positions found.")
            return

        # Get account data for margin information
        r = api.connectClient.get_account(
            api.getAccountHash(), fields=api.connectClient.Account.Fields.POSITIONS
        )
        data = r.json()

        # Get margin data for all shorts
        margin_data = []
        total_margin = 0

        for short in shorts:
            margin = 0
            option_type = "Call" if "C" in short["optionSymbol"] else "Put"

            for position in data["securitiesAccount"]["positions"]:
                if position["instrument"]["symbol"] == short["optionSymbol"]:
                    if "maintenanceRequirement" in position:
                        margin = position["maintenanceRequirement"]
                    break

            # Only include positions with non-zero margin
            if margin > 0:
                total_margin += margin
                margin_data.append({
                    "symbol": short["stockSymbol"],
                    "type": f"Short {option_type}",
                    "strike": short["strike"],
                    "expiration": short["expiration"],
                    "count": int(short["count"]),
                    "margin": margin
                })

        # Sort by margin in descending order
        margin_data.sort(key=lambda x: x["margin"], reverse=True)

        if not margin_data:
            print("No positions with margin requirements found.")
            return

        # Print total margin requirement
        print(f"\nTotal Margin Requirement: ${total_margin:,.2f}")

        print("\nDetailed Margin Requirements (Sorted by Margin):")
        print("-" * 95)
        print(f"{'Symbol':<15} {'Type':<12} {'Strike':<10} {'Expiration':<12} {'Count':<8} {'Margin':<15}")
        print("-" * 95)

        for position in margin_data:
            print(
                f"{position['symbol']:<15} "
                f"{position['type']:<12} "
                f"{position['strike']:<10} "
                f"{position['expiration']:<12} "
                f"{position['count']:<8} "
                f"${position['margin']:<14,.2f}"
            )
        print("-" * 95)

    def writeNewContracts(
        self,
        oldSymbol,
        oldAmount,
        oldDebit,
        newSymbol,
        newAmount,
        newCredit,
        fullPricePercentage,
    ):
        """
        Send an order for writing new contracts to the api
        fullPricePercentage is for reducing the price by a custom amount if we cant get filled
        """

        if oldSymbol is None:
            price = newCredit

            if fullPricePercentage == 100:
                price = round(price, 2)
            else:
                price = round(price * (fullPricePercentage / 100), 2)

            # init a new position, sell to open
            order = (
                schwab.orders.options.option_sell_to_open_limit(
                    newSymbol, newAmount, price
                )
                .set_duration(schwab.orders.common.Duration.DAY)
                .set_session(schwab.orders.common.Session.NORMAL)
            )

            if newAmount > 1:
                order.set_special_instruction(
                    schwab.orders.common.SpecialInstruction.ALL_OR_NONE
                )
        else:
            # roll

            if oldAmount != newAmount:
                # custom order
                price = -(oldDebit * oldAmount - newCredit * newAmount)
            else:
                # diagonal, we ignore amount
                price = -(oldDebit - newCredit)

            if fullPricePercentage == 100:
                price = round(price, 2)
            else:
                if price < 100:
                    # reduce the price by 1$ for each retry, to have better fills and allow it to go below 0
                    price = round(price - ((100 - fullPricePercentage) * 0.01), 2)
                else:
                    # reduce the price by 1% for each retry
                    price = round(price * (fullPricePercentage / 100), 2)

            order = schwab.orders.generic.OrderBuilder()

            orderType = schwab.orders.common.OrderType.NET_CREDIT

            if price < 0:
                price = -price
                orderType = schwab.orders.common.OrderType.NET_DEBIT

            order.add_option_leg(
                schwab.orders.common.OptionInstruction.BUY_TO_CLOSE,
                oldSymbol,
                oldAmount,
            ).add_option_leg(
                schwab.orders.common.OptionInstruction.SELL_TO_OPEN,
                newSymbol,
                newAmount,
            ).set_duration(
                schwab.orders.common.Duration.DAY
            ).set_session(
                schwab.orders.common.Session.NORMAL
            ).set_price(
                price
            ).set_order_type(
                orderType
            ).set_order_strategy_type(
                schwab.orders.common.OrderStrategyType.SINGLE
            )

        if not debugCanSendOrders:
            print(order.build())
            exit()

        r = self.connectClient.place_order(SchwabAccountID, order)

        order_id = Utils(self.connectClient, SchwabAccountID).extract_order_id(r)
        assert order_id is not None

        return order_id

    def checkOrder(self, orderId):
        r = self.connectClient.get_order(orderId, self.getAccountHash())

        assert r.status_code == 200, r.raise_for_status()

        data = r.json()
        if data["status"] == "FILLED":
            print(f"Check Order details: {data}")
        complexOrderStrategyType = None

        try:
            status = data["status"]
            filled = data["status"] == "FILLED"
            price = data["price"]
            partialFills = data["filledQuantity"]
            orderType = "CREDIT"
            typeAdjustedPrice = price

            if data["orderType"] == "NET_DEBIT":
                orderType = "DEBIT"
                typeAdjustedPrice = -price

            if "complexOrderStrategyType" in data:
                complexOrderStrategyType = data["complexOrderStrategyType"]

        except KeyError:
            return alert.botFailed(None, "Error while checking working order")

        return {
            "status": status,
            "filled": filled,
            "price": price,
            "partialFills": partialFills,
            "complexOrderStrategyType": complexOrderStrategyType,
            "typeAdjustedPrice": typeAdjustedPrice,
            "orderType": orderType,
        }

    def cancelOrder(self, orderId):
        r = self.connectClient.cancel_order(orderId, self.getAccountHash())

        # throws error if cant cancel (code 400 - 404)
        assert r.status_code == 200, r.raise_for_status()

    def getRecentOrders(self, max_results=50):
        """Get recent orders for the account."""
        try:
            # Try different approaches to get orders
            logger.debug(f"Attempting to fetch orders with account hash: {self.getAccountHash()}")
            
            # First try: Get orders with basic parameters using account-specific method
            try:
                r = self.connectClient.get_orders_for_account(
                    self.getAccountHash(),
                    max_results=max_results
                )
                r.raise_for_status()
                data = r.json()
                logger.debug(f"Orders fetched successfully: {len(data) if isinstance(data, list) else 'Not a list'}")
                return data
            except Exception as e:
                logger.error(f"Error with basic get_orders_for_account: {e}")
            
            # Second try: Get orders with status filter
            try:
                r = self.connectClient.get_orders_for_account(
                    self.getAccountHash(),
                    max_results=max_results,
                    status=self.connectClient.Order.Status.ALL
                )
                r.raise_for_status()
                data = r.json()
                logger.debug(f"Orders with status filter: {len(data) if isinstance(data, list) else 'Not a list'}")
                return data
            except Exception as e:
                logger.error(f"Error with status filter get_orders_for_account: {e}")
                
            # Third try: Get orders with different parameters
            try:
                from datetime import datetime, timedelta
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)
                
                r = self.connectClient.get_orders_for_account(
                    self.getAccountHash(),
                    max_results=max_results,
                    from_entered_datetime=start_date,
                    to_entered_datetime=end_date
                )
                r.raise_for_status()
                data = r.json()
                logger.debug(f"Orders with date filter: {len(data) if isinstance(data, list) else 'Not a list'}")
                return data
            except Exception as e:
                logger.error(f"Error with date filter get_orders_for_account: {e}")
                
            # If all attempts fail, return empty list
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching recent orders: {e}")
            return []

    def formatOrderForDisplay(self, order):
        """Format an order for display in the UI."""
        try:
            logger.debug(f"Formatting order: {order}")
            order_id = order.get("orderId", "")
            status = order.get("status", "")
            entered_time = order.get("enteredTime", "")
            
            # Extract asset and order type information
            asset = ""
            order_type = ""
            quantity = ""
            price = ""
            
            # Handle different order structures
            if "orderLegCollection" in order and order["orderLegCollection"]:
                first_leg = order["orderLegCollection"][0]
                if "instrument" in first_leg:
                    # Try to get the underlying symbol first, then fall back to symbol
                    asset = first_leg["instrument"].get("underlyingSymbol", "")
                    if not asset:
                        asset = first_leg["instrument"].get("symbol", "")
                
                # Use instruction instead of orderLegType for better accuracy
                order_type = first_leg.get("instruction", first_leg.get("orderLegType", ""))
                quantity = first_leg.get("quantity", "")
            
            # Try different ways to get price
            if "price" in order:
                price = order["price"]
            elif "orderPrice" in order:
                price = order["orderPrice"]
            
            formatted_order = {
                "order_id": order_id,
                "status": status,
                "entered_time": entered_time,
                "asset": asset,
                "order_type": order_type,
                "quantity": quantity,
                "price": price
            }
            logger.debug(f"Formatted order: {formatted_order}")
            return formatted_order
        except Exception as e:
            logger.error(f"Error formatting order: {e}")
            # Return a more informative error row
            return {
                "order_id": "Error",
                "status": "Format Error",
                "entered_time": "",
                "asset": str(e),
                "order_type": "",
                "quantity": "",
                "price": ""
            }
        r = self.connectClient.get_account(
            self.getAccountHash(), fields=self.connectClient.Account.Fields.POSITIONS
        )

        assert r.status_code == 200, r.raise_for_status()

        data = r.json()

        if existingSymbol and not self.checkPreviousSoldCcsStillHere(
            existingSymbol, amountWillBuyBack, data
        ):
            # something bad happened, let the user know he needs to look into it
            return alert.botFailed(
                asset,
                "The cc's the bot wants to buy back aren't in the account anymore, manual review required.",
            )

        # set to this instead of 0 because we ignore the amount of options the bot has sold itself, as we are buying them back
        coverage = amountWillBuyBack

        try:
            for position in data["securitiesAccount"]["positions"]:
                if (
                    position["instrument"]["assetType"] == "EQUITY"
                    and position["instrument"]["symbol"] == asset
                ):
                    amountOpen = int(position["longQuantity"]) - int(
                        position["shortQuantity"]
                    )

                    # can be less than 0, removes coverage then
                    coverage += math.floor(amountOpen / 100)

                if (
                    position["instrument"]["assetType"] == "OPTION"
                    and position["instrument"]["underlyingSymbol"] == asset
                    and position["instrument"]["putCall"] == "CALL"
                ):
                    optionData = self.getOptionDetails(position["instrument"]["symbol"])
                    strike = optionData["strike"]
                    optionDate = optionData["expiration"]
                    amountOpen = int(position["longQuantity"]) - int(
                        position["shortQuantity"]
                    )

                    if amountOpen > 0 and (
                        strike >= optionStrikeToCover or optionDate < optionDateToCover
                    ):
                        # we cant cover with this, so we dont add it to coverage if its positive,
                        # but we substract when negative
                        continue

                    coverage += amountOpen

            return coverage >= amountToCover

        except KeyError:
            return alert.botFailed(asset, "Error while checking the account coverage")

    def checkPreviousSoldCcsStillHere(self, asset, amount, data):
        """
        Check if we still have the amount of cc's we sold in the account
        If not, then something bad happened like early assignment f.ex.
        """
        try:
            for position in data["securitiesAccount"]["positions"]:
                if position["instrument"]["symbol"] == asset:
                    # we allow there to be MORE sold of this option but not less
                    # Useful f.ex. if someone wants to manually sell more (independent of the bot)
                    return (
                        position["shortQuantity"] >= amount
                        and position["longQuantity"] == 0
                    )
            return False

        except KeyError:
            return False

    def get_quote(self, asset):
        r = self.connectClient.get_quotes([asset])
        assert r.status_code == 200 or r.status_code == 201, r.raise_for_status()
        return r.json()

    def getOptionDetails(self, asset):
        r = self.connectClient.get_quotes(asset)

        assert r.status_code == 200, r.raise_for_status()

        data = r.json()

        try:
            year = str(data[asset]["reference"]["expirationYear"])
            month = str(data[asset]["reference"]["expirationMonth"]).zfill(2)
            day = str(data[asset]["reference"]["expirationDay"]).zfill(2)
            expiration = year + "-" + month + "-" + day

            if not validDateFormat(expiration):
                return alert.botFailed(
                    asset, "Incorrect date format from api: " + expiration
                )

            return {
                "strike": data[asset]["reference"]["strikePrice"],
                "expiration": expiration,
                "delta": data[asset]["quote"]["delta"],
            }
        except KeyError:
            return alert.botFailed(
                asset, "Wrong data from api when getting option expiry data"
            )

    def updateShortPosition(self):
        # get account positions
        r = self.connectClient.get_account(
            self.getAccountHash(), fields=self.connectClient.Account.Fields.POSITIONS
        )
        return self.optionPositions(r.text)

    def optionPositions(self, data):
        data = json.loads(data)
        positions = data["securitiesAccount"]["positions"]
        logger.debug("Positions: %s", positions)
        shortPositions = []
        for position in positions:
            if (
                position["instrument"]["assetType"] != "OPTION"
                and position["instrument"].get("putCall") != "CALL"
                and position["shortQuantity"] == 0
            ):
                continue
            entry = {
                "stockSymbol": position["instrument"].get("underlyingSymbol"),
                "optionSymbol": position["instrument"]["symbol"],
                "expiration": extract_date(position["instrument"]["description"]),
                "count": position["shortQuantity"],
                "strike": extract_strike_price(position["instrument"]["description"]),
                "receivedPremium": position["averagePrice"],
            }
            shortPositions.append(entry)
        shortPositions = sorted(shortPositions, key=itemgetter("expiration"))
        return shortPositions

    def rollOver(self, oldSymbol, newSymbol, amount, price):
        # init a new position, sell to open,
        # price is the net amount to be credited (received) for the roll
        order = schwab.orders.generic.OrderBuilder()

        orderType = schwab.orders.common.OrderType.NET_CREDIT

        if price < 0:
            price = -price
            orderType = schwab.orders.common.OrderType.NET_DEBIT

        order.add_option_leg(
            schwab.orders.common.OptionInstruction.BUY_TO_CLOSE,
            oldSymbol,
            amount,
        ).add_option_leg(
            schwab.orders.common.OptionInstruction.SELL_TO_OPEN,
            newSymbol,
            amount,
        ).set_duration(
            schwab.orders.common.Duration.DAY
        ).set_session(
            schwab.orders.common.Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            orderType
        ).set_order_strategy_type(
            schwab.orders.common.OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            schwab.orders.common.ComplexOrderStrategyType.DIAGONAL
        )

        if not debugCanSendOrders:
            print("Order not placed: ", order.build())
            exit()
        try:
            r = self.connectClient.place_order(self.getAccountHash(), order)
        except Exception as e:
            print(e)
            return alert.botFailed(None, "Error while placing the roll order")

        order_id = Utils(self.connectClient, self.getAccountHash()).extract_order_id(r)
        assert order_id is not None

        return order_id

    def vertical_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):

        if "$" in symbol:
            # remove $ from symbol
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = schwab.orders.generic.OrderBuilder()

        orderType = schwab.orders.common.OrderType.NET_DEBIT

        order.add_option_leg(
            schwab.orders.common.OptionInstruction.BUY_TO_OPEN,
            long_call_sym,
            amount,
        ).add_option_leg(
            schwab.orders.common.OptionInstruction.SELL_TO_OPEN,
            short_call_sym,
            amount,
        ).set_duration(
            schwab.orders.common.Duration.DAY
        ).set_session(
            schwab.orders.common.Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            orderType
        ).set_order_strategy_type(
            schwab.orders.common.OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            schwab.orders.common.ComplexOrderStrategyType.VERTICAL
        )

        if not debugCanSendOrders:
            print("Order not placed: ", order.build())
            return None  # Return None instead of exiting
        hash = self.getAccountHash()
        try:
            r = self.connectClient.place_order(hash, order)
        except Exception as e:
            print(e)
            return alert.botFailed(None, "Error while placing the vertical call order")

        order_id = Utils(self.connectClient, hash).extract_order_id(r)
        assert order_id is not None

        return order_id

    def synthetic_covered_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):

        if "$" in symbol:
            # remove $ from symbol
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_put_sym = OptionSymbol(symbol, expiration, "P", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = schwab.orders.generic.OrderBuilder()

        orderType = schwab.orders.common.OrderType.NET_DEBIT

        order.add_option_leg(
            schwab.orders.common.OptionInstruction.BUY_TO_OPEN,
            long_call_sym,
            amount,
        ).add_option_leg(
            schwab.orders.common.OptionInstruction.SELL_TO_OPEN,
            short_call_sym,
            amount,
        ).add_option_leg(
            schwab.orders.common.OptionInstruction.SELL_TO_OPEN,
            short_put_sym,
            amount,
        ).set_duration(
            schwab.orders.common.Duration.DAY
        ).set_session(
            schwab.orders.common.Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            orderType
        ).set_order_strategy_type(
            schwab.orders.common.OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            schwab.orders.common.ComplexOrderStrategyType.CUSTOM
        )

        if not debugCanSendOrders:
            print("Order not placed: ", order.build())
            return None  # Return None instead of exiting
        hash = self.getAccountHash()
        try:
            r = self.connectClient.place_order(hash, order)
        except Exception as e:
            print(e)
            return alert.botFailed(None, "Error while placing the vertical call order")

        order_id = Utils(self.connectClient, hash).extract_order_id(r)
        assert order_id is not None

        return order_id

    def place_order(self, order_func, order_params, price):
        """
        Place an order with automatic price improvements if not filled
        """
        max_retries = 75
        fixed_step = 0.05  # fixed $0.05 step per retry
        initial_price = price


        now = datetime.now(get_localzone())
        if now.time() >= time_module(15, 30):  # After 3:30 PM
            order_timeout = 15  # Update faster near market close
        else:
            order_timeout = 60  # Normal interval during regular hours

        # Determine if this is a debit order (paying) or credit order (receiving)
        is_debit_order = price > 0  # Positive price means we're paying

        for retry in range(max_retries):
            # Calculate new price with fixed $0.05 step
            if is_debit_order:
                # For debit orders, increase the price we're willing to pay
                current_price = round_to_nearest_five_cents(initial_price + retry * fixed_step)
            else:
                # For credit orders, decrease the price we're willing to accept
                current_price = round_to_nearest_five_cents(initial_price - retry * fixed_step)

            if retry > 0:
                if is_debit_order:
                    print(f"\nAttempt {retry + 1}/{max_retries}")
                    print(f"Improving price by +${retry * fixed_step:.2f} to {current_price}")
                else:
                    print(f"\nAttempt {retry + 1}/{max_retries}")
                    print(f"Improving price by -${retry * fixed_step:.2f} to {current_price}")

            try:
                # Call order function with params and explicit price kwarg
                order_id = order_func(*order_params, price=current_price)

                if not order_id:
                    print("Failed to place order")
                    return False

                # Monitor order with longer timeout
                result = monitor_order(self, order_id, timeout=order_timeout)

                if result == True:  # Order filled
                    return True
                elif result == "cancelled":  # User cancelled
                    return False
                elif result == "timeout":  # Timeout - try price improvement
                    try:
                        self.cancelOrder(order_id)
                        continue
                    except Exception as e:
                        print(f"Error cancelling order: {e}")
                        return False
                else:  # Other failure
                    return False

            except Exception as e:
                print(f"Error during order placement: {str(e)}")
                return False

        print("\nFailed to fill order after all price improvement attempts")
        return False
