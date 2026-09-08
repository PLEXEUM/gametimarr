import sqlite3
import os
from pathlib import Path

DB_PATH = Path("/app/config/gametimarr.db")


def get_connection():
    """Get a database connection."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create minimal tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- Sports lookup
        CREATE TABLE IF NOT EXISTS sports (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE
        );

        -- Teams
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sport_id INTEGER,
            external_id TEXT,
            FOREIGN KEY (sport_id) REFERENCES sports(id)
        );

        -- Games (updated with status column)
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY,
            sport_id INTEGER,
            home_team_id INTEGER,
            away_team_id INTEGER,
            event_date TEXT NOT NULL,
            event_time TEXT,
            year INTEGER,
            external_id TEXT UNIQUE,
            status TEXT DEFAULT 'Scheduled',
            FOREIGN KEY (sport_id) REFERENCES sports(id),
            FOREIGN KEY (home_team_id) REFERENCES teams(id),
            FOREIGN KEY (away_team_id) REFERENCES teams(id)
        );

        -- User selections and download status
        CREATE TABLE IF NOT EXISTS user_games (
            id INTEGER PRIMARY KEY,
            game_id INTEGER NOT NULL,
            status TEXT DEFAULT 'wanted',  -- wanted, requested, downloaded
            search_query TEXT,
            torrent_hash TEXT,
            downloaded_file TEXT,
            requested_at DATETIME,
            downloaded_at DATETIME,
            FOREIGN KEY (game_id) REFERENCES games(id)
        );

        -- Settings (key-value for simple config)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Indexes for speed
        CREATE INDEX IF NOT EXISTS idx_games_date ON games(event_date);
        CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
        CREATE INDEX IF NOT EXISTS idx_user_games_status ON user_games(status);
    """)

    # Insert default settings if missing
    defaults = [
        ('search_schedule', '0 */4 * * *'),
        ('sport_folders', '{"NCAAF":"/media/NCAAF","NFL":"/media/NFL","MLB":"/media/MLB"}'),
    ]
    
    for key, value in defaults:
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    """Get a setting value."""
    conn = get_connection()
    result = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return result["value"] if result else ""


def set_setting(key: str, value: str) -> None:
    """Set a setting value."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()