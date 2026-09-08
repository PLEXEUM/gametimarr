import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from app.utils.logger import get_logger
from app.utils.database import get_connection, get_setting

logger = get_logger()

# Global scheduler instance
scheduler = AsyncIOScheduler()
_search_in_progress = False


async def run_scheduled_search():
    """Run a scheduled search for all wanted games."""
    global _search_in_progress
    
    if _search_in_progress:
        logger.info("Scheduled search already running, skipping")
        return
    
    _search_in_progress = True
    logger.info("Starting scheduled search...")
    
    try:
        conn = get_connection()
        
        # Get all games with status 'wanted'
        wanted = conn.execute("""
            SELECT g.id, g.event_date, g.event_time, 
                   h.name as home, a.name as away,
                   s.slug as sport
            FROM user_games ug
            JOIN games g ON ug.game_id = g.id
            JOIN teams h ON g.home_team_id = h.id
            JOIN teams a ON g.away_team_id = a.id
            JOIN sports s ON g.sport_id = s.id
            WHERE ug.status = 'wanted'
        """).fetchall()
        
        conn.close()
        
        if not wanted:
            logger.info("No wanted games found")
            return
        
        logger.info(f"Found {len(wanted)} wanted games to search")
        
        # Import here to avoid circular imports
        from app.core.prowlarr import ProwlarrClient
        from app.core.jackett import JackettClient
        from app.core.qbittorrent import QBittorrentClient
        
        # Try Prowlarr first, fallback to Jackett
        search_client = ProwlarrClient()
        if not search_client.is_configured():
            search_client = JackettClient()
        
        if not search_client.is_configured():
            logger.warning("No search client configured (Prowlarr or Jackett)")
            return
        
        qbit = QBittorrentClient()
        if not qbit.is_configured():
            logger.warning("qBittorrent not configured")
            return
        
        # Search each game
        for game in wanted:
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
                            # Update status to 'requested'
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
        
        logger.info("Scheduled search complete")
        
    except Exception as e:
        logger.error(f"Scheduled search failed: {e}")
    finally:
        _search_in_progress = False


def start_scheduler():
    """Start the scheduler with the configured schedule."""
    global scheduler
    
    schedule_str = get_setting("search_schedule") or "0 */4 * * *"
    
    try:
        trigger = CronTrigger.from_crontab(schedule_str)
        
        if scheduler.running:
            scheduler.shutdown()
        
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_scheduled_search,
            trigger=trigger,
            id="gametimarr_search",
            name="Gametimarr Search"
        )
        scheduler.start()
        logger.info(f"Scheduler started with schedule: {schedule_str}")
        return True
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return False


def stop_scheduler():
    """Stop the scheduler."""
    global scheduler
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


def get_next_run_time() -> str:
    """Get the next scheduled run time."""
    job = scheduler.get_job("gametimarr_search")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    return "Not scheduled"