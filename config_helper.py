# Configuration fallback for missing assets
import logging

# Default configuration for any missing assets
DEFAULT_ASSET_CONFIG = {
    "ITMLimit": 10,
    "deepITMLimit": 25,
    "deepOTMLimit": 10,
    "minPremium": 1,
    "idealPremium": 15,
    "minRollupGap": 5,
    "maxRollOutWindow": 30,
    "minRollOutWindow": 7,
    "minStrike": 50,
    "type": "etf"
}

def get_asset_config_safe(asset_symbol, configuration_dict):
    """
    Safely get asset configuration with fallback to defaults

    Args:
        asset_symbol: The asset symbol to look up
        configuration_dict: The main configuration dictionary

    Returns:
        Dictionary with asset configuration (either from config or defaults)
    """
    try:
        if asset_symbol in configuration_dict:
            config = configuration_dict[asset_symbol]
            if isinstance(config, dict):
                # Ensure all required fields exist
                result = DEFAULT_ASSET_CONFIG.copy()
                result.update(config)
                return result
            else:
                print(f"WARNING: Configuration for {asset_symbol} is not a dictionary, using defaults")
                return DEFAULT_ASSET_CONFIG.copy()
        else:
            print(f"INFO: No configuration found for {asset_symbol}, using defaults")
            return DEFAULT_ASSET_CONFIG.copy()
    except Exception as e:
        print(f"ERROR: Exception accessing configuration for {asset_symbol}: {e}")
        return DEFAULT_ASSET_CONFIG.copy()