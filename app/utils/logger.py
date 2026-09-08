import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_PATH = Path("/app/logs/gametimarr.log")


def setup_logger(log_level: str = "INFO") -> logging.Logger:
    """Set up and return the application logger."""
    os.makedirs(LOG_PATH.parent, exist_ok=True)
    
    logger = logging.getLogger("gametimarr")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        str(LOG_PATH),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    # Console handler for Docker logs
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger() -> logging.Logger:
    """Get the application logger."""
    return logging.getLogger("gametimarr")