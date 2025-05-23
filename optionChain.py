from statistics import median

import alert
from logger_config import get_logger
from support import validDateFormat

logger = get_logger()

class OptionChain:
    """
    Handles option chain data from Schwab API
    """
    def __init__(self, api, asset, date, daysLessAllowed):
        """
        Initialize with Schwab API

        Args:
            api: Schwab API instance
            asset: Asset symbol
            date: Target date
            daysLessAllowed: Days window for options
        """
        self.api = api
        self.asset = asset
        self.date = date
        self.daysLessAllowed = daysLessAllowed

    def get(self):
        """Get option chain data from the API"""
        try:
            apiData = self.api.getOptionChain(
                self.asset, 150, self.date, self.daysLessAllowed
            )
            return self.mapApiData(apiData)
        except Exception as e:
            logger.error(f"Error getting option chain: {str(e)}")
            return []

    def mapApiData(self, data, put=False):
        """Map API data to standardized format"""
        map_list = []
        try:
            exp_date_map = data["callExpDateMap"] if not put else data["putExpDateMap"]
            for key, value in exp_date_map.items():
                split = key.split(":")
                date = split[0]
                days = int(split[1])

                if not validDateFormat(date):
                    return alert.botFailed(
                        self.asset, "Incorrect date format from api: " + date
                    )

                contracts = []
                for contract_value in value.values():
                    # Ensure strike price is a float
                    try:
                        strike_price = float(contract_value[0]["strikePrice"])
                    except (ValueError, TypeError):
                        continue  # Skip contracts with invalid strike prices

                    contracts.append(
                        {
                            "symbol": contract_value[0]["symbol"],
                            "strike": strike_price,
                            "bid": contract_value[0]["bid"],
                            "ask": contract_value[0]["ask"],
                            "delta": contract_value[0].get("delta"),
                            "theta": contract_value[0].get("theta"),
                            "vega": contract_value[0].get("vega"),
                            "gamma": contract_value[0].get("gamma"),
                            "rho": contract_value[0].get("rho"),
                            "optionRoot": contract_value[0]["optionRoot"],
                            "underlying": contract_value[0]["optionDeliverablesList"][
                                0
                            ]["symbol"],
                            "putCall": contract_value[0]["putCall"],
                        }
                    )

                if contracts:  # Only add to map_list if there are valid contracts
                    map_list.append({"date": date, "days": days, "contracts": contracts})
        except KeyError:
            logger.error(f"Error mapping API data for {self.asset}")
            return []

        if map_list:
            map_list = sorted(map_list, key=lambda d: d["days"])

        return map_list

    def sortDateChain(self, chain):
        """Sort chain by strike price"""
        return sorted(chain, key=lambda d: d["strike"])

    def getContractFromDateChain(self, strike, chain):
        """Get first contract with strike >= target strike"""
        sorted_chain = self.sortDateChain(chain)
        for contract in sorted_chain:
            if contract["strike"] >= strike:
                return contract
        return None

    def getContractFromDateChainByMinYield(self, minStrike, maxStrike, minYield, chain):
        """Get contract within strike range meeting minimum yield"""
        sorted_chain = self.sortDateChain(chain)
        for contract in reversed(sorted_chain):
            if contract["strike"] > maxStrike:
                continue
            if contract["strike"] < minStrike:
                break
            if median([contract["bid"], contract["ask"]]) >= minYield:
                return contract
        return None
