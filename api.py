import datetime
import json
import math
import os
import time
from datetime import datetime, timedelta
from operator import itemgetter
from statistics import median

import pytz
import requests
import schwab
from schwab import auth
from schwab.orders.options import OptionSymbol
from schwab.utils import Utils

import alert
from configuration import SchwabAccountID, debugCanSendOrders
from logger_config_quiet import get_logger
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
                if response.status_code != 200:
                    logger.error(f"HTTP error occurred: {response.status_code} {response.text}")
                    self._handle_auth_error()
                    return
                return
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    logger.info("Token file not found, starting manual authentication flow.")
                    self._handle_auth_error()
                    return
                logger.error(f"Error while setting up the api: {e}")
                error_str = str(e).lower()
                if (
                    "refresh token invalid" in error_str
                    or "refresh_token_authentication_error" in error_str
                    or "unsupported_token_type" in error_str
                ):
                    self._handle_auth_error()
                    return
                attempt += 1
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise

    def _handle_auth_error(self):
        if os.path.exists(self.tokenPath):
            os.remove(self.tokenPath)
        try:
            self.connectClient = auth.client_from_manual_flow(
                api_key=self.apiKey,
                app_secret=self.appSecret,
                callback_url=self.apiRedirectUri,
                token_path=self.tokenPath,
            )
        except Exception as http_err:
            logger.error(f"Auth error: {http_err}")
            print("Authorization code has expired. Please re-authenticate.")
            return

    def delete_token(self):
        try:
            token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
            if os.path.exists(token_path):
                os.remove(token_path)
                logger.info(f"Successfully deleted token file at {token_path}")
                print("Token file deleted successfully.")
            else:
                logger.info("No token file found to delete.")
                print("No existing token file found.")
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
        try:
            r = self.connectClient.get_account_numbers()
            if r.status_code != 200:
                logger.error(f"get_account_numbers failed: {r.status_code} {r.text}")
                return alert.botFailed(None, f"Error getting account hash: {r.status_code} {r.text}")
            data = r.json()
            try:
                return self.get_hash_value(SchwabAccountID, data)
            except KeyError:
                return alert.botFailed(None, "Error while getting account hash value")
        except Exception as e:
            logger.error(f"Exception in getAccountHash: {e}")
            return alert.botFailed(None, f"Exception in getAccountHash: {e}")

    def getATMPrice(self, asset):
        try:
            r = self.connectClient.get_quote(asset)
            if r.status_code != 200:
                logger.error(f"get_quote failed: {r.status_code} {r.text}")
                return alert.botFailed(asset, f"Error getting ATM price: {r.status_code} {r.text}")
            data = r.json()
            lastPrice = 0
            try:
                if data[asset]["assetMainType"] == "OPTION":
                    lastPrice = median([
                        data[asset]["quote"]["bidPrice"], data[asset]["quote"]["askPrice"]
                    ])
                else:
                    lastPrice = data[asset]["quote"]["lastPrice"]
            except KeyError:
                return alert.botFailed(asset, "Wrong data from api when getting ATM price")
            return lastPrice
        except Exception as e:
            logger.error(f"Exception in getATMPrice: {e}")
            return alert.botFailed(asset, f"Exception in getATMPrice: {e}")

    def getOptionChain(self, asset, strikes, date, daysLessAllowed):
        try:
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
            if r.status_code != 200:
                logger.error(f"get_option_chain failed: {r.status_code} {r.text}")
                return alert.botFailed(asset, f"Error getting option chain: {r.status_code} {r.text}")
            return r.json()
        except Exception as e:
            logger.error(f"Exception in getOptionChain: {e}")
            return alert.botFailed(asset, f"Exception in getOptionChain: {e}")

    def getPutOptionChain(self, asset, strikes, date, daysLessAllowed):
        try:
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
            if r.status_code != 200:
                logger.error(f"get_option_chain (PUT) failed: {r.status_code} {r.text}")
                return alert.botFailed(asset, f"Error getting put option chain: {r.status_code} {r.text}")
            return r.json()
        except Exception as e:
            logger.error(f"Exception in getPutOptionChain: {e}")
            return alert.botFailed(asset, f"Exception in getPutOptionChain: {e}")

    def getOptionExecutionWindow(self):
        from datetime import timezone
        try:
            now = datetime.now(timezone.utc)  # Make now timezone-aware (UTC)
            r = self.connectClient.get_market_hours(
                self.connectClient.MarketHours.Market.OPTION
            )
            if r.status_code != 200:
                logger.error(f"get_market_hours failed: {r.status_code} {r.text}")
                return {"open": False, "openDate": None, "nowDate": now, "error": f"{r.status_code} {r.text}"}
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
                # Parse start and end as timezone-aware UTC
                start = datetime.fromisoformat(regular_market_hours[0]["start"]).astimezone(timezone.utc)
                end = datetime.fromisoformat(regular_market_hours[0]["end"]).astimezone(timezone.utc)
                window_start = start + timedelta(minutes=10)
                if window_start <= now <= end:
                    return {"open": True, "openDate": window_start, "nowDate": now}
                else:
                    return {"open": False, "openDate": window_start, "nowDate": now}
            except (KeyError, TypeError, ValueError) as e:
                logger.error(f"Error processing market hours data: {e}")
                return {"open": False, "openDate": None, "nowDate": now, "error": str(e)}
        except Exception as e:
            logger.error(f"Exception in getOptionExecutionWindow: {e}")
            from datetime import timezone
            return {"open": False, "openDate": None, "nowDate": datetime.now(timezone.utc), "error": str(e)}

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
            print("Order not placed: ", order.build())
            return alert.botFailed(None, "Order not placed: debugCanSendOrders is disabled")

        r = self.connectClient.place_order(SchwabAccountID, order)

        order_id = Utils(self.connectClient, SchwabAccountID).extract_order_id(r)
        assert order_id is not None

        return order_id

    def checkOrder(self, orderId):
        try:
            r = self.connectClient.get_order(orderId, self.getAccountHash())
            if r.status_code != 200:
                logger.error(f"get_order failed: {r.status_code} {r.text}")
                return alert.botFailed(None, f"Error checking order: {r.status_code} {r.text}")
            data = r.json()
            if data.get("status") == "FILLED":
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
        except Exception as e:
            logger.error(f"Exception in checkOrder: {e}")
            return alert.botFailed(None, f"Exception in checkOrder: {e}")

    def cancelOrder(self, orderId):
        try:
            r = self.connectClient.cancel_order(orderId, self.getAccountHash())
            if r.status_code != 200:
                logger.error(f"cancel_order failed: {r.status_code} {r.text}")
                return alert.botFailed(None, f"Error cancelling order: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"Exception in cancelOrder: {e}")
            return alert.botFailed(None, f"Exception in cancelOrder: {e}")

    def checkAccountHasEnoughToCover(
        self,
        asset,
        existingSymbol,
        amountWillBuyBack,
        amountToCover,
        optionStrikeToCover,
        optionDateToCover,
    ):
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
        try:
            r = self.connectClient.get_quotes([asset])
            if r.status_code not in [200, 201]:
                logger.error(f"get_quotes failed: {r.status_code} {r.text}")
                return alert.botFailed(asset, f"Error getting quote: {r.status_code} {r.text}")
            return r.json()
        except Exception as e:
            logger.error(f"Exception in get_quote: {e}")
            return alert.botFailed(asset, f"Exception in get_quote: {e}")

    def getOptionDetails(self, asset):
        try:
            r = self.connectClient.get_quotes(asset)
            if r.status_code != 200:
                logger.error(f"get_quotes failed: {r.status_code} {r.text}")
                return alert.botFailed(asset, f"Error getting option details: {r.status_code} {r.text}")
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
        except Exception as e:
            logger.error(f"Exception in getOptionDetails: {e}")
            return alert.botFailed(asset, f"Exception in getOptionDetails: {e}")

    def updateShortPosition(self):
        try:
            r = self.connectClient.get_account(
                self.getAccountHash(), fields=self.connectClient.Account.Fields.POSITIONS
            )
            if r.status_code != 200:
                logger.error(f"get_account failed: {r.status_code} {r.text}")
                return alert.botFailed(None, f"Error updating short position: {r.status_code} {r.text}")
            return self.optionPositions(r.text)
        except Exception as e:
            logger.error(f"Exception in updateShortPosition: {e}")
            return alert.botFailed(None, f"Exception in updateShortPosition: {e}")

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
        """
        Place a roll order using the exact option symbols as returned by the Schwab API option chain.
        Both oldSymbol and newSymbol must be the 'symbol' field from the Schwab API, with no manual construction or modification.
        """
        print(f"DEBUG: rollOver called with oldSymbol={oldSymbol}, newSymbol={newSymbol}, amount={amount}, price={price}")

        order = schwab.orders.generic.OrderBuilder()

        orderType = schwab.orders.common.OrderType.NET_CREDIT
        abs_price = abs(float(price))

        if price < 0:
            orderType = schwab.orders.common.OrderType.NET_DEBIT

        print(f"DEBUG: Order type: {orderType}, Price: {abs_price}")

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
            abs_price  # Always use absolute value, orderType determines debit/credit
        ).set_order_type(
            orderType
        ).set_order_strategy_type(
            schwab.orders.common.OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            schwab.orders.common.ComplexOrderStrategyType.DIAGONAL
        )

        print("DEBUG: Order built successfully")

        if not debugCanSendOrders:
            print("DEBUG: Order not placed (debugCanSendOrders=False):", order.build())
            return alert.botFailed(None, "Order not placed: debugCanSendOrders is disabled")

        hash = self.getAccountHash()
        print(f"DEBUG: Account hash: {hash}")

        try:
            print("DEBUG: About to place order...")
            r = self.connectClient.place_order(hash, order)
            print(f"DEBUG: Order response status: {r.status_code}")

            # Check if the response indicates success
            if r.status_code not in [200, 201]:
                error_msg = f"Order failed with status {r.status_code}"
                try:
                    error_detail = r.json()
                    error_msg += f": {error_detail}"
                except Exception:
                    error_msg += f": {r.text}"
                logger.error(error_msg)
                return alert.botFailed(None, error_msg)

        except Exception as e:
            logger.error(f"Error placing roll order: {e}")
            return alert.botFailed(None, f"Error while placing the roll order: {str(e)}")

        try:
            order_id = Utils(self.connectClient, hash).extract_order_id(r)
            print(f"DEBUG: Extracted order ID: {order_id}")

            if order_id is None:
                logger.error("Failed to extract order ID from response")
                return alert.botFailed(None, "Failed to extract order ID from roll order response")

            return order_id
        except Exception as e:
            logger.error(f"Error extracting order ID: {e}")
            return alert.botFailed(None, f"Error extracting order ID: {str(e)}")

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
            return alert.botFailed(None, "Order not placed: debugCanSendOrders is disabled")
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
            return alert.botFailed(None, "Order not placed: debugCanSendOrders is disabled")
        hash = self.getAccountHash()
        try:
            r = self.connectClient.place_order(hash, order)
        except Exception as e:
            print(e)
            return alert.botFailed(None, "Error while placing the vertical call order")

        order_id = Utils(self.connectClient, hash).extract_order_id(r)
        assert order_id is not None

        return order_id

    def get_orders(self, max_results=1000, days_back=None, status=None):
        """
        Get orders from Schwab API with multiple fallback strategies
        Returns list of orders or empty list if none found
        """
        try:
            # Try multiple approaches to get orders
            approaches = []

            # Approach 1: All orders without filters
            approaches.append(("all_orders", {
                "account_hash": self.getAccountHash(),
                "max_results": max_results
            }))

            # Approach 2: Orders with specific status
            if status:
                try:
                    status_enum = getattr(self.connectClient.Order.Status, status, None)
                    if status_enum:
                        approaches.append((f"status_{status}", {
                            "account_hash": self.getAccountHash(),
                            "max_results": max_results,
                            "status": status_enum
                        }))
                except AttributeError:
                    pass

            # Approach 3: Orders with date range
            if days_back is not None:
                from_date = datetime.now() - timedelta(days=days_back)
                to_date = datetime.now()
                approaches.append((f"date_range_{days_back}", {
                    "account_hash": self.getAccountHash(),
                    "max_results": max_results,
                    "from_entered_datetime": from_date,
                    "to_entered_datetime": to_date
                }))

            # Try each approach
            for approach_name, params in approaches:
                try:
                    logger.debug(f"Trying order retrieval approach: {approach_name}")

                    # Remove None values from params
                    clean_params = {k: v for k, v in params.items() if v is not None}

                    response = self.connectClient.get_orders_for_account(**clean_params)

                    if response.status_code == 200:
                        orders = response.json()
                        if orders:
                            logger.debug(f"Successfully retrieved {len(orders)} orders using {approach_name}")
                            return orders

                except Exception as e:
                    logger.debug(f"Approach {approach_name} failed: {e}")
                    continue

            # If no approach worked, try all linked accounts
            try:
                logger.debug("Trying get_orders_for_all_linked_accounts")
                response = self.connectClient.get_orders_for_all_linked_accounts(max_results=max_results)
                if response.status_code == 200:
                    orders = response.json()
                    if orders:
                        logger.debug(f"Retrieved {len(orders)} orders from all linked accounts")
                        return orders
            except Exception as e:
                logger.debug(f"All linked accounts approach failed: {e}")

            logger.warning("No orders found with any approach")
            return []

        except Exception as e:
            logger.error(f"Error retrieving orders: {e}")
            return []

    def get_order_details(self, order_id):
        """
        Get details for a specific order
        Returns order details dict or None if not found
        """
        try:
            response = self.connectClient.get_order(order_id, self.getAccountHash())
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get order details for {order_id}: HTTP {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting order details for {order_id}: {e}")
            return None

    def box_spread_order(self, symbol, expiration_date, low_strike, high_strike, quantity, net_price):
        """
        Place a box spread order (4-leg strategy)

        For a SELL box spread (most common - borrowing money):
        - Sell low strike call
        - Buy high strike call
        - Buy low strike put
        - Sell high strike put
        """
        try:
            if "$" in symbol:
                # remove $ from symbol
                symbol = symbol[1:]

            # Create option symbols using the OptionSymbol builder
            low_call_sym = OptionSymbol(symbol, expiration_date, "C", str(low_strike)).build()
            high_call_sym = OptionSymbol(symbol, expiration_date, "C", str(high_strike)).build()
            low_put_sym = OptionSymbol(symbol, expiration_date, "P", str(low_strike)).build()
            high_put_sym = OptionSymbol(symbol, expiration_date, "P", str(high_strike)).build()

            print(f"Box spread symbols: {low_call_sym}, {high_call_sym}, {low_put_sym}, {high_put_sym}")

            # Build the 4-leg box spread order
            order = schwab.orders.generic.OrderBuilder()

            # Box spreads are typically net credit orders
            orderType = schwab.orders.common.OrderType.NET_CREDIT
            abs_price = abs(float(net_price))

            # If net_price is negative, it's a net debit
            if net_price < 0:
                orderType = schwab.orders.common.OrderType.NET_DEBIT

            # Add all 4 legs for the box spread
            order.add_option_leg(
                schwab.orders.common.OptionInstruction.SELL_TO_OPEN,  # Sell low call
                low_call_sym,
                quantity,
            ).add_option_leg(
                schwab.orders.common.OptionInstruction.BUY_TO_OPEN,   # Buy high call
                high_call_sym,
                quantity,
            ).add_option_leg(
                schwab.orders.common.OptionInstruction.BUY_TO_OPEN,   # Buy low put
                low_put_sym,
                quantity,
            ).add_option_leg(
                schwab.orders.common.OptionInstruction.SELL_TO_OPEN,  # Sell high put
                high_put_sym,
                quantity,
            ).set_duration(
                schwab.orders.common.Duration.DAY
            ).set_session(
                schwab.orders.common.Session.NORMAL
            ).set_price(
                abs_price
            ).set_order_type(
                orderType
            ).set_order_strategy_type(
                schwab.orders.common.OrderStrategyType.SINGLE
            ).set_complex_order_strategy_type(
                schwab.orders.common.ComplexOrderStrategyType.CUSTOM
            )

            print(f"Placing box spread order: {symbol} {low_strike}-{high_strike} for ${net_price}")

            if not debugCanSendOrders:
                print("Box spread order not placed: ", order.build())
                return alert.botFailed(None, "Order not placed: debugCanSendOrders is disabled")

            hash = self.getAccountHash()
            try:
                r = self.connectClient.place_order(hash, order)
                print(f"Box spread order response status: {r.status_code}")

                if r.status_code not in [200, 201]:
                    error_msg = f"Box spread order failed with status {r.status_code}: {r.text}"
                    logger.error(error_msg)
                    return alert.botFailed(None, error_msg)

            except Exception as e:
                print(f"Error placing box spread order: {e}")
                return alert.botFailed(None, f"Error while placing the box spread order: {str(e)}")

            order_id = Utils(self.connectClient, hash).extract_order_id(r)
            if order_id is None:
                logger.error("Failed to extract order ID from box spread response")
                return alert.botFailed(None, "Failed to extract order ID from box spread order response")

            print(f"Box spread order placed successfully. Order ID: {order_id}")
            return order_id

        except Exception as e:
            error_msg = f"Exception in box_spread_order: {str(e)}"
            print(error_msg)
            logger.error(error_msg)
            import traceback
            traceback.print_exc()
            return alert.botFailed(None, error_msg)

    def is_token_valid(self):
        """
        Check if the current token is valid by making a lightweight authenticated call.
        Returns True if valid, False if expired/invalid.
        """
        try:
            if self.connectClient is None:
                # Try to set up the client if not already done
                self.setup(retries=1, delay=1)
            response = self.connectClient.get_account_numbers()
            if hasattr(response, 'status_code') and response.status_code == 200:
                return True
            # If unauthorized or bad request, token is likely invalid
            if hasattr(response, 'status_code') and response.status_code in (400, 401):
                return False
            # If response is not as expected, treat as invalid
            return False
        except Exception as e:
            if "token" in str(e).lower() or "auth" in str(e).lower():
                return False
            return False