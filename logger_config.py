import logging
from configuration import loggingLevel

def get_logger(use_underlying_logger=False):
    logger_name = __name__ if use_underlying_logger else 'my_application'
    logger = logging.getLogger(logger_name)

    # Only add a new handler if the logger doesn't have any
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(getattr(logging, loggingLevel.upper()))
        logger.addHandler(stream_handler)
        logger.setLevel(getattr(logging, loggingLevel.upper()))

    return logger