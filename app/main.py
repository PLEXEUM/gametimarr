from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
import os

from app.utils.logger import setup_logger, get_logger
from app.utils.database import init_db, get_connection
from app.api import settings as settings_api

# Initialize database
init_db()

# Setup logger
setup_logger(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_max_size_mb=10,
    log_max_files=5
)
logger = get_logger()
logger.info("Gametimarr starting up...")

# Create FastAPI application
app = FastAPI(
    title="Gametimarr",
    description="Sports event downloader for NCAAF, MLB, and NFL",
    version="0.1.0"
)

# Include API routers
app.include_router(settings_api.router, prefix="/api")

# Setup templates and static files
templates = Jinja2Templates(directory="app/web/templates")

# Create static folder if it doesn't exist
static_path = Path("app/web/static")
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


# ============== ROUTES ==============

@app.get("/", response_class=HTMLResponse)
async def schedule_page(request: Request):
    """Main schedule viewer page."""
    logger.info("Serving schedule page")
    return templates.TemplateResponse("schedule.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    """Downloads history page."""
    return templates.TemplateResponse("downloads.html", {"request": request})


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/status")
async def api_status():
    """Simple API status endpoint."""
    try:
        conn = get_connection()
        sports_count = conn.execute("SELECT COUNT(*) FROM sports").fetchone()[0]
        games_count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        user_games_count = conn.execute("SELECT COUNT(*) FROM user_games").fetchone()[0]
        conn.close()
        
        return {
            "status": "ok",
            "sports": sports_count,
            "games": games_count,
            "user_games": user_games_count
        }
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return {"status": "error", "message": str(e)}


# ============== SHUTDOWN ==============

@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event."""
    logger.info("Gametimarr shutting down...")