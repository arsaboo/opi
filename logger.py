import logging
import os
from datetime import datetime

def get_logger(name="options_trading"):
    """Configure and return a file-based logger that doesn't interfere with Textual UI"""
    logger = logging.getLogger(name)

    # Only configure once
    if not logger.handlers:
        # Create logs directory if it doesn't exist
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Create log filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f"options_trading_{timestamp}.log")

        # Create file handler
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.INFO)

        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    # Remove any StreamHandlers if present (defensive)
    for h in list(logger.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            logger.removeHandler(h)

    return logger