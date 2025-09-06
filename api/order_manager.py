import time
import datetime
import sys
from statistics import median
from tzlocal import get_localzone
from core.common import round_to_nearest_five_cents
from configuration import debugCanSendOrders
from status import notify, notify_exception
from logger_config import get_logger
from schwab.orders.options import OptionSymbol
from schwab.orders.generic import OrderBuilder
from schwab.orders.common import (
    Duration, Session, OrderType, OrderStrategyType,
    ComplexOrderStrategyType, OptionInstruction
)
import alert

# Global flag for order cancellation
cancel_order = False

logger = get_logger()


def handle_cancel(e):
    global cancel_order
    if e.name == 'c':
        cancel_order = True


def reset_cancel_flag():
    """Reset the global cancel flag"""
    global cancel_order
    cancel_order = False


class OrderManager:
    def __init__(self, api_client):
        self.api = api_client
        self._order_cache = {}  # For caching order status
        self._cache_expiry = 1  # Cache expiry in seconds

    def _get_account_hash(self):
        """Get account hash from API client"""
        return self.api.getAccountHash()

    def _place_order_api(self, order_spec):
        """Place order through API client"""
        if not debugCanSendOrders:
            notify(str(order_spec.build()))
            return None

        r = self.api.connectClient.place_order(self._get_account_hash(), order_spec)

        from schwab.utils import Utils
        order_id = Utils(self.api.connectClient, self._get_account_hash()).extract_order_id(r)
        assert order_id is not None

        # Extract order details for notification
        try:
            order_details = order_spec.build()

            # Extract details from order legs
            symbol = "Unknown"
            quantity = "Unknown"
            price = "Unknown"

            # Try to extract details from the built order
            if hasattr(order_details, 'get'):
                # Dictionary-like access
                order_dict = order_details
            elif hasattr(order_details, '__dict__'):
                # Object with __dict__
                order_dict = order_details.__dict__
            else:
                # Try to convert to dict
                order_dict = dict(order_details) if order_details else {}

            # Extract price first
            for price_key in ['price', 'orderPrice', 'limitPrice']:
                if price_key in order_dict and order_dict[price_key] is not None:
                    try:
                        price = f"${float(order_dict[price_key]):.2f}"
                        break
                    except (ValueError, TypeError):
                        continue

            # Extract from order legs
            legs = order_dict.get('orderLegCollection', []) or []
            if legs:
                first_leg = legs[0]
                if isinstance(first_leg, dict):
                    # Extract quantity
                    if 'quantity' in first_leg:
                        try:
                            quantity = str(int(first_leg['quantity']))
                        except (ValueError, TypeError):
                            quantity = str(first_leg['quantity'])

                    # Extract symbol from instrument
                    instrument = first_leg.get('instrument', {})
                    if isinstance(instrument, dict):
                        # Try different symbol fields
                        for sym_key in ['symbol', 'underlyingSymbol', 'cusip']:
                            if sym_key in instrument and instrument[sym_key]:
                                symbol = str(instrument[sym_key])
                                break

            # If still unknown, try alternative extraction methods
            if symbol == "Unknown" and hasattr(order_spec, '_legs'):
                try:
                    legs = order_spec._legs
                    if legs:
                        first_leg = legs[0]
                        if hasattr(first_leg, 'instrument') and hasattr(first_leg.instrument, 'symbol'):
                            symbol = str(first_leg.instrument.symbol)
                        elif hasattr(first_leg, '_instrument'):
                            symbol = str(first_leg._instrument)
                except:
                    pass

            # Notify about order placement with details
            try:
                alert.alert(None, f"Order placed successfully for {symbol} (Quantity: {quantity}, Price: {price}, ID: {order_id})")
            except Exception:
                pass
        except Exception as e:
            # Fallback to simple notification if we can't extract details
            try:
                alert.alert(None, f"Order placed successfully (ID: {order_id})")
            except Exception:
                pass

        return order_id

    def write_new_contracts(
        self,
        old_symbol,
        old_amount,
        old_debit,
        new_symbol,
        new_amount,
        new_credit,
        full_price_percentage,
    ):
        """
        Send an order for writing new contracts
        fullPricePercentage is for reducing the price by a custom amount if we can't get filled
        """

        if old_symbol is None:
            price = new_credit

            if full_price_percentage == 100:
                price = round(price, 2)
            else:
                price = round(price * (full_price_percentage / 100), 2)

            # init a new position, sell to open
            order = (
                self.api.connectClient.options.option_sell_to_open_limit(
                    new_symbol, new_amount, price
                )
                .set_duration(Duration.DAY)
                .set_session(Session.NORMAL)
            )

            if new_amount > 1:
                order.set_special_instruction(
                    self.api.connectClient.orders.common.SpecialInstruction.ALL_OR_NONE
                )
        else:
            # roll

            if old_amount != new_amount:
                # custom order
                price = -(old_debit * old_amount - new_credit * new_amount)
            else:
                # diagonal, we ignore amount
                price = -(old_debit - new_credit)

            if full_price_percentage == 100:
                price = round(price, 2)
            else:
                if price < 100:
                    # reduce the price by 1$ for each retry, to have better fills and allow it to go below 0
                    price = round(price - ((100 - full_price_percentage) * 0.01), 2)
                else:
                    # reduce the price by 1% for each retry
                    price = round(price * (full_price_percentage / 100), 2)

            order = OrderBuilder()

            order_type = OrderType.NET_CREDIT

            if price < 0:
                price = -price
                order_type = OrderType.NET_DEBIT

            order.add_option_leg(
                OptionInstruction.BUY_TO_CLOSE,
                old_symbol,
                old_amount,
            ).add_option_leg(
                OptionInstruction.SELL_TO_OPEN,
                new_symbol,
                new_amount,
            ).set_duration(
                Duration.DAY
            ).set_session(
                Session.NORMAL
            ).set_price(
                price
            ).set_order_type(
                order_type
            ).set_order_strategy_type(
                OrderStrategyType.SINGLE
            )

        return self._place_order_api(order)

    def roll_over(self, old_symbol, new_symbol, amount, price):
        """Roll over existing position to new position"""
        order = OrderBuilder()

        order_type = OrderType.NET_CREDIT

        if price < 0:
            price = -price
            order_type = OrderType.NET_DEBIT

        order.add_option_leg(
            OptionInstruction.BUY_TO_CLOSE,
            old_symbol,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            new_symbol,
            amount,
        ).set_duration(
            Duration.DAY
        ).set_session(
            Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            order_type
        ).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            ComplexOrderStrategyType.DIAGONAL
        )

        return self._place_order_api(order)

    def vertical_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):
        """Create a vertical call spread order"""

        if "$" in symbol:
            # remove $ from symbol
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = OrderBuilder()

        order_type = OrderType.NET_DEBIT

        order.add_option_leg(
            OptionInstruction.BUY_TO_OPEN,
            long_call_sym,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            short_call_sym,
            amount,
        ).set_duration(
            Duration.DAY
        ).set_session(
            Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            order_type
        ).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            ComplexOrderStrategyType.VERTICAL
        )

        return self._place_order_api(order)

    def synthetic_covered_call_order(
        self, symbol, expiration, strike_low, strike_high, amount, *, price
    ):
        """Create a synthetic covered call order"""

        if "$" in symbol:
            # remove $ from symbol
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_put_sym = OptionSymbol(symbol, expiration, "P", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = OrderBuilder()

        order_type = OrderType.NET_DEBIT

        order.add_option_leg(
            OptionInstruction.BUY_TO_OPEN,
            long_call_sym,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            short_call_sym,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            short_put_sym,
            amount,
        ).set_duration(
            Duration.DAY
        ).set_session(
            Session.NORMAL
        ).set_price(
            str(price)
        ).set_order_type(
            order_type
        ).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(
            ComplexOrderStrategyType.CUSTOM
        )

        return self._place_order_api(order)

    def check_order_status(self, order_id):
        """Check the status of an order"""
        # Check cache first
        cache_key = str(order_id)
        current_time = time.time()

        if cache_key in self._order_cache:
            cached_time, cached_status = self._order_cache[cache_key]
            if current_time - cached_time < self._cache_expiry:
                return cached_status

        r = self.api.connectClient.get_order(order_id, self._get_account_hash())

        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                notify_exception(e, prefix="get_order")
            raise

        data = r.json()
        if data["status"] == "FILLED":
            notify(f"Check Order details: {data}")
        complex_order_strategy_type = None

        try:
            status = data["status"]
            filled = data["status"] == "FILLED"
            price = data["price"]
            partial_fills = data["filledQuantity"]
            order_type = "CREDIT"
            type_adjusted_price = price

            if data["orderType"] == "NET_DEBIT":
                order_type = "DEBIT"
                type_adjusted_price = -price

            if "complexOrderStrategyType" in data:
                complex_order_strategy_type = data["complexOrderStrategyType"]

        except KeyError:
            return alert.botFailed(None, "Error while checking working order")

        status_result = {
            "status": status,
            "filled": filled,
            "price": price,
            "partialFills": partial_fills,
            "complexOrderStrategyType": complex_order_strategy_type,
            "typeAdjustedPrice": type_adjusted_price,
            "orderType": order_type,
        }

        # Cache the result
        self._order_cache[cache_key] = (current_time, status_result)

        return status_result

    def cancel_order(self, order_id):
        """Cancel an order"""
        r = self.api.connectClient.cancel_order(order_id, self._get_account_hash())

        # throws error if cant cancel (code 400 - 404)
        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                notify_exception(e, prefix="cancel_order")
            raise

    def edit_order_price(self, order_id, new_price):
        """Edit an existing order's limit price"""
        try:
            account_hash = self._get_account_hash()
            # Fetch current order JSON
            r = self.api.connectClient.get_order(order_id, account_hash)
            r.raise_for_status()
            order = r.json()

            # Build a minimal editable spec from existing order
            # Keep only fields Schwab accepts for edit/replace
            legs = []
            for leg in order.get("orderLegCollection", []) or []:
                instr = leg.get("instrument", {})
                symbol = instr.get("symbol")
                qty = leg.get("quantity", 1)
                instruction_str = leg.get("instruction", "BUY_TO_OPEN")
                legs.append({
                    "instruction": instruction_str,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": instr.get("assetType", "OPTION")
                    },
                    "quantity": qty,
                })

            order_type_str = order.get("orderType", "NET_DEBIT")
            duration = order.get("duration", "DAY")
            session = order.get("session", "NORMAL")
            complex_type = order.get("complexOrderStrategyType")

            order_spec = {
                "orderType": order_type_str,
                "session": session,
                "price": str(abs(new_price)),
                "duration": duration,
                "orderStrategyType": order.get("orderStrategyType", "SINGLE"),
                "orderLegCollection": legs,
            }
            if complex_type:
                order_spec["complexOrderStrategyType"] = complex_type

            # Try explicit replace/edit methods if exposed by client
            replace_fn = getattr(self.api.connectClient, "replace_order", None)
            edit_fn = getattr(self.api.connectClient, "edit_order", None)

            if replace_fn is not None:
                if not debugCanSendOrders:
                    notify("Replace (debug): " + str(order_spec))
                    return None
                r2 = replace_fn(account_hash, order_id, order_spec)
                # Some implementations return 200/201 with body
                try:
                    from schwab.utils import Utils
                    new_order_id = Utils(self.api.connectClient, account_hash).extract_order_id(r2)
                except Exception:
                    new_order_id = order_id
                return new_order_id
            if edit_fn is not None:
                if not debugCanSendOrders:
                    notify("Edit (debug): " + str(order_spec))
                    return None
                r2 = edit_fn(account_hash, order_id, order_spec)
                try:
                    from schwab.utils import Utils
                    new_order_id = Utils(self.api.connectClient, account_hash).extract_order_id(r2)
                except Exception:
                    new_order_id = order_id
                return new_order_id

            # Fallback: cancel-and-place using existing helper
            try:
                # Attempt cancel
                self.cancel_order(order_id)
            except Exception as e:
                logger.warning(f"editOrderPrice cancel fallback failed: {e}")

            # Rebuild a replacement order from legs
            ob = OrderBuilder()
            order_type_str = order.get("orderType", "NET_DEBIT")
            order_type_enum = getattr(OrderType, order_type_str, OrderType.NET_DEBIT)
            legs = order.get("orderLegCollection", [])
            for leg in legs:
                instr = leg.get("instrument", {})
                symbol = instr.get("symbol")
                qty = leg.get("quantity", 1)
                instruction_str = leg.get("instruction", "BUY_TO_OPEN")
                try:
                    instruction_enum = getattr(OptionInstruction, instruction_str)
                except Exception:
                    instruction_enum = OptionInstruction.BUY_TO_OPEN if instruction_str.upper().startswith("BUY") else OptionInstruction.SELL_TO_OPEN
                ob.add_option_leg(instruction_enum, symbol, qty)

            ob.set_duration(Duration.DAY)
            ob.set_session(Session.NORMAL)
            ob.set_price(str(abs(new_price)))
            ob.set_order_type(order_type_enum)
            ob.set_order_strategy_type(OrderStrategyType.SINGLE)
            co = order.get("complexOrderStrategyType")
            if co:
                try:
                    co_enum = getattr(ComplexOrderStrategyType, co)
                    ob.set_complex_order_strategy_type(co_enum)
                except Exception:
                    pass

            if not debugCanSendOrders:
                notify("Replacement order (debug): " + str(ob.build()))
                return None
            r3 = self.api.connectClient.place_order(account_hash, ob)
            from schwab.utils import Utils
            new_order_id = Utils(self.api.connectClient, account_hash).extract_order_id(r3)
            return new_order_id
        except Exception as e:
            logger.error(f"Error editing order {order_id}: {e}")
            return None

    def place_order_with_improvement(self, order_func, order_params, price):
        """
        Place an order with automatic price improvements if not filled
        """
        max_retries = 75
        fixed_step = 0.05  # fixed $0.05 step per retry
        initial_price = price

        now = datetime.datetime.now(get_localzone())
        if now.time() >= datetime.time(15, 30):  # After 3:30 PM
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
                    notify(f"Attempt {retry + 1}/{max_retries}")
                    notify(f"Improving price by +${retry * fixed_step:.2f} to {current_price}")
                else:
                    notify(f"Attempt {retry + 1}/{max_retries}")
                    notify(f"Improving price by -${retry * fixed_step:.2f} to {current_price}")

            try:
                # Call order function with params and explicit price kwarg
                order_id = order_func(*order_params, price=current_price)

                if not order_id:
                    notify("Failed to place order", level="error")
                    return False

                # Monitor order with longer timeout
                result = self.monitor_order(order_id, timeout=order_timeout)

                if result == True:  # Order filled
                    return True
                elif result == "cancelled":  # User cancelled
                    return False
                elif result == "timeout":  # Timeout - try price improvement
                    try:
                        self.cancel_order(order_id)
                        continue
                    except Exception as e:
                        notify_exception(e, prefix="Error cancelling order")
                        return False
                else:  # Other failure
                    return False

            except Exception as e:
                notify_exception(e, prefix="Error during order placement")
                return False

        notify("Failed to fill order after all price improvement attempts", level="warning")
        return False

    def monitor_order(self, order_id, timeout=60):
        """Monitor order status and handle cancellation with dynamic display"""
        global cancel_order

        start_time = time.time()
        last_status_check = 0
        next_log_time = 0  # throttle UI log updates

        while time.time() - start_time < timeout:
            current_time = time.time()
            elapsed_time = int(current_time - start_time)

            # Check for user cancellation
            if cancel_order:
                try:
                    self.cancel_order(order_id)
                    notify("Cancelling order...")
                    return "cancelled"
                except Exception as e:
                    notify_exception(e, prefix="Error cancelling order")
                    return False

            try:
                if current_time - last_status_check >= 1:  # Check every second
                    order_status = self.check_order_status(order_id)
                    last_status_check = current_time

                    if current_time >= next_log_time:
                        remaining = int(timeout - elapsed_time)
                        status_str = order_status.get('status', 'N/A')
                        rejection_reason = order_status.get('rejection_reason', '')
                        price = order_status.get('price', 'N/A')
                        filled = order_status.get('filledQuantity', '0')
                        msg = f"Status: {status_str} {rejection_reason} | Remaining: {remaining}s | Price: {price} | Filled: {filled}"
                        notify(msg)
                        next_log_time = current_time + 5  # log every 5s

                    if order_status["filled"]:
                        notify("Order filled successfully!")
                        # Notify about order filled
                        try:
                            alert.alert(None, f"Order {order_id} filled successfully!")
                        except Exception:
                            pass
                        return True
                    elif order_status["status"] == "REJECTED":
                        notify("Order rejected: " + order_status.get('rejection_reason', 'No reason provided'))
                        return "rejected"
                    elif order_status["status"] == "CANCELED":
                        notify("Order cancelled.")
                        return False

                time.sleep(0.1)  # Small sleep to prevent CPU thrashing

            except Exception as e:
                notify_exception(e, prefix="Error checking order status")
                return False

        # If we reach here, order timed out
        notify("Order timed out, moving to price improvement...")
        try:
            self.cancel_order(order_id)
        except:
            pass
        return "timeout"