from logger_config import get_logger


def calculate_margin_requirement(asset, strategy_type, **kwargs):
    from configuration import spreads, margin_rules
    logger = get_logger()
    try:
        asset_type = spreads[asset].get('type', 'etf')
        if strategy_type == 'credit_spread':
            strike_diff = kwargs.get('strike_diff')
            contracts = kwargs.get('contracts', 1)
            return margin_rules['spreads']['credit'](strike_diff, contracts)
        elif strategy_type == 'debit_spread':
            cost = kwargs.get('cost')
            return margin_rules['spreads']['debit'](cost)
        elif strategy_type == 'synthetic_covered_call':
            strike = kwargs.get('put_strike')
            underlying_value = kwargs.get('underlying_value')
            premium = kwargs.get('put_premium', 0)
            max_loss = kwargs.get('max_loss', strike * 100) if strike else 0
            if not all([strike, underlying_value]):
                return 0
            otm_amount = max(0, strike - underlying_value)
            if asset_type == 'broad_based_index':
                method_1 = strike * 0.15 - otm_amount + premium * 100
                method_2 = strike * 0.10 + premium * 100
                return max(method_1, method_2)
            else:
                return max((strike * 0.20 - otm_amount) * 100 + premium * 100, 2000)
        elif strategy_type == 'naked_call':
            underlying_value = kwargs.get('underlying_value')
            strike = kwargs.get('strike', 0)
            otm_amount = kwargs.get('otm_amount', max(0, underlying_value - strike))
            premium = kwargs.get('premium', 0)
            contracts = kwargs.get('contracts', 1)
            if asset_type == 'broad_based_index':
                method_1 = (underlying_value * 0.15 - otm_amount) * 100 + premium * 100
                method_2 = underlying_value * 0.10 * 100 + premium * 100
                return max(method_1, method_2) * contracts
            elif asset_type == 'leveraged_etf':
                leverage = kwargs.get('leverage', '2x')
                return margin_rules['naked_calls']['leveraged_etf'][leverage]['initial_req'](underlying_value, otm_amount, premium) * contracts
            else:
                method_1 = (underlying_value * 0.20 - otm_amount) * 100 + premium * 100
                method_2 = underlying_value * 0.10 * 100 + premium * 100
                return max(method_1, method_2, 2000) * contracts
        elif strategy_type == 'naked_put':
            strike = kwargs.get('strike', kwargs.get('put_strike', 0))
            underlying_value = kwargs.get('underlying_value', 0)
            otm_amount = max(0, strike - underlying_value)
            premium = kwargs.get('premium', 0)
            contracts = kwargs.get('contracts', 1)
            if asset_type == 'broad_based_index':
                method_1 = (strike * 0.15 - otm_amount) * 100 + premium * 100
                method_2 = strike * 0.10 * 100 + premium * 100
                return max(method_1, method_2) * contracts
            elif asset_type == 'etf_index':
                return max(underlying_value * 0.10 * 100, 2500) * contracts
            else:
                method_1 = (strike * 0.20 - otm_amount) * 100 + premium * 100
                method_2 = underlying_value * 0.10 * 100 + premium * 100
                return max(method_1, method_2, 2000) * contracts
    except Exception:
        return 0
    return 0


def calculate_annualized_return_on_margin(profit, margin_req, days):
    if margin_req <= 0 or days <= 0:
        return 0
    simple_return = (profit / margin_req) * 100
    return (simple_return * 365) / days


def calculate_short_option_rom(strike, bid, underlying_price, days, asset):
    if underlying_price <= 0 or days <= 0:
        return 0
    from configuration import spreads
    otm_amount = max(0, strike - underlying_price)
    margin_req = calculate_margin_requirement(
        asset,
        'naked_call',
        underlying_value=underlying_price,
        otm_amount=otm_amount,
        premium=bid
    )
    if margin_req <= 0:
        return 0
    credit = bid * 100
    return calculate_annualized_return_on_margin(credit, margin_req, days)

