import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time as time_module

import keyboard
from colorama import Fore, Style
from prettytable import PrettyTable
from tzlocal import get_localzone

import alert
from configuration import configuration, spreads
from config_helper import get_asset_config_safe
from logger_config_quiet import get_logger
from margin_utils import (
    calculate_annualized_return_on_margin,
    calculate_margin_requirement,
    calculate_short_option_rom,
)
from optionChain import OptionChain
from support import calculate_cagr
from order_utils import monitor_order, handle_cancel, cancel_order

logger = get_logger()

class Cc:
    def __init__(self, asset):
        self.asset = asset

    def find_new_contract(self, api, existing):
        # check if asset is in configuration
        if self.asset not in configuration:
            print(f"Configuration for {self.asset} not found")
            return None
        days = configuration[self.asset]["maxRollOutWindow"]
        toDate = datetime.today() + timedelta(days=days)
        option_chain = OptionChain(api, self.asset, toDate, days)
        chain = option_chain.get()
        roll = find_best_rollover(api, chain, existing)
        if roll is None:
            alert.botFailed(self.asset, "No rollover contract found")
            return None
        return roll

def _calculate_roll_metrics(api, short, chain, roll):
    """Calculate common metrics for rolling options"""
    # Get current position details
    prem_short_contract = get_median_price(short["optionSymbol"], chain)
    if prem_short_contract is None:
        print("Short contract not found in chain")
        return None

    # Get underlying price and calculate position metrics
    underlying_price = api.getATMPrice(short["stockSymbol"])
    short_strike = float(short["strike"])
    short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
    days_to_expiry = (short_expiration - datetime.now().date()).days

    # Get delta (different approach for SPX vs other assets)
    if short["stockSymbol"] == "$SPX":
        short_delta = get_option_delta(short["optionSymbol"], chain)
    else:
        option_details = api.getOptionDetails(short["optionSymbol"])
        if option_details is None:
            print("Could not get option details for short position")
            return None
        short_delta = option_details["delta"]

    # Determine position status
    value = round(short_strike - underlying_price, 2)
    if value > 0:
        position_status = f"{Fore.GREEN}OTM{Style.RESET_ALL}"
    elif value < 0:
        config = configuration[short["stockSymbol"]]
        if abs(value) > config.get("deepITMLimit", 50):
            position_status = f"{Fore.RED}Deep ITM{Style.RESET_ALL}"
        elif abs(value) > config.get("ITMLimit", 25):
            position_status = f"{Fore.YELLOW}ITM{Style.RESET_ALL}"
        else:
            position_status = f"{Fore.GREEN}Just ITM{Style.RESET_ALL}"
    else:
        position_status = "ATM"

    # Calculate roll metrics
    roll_premium = get_median_price(roll["symbol"], chain)
    if roll_premium is None:
        print("Roll contract not found in chain")
        return None

    credit = round(roll_premium - prem_short_contract, 2)
    credit_percent = (credit / underlying_price) * 100
    ret = api.getOptionDetails(roll["symbol"])
    if ret is None:
        print("Could not get option details for roll contract")
        return None

    ret_expiration = datetime.strptime(ret["expiration"], "%Y-%m-%d").date()
    roll_out_time = ret_expiration - short_expiration
    new_strike = float(roll["strike"])
    strike_improvement = new_strike - short_strike
    strike_improvement_percent = (strike_improvement / short_strike) * 100

    # Calculate annualized return
    days_to_new_expiry = (ret_expiration - datetime.now().date()).days
    if days_to_new_expiry > 0:
        annualized_return = (credit / underlying_price) * (365 / days_to_new_expiry) * 100
    else:
        annualized_return = 0

    # Calculate margin requirement and return on margin for new position
    otm_amount = max(0, new_strike - underlying_price)
    margin_req = calculate_margin_requirement(
        short["stockSymbol"],
        'naked_call',
        underlying_value=underlying_price,
        otm_amount=otm_amount,
        premium=roll_premium
    )

    # Calculate return on margin
    profit = roll_premium * 100  # Convert to dollar amount
    rom = calculate_annualized_return_on_margin(profit, margin_req, days_to_new_expiry)

    # Calculate break-even
    break_even = new_strike - credit

    return {
        "short_strike": short_strike,
        "days_to_expiry": days_to_expiry,
        "short_delta": short_delta,
        "position_status": position_status,
        "underlying_price": underlying_price,
        "roll_premium": roll_premium,
        "credit": credit,
        "credit_percent": credit_percent,
        "ret": ret,
        "ret_expiration": ret_expiration,
        "roll_out_time": roll_out_time,
        "new_strike": new_strike,
        "strike_improvement": strike_improvement,
        "strike_improvement_percent": strike_improvement_percent,
        "annualized_return": annualized_return,
        "margin_req": margin_req,
        "rom": rom,
        "break_even": break_even
    }

