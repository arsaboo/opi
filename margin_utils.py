from logger_config import get_logger

def calculate_margin_requirement(asset, strategy_type, **kwargs):
    """
    Calculate margin requirement for different option strategies
    :param asset: The asset symbol
    :param strategy_type: Type of strategy (e.g., 'credit_spread', 'debit_spread')
    :param kwargs: Strategy-specific parameters
    :return: Margin requirement
    """
    from configuration import spreads, margin_rules

    asset_type = spreads[asset].get('type', 'etf')

    # Add debug logging
    logger = get_logger()
    logger.debug(f"Calculating margin for {strategy_type} on {asset} ({asset_type})")
    logger.debug(f"Parameters: {kwargs}")

    if strategy_type == 'credit_spread':
        strike_diff = kwargs.get('strike_diff')
        contracts = kwargs.get('contracts', 1)
        return margin_rules['spreads']['credit'](strike_diff, contracts)

    elif strategy_type == 'debit_spread':
        cost = kwargs.get('cost')
        return margin_rules['spreads']['debit'](cost)

    elif strategy_type == 'synthetic_covered_call':
        # For synthetic covered calls, margin is only required for the short put
        strike = kwargs.get('put_strike')
        underlying_value = kwargs.get('underlying_value')
        otm_amount = max(0, strike - underlying_value) if strike and underlying_value else 0
        premium = kwargs.get('put_premium', 0)

        if not all([strike, underlying_value]):
            logger.error(f"Missing required parameters for synthetic_covered_call margin calculation: {kwargs}")
            return 0

        # Calculate margin for broad-based index
        if asset_type == 'broad_based_index':
            method_1 = strike * 0.15 - otm_amount + premium * 100  # 15% method
            method_2 = strike * 0.10 + premium * 100  # 10% method
            margin = max(method_1, method_2)
            logger.debug(f"Margin calculation for {asset}: Method 1={method_1}, Method 2={method_2}, Using={margin}")
            return margin
        # For non-index options, use standard margin calculation
        else:
            margin = strike * 0.20  # Standard 20% requirement for equity options
            logger.debug(f"Using standard 20% margin for {asset}: {margin}")
            return margin

    elif strategy_type == 'naked_call':
        underlying_value = kwargs.get('underlying_value')
        otm_amount = kwargs.get('otm_amount', 0)
        premium = kwargs.get('premium')

        if asset_type == 'broad_based_index':
            return margin_rules['naked_calls']['broad_based_index']['initial_req'](
                underlying_value, otm_amount, premium
            )
        elif asset_type == 'leveraged_etf':
            leverage = kwargs.get('leverage', '2x')
            return margin_rules['naked_calls']['leveraged_etf'][leverage]['initial_req'](
                underlying_value, otm_amount, premium
            )

    elif strategy_type == 'naked_put':
        strike = kwargs.get('strike', kwargs.get('put_strike', 0))  # Try both parameter names
        underlying_value = kwargs.get('underlying_value', 0)
        otm_amount = max(0, strike - underlying_value)
        premium = kwargs.get('premium', 0)

        if asset_type == 'broad_based_index':
            method_1 = strike * 0.15 - otm_amount + premium * 100
            method_2 = strike * 0.10 + premium * 100
            margin = max(method_1, method_2)
            logger.debug(f"Naked put margin for {asset}: Method 1={method_1}, Method 2={method_2}, Using={margin}")
            return margin

    # Default return value
    logger.warning(f"No specific margin rule found for {strategy_type} on {asset}. Using 0.")
    return 0

def calculate_annualized_return_on_margin(profit, margin_req, days):
    """
    Calculate annualized return on margin
    :param profit: Expected profit
    :param margin_req: Margin requirement
    :param days: Days to expiration
    :return: Annualized return percentage
    """
    if margin_req <= 0:
        return 0

    # Calculate simple return
    simple_return = (profit / margin_req) * 100

    # Annualize the return
    annual_return = (simple_return * 365) / days

    return annual_return

def calculate_short_option_rom(strike, bid, underlying_price, days, asset):
    """
    Calculate annualized return for rolling individual short options (not spreads)
    :param strike: Strike price of the short option
    :param bid: Bid price of the short option (premium received)
    :param underlying_price: Current price of the underlying
    :param days: Days to expiration
    :param asset: Asset symbol
    :return: Annualized return percentage
    """
    if underlying_price <= 0 or days <= 0:
        return 0

    # For individual short options, calculate margin requirement
    from configuration import spreads
    asset_type = spreads[asset].get('type', 'etf')

    # Calculate OTM amount
    otm_amount = max(0, strike - underlying_price)

    # Calculate margin requirement based on option type
    margin_req = calculate_margin_requirement(
        asset,
        'naked_call',
        underlying_value=underlying_price,
        otm_amount=otm_amount,
        premium=bid
    )

    if margin_req <= 0:
        return 0

    # Calculate annualized return based on margin requirement
    credit = bid * 100  # Convert to dollar amount
    return calculate_annualized_return_on_margin(credit, margin_req, days)
