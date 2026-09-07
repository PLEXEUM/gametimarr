import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Default log path
LOG_PATH = Path("/app/logs/gametimarr.log")


def redact_sensitive(message: str) -> str:
    """Replace sensitive information in log messages with [REDACTED]."""
    # Redact API keys (32+ alphanumeric chars)
    message = re.sub(r'[a-zA-Z0-9]{32,}', '[REDACTED]', message)
    # Redact API key patterns in URLs
    message = re.sub(r'(apikey=)[^&\s]+', r'\1[REDACTED]', message)
    message = re.sub(r'(X-Api-Key:\s*)\S+', r'\1[REDACTED]', message)
    message = re.sub(r'(Authorization:\s*Bearer\s*)\S+', r'\1[REDACTED]', message)
    # Redact passwords in URLs
    message = re.sub(r'(://[^:]+:)[^@]+(@)', r'\1[REDACTED]\2', message)
    return message


class RedactingFormatter(logging.Formatter):
    """Custom log formatter that redacts sensitive information."""
    
    def format(self, record):
        msg = super().format(record)
        return redact_sensitive(msg)


def setup_logger(
    log_level: str = "INFO",
    log_max_size_mb: int = 10,
    log_max_files: int = 5
) -> logging.Logger:
    """Set up and return the application logger with file rotation."""
    
    # Ensure log directory exists
    os.makedirs(LOG_PATH.parent, exist_ok=True)
    
    logger = logging.getLogger("gametimarr")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        str(LOG_PATH),
        maxBytes=log_max_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=log_max_files,
        encoding="utf-8"
    )
    file_handler.setFormatter(RedactingFormatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    # Console handler for Docker logs
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(RedactingFormatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Logging initialized at {LOG_PATH}")
    return logger


def get_logger() -> logging.Logger:
    """Get the application logger."""
    return logging.getLogger("gametimarr")