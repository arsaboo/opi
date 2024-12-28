import datetime
import re
from datetime import datetime
from typing import Dict
import csv

import pytz

from logger_config import get_logger

logger = get_logger()

class TaxTracker:
    # All option-related transaction types
    OPTION_TYPES = {
        'SCO',      # Sell call option
        'SPO',      # Sell put option
        'BCC',      # Buy call option
        'BPC',      # Buy put option
        'SCO-VC',   # Sell call option
        'BCO-VC',   # Buy call option
        'BCC-VC',   # Buy call option
        'BCC-VC-F', # Buy call option
        'BCO-COM',  # Buy call option
        'SPO-COM',  # Sell put option
        'SCC-VC',   # Sell call option
        'SCC-VC-F', # Sell call option
        'BPC-COM',  # Buy put option
        'BCO'       # Buy call option
    }

    def __init__(self, sheets_api):
        self.api = sheets_api

    def parse_expiration_date(self, remarks):
        """Parse expiration date from the remarks column"""
        match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', remarks)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()
        return None

    def get_year_summary(self, year: int = None) -> Dict:
        """Get summary of all transactions for a specific tax year"""
        if year is None:
            year = datetime.now().year

        # Initialize summary
        summary = {
            'total_income': 0.0,
            'option_income': 0.0,  # Combined option premiums and gains
            'stock_gains': 0.0,
            'dividends': 0.0,
            'transactions_by_type': {
                'Options': [],
                'Stocks': [],
                'Dividends': []
            }
        }

        try:
            # Get all transactions for the year
            transactions = self.api.read_transactions()

            for trans in transactions:
                # Skip if not in the requested year
                trans_date = trans['date']
                if trans_date.year != year:
                    continue

                trans_type = trans['type'].upper()
                cash_flow = float(trans['cash_flow'])

                # Log transaction details for debugging
                logger.debug(f"Processing transaction: Type={trans_type}, Cash Flow={cash_flow}, Stock={trans.get('stock', '')}")

                # Skip if no cash flow
                if cash_flow == 0:
                    continue

                # Categorize based on transaction type
                if trans_type == 'DIV':
                    summary['dividends'] += cash_flow
                    summary['total_income'] += cash_flow
                    summary['transactions_by_type']['Dividends'].append({
                        'date': trans_date.strftime('%Y-%m-%d'),
                        'type': trans_type,
                        'symbol': trans['stock'],
                        'amount': cash_flow,
                        'description': f"Dividend - {trans['stock']}"
                    })
                elif trans_type in self.OPTION_TYPES:
                    # Parse expiration date from remarks
                    expiration_date = self.parse_expiration_date(trans.get('remarks', ''))
                    if expiration_date is None or expiration_date <= datetime.now().date():
                        # Include premium in income if option is closed or expired
                        summary['option_income'] += cash_flow
                        summary['total_income'] += cash_flow

                    # Determine if this is a premium received or paid
                    if trans_type.startswith('S'):  # Sell transactions
                        action = "Premium Received"
                    else:  # Buy transactions
                        action = "Premium Paid"

                    summary['transactions_by_type']['Options'].append({
                        'date': trans_date.strftime('%Y-%m-%d'),
                        'type': trans_type,
                        'symbol': trans['stock'],
                        'amount': cash_flow,
                        'description': f"{action} - {trans['stock']} ({trans_type})"
                    })

                    # Log option transaction
                    logger.debug(f"Option transaction added: {action}, Amount={cash_flow}")

                elif trans_type == 'SELL':
                    # Use gains/losses column for stock transactions
                    gain_loss = float(trans['gains_losses'])
                    summary['stock_gains'] += gain_loss
                    summary['total_income'] += gain_loss
                    summary['transactions_by_type']['Stocks'].append({
                        'date': trans_date.strftime('%Y-%m-%d'),
                        'type': trans_type,
                        'symbol': trans['stock'],
                        'amount': gain_loss,
                        'description': f"Stock Sale - {trans['stock']} (Gain/Loss)"
                    })

        except Exception as e:
            logger.error(f"Error getting year summary: {e}")
            print(f"Error getting year summary: {e}")

        return summary

    def analyze_tax_implications(self, year: int = None) -> Dict:
        """
        Analyze tax implications and suggest potential tax optimization strategies
        """
        if year is None:
            year = datetime.datetime.now().year

        summary = self.get_year_summary(year)
        total_income = summary['total_income']

        analysis = {
            'total_taxable_income': total_income,
            'recommendations': []
        }

        # Tax bracket thresholds for 2023 (example)
        brackets = [
            (0, 11000, 0.10),
            (11000, 44725, 0.12),
            (44725, 95375, 0.22),
            (95375, 182100, 0.24),
            (182100, 231250, 0.32),
            (231250, 578125, 0.35),
            (578125, float('inf'), 0.37)
        ]

        # Find current tax bracket
        current_bracket = None
        for i, (low, high, rate) in enumerate(brackets):
            if low <= total_income < high:
                current_bracket = (low, high, rate)
                # Get next bracket if not in highest bracket
                if i < len(brackets) - 1:
                    next_low, next_high, next_rate = brackets[i + 1]
                    distance_to_next = next_low - total_income
                    if distance_to_next < 10000:
                        analysis['recommendations'].append(
                            f"Warning: Only ${distance_to_next:,.2f} away from next tax bracket "
                            f"({(rate * 100):.1f}% -> {(next_rate * 100):.1f}%)"
                        )
                break

        # Option income analysis
        if summary['option_income'] > 0:
            analysis['recommendations'].append(
                f"Current net option income: ${summary['option_income']:,.2f}. "
                "Consider tax-loss harvesting opportunities to offset this income."
            )

        # Stock gains analysis
        if summary['stock_gains'] > 0:
            analysis['recommendations'].append(
                f"Current stock gains: ${summary['stock_gains']:,.2f}. "
                "Review positions for tax-loss harvesting opportunities."
            )

        # Dividend analysis
        if summary['dividends'] > 0:
            analysis['recommendations'].append(
                f"Current dividend income: ${summary['dividends']:,.2f}. "
                "Consider reviewing qualified vs non-qualified dividend status."
            )

        return analysis

    def export_tax_report(self, year: int = None, format: str = 'csv') -> str:
        """
        Export tax data in specified format
        Default format changed to CSV
        """
        if year is None:
            year = datetime.datetime.now().year

        summary = self.get_year_summary(year)

        # Create CSV report content
        filename = f'tax_report_{year}.csv'
        with open(filename, 'w', newline='') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(["Tax Summary Report"])
            csvwriter.writerow([f"Year: {year}"])
            csvwriter.writerow([])
            csvwriter.writerow(["Total Income", f"${summary['total_income']:,.2f}"])
            csvwriter.writerow(["Net Option Income", f"${summary['option_income']:,.2f}"])
            csvwriter.writerow(["Stock Gains", f"${summary['stock_gains']:,.2f}"])
            csvwriter.writerow(["Dividends", f"${summary['dividends']:,.2f}"])
            csvwriter.writerow([])
            csvwriter.writerow(["Transaction Details"])
            csvwriter.writerow([])

            for category, transactions in summary['transactions_by_type'].items():
                if transactions:  # Only show categories with transactions
                    csvwriter.writerow([category])
                    csvwriter.writerow(["Date", "Description", "Amount"])
                    for t in sorted(transactions, key=lambda x: x['date']):
                        csvwriter.writerow([t['date'], t['description'], f"${t['amount']:,.2f}"])
                    csvwriter.writerow([])

        return filename
