import os
import re
from datetime import datetime, timedelta
from logger import get_logger

logger = get_logger(__name__)

def cleanup_old_logs(log_dir="logs", days_to_keep=2):
    """
    Delete log files older than the specified number of days.
    
    Args:
        log_dir (str): Path to the logs directory
        days_to_keep (int): Number of days to keep logs (default: 2)
    """
    try:
        # Check if logs directory exists
        if not os.path.exists(log_dir):
            logger.info(f"Log directory '{log_dir}' does not exist. Skipping cleanup.")
            return
            
        # Calculate the cutoff date (files older than this will be deleted)
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        # Regex pattern to match log files with date format: options_trading_YYYYMMDD.log
        pattern = re.compile(r"options_trading_(\d{8})\.log")
        
        deleted_count = 0
        
        # Iterate through files in the logs directory
        for filename in os.listdir(log_dir):
            match = pattern.match(filename)
            if match:
                try:
                    # Extract date from filename
                    date_str = match.group(1)
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    
                    # Delete file if it's older than cutoff date
                    if file_date < cutoff_date:
                        file_path = os.path.join(log_dir, filename)
                        os.remove(file_path)
                        logger.info(f"Deleted old log file: {filename}")
                        deleted_count += 1
                        
                except ValueError as e:
                    logger.warning(f"Could not parse date from log filename '{filename}': {e}")
                    continue
                    
        logger.info(f"Log cleanup completed. Deleted {deleted_count} old log file(s).")
        
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")