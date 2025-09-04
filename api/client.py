import datetime
import json
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
from status import notify, notify_exception, publish_exception
from core.common import round_to_nearest_five_cents, extract_date, extract_strike_price, validDateFormat
from configuration import debugCanSendOrders
from logger_config import get_logger
from api.order_manager import OrderManager
import os

# Get SchwabAccountID from environment variables
SchwabAccountID = os.getenv("SCHWAB_ACCOUNT_ID")

logger = get_logger()


class Api:
    connectClient = None
    tokenPath = ""
    apiKey = ""
    apiRedirectUri = ""
    _account_hash = None
    _order_manager = None

    def __init__(self, apiKey, apiRedirectUri, appSecret):
        # Token file is in the root directory
        self.tokenPath = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "token.json"
        )
        self.tokenPath = os.path.normpath(self.tokenPath)
        self.apiKey = apiKey
        self.apiRedirectUri = apiRedirectUri
        self.appSecret = appSecret
        
    @property
    def order_manager(self):
        """Lazy initialization of OrderManager"""
        if self._order_manager is None:
            self._order_manager = OrderManager(self)
        return self._order_manager

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
                # User-facing: before UI prints; after UI routes to Status Log
                notify("Authorization code has expired. Please re-authenticate.")
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
            # Check if token file exists before attempting to delete
            if os.path.exists(self.tokenPath):
                os.remove(self.tokenPath)
                logger.info(f"Successfully deleted token file at {self.tokenPath}")
                notify("Token file deleted successfully.")
            else:
                logger.info("No token file found to delete.")
                notify("No existing token file found.")

            # Also check for any other potential token-related files in the root directory
            root_directory = os.path.dirname(self.tokenPath)
            for filename in os.listdir(root_directory):
                if filename.endswith('.token') or 'token' in filename.lower():
                    file_path = os.path.join(root_directory, filename)
                    os.remove(file_path)
                    logger.info(f"Deleted additional token file: {file_path}")
                    notify(f"Deleted additional token file: {filename}")

            return True
        except Exception as e:
            logger.error(f"Error while deleting token: {str(e)}")
            notify(f"Error while deleting token: {str(e)}", level="error")
            return False

    def get_hash_value(self, account_number, data):
        for item in data:
            if item["accountNumber"] == account_number:
                return item["hashValue"]
        return None

    def getAccountHash(self):
        # Cache account hash for performance; fetch once per session
        if self._account_hash:
            return self._account_hash
        r = self.connectClient.get_account_numbers()
        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_account_numbers")
            raise
        data = r.json()
        try:
            self._account_hash = self.get_hash_value(SchwabAccountID, data)
            return self._account_hash
        except KeyError:
            return alert.botFailed(None, "Error while getting account hash value")

    def getATMPrice(self, asset):
        # client can be None
        r = self.connectClient.get_quote(asset)
        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_quote")
            raise

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

        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_option_chain CALL")
            raise

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

        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_option_chain PUT")
            raise

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
                return {"open": True, "openDate": window_start, "closeDate": end, "nowDate": now}
            else:
                return {"open": False, "openDate": window_start, "closeDate": end, "nowDate": now}
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Error processing market hours data: {e}")
            return {"open": False, "openDate": None, "nowDate": now, "error": str(e)}

    def display_margin_requirements(api, shorts):
        if not shorts:
            notify("No short options positions found.")
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
            notify("No positions with margin requirements found.")
            return

        # Print total margin requirement
        notify(f"Total Margin Requirement: ${total_margin:,.2f}")

        # Keep the detailed table on stdout only if UI is not active
        header = "Detailed Margin Requirements (Sorted by Margin)"
        notify(header)

        for position in margin_data:
            # Avoid flooding the Status Log with table rows; log concisely
            notify(
                f"{position['symbol']} {position['type']} x{position['count']} @ {position['strike']} exp {position['expiration']}: ${position['margin']:,}"
            )

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
        return self.order_manager.write_new_contracts(
            oldSymbol, oldAmount, oldDebit, newSymbol, newAmount, newCredit, fullPricePercentage
        )

    def checkOrder(self, orderId):
        return self.order_manager.check_order_status(orderId)

    def cancelOrder(self, orderId):
        return self.order_manager.cancel_order(orderId)

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
        if r.status_code not in (200, 201):
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_quotes list")
            raise
        return r.json()

    def getOptionDetails(self, asset):
        r = self.connectClient.get_quotes(asset)

        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                publish_exception(e, prefix="get_quotes single")
            raise

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
        return self.order_manager.roll_over(oldSymbol, newSymbol, amount, price)

    def vertical_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):
        return self.order_manager.vertical_call_order(
            symbol, expiration, strike_low, strike_high, amount, price=price
        )

    def synthetic_covered_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):
        return self.order_manager.synthetic_covered_call_order(
            symbol, expiration, strike_low, strike_high, amount, price=price
        )

    def place_order(self, order_func, order_params, price):
        """
        Place an order with automatic price improvements if not filled
        """
        return self.order_manager.place_order_with_improvement(order_func, order_params, price)

    def editOrderPrice(self, order_id, new_price):
        """Edit an existing order's limit price using Schwab's edit/replace endpoint when available.

        Falls back to cancel-and-place if edit is not supported by the client.

        Returns the new order ID (for replace flows) or the same order ID if edited in place.
        Returns None on failure.
        """
        return self.order_manager.edit_order_price(order_id, new_price)
