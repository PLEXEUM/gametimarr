"""
database.py - SQLite persistence layer for gametimarr.

Tables:
    settings  - key/value store for user configuration
    watchlist - teams to follow, with optional aliases
    grabbed   - GUIDs already handed to qBittorrent (for dedup)
"""

import sqlite3
import os
import threading
from datetime import datetime, timedelta


_db_path = None
_conn = None
_lock = threading.Lock()

GRAB_RETENTION_HOURS = 48


def init_db(db_path: str) -> None:
    global _db_path, _conn

    _db_path = db_path

    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row

    _create_tables()


def _create_tables() -> None:
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
                aliases TEXT,
                sport   TEXT DEFAULT ''
            )
        """)

        # If the table already existed from a previous version, add the sport column.
        cur.execute("PRAGMA table_info(watchlist)")
        columns = [row[1] for row in cur.fetchall()]
        if "sport" not in columns:
            cur.execute("ALTER TABLE watchlist ADD COLUMN sport TEXT DEFAULT ''")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS grabbed (
                guid         TEXT PRIMARY KEY,
                title        TEXT,
                torrent_hash TEXT,
                grabbed_at   TEXT,
                copied_at    TEXT
            )
        """)

        _conn.commit()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = None) -> str:
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        _conn.commit()


def get_all_settings() -> dict:
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def get_watchlist() -> list:
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT team, aliases, sport FROM watchlist ORDER BY team")
        return [
            {
                "team": row["team"],
                "aliases": row["aliases"] or "",
                "sport": row["sport"] or "",
            }
            for row in cur.fetchall()
        ]

def add_team(team: str, aliases: str = "", sport: str = "") -> None:
    team = team.strip()
    if not team:
        return
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT INTO watchlist (team, aliases, sport) VALUES (?, ?, ?)
            ON CONFLICT(team) DO UPDATE SET
                aliases = excluded.aliases,
                sport = excluded.sport
        """, (team, aliases.strip(), sport.strip()))
        _conn.commit()


def remove_team(team: str) -> None:
    with _lock:
        cur = _conn.cursor()
        cur.execute("DELETE FROM watchlist WHERE team = ?", (team,))
        _conn.commit()


# ---------------------------------------------------------------------------
# Grabbed (dedup)
# ---------------------------------------------------------------------------

def is_grabbed(guid: str) -> bool:
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT 1 FROM grabbed WHERE guid = ?", (guid,))
        return cur.fetchone() is not None


def record_grab(guid: str, title: str, torrent_hash: str = "") -> None:
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO grabbed (guid, title, torrent_hash, grabbed_at, copied_at)
            VALUES (?, ?, ?, ?, NULL)
        """, (guid, title, torrent_hash, _now_iso()))
        _conn.commit()


def record_copy(guid: str) -> None:
    with _lock:
        cur = _conn.cursor()
        cur.execute("UPDATE grabbed SET copied_at = ? WHERE guid = ?", (_now_iso(), guid))
        _conn.commit()


def get_grabbed_by_hash(torrent_hash: str) -> dict:
    with _lock:
        cur = _conn.cursor()
        cur.execute("SELECT * FROM grabbed WHERE torrent_hash = ?", (torrent_hash,))
        row = cur.fetchone()
        return dict(row) if row else {}


def get_uncopied() -> list:
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            SELECT * FROM grabbed
            WHERE torrent_hash != '' AND copied_at IS NULL
        """)
        return [dict(row) for row in cur.fetchall()]


def expire_old_grabs() -> None:
    cutoff = (datetime.utcnow() - timedelta(hours=GRAB_RETENTION_HOURS)).isoformat()
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            DELETE FROM grabbed
            WHERE grabbed_at < ? AND copied_at IS NOT NULL
        """, (cutoff,))
        _conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")