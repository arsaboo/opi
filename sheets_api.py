import json
import os.path
import pickle
from datetime import date, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from logger_config import get_logger

logger = get_logger()

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def clean_number(value):
    """Clean number strings by removing currency symbols and commas"""
    if not value or value == '-':
        return '0'
    return value.replace('$', '').replace(',', '').strip()

class SheetsAPIError(Exception):
    """Custom exception for Sheets API errors"""
    pass

class SheetsAPI:
    def __init__(self, spreadsheet_id):
        if not spreadsheet_id:
            raise SheetsAPIError("Spreadsheet ID is required")
        self.spreadsheet_id = spreadsheet_id
        self.service = None
        self.creds = None
        self.cache_dir = os.path.join(os.path.dirname(__file__), '.cache')
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def authenticate(self):
        """Authenticate with Google Sheets API"""
        max_retries = 2
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Clear credentials and service
                self.creds = None
                self.service = None

                # Try to load existing token
                if os.path.exists('token.pickle'):
                    with open('token.pickle', 'rb') as token:
                        self.creds = pickle.load(token)

                # Get new credentials if needed
                if not self.creds or not self.creds.valid:
                    if self.creds and self.creds.expired and self.creds.refresh_token:
                        self.creds.refresh(Request())
                    else:
                        if not os.path.exists('credentials.json'):
                            raise SheetsAPIError(
                                "credentials.json not found. Please follow the setup instructions in README.md"
                            )
                        flow = InstalledAppFlow.from_client_secrets_file(
                            'credentials.json', SCOPES)
                        self.creds = flow.run_local_server(port=0)

                    # Save the credentials
                    with open('token.pickle', 'wb') as token:
                        pickle.dump(self.creds, token)

                self.service = build('sheets', 'v4', credentials=self.creds)
                logger.info("Successfully authenticated with Google Sheets")
                return  # Success - exit the function

            except Exception as e:
                retry_count += 1
                if 'invalid_grant' in str(e):
                    logger.warning(f"Token invalid, attempt {retry_count} of {max_retries}")
                    if os.path.exists('token.pickle'):
                        os.remove('token.pickle')
                    continue  # Try again
                else:
                    raise SheetsAPIError(f"Authentication failed: {str(e)}")

        raise SheetsAPIError("Failed to authenticate after maximum retries")

    def validate_sheet_structure(self):
        """Validate that the spreadsheet has the required structure"""
        try:
            # Check Stocks sheet
            stocks_range = 'Stocks!A1:U1'
            stocks_result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=stocks_range
            ).execute()
            stocks_headers = stocks_result.get('values', [[]])[0]
            required_stocks_headers = [
                'Category', 'Stock Name', 'Google Price', 'Units', 'Cost',
                'Unrealised Gain/Loss', 'Remarks'
            ]
            for header in required_stocks_headers:
                if header not in stocks_headers:
                    raise SheetsAPIError(f"Missing required column '{header}' in Stocks sheet")

            # Check Transactions sheet
            trans_range = 'Transactions!A1:U1'
            trans_result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=trans_range
            ).execute()
            trans_headers = trans_result.get('values', [[]])[0]
            required_trans_headers = [
                'Date', 'Type', 'Stock', 'Units', 'Price (per unit)',
                'Cumulative Units', 'Account'
            ]
            for header in required_trans_headers:
                if header not in trans_headers:
                    raise SheetsAPIError(f"Missing required column '{header}' in Transactions sheet")

        except HttpError as e:
            if e.resp.status == 404:
                raise SheetsAPIError("Spreadsheet not found. Please check your Spreadsheet ID.")
            elif e.resp.status == 403:
                raise SheetsAPIError("Permission denied. Please share the spreadsheet with your Google Cloud project.")
            else:
                raise SheetsAPIError(f"Error accessing spreadsheet: {str(e)}")

    def read_current_positions(self):
        """Read current positions from the Stocks sheet"""
        try:
            if not self.service:
                self.authenticate()

            range_name = 'Stocks!A2:U'  # Skip header row
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            values = result.get('values', [])

            if not values:
                logger.warning('No positions found')
                return []

            positions = []
            for row in values:
                try:
                    # Only process Schwab positions
                    if len(row) >= 20 and row[19] == 'Schwab':  # Remarks column
                        position = {
                            'category': row[0],
                            'stock_name': row[1],
                            'current_price': float(clean_number(row[5])) if row[5] else 0,
                            'units': float(clean_number(row[6])) if row[6] else 0,
                            'cost': float(clean_number(row[7])) if row[7] else 0,
                            'cost_per_unit': float(clean_number(row[8])) if row[8] else 0,
                            'unrealized_gl': float(clean_number(row[9])) if row[9] else 0,
                            'unrealized_gl_pct': float(row[10].strip('%'))/100 if row[10] and row[10] != '-' else 0,
                            'realized_gl': float(clean_number(row[11])) if row[11] else 0,
                            'dividends': float(clean_number(row[12])) if row[12] else 0,
                            'total_gl': float(clean_number(row[13])) if row[13] else 0,
                            'market_value': float(clean_number(row[14])) if row[14] else 0,
                            'returns': float(row[15].strip('%'))/100 if row[15] and row[15] != '-' else 0,
                            'week_52_low': float(clean_number(row[16])) if row[16] else 0,
                            'week_52_high': float(clean_number(row[17])) if row[17] else 0,
                            'additional_deltas': row[18] if len(row) > 18 else '',
                            'broker': row[19] if len(row) > 19 else ''
                        }
                        positions.append(position)
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing position row: {str(e)}")
                    logger.error(f"Problematic row: {row}")
                    continue

            return positions

        except HttpError as e:
            if e.resp.status == 404:
                raise SheetsAPIError("Stocks sheet not found")
            else:
                raise SheetsAPIError(f"Error reading positions: {str(e)}")

    def _get_cache_path(self, account):
        """Get the path for the cache file"""
        return os.path.join(self.cache_dir, f'transactions_{account}_{date.today()}.json')

    def _is_cache_valid(self, cache_path):
        """Check if cache exists and is from today"""
        if not os.path.exists(cache_path):
            return False

        # Get the file's last modification time
        file_mtime = datetime.fromtimestamp(os.path.getmtime(cache_path)).date()
        today = date.today()

        # Check if the file was last modified today
        return file_mtime == today

    def _save_to_cache(self, transactions, cache_path):
        """Save transactions to cache file"""
        # Delete any existing cache files for this account
        cache_prefix = cache_path.rsplit('_', 1)[0]  # Get path without date
        for old_file in os.listdir(self.cache_dir):
            if old_file.startswith(os.path.basename(cache_prefix)):
                old_path = os.path.join(self.cache_dir, old_file)
                try:
                    os.remove(old_path)
                except OSError as e:
                    logger.warning(f"Failed to delete old cache file {old_file}: {e}")

        # Convert datetime objects to string for JSON serialization
        serializable_transactions = []
        for t in transactions:
            t_copy = t.copy()
            t_copy['date'] = t_copy['date'].isoformat()
            serializable_transactions.append(t_copy)

        with open(cache_path, 'w') as f:
            json.dump(serializable_transactions, f)

    def _load_from_cache(self, cache_path):
        """Load transactions from cache file"""
        with open(cache_path, 'r') as f:
            transactions = json.load(f)
            # Convert date strings back to datetime.date objects
            for t in transactions:
                t['date'] = datetime.fromisoformat(t['date']).date()
            return transactions

    def read_transactions(self, account='Schwab'):
        """Read transactions from cache or Google Sheets"""
        cache_path = self._get_cache_path(account)

        # Check if we have valid cache
        if self._is_cache_valid(cache_path):
            logger.info("Loading transactions from cache")
            return self._load_from_cache(cache_path)

        # If no valid cache, fetch from Google Sheets
        logger.info("Fetching transactions from Google Sheets")
        try:
            if not self.service:
                self.authenticate()

            range_name = 'Transactions!A2:U'  # Skip header row
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            values = result.get('values', [])

            if not values:
                logger.warning('No transactions found')
                return []

            transactions = []
            for row in values:
                try:
                    # Filter for specified account
                    if len(row) >= 21 and row[20] == account:
                        # Parse date in yyyy-mm-dd format
                        transaction = {
                            'date': datetime.strptime(row[0], '%Y-%m-%d').date(),
                            'type': row[1],
                            'stock': row[2],
                            'units': float(clean_number(row[3])) if row[3] else 0,
                            'price_per_unit': float(clean_number(row[4])) if row[4] else 0,
                            'fees': float(clean_number(row[5])) if row[5] else 0,
                            'split_ratio': float(clean_number(row[6])) if row[6] else 1,
                            'prev_row': row[7] if len(row) > 7 else '',
                            'previous_units': float(clean_number(row[8])) if row[8] else 0,
                            'cumulative_units': float(clean_number(row[9])) if row[9] else 0,
                            'transacted_value': float(clean_number(row[10])) if row[10] else 0,
                            'previous_cost': float(clean_number(row[11])) if row[11] else 0,
                            'cost_of_transaction': float(clean_number(row[12])) if row[12] else 0,
                            'cost_per_unit_transaction': float(clean_number(row[13])) if row[13] else 0,
                            'cumulative_cost': float(clean_number(row[14])) if row[14] else 0,
                            'gains_losses': float(clean_number(row[15])) if row[15] else 0,
                            'yield': float(row[16].strip('%'))/100 if row[16] and row[16] != '-' else 0,
                            'cash_flow': float(clean_number(row[17])) if row[17] else 0,
                            'tic': row[18] if len(row) > 18 else '',
                            'remarks': row[19] if len(row) > 19 else '',
                            'account': row[20] if len(row) > 20 else ''
                        }
                        transactions.append(transaction)
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing transaction row: {str(e)}")
                    logger.error(f"Problematic row: {row}")
                    continue

            # Save to cache before returning
            self._save_to_cache(transactions, cache_path)
            return transactions

        except HttpError as e:
            if e.resp.status == 404:
                raise SheetsAPIError("Transactions sheet not found")
            else:
                raise SheetsAPIError(f"Error reading transactions: {str(e)}")

    def get_option_transactions(self, account='Schwab'):
        """Get option-related transactions"""
        transactions = self.read_transactions(account)
        option_types = {'SCO', 'BCC', 'BCO-VC', 'SCO-VC', 'BCO', 'BCC-VC-F',
                       'BCO-COM', 'SPO-COM', 'SCC-VC-F', 'BPC', 'BPC-COM',
                       'SCC-VC', 'BCC-VC', 'SPO'}

        return [t for t in transactions if t['type'] in option_types]

    def get_stock_transactions(self, account='Schwab'):
        """Get stock-related transactions"""
        transactions = self.read_transactions(account)
        stock_types = {'Buy', 'Sell', 'Div'}

        return [t for t in transactions if t['type'] in stock_types]

    def get_open_positions(self, account='Schwab'):
        """Get current open positions"""
        positions = self.read_current_positions()
        return [p for p in positions if p['broker'] == account and p['units'] > 0]
