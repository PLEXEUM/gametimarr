"""
main.py - Entry point for gametimarr.

Startup sequence:
    1. Read environment variables.
    2. Configure logging.
    3. Validate mounted paths (fail fast if misconfigured).
    4. Initialize the database.
    5. Start scanner thread (every 90 minutes).
    6. Start monitor thread (every 60 minutes).
    7. Run the web server on port 8080.

All three run inside one container. They share the same SQLite connection
(thread-safe via a lock in database.py).
"""

import os
import sys
import time
import asyncio
import logging
import threading

import uvicorn

from app.database import init_db, log_event
from app.scanner import scan_once
from app.postprocess import check_completed
from app import web


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("DB_PATH", "/data/gametimarr.db")
DOWNLOAD_PATH = os.environ.get("DOWNLOAD_PATH", "/downloads")
DESTINATION_PATH = os.environ.get("DESTINATION_PATH", "/watch")

# Intervals in minutes
SCAN_INTERVAL = 90
MONITOR_INTERVAL = 60

# Web server port
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gametimarr")


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_paths() -> bool:
    """
    Verify that the mounted paths exist and are usable. Return False if any
    critical path is missing, so the container exits with a clear error.
    """
    ok = True

    # Data directory must be writable (SQLite needs to create/update the DB)
    data_dir = os.path.dirname(DB_PATH)
    if not os.path.isdir(data_dir):
        logger.error(f"Data directory does not exist: {data_dir}")
        ok = False
    elif not os.access(data_dir, os.W_OK):
        logger.error(f"Data directory not writable: {data_dir}")
        ok = False
    else:
        logger.info(f"Data directory OK: {data_dir}")

    # Download path must exist and be readable (we read completed files)
    if not os.path.isdir(DOWNLOAD_PATH):
        logger.error(f"Download path does not exist: {DOWNLOAD_PATH}")
        ok = False
    elif not os.access(DOWNLOAD_PATH, os.R_OK):
        logger.error(f"Download path not readable: {DOWNLOAD_PATH}")
        ok = False
    else:
        logger.info(f"Download path OK: {DOWNLOAD_PATH}")

    # Destination path must exist and be writable (we copy files into it)
    if not os.path.isdir(DESTINATION_PATH):
        logger.error(f"Destination path does not exist: {DESTINATION_PATH}")
        ok = False
    elif not os.access(DESTINATION_PATH, os.W_OK):
        logger.error(f"Destination path not writable: {DESTINATION_PATH}")
        ok = False
    else:
        logger.info(f"Destination path OK: {DESTINATION_PATH}")

    return ok


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

def scanner_loop():
    """
    Run scan_once() every SCAN_INTERVAL minutes.
    Runs in its own thread. Catches all exceptions so a scan failure never
    kills the thread.
    """
    logger.info(f"Scanner thread started (interval: {SCAN_INTERVAL} min)")

    # Small initial delay so the web server is up before the first scan
    time.sleep(15)

    while True:
        try:
            asyncio.run(scan_once())
        except Exception as e:
            logger.exception(f"Scanner error: {e}")
            try:
                log_event(f"Scanner error: {e}")
            except Exception:
                pass

        time.sleep(SCAN_INTERVAL * 60)


def monitor_loop():
    """
    Run check_completed() every MONITOR_INTERVAL minutes.
    Runs in its own thread. Catches all exceptions so a monitor failure never
    kills the thread.
    """
    logger.info(f"Monitor thread started (interval: {MONITOR_INTERVAL} min)")

    # Offset from the scanner so they don't run at the same instant
    time.sleep(30)

    while True:
        try:
            asyncio.run(check_completed())
        except Exception as e:
            logger.exception(f"Monitor error: {e}")
            try:
                log_event(f"Monitor error: {e}")
            except Exception:
                pass

        time.sleep(MONITOR_INTERVAL * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=== gametimarr starting ===")

    # Validate paths before anything else
    if not validate_paths():
        logger.error("Startup validation failed. Exiting.")
        sys.exit(1)

    # Initialize database
    try:
        init_db(DB_PATH)
        logger.info(f"Database initialized at {DB_PATH}")
    except Exception as e:
        logger.exception(f"Database initialization failed: {e}")
        sys.exit(1)

    # Log a startup event so the UI shows something immediately
    try:
        log_event("App started")
    except Exception:
        pass

    # Start background threads as daemons so they exit with the process
    scanner_thread = threading.Thread(target=scanner_loop, daemon=True, name="scanner")
    scanner_thread.start()

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="monitor")
    monitor_thread.start()

    # Run the web server in the main thread
    logger.info(f"Web server starting on port {WEB_PORT}")
    uvicorn.run(web.app, host="0.0.0.0", port=WEB_PORT, log_level="warning")


if __name__ == "__main__":
    main()