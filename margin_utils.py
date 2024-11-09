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

    if strategy_type == 'credit_spread':
        strike_diff = kwargs.get('strike_diff')
        contracts = kwargs.get('contracts', 1)
        return margin_rules['spreads']['credit'](strike_diff, contracts)

    elif strategy_type == 'debit_spread':
        cost = kwargs.get('cost')
        return margin_rules['spreads']['debit'](cost)

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
        underlying_value = kwargs.get('underlying_value')
        otm_amount = kwargs.get('otm_amount', 0)
        premium = kwargs.get('premium')
        max_loss = kwargs.get('max_loss')

        if asset_type == 'broad_based_index':
            return margin_rules['naked_puts']['broad_based_index']['initial_req'](
                underlying_value, otm_amount, premium, max_loss
            )

    return None

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
