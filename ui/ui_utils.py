"""
UI Utilities for Options Trading Application

This module contains utility functions for processing data for UI display,
handling different screen types, and other UI-related business logic.
"""

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from configuration import configuration, spreads
from cc import find_best_rollover, get_median_price
from optionChain import OptionChain
from strategies import BoxSpread, calculate_spread


def process_roll_short_data(api):
    """Process data for roll short options screen"""
    try:
        shorts = api.updateShortPosition()
        if not shorts:
            return []

        soon_expiring = []
        today = datetime.now().date()
        for short in shorts:
            exp = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
            if (exp - today).days <= 14:
                soon_expiring.append(short)

        if not soon_expiring:
            return []

        table_data = []
        for short in soon_expiring:
            try:
                days = configuration[short["stockSymbol"]]["maxRollOutWindow"]
                short_expiration = datetime.strptime(short["expiration"], "%Y-%m-%d").date()
                toDate = short_expiration + datetime.timedelta(days=days)
                optionChain = OptionChain(api, short["stockSymbol"], toDate, days)
                chain = optionChain.get()
                prem_short_contract = get_median_price(short["optionSymbol"], chain)
                if prem_short_contract is None:
                    continue
                roll = find_best_rollover(api, chain, short)
                if not roll:
                    continue
                roll_premium = get_median_price(roll["symbol"], chain)
                credit = round(roll_premium - prem_short_contract, 2)
                ret = api.getOptionDetails(roll["symbol"])
                table_data.append({
                    'asset': short["stockSymbol"],
                    'symbol': short["stockSymbol"],
                    'cur_strike': short["strike"],
                    'cur_exp': short["expiration"],
                    'roll_strike': roll["strike"],
                    'roll_exp': ret["expiration"],
                    'credit': credit,
                    'refreshed': datetime.now().strftime('%H:%M:%S')
                })
            except Exception as e:
                continue

        return table_data
    except Exception as e:
        return []


def process_box_spreads_data(api):
    """Process box spreads data using the existing BoxSpread function from strategies.py"""
    try:
        from strategies import BoxSpread

        # Limit box spreads to SPX/SPXW only (European-style options)
        spx_assets = ["$SPX", "$SPXW"]

        all_results = []

        for asset in spx_assets:
            try:
                # Call the existing BoxSpread function
                results = BoxSpread(api, asset)

                if results:
                    for result in results:
                        # Format Ann ROM % to 2 decimal places
                        ann_rom = result.get('return_on_margin', 0)
                        if isinstance(ann_rom, (int, float)):
                            ann_rom_formatted = f"{ann_rom:.2f}%"
                        else:
                            ann_rom_formatted = str(ann_rom)
                            if '%' not in ann_rom_formatted:
                                try:
                                    ann_rom_formatted = f"{float(ann_rom_formatted):.2f}%"
                                except:
                                    ann_rom_formatted = "0.00%"

                        # Convert the strategy.py result format to UI format
                        ui_row = {
                            'asset': asset,
                            'Date': result.get('date', ''),
                            'Direction': result.get('trade_direction', ''),
                            'Low Strike': result.get('strike1', 0),
                            'High Strike': result.get('strike2', 0),
                            'Net Price': result.get('net_debit', 0),
                            'Margin Req': result.get('margin_requirement', 0),
                            'Ann ROM %': ann_rom_formatted
                        }
                        all_results.append(ui_row)

            except Exception as e:
                print(f"Error processing box spreads for {asset}: {e}")
                continue

        return all_results if all_results else None

    except Exception as e:
        print(f"Error in process_box_spreads_data: {e}")
        return None


def process_vertical_spreads_data(api, synthetic=False):
    """Process data for vertical spreads screen"""
    try:
        spreads_data = _find_spreads_no_input(api, synthetic)
        now_str = datetime.now().strftime('%H:%M:%S')
        if spreads_data:
            for row in spreads_data:
                row['refreshed'] = now_str
        return spreads_data
    except Exception as e:
        return []


