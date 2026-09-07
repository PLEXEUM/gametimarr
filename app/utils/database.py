import sqlite3
import os
from pathlib import Path

# Path to the database file inside the config volume
DB_PATH = Path("/app/config/gametimarr.db")


def get_connection():
    """Get a database connection with WAL mode enabled."""
    # Ensure the config directory exists
    os.makedirs(DB_PATH.parent, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL for concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist yet."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- Sports lookup table
        CREATE TABLE IF NOT EXISTS sports (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            external_id TEXT
        );

        -- Teams table
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            short_name TEXT,
            sport_id INTEGER,
            external_id TEXT,
            FOREIGN KEY (sport_id) REFERENCES sports(id)
        );

        -- Games table (synced from TheSportsDB)
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY,
            sport_id INTEGER,
            home_team_id INTEGER,
            away_team_id INTEGER,
            event_date TEXT NOT NULL,
            event_time TEXT,
            venue TEXT,
            external_id TEXT UNIQUE,
            year INTEGER,
            FOREIGN KEY (sport_id) REFERENCES sports(id),
            FOREIGN KEY (home_team_id) REFERENCES teams(id),
            FOREIGN KEY (away_team_id) REFERENCES teams(id)
        );

        -- User game selections and download tracking
        CREATE TABLE IF NOT EXISTS user_games (
            id INTEGER PRIMARY KEY,
            game_id INTEGER NOT NULL,
            status TEXT DEFAULT 'wanted',  -- 'wanted', 'requested', 'downloaded', 'failed'
            search_query TEXT,
            torrent_hash TEXT,
            download_path TEXT,
            copied_path TEXT,
            requested_at DATETIME,
            downloaded_at DATETIME,
            error_message TEXT,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        );

        -- Settings table
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            thesportsdb_api_key TEXT,
            prowlarr_url TEXT,
            prowlarr_api_key TEXT,
            qbit_host TEXT DEFAULT 'localhost',
            qbit_port INTEGER DEFAULT 8080,
            qbit_username TEXT DEFAULT 'admin',
            qbit_password TEXT,
            search_schedule TEXT DEFAULT '0 */4 * * *',
            sport_folders TEXT,  -- JSON stored as text
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Search history
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY,
            game_id INTEGER,
            search_query TEXT,
            results_count INTEGER,
            selected_release TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games(id)
        );

        -- Create indexes for faster lookups
        CREATE INDEX IF NOT EXISTS idx_games_date ON games(event_date);
        CREATE INDEX IF NOT EXISTS idx_games_sport ON games(sport_id);
        CREATE INDEX IF NOT EXISTS idx_user_games_status ON user_games(status);
        CREATE INDEX IF NOT EXISTS idx_user_games_game ON user_games(game_id);
        CREATE INDEX IF NOT EXISTS idx_teams_sport ON teams(sport_id);
        CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name);
    """)

    # Check if settings exist, if not create default
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if not settings:
        conn.execute("""
            INSERT INTO settings (id, search_schedule, sport_folders)
            VALUES (1, '0 */4 * * *', '{}')
        """)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")