import logging
from logging.handlers import RotatingFileHandler
import os
import sys

def _get_app_root_for_logging():
    """
    A self-contained function to find the app root, specifically for the logger.
    This avoids importing from helpers.py and causing a circular dependency.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # __file__ is logger.py -> dirname is utils/ -> dirname is the project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def setup_logging():
    """Configures the application's logging system."""
    log_file = os.path.join(_get_app_root_for_logging(), "app.log")

    logger = logging.getLogger("PieceNote")
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        return logger

    # --- File Handler ---
    # Create the directory for the log file if it doesn't exist
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler = RotatingFileHandler(
        log_file, maxBytes=1*1024*1024, backupCount=5, encoding='utf-8'
    )
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # --- Console Handler ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("="*50)
    logger.info("Logging configured successfully. Application starting.")
    logger.info("="*50)
    return logger

log = setup_logging()