def _display_roll_results(short, metrics):
    """Display roll results in a formatted table"""
    # Create combined table
    table = PrettyTable()
    table.field_names = [
        "Current Strike",
        "Current DTE",
        "Current Delta",
        "Status",
        "New Strike",
        "Strike Improvement",
        "Credit",
        "Credit %",
        "Roll Duration",
        "New Delta",
        "Delta Change",
        "Break-even",
        "Ann. Return",
        "Ann. ROM %"
    ]
    table.add_row([
        metrics["short_strike"],
        metrics["days_to_expiry"],
        f"{metrics['short_delta']:.3f}",
        metrics["position_status"],
        metrics["new_strike"],
        f"{metrics['strike_improvement']:+.1f} ({metrics['strike_improvement_percent']:+.1f}%)",
        f"${metrics['credit']:+.2f}",
        f"{metrics['credit_percent']:+.2f}%",
        f"{metrics['roll_out_time'].days} days",
        f"{metrics['ret']['delta']:.3f}",
        f"{metrics['ret']['delta'] - metrics['short_delta']:+.3f}",
        round(metrics["break_even"], 2),
        f"{metrics['annualized_return']:.1f}%",
        f"{metrics['rom']:.1f}%"
    ])

    print(f"Underlying Price: {round(metrics['underlying_price'], 2)}")
    print("\n" + str(table))

def RollCalls(api, short):
    try:
        if short["stockSymbol"] not in configuration:
            print(f"Configuration for {short['stockSymbol']} not found")
            return False

        days = configuration[short["stockSymbol"]]["maxRollOutWindow"]
        short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
        toDate = short_expiration + timedelta(days=days)
        optionChain = OptionChain(api, short["stockSymbol"], toDate, days)
        chain = optionChain.get()

        # Find roll opportunity
        roll = find_best_rollover(api, chain, short)
        if roll is None:
            print("No rollover contract found")
            return False

        # Calculate metrics
        metrics = _calculate_roll_metrics(api, short, chain, roll)
        if metrics is None:
            print("Failed to calculate roll metrics")
            return False

        # Display results
        _display_roll_results(short, metrics)

        # Execute the roll
        print("Proceeding with roll automatically (Textual UI only, no CLI prompt)...")
        result = roll_contract(api, short, roll, round(metrics["credit"], 2))
        return result

    except Exception as e:
        print(f"Error in RollCalls: {str(e)}")
        logger.error(f"Error in RollCalls: {e}")
        return False

def RollSPX(api, short):
    """SPX uses the same logic as RollCalls now"""
    return RollCalls(api, short)

