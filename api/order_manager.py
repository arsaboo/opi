import time
import datetime
from tzlocal import get_localzone
from configuration import debugCanSendOrders
from status import notify, notify_exception
from logger_config import get_logger
from schwab.orders.options import OptionSymbol
from schwab.orders.generic import OrderBuilder
from schwab.orders.common import (
    Duration,
    Session,
    OrderType,
    OrderStrategyType,
    ComplexOrderStrategyType,
    OptionInstruction,
)
import alert

from core.common import round_to_nearest_five_cents

# Global flag for order cancellation
cancel_order = False

logger = get_logger()


def handle_cancel(e):
    global cancel_order
    if e.name == "c":
        cancel_order = True


def reset_cancel_flag():
    global cancel_order
    cancel_order = False


class OrderManager:
    def __init__(self, api_client):
        self.api = api_client
        self._order_cache: dict[str, tuple[float, dict]] = {}
        self._cache_expiry = 1  # seconds

    def _round_price_for_symbol(self, symbol: str, price: float) -> float:
        """Round limit price to a valid tick size for the underlying.

        - SPX/SPXW index options commonly use $0.05 ticks.
        - ETF/equity options like SPY/QQQ use $0.01 ticks.
        """
        try:
            sym = symbol[1:] if symbol and symbol.startswith("$") else symbol
            u = str(sym).upper() if sym else ""
            tick = 0.05 if u in {"SPX", "SPXW"} else 0.01
            # Round to nearest tick, then to 2 decimals for API
            return round(round(float(price) / tick) * tick, 2)
        except Exception:
            try:
                return round(float(price), 2)
            except Exception:
                return price

    def _get_account_hash(self):
        return self.api.getAccountHash()

    def _place_order_api(self, order_spec):
        if not debugCanSendOrders:
            notify(str(order_spec.build()))
            return None

        r = self.api.connectClient.place_order(self._get_account_hash(), order_spec)

        from schwab.utils import Utils

        order_id = Utils(self.api.connectClient, self._get_account_hash()).extract_order_id(r)
        assert order_id is not None

        # Friendly alert (best-effort)
        try:
            od = order_spec.build()
            price = None
            for k in ("price", "orderPrice", "limitPrice"):
                try:
                    v = od.get(k)
                    if v is not None:
                        price = f"${float(v):.2f}"
                        break
                except Exception:
                    pass
            legs = od.get("orderLegCollection", []) or []
            qty = legs[0].get("quantity") if legs else "?"
            instr = (legs[0].get("instrument") or {}) if legs else {}
            sym = instr.get("symbol") or instr.get("underlyingSymbol") or instr.get("cusip") or "?"
            alert.alert(None, f"Order placed successfully for {sym} (Quantity: {qty}, Price: {price}, ID: {order_id})")
        except Exception:
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
        """Send an order for writing new contracts or rolling existing ones."""
        if old_symbol is None:
            price = new_credit
            if full_price_percentage == 100:
                price = round(price, 2)
            else:
                price = round(price * (full_price_percentage / 100), 2)

            # Normalize tick for the new symbol's underlying
            try:
                base_sym = (new_symbol or "").split()[0]
            except Exception:
                base_sym = ""
            norm_price = self._round_price_for_symbol(base_sym, price)
            order = (
                self.api.connectClient.options.option_sell_to_open_limit(new_symbol, new_amount, norm_price)
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
                price = -(old_debit * old_amount - new_credit * new_amount)
            else:
                price = -(old_debit - new_credit)

            if full_price_percentage == 100:
                price = round(price, 2)
            else:
                if price < 100:
                    price = round(price - ((100 - full_price_percentage) * 0.01), 2)
                else:
                    price = round(price * (full_price_percentage / 100), 2)

            order = OrderBuilder()

            order_type = OrderType.NET_CREDIT
            if price < 0:
                price = -price
                order_type = OrderType.NET_DEBIT

            # Normalize tick based on new leg underlying
            try:
                base_sym = (new_symbol or "").split()[0]
            except Exception:
                base_sym = ""
            norm_price = self._round_price_for_symbol(base_sym, price)
            order.add_option_leg(
                OptionInstruction.BUY_TO_CLOSE,
                old_symbol,
                old_amount,
            ).add_option_leg(
                OptionInstruction.SELL_TO_OPEN,
                new_symbol,
                new_amount,
            ).set_duration(Duration.DAY).set_session(Session.NORMAL).set_price(norm_price).set_order_type(order_type).set_order_strategy_type(
                OrderStrategyType.SINGLE
            )

        return self._place_order_api(order)

    def roll_over(self, old_symbol, new_symbol, amount, price):
        order = OrderBuilder()
        order_type = OrderType.NET_CREDIT
        if price < 0:
            price = -price
            order_type = OrderType.NET_DEBIT

        # Normalize price based on new_symbol underlying
        try:
            base_sym = (new_symbol or "").split()[0]
        except Exception:
            base_sym = ""
        norm_price = self._round_price_for_symbol(base_sym, price)
        order.add_option_leg(
            OptionInstruction.BUY_TO_CLOSE,
            old_symbol,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            new_symbol,
            amount,
        ).set_duration(Duration.DAY).set_session(Session.NORMAL).set_price(str(norm_price)).set_order_type(order_type).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(ComplexOrderStrategyType.DIAGONAL)

        return self._place_order_api(order)

    def vertical_call_order(self, symbol, expiration, strike_low, strike_high, amount, *, price):
        if "$" in symbol:
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = OrderBuilder()
        order_type = OrderType.NET_DEBIT
        norm_price = self._round_price_for_symbol(symbol, price)
        order.add_option_leg(
            OptionInstruction.BUY_TO_OPEN,
            long_call_sym,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            short_call_sym,
            amount,
        ).set_duration(Duration.DAY).set_session(Session.NORMAL).set_price(str(norm_price)).set_order_type(order_type).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(ComplexOrderStrategyType.VERTICAL)

        return self._place_order_api(order)

    def synthetic_covered_call_order(self, symbol, expiration, strike_low, strike_high, amount, *, price):
        if "$" in symbol:
            symbol = symbol[1:]
        long_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_low)).build()
        short_put_sym = OptionSymbol(symbol, expiration, "P", str(strike_low)).build()
        short_call_sym = OptionSymbol(symbol, expiration, "C", str(strike_high)).build()

        order = OrderBuilder()
        order_type = OrderType.NET_DEBIT
        # Ensure price adheres to symbol tick size (avoid 3-decimal rejections)
        norm_price = self._round_price_for_symbol(symbol, price)
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
        ).set_duration(Duration.DAY).set_session(Session.NORMAL).set_price(str(norm_price)).set_order_type(order_type).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(ComplexOrderStrategyType.CUSTOM)

        return self._place_order_api(order)

    def sell_box_spread_order(
        self,
        low_call_symbol: str,
        high_call_symbol: str,
        low_put_symbol: str,
        high_put_symbol: str,
        amount: int,
        *,
        price: float,
    ):
        """Create a 4-leg SELL box spread order (borrow now, repay at expiry)."""
        order = OrderBuilder()
        order_type = OrderType.NET_CREDIT
        # Infer underlying from first leg for tick rounding
        try:
            base_sym = (low_call_symbol or high_call_symbol or low_put_symbol or high_put_symbol or "").split()[0]
        except Exception:
            base_sym = ""
        norm_price = self._round_price_for_symbol(base_sym, price)
        order.add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            low_call_symbol,
            amount,
        ).add_option_leg(
            OptionInstruction.BUY_TO_OPEN,
            high_call_symbol,
            amount,
        ).add_option_leg(
            OptionInstruction.SELL_TO_OPEN,
            high_put_symbol,
            amount,
        ).add_option_leg(
            OptionInstruction.BUY_TO_OPEN,
            low_put_symbol,
            amount,
        ).set_duration(Duration.DAY).set_session(Session.NORMAL).set_price(str(norm_price)).set_order_type(order_type).set_order_strategy_type(
            OrderStrategyType.SINGLE
        ).set_complex_order_strategy_type(ComplexOrderStrategyType.CUSTOM)

        return self._place_order_api(order)

    def check_order_status(self, order_id):
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
        if data.get("status") == "FILLED":
            notify(f"Check Order details: {data}")

        try:
            status = data["status"]
            filled = data["status"] == "FILLED"
            price = data.get("price")
            partial_fills = data.get("filledQuantity")
            order_type = "CREDIT"
            type_adjusted_price = price
            if data.get("orderType") == "NET_DEBIT":
                order_type = "DEBIT"
                try:
                    type_adjusted_price = -price if price is not None else price
                except Exception:
                    type_adjusted_price = price
            complex_order_strategy_type = data.get("complexOrderStrategyType")
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
        self._order_cache[cache_key] = (current_time, status_result)
        return status_result

    def cancel_order(self, order_id):
        r = self.api.connectClient.cancel_order(order_id, self._get_account_hash())
        if r.status_code != 200:
            try:
                r.raise_for_status()
            except Exception as e:
                notify_exception(e, prefix="cancel_order")
            raise

    def edit_order_price(self, order_id, new_price):
        try:
            account_hash = self._get_account_hash()
            r = self.api.connectClient.get_order(order_id, account_hash)
            r.raise_for_status()
            order = r.json()

            legs = []
            for leg in order.get("orderLegCollection", []) or []:
                instr = leg.get("instrument", {})
                symbol = instr.get("symbol")
                qty = leg.get("quantity", 1)
                instruction_str = leg.get("instruction", "BUY_TO_OPEN")
                legs.append(
                    {
                        "instruction": instruction_str,
                        "instrument": {"symbol": symbol, "assetType": instr.get("assetType", "OPTION")},
                        "quantity": qty,
                    }
                )

            order_type_str = order.get("orderType", "NET_DEBIT")
            duration = order.get("duration", "DAY")
            session = order.get("session", "NORMAL")
            complex_type = order.get("complexOrderStrategyType")

            # Determine an underlying-like symbol for tick rounding from first leg symbol
            base_sym_for_tick = None
            try:
                if legs:
                    leg_sym = legs[0].get("instrument", {}).get("symbol")
                    if isinstance(leg_sym, str) and leg_sym:
                        base_sym_for_tick = leg_sym.split()[0]
            except Exception:
                base_sym_for_tick = None

            rounded_price = self._round_price_for_symbol(base_sym_for_tick or "", new_price)

            order_spec = {
                "orderType": order_type_str,
                "session": session,
                "price": str(abs(rounded_price)),
                "duration": duration,
                "orderStrategyType": order.get("orderStrategyType", "SINGLE"),
                "orderLegCollection": legs,
            }
            if complex_type:
                order_spec["complexOrderStrategyType"] = complex_type

            replace_fn = getattr(self.api.connectClient, "replace_order", None)
            edit_fn = getattr(self.api.connectClient, "edit_order", None)

            if replace_fn is not None:
                if not debugCanSendOrders:
                    notify("Replace (debug): " + str(order_spec))
                    return None
                r2 = replace_fn(account_hash, order_id, order_spec)
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

            try:
                self.cancel_order(order_id)
            except Exception as e:
                logger.warning(f"editOrderPrice cancel fallback failed: {e}")

            ob = OrderBuilder()
            order_type_enum = getattr(OrderType, order_type_str, OrderType.NET_DEBIT)
            for leg in legs:
                instr = leg.get("instrument", {})
                symbol = instr.get("symbol")
                qty = leg.get("quantity", 1)
                instruction_str = leg.get("instruction", "BUY_TO_OPEN")
                try:
                    instruction_enum = getattr(OptionInstruction, instruction_str)
                except Exception:
                    instruction_enum = (
                        OptionInstruction.BUY_TO_OPEN if instruction_str.upper().startswith("BUY") else OptionInstruction.SELL_TO_OPEN
                    )
                ob.add_option_leg(instruction_enum, symbol, qty)

            ob.set_duration(Duration.DAY)
            ob.set_session(Session.NORMAL)
            ob.set_price(str(abs(rounded_price)))
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
        max_retries = 75
        initial_price = price

        def _infer_base_symbol_and_tick() -> tuple[str | None, float]:
            try:
                name = getattr(order_func, "__name__", "") or ""
            except Exception:
                name = ""
            base = None
            try:
                if name in {"rollOver", "roll_over"} and len(order_params) >= 2:
                    base = (order_params[1] or "").split()[0]
                elif name in {"vertical_call_order", "synthetic_covered_call_order"} and len(order_params) >= 1:
                    base = (order_params[0] or "").split()[0]
                elif name in {"sell_box_spread_order"} and len(order_params) >= 1:
                    base = (order_params[0] or "").split()[0]
                else:
                    # Fallback: first string-like param
                    for p in order_params:
                        if isinstance(p, str) and p:
                            base = p.split()[0]
                            break
            except Exception:
                base = None
            u = (str(base).lstrip("$").upper()) if base else ""
            tick = 0.05 if u in {"SPX", "SPXW"} else 0.01
            return base, tick

        base_symbol, tick_size = _infer_base_symbol_and_tick()

        now = datetime.datetime.now(get_localzone())
        if now.time() >= datetime.time(15, 30):
            order_timeout = 15
        else:
            order_timeout = 60

        is_debit_order = price > 0

        for retry in range(max_retries):
            if is_debit_order:
                current_price = self._round_price_for_symbol(base_symbol or "", initial_price + retry * tick_size)
            else:
                current_price = self._round_price_for_symbol(base_symbol or "", initial_price - retry * tick_size)

            if retry > 0:
                if is_debit_order:
                    notify(f"Attempt {retry + 1}/{max_retries}")
                    notify(f"Improving price by +${retry * tick_size:.2f} to {current_price}")
                else:
                    notify(f"Attempt {retry + 1}/{max_retries}")
                    notify(f"Improving price by -${retry * tick_size:.2f} to {current_price}")

            try:
                order_id = order_func(*order_params, price=current_price)

                if not order_id:
                    notify("Failed to place order", level="error")
                    return False

                result = self.monitor_order(order_id, timeout=order_timeout)

                if result is True:
                    return True
                elif result == "cancelled":
                    return False
                elif result == "timeout":
                    try:
                        self.cancel_order(order_id)
                    except Exception as e:
                        notify_exception(e, prefix="Error cancelling order (continuing with next price improvement)")
                    continue
                else:
                    return False

            except Exception as e:
                notify_exception(e, prefix="Error during order placement")
                return False

        notify("Failed to fill order after all price improvement attempts", level="warning")
        return False

    def monitor_order(self, order_id, timeout=60):
        global cancel_order

        start_time = time.time()
        last_status_check = 0
        next_log_time = 0

        while time.time() - start_time < timeout:
            current_time = time.time()
            elapsed_time = int(current_time - start_time)

            if cancel_order:
                try:
                    self.cancel_order(order_id)
                    notify("Cancelling order...")
                    return "cancelled"
                except Exception as e:
                    notify_exception(e, prefix="Error cancelling order")
                    return False

            try:
                if current_time - last_status_check >= 1:
                    order_status = self.check_order_status(order_id)
                    last_status_check = current_time

                    if current_time >= next_log_time:
                        remaining = int(timeout - elapsed_time)
                        status_str = order_status.get("status", "N/A")
                        rejection_reason = order_status.get("rejection_reason", "")
                        price = order_status.get("price", "N/A")
                        filled = order_status.get("filledQuantity", "0")
                        msg = f"Status: {status_str} {rejection_reason} | Remaining: {remaining}s | Price: {price} | Filled: {filled}"
                        notify(msg)
                        next_log_time = current_time + 5

                    if order_status["filled"]:
                        notify("Order filled successfully!")
                        try:
                            alert.alert(None, f"Order {order_id} filled successfully!")
                        except Exception:
                            pass
                        return True
                    elif order_status["status"] == "REJECTED":
                        notify("Order rejected: " + order_status.get("rejection_reason", "No reason provided"))
                        return "rejected"
                    elif order_status["status"] == "CANCELED":
                        notify("Order cancelled.")
                        return False

                time.sleep(0.1)

            except Exception as e:
                notify_exception(e, prefix="Error checking order status")
                return False

        notify("Order timed out, moving to price improvement...")
        try:
            self.cancel_order(order_id)
        except Exception:
            pass
        return "timeout"
