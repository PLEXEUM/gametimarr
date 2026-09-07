from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
import json

from app.utils.database import get_connection
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


# ============== PYDANTIC MODELS ==============

class TheSportsDbSettings(BaseModel):
    api_key: str


class ProwlarrSettings(BaseModel):
    url: str
    api_key: str


class QbitSettings(BaseModel):
    host: str
    port: int
    username: str
    password: str


class FolderSettings(BaseModel):
    folders: Dict[str, str]


class ScheduleSettings(BaseModel):
    schedule: str


# ============== GET ALL SETTINGS ==============

@router.get("/settings")
async def get_all_settings():
    """Get all settings."""
    conn = get_connection()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    
    if not settings:
        return {
            "thesportsdb_api_key": None,
            "prowlarr_url": None,
            "prowlarr_api_key": None,
            "qbit_host": "localhost",
            "qbit_port": 8080,
            "qbit_username": "admin",
            "qbit_password": None,
            "search_schedule": "0 */4 * * *",
            "sport_folders": {}
        }
    
    # Parse JSON folders
    folders = {}
    if settings["sport_folders"]:
        try:
            folders = json.loads(settings["sport_folders"])
        except:
            folders = {}
    
    return {
        "thesportsdb_api_key": settings["thesportsdb_api_key"],
        "prowlarr_url": settings["prowlarr_url"],
        "prowlarr_api_key": settings["prowlarr_api_key"],
        "qbit_host": settings["qbit_host"] or "localhost",
        "qbit_port": settings["qbit_port"] or 8080,
        "qbit_username": settings["qbit_username"] or "admin",
        "qbit_password": settings["qbit_password"],
        "search_schedule": settings["search_schedule"] or "0 */4 * * *",
        "sport_folders": folders
    }


# ============== SETTINGS ENDPOINTS ==============

@router.post("/settings/thesportsdb")
async def save_thesportsdb_settings(data: TheSportsDbSettings):
    """Save TheSportsDB API key."""
    if not data.api_key or len(data.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key format")
    
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE settings SET 
                thesportsdb_api_key = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (data.api_key,))
        conn.commit()
        logger.info("TheSportsDB API key saved")
        return {"success": True, "message": "API key saved"}
    except Exception as e:
        logger.error(f"Failed to save TheSportsDB key: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/settings/prowlarr")
async def save_prowlarr_settings(data: ProwlarrSettings):
    """Save Prowlarr settings."""
    if not data.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    if not data.api_key or len(data.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key format")
    
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE settings SET 
                prowlarr_url = ?,
                prowlarr_api_key = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (data.url.rstrip("/"), data.api_key))
        conn.commit()
        logger.info(f"Prowlarr settings saved: {data.url}")
        return {"success": True, "message": "Prowlarr settings saved"}
    except Exception as e:
        logger.error(f"Failed to save Prowlarr settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/settings/qbit")
async def save_qbit_settings(data: QbitSettings):
    """Save qBittorrent settings."""
    if not data.host:
        raise HTTPException(status_code=400, detail="Host is required")
    if data.port < 1 or data.port > 65535:
        raise HTTPException(status_code=400, detail="Invalid port number")
    
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE settings SET 
                qbit_host = ?,
                qbit_port = ?,
                qbit_username = ?,
                qbit_password = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (data.host, data.port, data.username, data.password))
        conn.commit()
        logger.info(f"qBittorrent settings saved: {data.host}:{data.port}")
        return {"success": True, "message": "qBittorrent settings saved"}
    except Exception as e:
        logger.error(f"Failed to save qBittorrent settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/settings/folders")
async def save_sport_folders(data: FolderSettings):
    """Save sport folder paths."""
    # Validate folders
    for sport, path in data.folders.items():
        if path and not path.startswith("/"):
            raise HTTPException(
                status_code=400, 
                detail=f"Path for {sport} must be absolute (start with /)"
            )
    
    conn = get_connection()
    try:
        folders_json = json.dumps(data.folders)
        conn.execute("""
            UPDATE settings SET 
                sport_folders = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (folders_json,))
        conn.commit()
        logger.info("Sport folders saved")
        return {"success": True, "message": "Folders saved"}
    except Exception as e:
        logger.error(f"Failed to save folders: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/settings/schedule")
async def save_schedule_settings(data: ScheduleSettings):
    """Save search schedule."""
    # Basic cron validation (5 fields)
    parts = data.schedule.strip().split()
    if len(parts) != 5:
        raise HTTPException(
            status_code=400, 
            detail="Cron expression must have exactly 5 fields"
        )
    
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE settings SET 
                search_schedule = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (data.schedule,))
        conn.commit()
        logger.info(f"Schedule saved: {data.schedule}")
        return {"success": True, "message": "Schedule saved"}
    except Exception as e:
        logger.error(f"Failed to save schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============== QBITTORRENT TEST ==============

@router.post("/qbit/test")
async def test_qbit_connection():
    """Test qBittorrent connection using saved settings."""
    conn = get_connection()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    
    if not settings or not settings["qbit_host"]:
        raise HTTPException(status_code=400, detail="qBittorrent not configured")
    
    # TODO: Import and use QbitClient when created
    # For now, return a placeholder
    return {
        "success": True,
        "message": "Connection successful (placeholder - QbitClient not yet implemented)"
    }