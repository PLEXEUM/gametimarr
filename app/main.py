from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import json

from app.utils.logger import setup_logger, get_logger
from app.utils.database import init_db, get_connection, get_setting, set_setting

# Initialize
init_db()
setup_logger(os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger()
logger.info("Gametimarr starting up...")

app = FastAPI(title="Gametimarr", version="0.1.0")
templates = Jinja2Templates(directory="app/web/templates")


# ============ MODELS ============

class SearchRequest(BaseModel):
    game_ids: List[int]


class SettingsRequest(BaseModel):
    thesportsdb_api_key: Optional[str] = None
    prowlarr_url: Optional[str] = None
    prowlarr_api_key: Optional[str] = None
    qbit_host: Optional[str] = None
    qbit_port: Optional[str] = None
    qbit_username: Optional[str] = None
    qbit_password: Optional[str] = None
    search_schedule: Optional[str] = None
    sport_folders: Optional[str] = None


# ============ FRONTEND ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Single page application."""
    return templates.TemplateResponse("index.html", {"request": request})


# ============ API - SCHEDULE ============

@app.get("/api/schedule")
async def get_schedule(sport: str = "NCAAF", year: int = 2026):
    """Get schedule for a sport and year."""
    conn = get_connection()
    
    # Try to get from database first
    games = conn.execute("""
        SELECT g.id, g.event_date as date, g.event_time as time,
               h.name as home, a.name as away,
               COALESCE(ug.status, 'wanted') as status
        FROM games g
        JOIN teams h ON g.home_team_id = h.id
        JOIN teams a ON g.away_team_id = a.id
        LEFT JOIN user_games ug ON g.id = ug.game_id
        WHERE g.sport_id = (SELECT id FROM sports WHERE slug = ?)
        AND g.year = ?
        ORDER BY g.event_date
    """, (sport, year)).fetchall()
    
    conn.close()
    
    if games:
        return [dict(row) for row in games]
    
    # No data yet - return sample data
    return get_sample_schedule(sport, year)


def get_sample_schedule(sport: str, year: int):
    """Return sample data until TheSportsDB is integrated."""
    samples = {
        "NCAAF": [
            {"id": 1, "date": f"09/05/{year}", "time": "7:30 PM", "home": "Auburn", "away": "Baylor", "status": "wanted"},
            {"id": 2, "date": f"09/05/{year}", "time": "3:30 PM", "home": "Alabama", "away": "Ohio State", "status": "wanted"},
            {"id": 3, "date": f"09/12/{year}", "time": "8:00 PM", "home": "Texas", "away": "Oklahoma", "status": "wanted"},
            {"id": 4, "date": f"09/12/{year}", "time": "12:00 PM", "home": "Clemson", "away": "Florida State", "status": "wanted"},
            {"id": 5, "date": f"09/19/{year}", "time": "7:00 PM", "home": "Georgia", "away": "Tennessee", "status": "wanted"},
        ],
        "NFL": [
            {"id": 101, "date": f"09/10/{year}", "time": "8:20 PM", "home": "Chiefs", "away": "Ravens", "status": "wanted"},
            {"id": 102, "date": f"09/13/{year}", "time": "1:00 PM", "home": "Cowboys", "away": "Giants", "status": "wanted"},
            {"id": 103, "date": f"09/13/{year}", "time": "4:25 PM", "home": "49ers", "away": "Packers", "status": "wanted"},
        ],
        "MLB": [
            {"id": 201, "date": f"09/05/{year}", "time": "7:05 PM", "home": "Yankees", "away": "Red Sox", "status": "wanted"},
            {"id": 202, "date": f"09/06/{year}", "time": "4:10 PM", "home": "Dodgers", "away": "Padres", "status": "wanted"},
            {"id": 203, "date": f"09/07/{year}", "time": "7:15 PM", "home": "Mets", "away": "Braves", "status": "wanted"},
        ]
    }
    return samples.get(sport, [])


# ============ API - SEARCH ============

@app.post("/api/search")
async def search_games(request: SearchRequest):
    """Search for selected games."""
    if not request.game_ids:
        return {"success": False, "message": "No games selected"}
    
    logger.info(f"Searching for {len(request.game_ids)} games")
    
    conn = get_connection()
    placeholders = ",".join("?" * len(request.game_ids))
    games = conn.execute(f"""
        SELECT g.id, g.event_date, g.event_time, h.name as home, a.name as away
        FROM games g
        JOIN teams h ON g.home_team_id = h.id
        JOIN teams a ON g.away_team_id = a.id
        WHERE g.id IN ({placeholders})
    """, request.game_ids).fetchall()
    
    # Update status to 'requested' for each game
    for game in games:
        conn.execute("""
            INSERT OR REPLACE INTO user_games (game_id, status, requested_at, search_query)
            VALUES (?, 'requested', datetime('now'), ?)
        """, (game["id"], f"{game['home']} {game['away']}"))
    
    conn.commit()
    conn.close()
    
    # TODO: Actual search logic goes here (Prowlarr + qBittorrent)
    # For now, just mark as requested
    
    return {
        "success": True,
        "message": f"Search started for {len(games)} games"
    }


# ============ API - STATUS ============

@app.get("/api/status")
async def get_status():
    """Get counts of games by status."""
    conn = get_connection()
    
    wanted = conn.execute(
        "SELECT COUNT(*) FROM user_games WHERE status = 'wanted'"
    ).fetchone()[0]
    requested = conn.execute(
        "SELECT COUNT(*) FROM user_games WHERE status = 'requested'"
    ).fetchone()[0]
    downloaded = conn.execute(
        "SELECT COUNT(*) FROM user_games WHERE status = 'downloaded'"
    ).fetchone()[0]
    
    conn.close()
    
    return {
        "wanted": wanted,
        "requested": requested,
        "downloaded": downloaded
    }


# ============ API - SETTINGS ============

@app.get("/api/settings")
async def get_settings():
    """Get all settings."""
    return {
        "thesportsdb_api_key": get_setting("thesportsdb_api_key"),
        "prowlarr_url": get_setting("prowlarr_url"),
        "prowlarr_api_key": get_setting("prowlarr_api_key"),
        "qbit_host": get_setting("qbit_host"),
        "qbit_port": get_setting("qbit_port"),
        "qbit_username": get_setting("qbit_username"),
        "qbit_password": get_setting("qbit_password"),
        "search_schedule": get_setting("search_schedule"),
        "sport_folders": get_setting("sport_folders"),
    }


@app.post("/api/settings")
async def save_settings(data: SettingsRequest):
    """Save all settings."""
    for key, value in data.dict().items():
        if value is not None:
            set_setting(key, value)
    
    logger.info("Settings saved")
    return {"success": True}


# ============ HEALTH ============

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("shutdown")
async def shutdown():
    logger.info("Gametimarr shutting down...")