def roll_contract(api, short, roll, order_premium):
    """Execute roll order with improved monitoring and cancellation"""
    global cancel_order

    # Clean up any existing hooks and reset flag
    keyboard.unhook_all()
    cancel_order = False

    # Get expiration date from roll contract with fallback handling
    try:
        if 'expiration' in roll:
            roll_expiration = roll['expiration']
        else:
            roll_expiration = api.getOptionDetails(roll['symbol'])['expiration']
    except:
        roll_expiration = roll['date']

    # Print detailed order information
    print("\nOrder Details:")
    print(f"Asset: {short['stockSymbol']}")
    print(f"Current Position: Short Call @ {short['strike']} expiring {short['expiration']}")
    print(f"Rolling to: Short Call @ {roll['strike']} expiring {roll_expiration}")
    print(f"Net Credit: ${order_premium}")
    print(f"Strategy: Roll Short Call")

    # Setup keyboard listener for cancellation
    keyboard.on_press_key('c', handle_cancel)

    try:
        print("\nPlacing order with automatic price improvements...")
        result = None
        initial_premium = order_premium

        # Try prices in sequence, starting with original price
        for i in range(0, 76):  # 0 = original price, 1-75 = improvements
            if cancel_order:
                print("\nOperation cancelled by user")
                break

            current_premium = (
                initial_premium if i == 0
                else round_to_nearest_five_cents(initial_premium * (1 - (i/100)))
            )

            if i > 0:
                print(f"\nTrying new price: ${current_premium} (improvement #{i})")

            # Place new order
            roll_order_id = api.rollOver(
                short["optionSymbol"],
                roll["symbol"],
                short["count"],
                current_premium
            )

            # Cancel any existing order before placing new one
            try:
                if i > 0:  # Don't need to cancel before first order
                    api.cancelOrder(roll_order_id)
                    time.sleep(1)  # Brief pause between orders
            except:
                pass

            result = monitor_order(api, roll_order_id, timeout=60)
            if result is True or result == "cancelled":
                break

    finally:
        keyboard.unhook_all()
        cancel_order = False  # Reset flag on exit

    return result is True

