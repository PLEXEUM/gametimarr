from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import asyncio

from app.utils.logger import setup_logger, get_logger
from app.utils.database import init_db, get_connection, get_setting, set_setting
from app.core.thesportsdb import TheSportsDBClient
from app.core.prowlarr import ProwlarrClient
from app.core.jackett import JackettClient
from app.core.qbittorrent import QBittorrentClient
from app.core.file_manager import FileManager
from app.core.scheduler import start_scheduler, stop_scheduler, get_next_run_time, run_scheduled_search

# Initialize
init_db()
setup_logger(os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger()
logger.info("Gametimarr starting up...")

app = FastAPI(title="Gametimarr", version="0.1.0")
templates = Jinja2Templates(directory="app/web/templates")

# Start scheduler on startup
start_scheduler()


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
    
    # No data yet - check if TheSportsDB is configured and try to sync
    tsdb = TheSportsDBClient()
    if tsdb.is_configured():
        logger.info(f"Syncing {sport} for {year} from TheSportsDB...")
        # Sync sport data
        await tsdb.sync_sport(sport, sport)
        # Sync events
        result = await tsdb.sync_events(sport, year)
        if result.get("success"):
            # Try again
            conn = get_connection()
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
    
    # Return sample data as fallback
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
        SELECT g.id, g.event_date, g.event_time, 
               h.name as home, a.name as away,
               s.slug as sport
        FROM games g
        JOIN teams h ON g.home_team_id = h.id
        JOIN teams a ON g.away_team_id = a.id
        JOIN sports s ON g.sport_id = s.id
        WHERE g.id IN ({placeholders})
    """, request.game_ids).fetchall()
    
    if not games:
        conn.close()
        return {"success": False, "message": "No games found"}
    
    # Update status to 'requested' for each game
    for game in games:
        conn.execute("""
            INSERT OR REPLACE INTO user_games (game_id, status, requested_at, search_query)
            VALUES (?, 'requested', datetime('now'), ?)
        """, (game["id"], f"{game['home']} vs {game['away']}"))
    
    conn.commit()
    conn.close()
    
    # Start the actual search in background
    asyncio.create_task(perform_search(games))
    
    return {
        "success": True,
        "message": f"Search started for {len(games)} games"
    }


async def perform_search(games: list):
    """Perform the actual search in the background."""
    # Try Prowlarr first, fallback to Jackett
    search_client = ProwlarrClient()
    if not search_client.is_configured():
        search_client = JackettClient()
    
    if not search_client.is_configured():
        logger.warning("No search client configured")
        return
    
    qbit = QBittorrentClient()
    if not qbit.is_configured():
        logger.warning("qBittorrent not configured")
        return
    
    for game in games:
        try:
            # Build search query
            year = game["event_date"].split("/")[-1] if game["event_date"] else None
            results = await search_client.search_sport_event(
                game["home"], 
                game["away"], 
                year
            )
            
            if results:
                # Take the first result
                release = results[0]
                download_url = await search_client.get_release_download_url(release)
                
                if download_url:
                    # Add to qBittorrent
                    result = await qbit.add_torrent(
                        download_url,
                        label=game["sport"]
                    )
                    
                    if result.get("success"):
                        # Update status to 'requested' with hash
                        conn = get_connection()
                        conn.execute("""
                            UPDATE user_games 
                            SET status = 'requested',
                                requested_at = datetime('now'),
                                search_query = ?,
                                torrent_hash = ?
                            WHERE game_id = ?
                        """, (f"{game['home']} vs {game['away']}", result.get("hash", ""), game["id"]))
                        conn.commit()
                        conn.close()
                        
                        logger.info(f"Download started for: {game['home']} vs {game['away']}")
                    else:
                        logger.error(f"Failed to add torrent for: {game['home']} vs {game['away']}")
            else:
                logger.info(f"No releases found for: {game['home']} vs {game['away']}")
                
        except Exception as e:
            logger.error(f"Error searching {game['home']} vs {game['away']}: {e}")


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
    
    # Get next scheduled run
    next_run = get_next_run_time()
    
    conn.close()
    
    return {
        "wanted": wanted,
        "requested": requested,
        "downloaded": downloaded,
        "next_run": next_run
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
    
    # Restart scheduler if schedule changed
    start_scheduler()
    
    logger.info("Settings saved")
    return {"success": True}


# ============ API - QBITTORRENT TEST ============

@app.post("/api/qbit/test")
async def test_qbit():
    """Test qBittorrent connection."""
    qbit = QBittorrentClient()
    result = await qbit.test_connection()
    return result


# ============ API - FORCE SYNC ============

@app.post("/api/sync/{sport}")
async def sync_sport(sport: str, year: int = 2026):
    """Force sync a sport from TheSportsDB."""
    tsdb = TheSportsDBClient()
    if not tsdb.is_configured():
        return {"success": False, "error": "TheSportsDB API key not configured"}
    
    # Sync sport
    result = await tsdb.sync_sport(sport, sport)
    if not result.get("success"):
        return result
    
    # Sync events
    result = await tsdb.sync_events(sport, year)
    return result


# ============ HEALTH ============

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
    logger.info("Gametimarr shutting down...")