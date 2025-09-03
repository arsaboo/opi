from datetime import datetime
import statistics

from configuration import configuration
from logger_config import get_logger
from core.common import (
    classify_status,
    parse_option_details,
    is_same_underlying,
)

logger = get_logger()


def find_best_rollover(api, data, short_option):
    short_strike, short_price, short_expiry, underlying_price = parse_option_details(
        api, data, short_option["optionSymbol"]
    )
    logger.debug(
        f"Short Strike: {short_strike}, Short Price: {short_price}, Short Expiry: {short_expiry}, Underlying Price: {underlying_price}"
    )
    if short_strike is None or short_price is None or short_expiry is None:
        return None

    # Configuration variables
    ITMLimit = configuration[short_option["stockSymbol"]].get("ITMLimit", 10)
    deepITMLimit = configuration[short_option["stockSymbol"]].get("deepITMLimit", 25)
    deepOTMLimit = configuration[short_option["stockSymbol"]].get("deepOTMLimit", 10)
    minPremium = configuration[short_option["stockSymbol"]].get("minPremium", 1)
    idealPremium = configuration[short_option["stockSymbol"]].get("idealPremium", 15)
    minRollupGap = configuration[short_option["stockSymbol"]].get("minRollupGap", 5)
    maxRollOutWindow = configuration[short_option["stockSymbol"]].get("maxRollOutWindow", 30)
    minRollOutWindow = configuration[short_option["stockSymbol"]].get("minRollOutWindow", 7)

    # Determine the short status using percent-aware thresholds
    short_status = classify_status(
        short_strike,
        underlying_price,
        itm_limit=ITMLimit,
        deep_itm_limit=deepITMLimit,
        deep_otm_limit=deepOTMLimit,
    )

    # Sort ordering depends on status
    if short_status == "deep_ITM":
        # Sort by date desc (farthest first), then strike desc
        entries = sorted(
            data,
            key=lambda entry: (
                -datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
                -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract),
            ),
        )
    else:
        # Sort by date asc (earliest first), then strike desc
        entries = sorted(
            data,
            key=lambda entry: (
                datetime.strptime(entry["date"], "%Y-%m-%d").timestamp(),
                -max(contract["strike"] for contract in entry["contracts"] if "strike" in contract),
            ),
        )

    # Initialize best option
    best_option = None
    closest_days_diff = float("inf")
    highest_strike = float("-inf")

    # Iterate to find the best rollover option
    while short_status and best_option is None:
        for entry in entries:
            expiry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            days_diff = (expiry_date - short_expiry).days
            if days_diff > maxRollOutWindow or days_diff < minRollOutWindow:
                continue
            for contract in entry["contracts"]:
                if contract["strike"] <= short_strike:
                    continue
                # Underlying root filter
                if not is_same_underlying(contract.get("optionRoot", ""), short_option["optionSymbol"]):
                    continue

                contract_price = round(statistics.median([contract["bid"], contract["ask"]]), 2)
                premium_diff = contract_price - short_price
                logger.debug(
                    f"Contract: {contract['symbol']}, Premium: {contract_price}, Days: {days_diff}, Premium Diff: {premium_diff}, Ideal Premium: {idealPremium}, Strike: {contract['strike']}"
                )
                if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                    if (contract["strike"] >= short_strike + minRollupGap and premium_diff >= idealPremium):
                        if days_diff < closest_days_diff:
                            closest_days_diff = days_diff
                            best_option = contract

                elif short_status == "ITM":
                    if (premium_diff >= minPremium and contract["strike"] >= short_strike + minRollupGap):
                        if contract["strike"] > highest_strike or (contract["strike"] == highest_strike and days_diff < closest_days_diff):
                            highest_strike = contract["strike"]
                            closest_days_diff = days_diff
                            best_option = contract

                elif short_status == "deep_ITM":
                    # Roll to the highest strike without paying a premium
                    if premium_diff >= 0.1 and contract["strike"] > highest_strike:
                        highest_strike = contract["strike"]
                        closest_days_diff = days_diff
                        best_option = contract

        # Adjust criteria if no best option found
        if best_option is None:
            logger.debug(
                f"Before adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
            )
            if short_status in ["deep_OTM", "OTM", "just_ITM"]:
                if idealPremium > minPremium:
                    idealPremium = max(idealPremium - 0.5, minPremium)
                elif minRollupGap > 0:
                    minRollupGap = max(minRollupGap - 5, 0)
            elif short_status == "ITM":
                if minRollupGap > 0:
                    minRollupGap = max(minRollupGap - 5, 0)
                elif minPremium > 0:
                    minPremium = max(minPremium - 0.25, 0)

            logger.debug(
                f"After adjustment - IdealPremium: {idealPremium}, MinRollupGap: {minRollupGap}"
            )

    return best_option