def find_best_rollover(api, data, short_option):
    """
    Main roll analysis function that ALWAYS returns current position data
    """
    try:
        # FIRST: Always extract current position details
        asset_symbol = short_option["stockSymbol"]

        # Get current position info using multiple fallback methods
        current_info = extract_current_position_info(short_option, api, data)

        # Ensure we have at least basic current position data
        if current_info["current_strike"] is None:
            try:
                current_info["current_strike"] = float(short_option.get("strike", 0))
            except (ValueError, TypeError):
                current_info["current_strike"] = 0

        if current_info["current_expiration"] is None:
            current_info["current_expiration"] = short_option.get("expiration", "Unknown")

        # Create result structure that always includes current position
        result = {
            "asset": asset_symbol,
            "current_strike": current_info["current_strike"],
            "current_expiration": current_info["current_expiration"],
            "current_price": current_info["current_price"],
            "underlying_price": current_info["underlying_price"],
            "roll_available": False,
            "no_roll_reason": "Unknown"
        }

        print(f"DEBUG: Current position for {asset_symbol} - Strike: {result['current_strike']}, Exp: {result['current_expiration']}")
        logger.info(f"Current position for {asset_symbol} - Strike: {result['current_strike']}, Exp: {result['current_expiration']}")

        # Continue with roll analysis only if we have the necessary data
        short_strike = current_info["current_strike"]
        short_price = current_info["current_price"]
        underlying_price = current_info["underlying_price"]

        # Parse expiration
        if current_info["current_expiration"]:
            try:
                short_expiry = datetime.strptime(current_info["current_expiration"], "%Y-%m-%d")
            except ValueError:
                print(f"WARNING: Could not parse expiration date: {current_info['current_expiration']}")
                result["no_roll_reason"] = "Invalid expiration date format"
                return result
        else:
            result["no_roll_reason"] = "Missing expiration date"
            return result

        # If we don't have price info, we can't find rolls but still return current info
        if short_price is None or underlying_price is None:
            result["no_roll_reason"] = "Missing price information"
            return result

        # Get configuration safely for roll analysis
        asset_config = get_asset_config_safe(asset_symbol, configuration)

        # Add timing variables for compatibility
        start_time = time.time()
        timeout_seconds = 60

        # Configuration variables with safe defaults
        ITMLimit = asset_config.get("ITMLimit", 10)
        deepITMLimit = asset_config.get("deepITMLimit", 25)
        deepOTMLimit = asset_config.get("deepOTMLimit", 10)
        minPremium = asset_config.get("minPremium", 1)
        idealPremium = asset_config.get("idealPremium", 15)
        minRollupGap = asset_config.get("minRollupGap", 5)
        maxRollOutWindow = asset_config.get("maxRollOutWindow", 30)
        minRollOutWindow = asset_config.get("minRollOutWindow", 7)

        # Determine the short status
        short_status = None
        if short_strike > underlying_price + deepOTMLimit:
            short_status = "deep_OTM"
        elif short_strike > underlying_price:
            short_status = "OTM"
        elif short_strike + ITMLimit > underlying_price:
            short_status = "just_ITM"
        elif short_strike + deepITMLimit > underlying_price:
            short_status = "ITM"
        else:
            short_status = "deep_ITM"

        value = round(short_strike - underlying_price, 2)

        # Sort entries based on short status
        if short_status == "deep_ITM":
            entries = sorted(
                data,
                key=lambda entry: (
                    -datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
                    -max(
                        contract["strike"]
                        for contract in entry["contracts"]
                        if "strike" in contract
                    ),
                ),
            )
        else:
            entries = sorted(
                data,
                key=lambda entry: (
                    datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
                    -max(
                        contract["strike"]
                        for contract in entry["contracts"]
                        if "strike" in contract
                    ),
                ),
            )

        # Initialize search variables
        best_option = None
        closest_days_diff = float("inf")
        highest_strike = float("-inf")
        max_attempts = 10
        attempt_count = 0

        logger.info(f"Starting roll analysis for {asset_symbol}")
        logger.info(f"Config for {asset_symbol} - ITM:{ITMLimit}, deepITM:{deepITMLimit}, deepOTM:{deepOTMLimit}")
        logger.info(f"Premium config - min:{minPremium}, ideal:{idealPremium}, rollupGap:{minRollupGap}")
        logger.info(f"Short status: {short_status}, Strike-Underlying: {value}")
        logger.info(f"Starting roll search for {asset_symbol} with {len(entries)} date entries")

        # Iterate to find the best rollover option
        while short_status and best_option is None and attempt_count < max_attempts:
            attempt_count += 1
            print(f"DEBUG: Roll search attempt {attempt_count}/{max_attempts}")

            # Add timeout check
            if time.time() - start_time > timeout_seconds:
                print(f"DEBUG: find_best_rollover timed out after {timeout_seconds} seconds")
                break

            for entry in entries:
                # Add timeout check in inner loop too
                if time.time() - start_time > timeout_seconds:
                    print("DEBUG: find_best_rollover timed out in entry loop")
                    break

                expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
                days_diff = (expiry_date - short_expiry).days
                if days_diff > maxRollOutWindow or days_diff < minRollOutWindow:
                    continue
                for contract in entry["contracts"]:
                    if contract["strike"] <= short_strike:
                        continue
                    if short_option["optionSymbol"].split()[0] == "SPX":
                        if contract["optionRoot"] != "SPXW":
                            continue
                    else:
                        if contract["optionRoot"] != short_option["optionSymbol"].split()[0]:
                            continue
                    contract_price = round(
                        statistics.median([contract["bid"], contract["ask"]]), 2
                    )
                    premium_diff = contract_price - short_price
                    try:
                        logger.debug(
                            f"Contract: {contract['symbol']}, Premium: {contract_price}, Days: {days_diff}, Premium Diff: {premium_diff}, Ideal Premium: {idealPremium}, Strike: {contract['strike']}"
                        )
                    except Exception:
                        pass  # Ignore logger errors
                    if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                        if (
                            contract["strike"] >= short_strike + minRollupGap
                            and premium_diff >= idealPremium
                        ):
                            if days_diff < closest_days_diff:
                                closest_days_diff = days_diff
                                best_option = contract
                                print(f"DEBUG: Found candidate for {short_status}: {contract['symbol']}")

                    elif short_status == "ITM":
                        if (
                            premium_diff >= minPremium
                            and contract["strike"] >= short_strike + minRollupGap
                        ):
                            if contract["strike"] > highest_strike or (
                                contract["strike"] == highest_strike
                                and days_diff < closest_days_diff
                            ):
                                highest_strike = contract["strike"]
                                closest_days_diff = days_diff
                                best_option = contract
                                print(f"DEBUG: Found ITM candidate: {contract['symbol']}")

                    elif short_status == "deep_ITM":
                        # Roll to the highest strike without paying a premium
                        if premium_diff >= 0.1 and contract["strike"] > highest_strike:
                            highest_strike = contract["strike"]
                            closest_days_diff = days_diff
                            best_option = contract
                            print(f"DEBUG: Found deep ITM candidate: {contract['symbol']}")

            # Adjust criteria if no best option found
            if best_option is None:
                try:
                    logger.debug(
                        f"Before adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
                    )
                except Exception:
                    print(f"DEBUG: Before adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}")

                if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                    if idealPremium > minPremium:
                        old_ideal = idealPremium
                        idealPremium = max(idealPremium - 0.5, minPremium)
                        print(f"DEBUG: Lowered ideal premium from {old_ideal} to {idealPremium}")
                    elif minRollupGap > 0:
                        old_gap = minRollupGap
                        minRollupGap = max(minRollupGap - 5, 0)
                        print(f"DEBUG: Lowered rollup gap from {old_gap} to {minRollupGap}")
                    else:
                        # If we can't adjust further, break to prevent infinite loop
                        print("DEBUG: Cannot adjust criteria further, breaking")
                        break
                elif short_status == "ITM":
                    if minRollupGap > 0:
                        old_gap = minRollupGap
                        minRollupGap = max(minRollupGap - 5, 0)
                        print(f"DEBUG: Lowered ITM rollup gap from {old_gap} to {minRollupGap}")
                    elif minPremium > 0:
                        old_min = minPremium
                        minPremium = max(minPremium - 0.25, 0)
                        print(f"DEBUG: Lowered min premium from {old_min} to {minPremium}")
                    else:
                        # If we can't adjust further, break to prevent infinite loop
                        print("DEBUG: Cannot adjust ITM criteria further, breaking")
                        break

                try:
                    logger.debug(
                        f"After adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
                    )
                except Exception:
                    print(f"DEBUG: After adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}")

            # Break if timeout reached
            if time.time() - start_time > timeout_seconds:
                break

        print(f"DEBUG: find_best_rollover completed in {time.time() - start_time:.2f} seconds, {attempt_count} attempts")
        if best_option:
            print(f"DEBUG: Found roll candidate: {best_option['symbol']} at strike {best_option['strike']}")
            # Return the roll option with current position details
            best_option.update({
                "current_strike": short_strike,
                "current_expiration": short_expiry.strftime("%Y-%m-%d") if short_expiry else current_info["current_expiration"],
                "current_price": short_price,
                "underlying_price": underlying_price,
                "roll_available": True
            })
            return best_option
        else:
            print(f"DEBUG: No roll candidate found for {asset_symbol}")
            result["no_roll_reason"] = "No suitable roll opportunities found"
            return result

    except Exception as e:
        print(f"ERROR: Exception in find_best_rollover for {short_option.get('stockSymbol', 'Unknown')}: {e}")
        import traceback
        traceback.print_exc()
        # Return basic info even on exception
        current_info = extract_current_position_info(short_option, api, data)
        return {
            "asset": short_option.get("stockSymbol", "Unknown"),
            "roll_available": False,
            "no_roll_reason": f"Exception: {str(e)}",
            **current_info  # Include all current position info
        }

