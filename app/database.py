"""
database.py - SQLite persistence layer for gametimarr.

Owns the schema and all read/write helpers. No network calls, no business logic.
Every other module talks to the database through the functions defined here.

Tables:
    settings  - key/value store for user configuration
    watchlist - teams to follow, with optional aliases
    grabbed   - GUIDs already handed to qBittorrent (for dedup)
    log       - recent activity, pruned to N entries
"""

import sqlite3
import os
import threading
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_db_path = None
_conn = None
_lock = threading.Lock()

# Number of log entries to retain (matches the UI requirement)
LOG_RETENTION = 5

# How long a grabbed GUID stays in the dedup table (hours)
GRAB_RETENTION_HOURS = 48


def init_db(db_path: str) -> None:
    """
    Initialize the database connection and create tables if they don't exist.
    Called once at startup from main.py.
    """
    global _db_path, _conn

    _db_path = db_path

    # Ensure the directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    # check_same_thread=False because we share the connection across threads
    # (scanner thread, monitor thread, web server thread). All writes go
    # through _lock to keep things safe.
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row

    _create_tables()


def _create_tables() -> None:
    """Create the four tables if they don't already exist."""
    with _lock:
        cur = _conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                team    TEXT PRIMARY KEY,
                aliases TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS grabbed (
                guid         TEXT PRIMARY KEY,
                title        TEXT,
                torrent_hash TEXT,
                grabbed_at   TEXT,
                copied_at    TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                message   TEXT
            )
        """)

        _conn.commit()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = None) -> str:
    """Return the value for a setting key, or default if not set."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Insert or update a setting."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        _conn.commit()


def get_all_settings() -> dict:
    """Return all settings as a dict. Useful for the web UI."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def get_watchlist() -> list:
    """
    Return the watchlist as a list of dicts:
        [{"team": "New England Patriots", "aliases": "Patriots, NE Patriots"}, ...]
    """
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT team, aliases FROM watchlist ORDER BY team")
        return [{"team": row["team"], "aliases": row["aliases"] or ""} for row in cur.fetchall()]


def add_team(team: str, aliases: str = "") -> None:
    """Add a team to the watchlist, or update its aliases if it already exists."""
    team = team.strip()
    if not team:
        return
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT INTO watchlist (team, aliases) VALUES (?, ?)
            ON CONFLICT(team) DO UPDATE SET aliases = excluded.aliases
        """, (team, aliases.strip()))
        _conn.commit()


def remove_team(team: str) -> None:
    """Remove a team from the watchlist."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("DELETE FROM watchlist WHERE team = ?", (team,))
        _conn.commit()


# ---------------------------------------------------------------------------
# Grabbed (dedup)
# ---------------------------------------------------------------------------

def is_grabbed(guid: str) -> bool:
    """Return True if this GUID has already been handed to qBittorrent."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT 1 FROM grabbed WHERE guid = ?", (guid,))
        return cur.fetchone() is not None


def record_grab(guid: str, title: str, torrent_hash: str = "") -> None:
    """Record that a GUID has been grabbed."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO grabbed (guid, title, torrent_hash, grabbed_at, copied_at)
            VALUES (?, ?, ?, ?, NULL)
        """, (guid, title, torrent_hash, _now_iso()))
        _conn.commit()


def record_copy(guid: str) -> None:
    """Mark a grabbed row as copied to the destination folder."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("UPDATE grabbed SET copied_at = ? WHERE guid = ?", (_now_iso(), guid))
        _conn.commit()


def get_grabbed_by_hash(torrent_hash: str) -> dict:
    """Look up a grabbed row by torrent hash. Used by postprocess."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT * FROM grabbed WHERE torrent_hash = ?", (torrent_hash,))
        row = cur.fetchone()
        return dict(row) if row else {}


def get_uncopied() -> list:
    """Return grabbed rows that have a torrent_hash but haven't been copied yet."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            SELECT * FROM grabbed
            WHERE torrent_hash != '' AND copied_at IS NULL
        """)
        return [dict(row) for row in cur.fetchall()]


def expire_old_grabs() -> None:
    """
    Delete grabbed rows older than GRAB_RETENTION_HOURS whose copy is done.
    Rows that haven't been copied yet are kept, so a failed copy can retry.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=GRAB_RETENTION_HOURS)).isoformat()
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            DELETE FROM grabbed
            WHERE grabbed_at < ? AND copied_at IS NOT NULL
        """, (cutoff,))
        _conn.commit()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def log_event(message: str) -> None:
    """Append an event to the log, then prune to LOG_RETENTION entries."""
    with _lock:
        cur = _conn.cursor()
        cur.execute(
            "INSERT INTO log (timestamp, message) VALUES (?, ?)",
            (_now_iso(), message)
        )
        # Keep only the newest N entries
        cur.execute("""
            DELETE FROM log WHERE id NOT IN (
                SELECT id FROM log ORDER BY id DESC LIMIT ?
            )
        """, (LOG_RETENTION,))
        _conn.commit()


def get_recent_log() -> list:
    """Return the log entries, newest first."""
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT timestamp, message FROM log ORDER BY id DESC")
        return [{"timestamp": row["timestamp"], "message": row["message"]} for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC time as an ISO string. Stored consistently everywhere."""
    return datetime.utcnow().isoformat(timespec="seconds")