def process_margin_requirements_data(api):
    """Process data for margin requirements screen"""
    try:
        shorts = api.updateShortPosition()
        if not shorts:
            return []

        # Get account data for margin information
        r = api.connectClient.get_account(
            api.getAccountHash(), fields=api.connectClient.Account.Fields.POSITIONS
        )
        data = r.json()
        table_data = []
        total_margin = 0
        for short in shorts:
            margin = 0
            count = 0
            option_type = "Call" if "C" in short["optionSymbol"] else "Put"
            for position in data["securitiesAccount"]["positions"]:
                if position["instrument"]["symbol"] == short["optionSymbol"]:
                    margin = position.get("maintenanceRequirement", 0)
                    count = int(position.get("shortQuantity", 0))
                    break
            if margin > 0:
                total_margin += margin
                table_data.append({
                    'asset': short["stockSymbol"],
                    'symbol': short["stockSymbol"],
                    'type': f"Short {option_type}",
                    'strike': short["strike"],
                    'expiry': short["expiration"],
                    'count': count,
                    'margin': f"{margin:,.2f}",
                    'refreshed': datetime.now().strftime('%H:%M:%S')
                })
        if table_data:
            table_data.append({'symbol': 'TOTAL', 'type': '', 'strike': '', 'expiry': '', 'count': '', 'margin': f"{total_margin:,.2f}", 'refreshed': datetime.now().strftime('%H:%M:%S')})
        return table_data
    except Exception as e:
        return []


def process_orders_data(api):
    """Process data for orders screen"""
    try:
        orders = api.get_orders(max_results=1000)
        now_str = datetime.now().strftime('%H:%M:%S')

        if not orders:
            return []

        table_data = []
        for order in orders:
            try:
                order_id = order.get('orderId', 'Unknown')
                status = order.get('status', 'Unknown')
                entered_time = order.get('enteredTime', '')
                if entered_time:
                    # Convert from ISO format to readable format
                    entered_time = entered_time[:19].replace('T', ' ')

                # Get order details from the order instruments
                instruments = order.get('orderLegCollection', [])
                if instruments:
                    instrument = instruments[0].get('instrument', {})
                    symbol = instrument.get('symbol', 'Unknown')
                    asset_type = instrument.get('assetType', 'Unknown')
                    quantity = instruments[0].get('quantity', 0)
                    instruction = instruments[0].get('instruction', 'Unknown')
                else:
                    symbol = 'Unknown'
                    asset_type = 'Unknown'
                    quantity = 0
                    instruction = 'Unknown'

                order_type = order.get('orderType', 'Unknown')
                price = order.get('price', 0)

                table_data.append({
                    'order_id': order_id,
                    'status': status,
                    'symbol': symbol,
                    'type': asset_type,
                    'instruction': instruction,
                    'quantity': quantity,
                    'order_type': order_type,
                    'price': f"${price:.2f}" if price else 'Market',
                    'entered': entered_time,
                    'refreshed': now_str
                })
            except Exception as e:
                continue

        return table_data
    except Exception as e:
        return []


def _find_spreads_no_input(api, synthetic=False):
    """Wrapper for find_spreads that returns data without requiring user input"""
    try:
        spread_dict = {}
        futures_to_asset = {}
        with ThreadPoolExecutor() as executor:
            for asset in spreads:
                spread = spreads[asset]["spread"]
                days = spreads[asset]["days"]
                downsideProtection = spreads[asset]["downsideProtection"]
                price_method = spreads[asset].get("price", "mid")
                future = executor.submit(
                    calculate_spread,
                    api,
                    asset,
                    spread,
                    days,
                    downsideProtection,
                    price_method,
                    synthetic,
                )
                futures_to_asset[future] = asset
            for future in as_completed(futures_to_asset):
                asset, result = future.result()
                if result is not None:
                    spread_dict[asset] = result
        spreads_list = []
        for asset, spread_data in spread_dict.items():
            if spread_data:
                table_row = {
                    'asset': asset,
                    'expiration': spread_data['date'],
                    'strike_low': spread_data['strike1'],
                    'strike_high': spread_data['strike2'],
                    'call_low_ba': f"{spread_data['bid1']}/{spread_data['ask1']}",
                    'call_high_ba': f"{spread_data['bid2']}/{spread_data['ask2']}",
                    'investment': spread_data['total_investment'],
                    'max_profit': spread_data['total_return'],
                    'cagr': spread_data['cagr_percentage'],
                    'protection': f"{spread_data['downside_protection']}%",
                    'margin_req': spread_data['margin_requirement'],
                    'ann_rom': f"{spread_data['return_on_margin']}%"
                }
                spreads_list.append(table_row)
        spreads_list.sort(key=lambda x: float(str(x['ann_rom']).replace('%', '')), reverse=True)
        return spreads_list
    except Exception as e:
        return []