def parse_option_details(api, data, option_symbol):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == option_symbol:
                short_strike = float(contract["strike"])
                short_price = round(
                    statistics.median([contract["bid"], contract["ask"]]), 2
                )
                short_expiry = datetime.strptime(entry["date"], "%Y-%m-%d")
                if contract["underlying"] == "SPX":
                    ticker = "$SPX"
                else:
                    ticker = contract["underlying"]
                underlying_price = api.getATMPrice(ticker)
                return short_strike, short_price, short_expiry, underlying_price
    return None, None, None, None

def round_to_nearest_five_cents(n):
    return math.ceil(n * 20) / 20

def get_median_price(symbol, data):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                bid = contract["bid"]
                ask = contract["ask"]
                return (bid + ask) / 2
    return None

def get_option_delta(symbol, data):
    for entry in data:
        for contract in entry["contracts"]:
            if contract["symbol"] == symbol:
                return contract["delta"]
    return None

def validate_asset_configuration(asset_symbol):
    """Validate that an asset has all required configuration parameters"""
    try:
        if asset_symbol not in configuration:
            print(f"WARNING: Asset {asset_symbol} not found in configuration")
            return False, f"Asset {asset_symbol} not in configuration"

        asset_config = configuration[asset_symbol]
        if not isinstance(asset_config, dict):
            print(f"WARNING: Configuration for {asset_symbol} is not a dictionary: {type(asset_config)}")
            return False, f"Invalid configuration type for {asset_symbol}"

        # Check for required fields - but don't fail validation, just warn
        required_fields = [
            "minRollupGap", "minStrike", "maxRollOutWindow", "minRollOutWindow",
            "idealPremium", "minPremium", "ITMLimit", "deepITMLimit", "deepOTMLimit"
        ]

        missing_fields = []
        for field in required_fields:
            if field not in asset_config:
                missing_fields.append(field)

        if missing_fields:
            print(f"WARNING: Missing configuration fields for {asset_symbol}: {missing_fields}")
            # Don't fail validation - we can use defaults

        print(f"DEBUG: Configuration validation passed for {asset_symbol}")
        return True, "Configuration valid"

    except Exception as e:
        error_msg = f"Error validating configuration for {asset_symbol}: {str(e)}"
        print(f"ERROR: {error_msg}")
        return False, error_msg

