import logging
import os
from logging.handlers import RotatingFileHandler
from configuration import loggingLevel

def get_logger():
    """Configure and return a logger instance that does not write to stdout.

    Logs are written to logs/app.log with rotation to avoid interfering with the
    Textual TUI rendering. Use the Status Log pane for user-facing messages.
    """
    logger = logging.getLogger("opi")

    if logger.handlers:
        return logger

    logger.setLevel(loggingLevel)

    # Ensure logs directory exists
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except (OSError, PermissionError):
        # Fallback to current directory if we can't create logs/
        log_dir = os.getcwd()

    log_path = os.path.join(log_dir, "app.log")

    # Rotating file handler (5 MB, keep 3 backups)
    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setLevel(loggingLevel)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Avoid propagating to root to prevent duplicate console output
    logger.propagate = False

    return logger
