"""
main.py - Entry point for gametimarr.

Startup sequence:
    1. Read environment variables.
    2. Configure logging (stdout + daily rotating file, 5 files kept).
    3. Validate mounted paths (fail fast if misconfigured).
    4. Initialize the database.
    5. Start scanner thread (every 90 minutes).
    6. Start monitor thread (every 60 minutes).
    7. Run the web server on port 7667.
"""

import os
import sys
import time
import glob
import asyncio
import logging
import threading
from datetime import date

import uvicorn

from app.database import init_db
from app.scanner import scan_once
from app.postprocess import check_completed
from app import web


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("DB_PATH", "/data/gametimarr.db")
DOWNLOAD_PATH = os.environ.get("DOWNLOAD_PATH", "/downloads")
DESTINATION_PATH = os.environ.get("DESTINATION_PATH", "/watch")
LOG_PATH = os.environ.get("LOG_PATH", "/logs")

SCAN_INTERVAL = 90      # minutes
MONITOR_INTERVAL = 60   # minutes
WEB_PORT = int(os.environ.get("WEB_PORT", "7667"))

LOG_FILES_TO_KEEP = 5


# ---------------------------------------------------------------------------
# Daily file handler
# ---------------------------------------------------------------------------

class DailyFileHandler(logging.Handler):
    """
    Writes log records to logs/YYYY-MM-DD.log, rolling over at midnight.
    Keeps the newest N files and deletes older ones.
    """

    def __init__(self, log_dir: str, keep: int = 5):
        super().__init__()
        self.log_dir = log_dir
        self.keep = keep
        self._current_date = None
        self._file = None

        os.makedirs(self.log_dir, exist_ok=True)
        self._open_for_today()

    def _open_for_today(self):
        """Open (or create) the log file for today's date."""
        today = date.today().isoformat()  # YYYY-MM-DD

        if self._file and self._current_date == today:
            return

        if self._file:
            self._file.close()

        path = os.path.join(self.log_dir, f"{today}.log")
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = today

        self._prune()

    def _prune(self):
        """Keep only the newest `keep` log files."""
        try:
            files = sorted(
                glob.glob(os.path.join(self.log_dir, "*.log")),
                reverse=True,
            )
            for old in files[self.keep:]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except Exception:
            pass

    def emit(self, record):
        try:
            # Roll over if the date changed since the last write
            self._open_for_today()
            msg = self.format(record)
            self._file.write(msg + "\n")
            self._file.flush()
        except Exception:
            self.handleError(record)


def setup_logging():
    """Configure root logger: stdout for Docker Desktop + daily file."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # stdout handler (shows in Docker Desktop's Logs tab)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # daily file handler
    file_handler = DailyFileHandler(LOG_PATH, keep=LOG_FILES_TO_KEEP)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


logger = logging.getLogger("gametimarr")


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_paths() -> bool:
    ok = True

    data_dir = os.path.dirname(DB_PATH)
    if not os.path.isdir(data_dir):
        logger.error(f"Data directory does not exist: {data_dir}")
        ok = False
    elif not os.access(data_dir, os.W_OK):
        logger.error(f"Data directory not writable: {data_dir}")
        ok = False
    else:
        logger.info(f"Data directory OK: {data_dir}")

    if not os.path.isdir(DOWNLOAD_PATH):
        logger.error(f"Download path does not exist: {DOWNLOAD_PATH}")
        ok = False
    else:
        logger.info(f"Download path OK: {DOWNLOAD_PATH}")

    if not os.path.isdir(DESTINATION_PATH):
        logger.error(f"Destination path does not exist: {DESTINATION_PATH}")
        ok = False
    else:
        logger.info(f"Destination path OK: {DESTINATION_PATH}")

    if not os.path.isdir(LOG_PATH):
        logger.error(f"Log directory does not exist: {LOG_PATH}")
        ok = False
    else:
        logger.info(f"Log directory OK: {LOG_PATH}")

    return ok


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

def scanner_loop():
    logger.info(f"Scanner thread started (interval: {SCAN_INTERVAL} min)")
    time.sleep(15)

    while True:
        try:
            asyncio.run(scan_once())
        except Exception as e:
            logger.exception(f"Scanner error: {e}")

        time.sleep(SCAN_INTERVAL * 60)


def monitor_loop():
    logger.info(f"Monitor thread started (interval: {MONITOR_INTERVAL} min)")
    time.sleep(30)

    while True:
        try:
            asyncio.run(check_completed())
        except Exception as e:
            logger.exception(f"Monitor error: {e}")

        time.sleep(MONITOR_INTERVAL * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    logger.info("=== gametimarr starting ===")

    if not validate_paths():
        logger.error("Startup validation failed. Exiting.")
        sys.exit(1)

    try:
        init_db(DB_PATH)
        logger.info(f"Database initialized at {DB_PATH}")
    except Exception as e:
        logger.exception(f"Database initialization failed: {e}")
        sys.exit(1)

    threading.Thread(target=scanner_loop, daemon=True, name="scanner").start()
    threading.Thread(target=monitor_loop, daemon=True, name="monitor").start()

    logger.info(f"Web server starting on port {WEB_PORT}")
    uvicorn.run(web.app, host="0.0.0.0", port=WEB_PORT, log_level="warning")


if __name__ == "__main__":
    main()