def extract_current_position_info(short_option, api=None, data=None):
    """
    Extract current position information with multiple fallback strategies

    Args:
        short_option: The short option dictionary
        api: API instance (optional)
        data: Option chain data (optional)

    Returns:
        Dictionary with current position info
    """
    current_info = {
        "current_strike": None,
        "current_expiration": None,
        "current_price": None,
        "underlying_price": None
    }

    try:
        # Method 1: Try to parse from option chain data if available
        if api and data:
            short_strike, short_price, short_expiry, underlying_price = parse_option_details(
                api, data, short_option["optionSymbol"]
            )
            if short_strike is not None:
                current_info["current_strike"] = short_strike
                current_info["current_expiration"] = short_expiry.strftime("%Y-%m-%d") if short_expiry else None
                current_info["current_price"] = short_price
                current_info["underlying_price"] = underlying_price
                return current_info
    except Exception as e:
        print(f"DEBUG: Could not parse from option chain: {e}")

    # Method 2: Extract from short_option dictionary (always available)
    try:
        if "strike" in short_option and short_option["strike"]:
            current_info["current_strike"] = float(short_option["strike"])
    except (ValueError, TypeError):
        print(f"DEBUG: Could not parse strike from short_option: {short_option.get('strike')}")

    try:
        if "expiration" in short_option and short_option["expiration"]:
            current_info["current_expiration"] = short_option["expiration"]
    except Exception:
        print(f"DEBUG: Could not parse expiration from short_option: {short_option.get('expiration')}")

    # Method 3: Try to get underlying price from API if available
    try:
        if api and "stockSymbol" in short_option:
            underlying_price = api.getATMPrice(short_option["stockSymbol"])
            if underlying_price:
                current_info["underlying_price"] = underlying_price
    except Exception as e:
        print(f"DEBUG: Could not get underlying price: {e}")

    return current_info

