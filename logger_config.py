import logging
from configuration import loggingLevel

def get_logger():
    """Configure and return a logger instance"""
    logger = logging.getLogger(__name__)

    # Check if handlers already exist to avoid duplicate handlers
    if not logger.handlers:
        # Create console handler and set level
        handler = logging.StreamHandler()
        handler.setLevel(loggingLevel)

        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(handler)
        logger.setLevel(loggingLevel)

    return logger