def get_roll_analysis_with_current_data(api, short_option):
    """
    Wrapper function that ensures current position data is always returned
    This function guarantees that current_strike and current_expiration are populated
    """
    try:
        # Get option chain data for analysis
        asset_symbol = short_option["stockSymbol"]

        # Get configuration safely
        asset_config = get_asset_config_safe(asset_symbol, configuration)
        days = asset_config.get("maxRollOutWindow", 30)

        # Parse expiration date
        try:
            short_expiration = datetime.strptime(short_option["expiration"], "%Y-%m-%d").date()
        except ValueError:
            print(f"WARNING: Invalid expiration format for {asset_symbol}: {short_option.get('expiration')}")
            short_expiration = datetime.now().date() + timedelta(days=7)  # fallback

        toDate = short_expiration + timedelta(days=days)

        # Get option chain
        try:
            optionChain = OptionChain(api, asset_symbol, toDate, days)
            chain = optionChain.get()
        except Exception as e:
            print(f"WARNING: Could not get option chain for {asset_symbol}: {e}")
            chain = []

        # Get roll analysis
        result = find_best_rollover(api, chain, short_option)

        # Ensure we always have current position data
        if result is None:
            # Create fallback result with at least the basic info
            current_info = extract_current_position_info(short_option, api, chain)
            result = {
                "asset": asset_symbol,
                "roll_available": False,
                "no_roll_reason": "Analysis failed",
                **current_info
            }

        # Make sure current_strike and current_expiration are populated
        if result.get("current_strike") is None:
            try:
                result["current_strike"] = float(short_option.get("strike", 0))
            except (ValueError, TypeError):
                result["current_strike"] = 0

        if result.get("current_expiration") is None:
            result["current_expiration"] = short_option.get("expiration", "Unknown")

        return result

    except Exception as e:
        print(f"ERROR: Exception in get_roll_analysis_with_current_data for {short_option.get('stockSymbol', 'Unknown')}: {e}")
        # Even on complete failure, return something with current position data
        return {
            "asset": short_option.get("stockSymbol", "Unknown"),
            "current_strike": float(short_option.get("strike", 0)) if short_option.get("strike") else 0,
            "current_expiration": short_option.get("expiration", "Unknown"),
            "current_price": None,
            "underlying_price": None,
            "roll_available": False,
            "no_roll_reason": f"Exception: {str(e)}"
        }

def get_current_position_data_for_ui(short_option, api=None):
    """
    Function specifically for UI to get current position data
    This function ALWAYS returns current strike and expiration data
    """
    try:
        asset_symbol = short_option.get("stockSymbol", "Unknown")

        # Initialize result with known data
        result = {
            "asset": asset_symbol,
            "current_strike": None,
            "current_expiration": None,
            "status": "No Config"
        }

        # Extract strike - try multiple sources
        if "strike" in short_option and short_option["strike"]:
            try:
                result["current_strike"] = float(short_option["strike"])
            except (ValueError, TypeError):
                print(f"DEBUG: Could not convert strike to float for {asset_symbol}: {short_option.get('strike')}")

        # Extract expiration - try multiple sources
        if "expiration" in short_option and short_option["expiration"]:
            result["current_expiration"] = short_option["expiration"]

        # Try to get additional data if API is available
        if api and asset_symbol != "Unknown":
            try:
                # Get option chain data to find current position
                asset_config = get_asset_config_safe(asset_symbol, configuration)
                days = asset_config.get("maxRollOutWindow", 30)

                # Parse expiration date safely
                try:
                    short_expiration = datetime.strptime(short_option["expiration"], "%Y-%m-%d").date()
                    toDate = short_expiration + timedelta(days=days)

                    optionChain = OptionChain(api, asset_symbol, toDate, days)
                    chain = optionChain.get()

                    # Try to find current position in chain
                    current_info = extract_current_position_info(short_option, api, chain)
                    if current_info["current_strike"] is not None:
                        result["current_strike"] = current_info["current_strike"]
                    if current_info["current_expiration"] is not None:
                        result["current_expiration"] = current_info["current_expiration"]

                    # Update status based on what we found
                    result["status"] = "Data Retrieved"

                except Exception as chain_error:
                    print(f"DEBUG: Could not get option chain for {asset_symbol}: {chain_error}")
                    # Keep the basic data we already have

            except Exception as api_error:
                print(f"DEBUG: API error for {asset_symbol}: {api_error}")
                # Keep the basic data we already have

        # Final validation - ensure we have at least basic data
        if result["current_strike"] is None:
            result["current_strike"] = 0.0  # Fallback

        if result["current_expiration"] is None:
            result["current_expiration"] = "Unknown"  # Fallback

        print(f"DEBUG: UI data for {asset_symbol}: Strike={result['current_strike']}, Exp={result['current_expiration']}, Status={result['status']}")
        return result

    except Exception as e:
        print(f"ERROR: Exception in get_current_position_data_for_ui for {short_option.get('stockSymbol', 'Unknown')}: {e}")
        # Return minimal safe data
        return {
            "asset": short_option.get("stockSymbol", "Unknown"),
            "current_strike": 0.0,
            "current_expiration": "Unknown",
            "status": f"Error: {str(e)}"
        }
