import httpx
from datetime import datetime
from app.utils.logger import get_logger
from app.utils.database import get_connection, get_setting

logger = get_logger()
BASE_URL = "https://www.thesportsdb.com/api/v1/json"

# Known league IDs for our supported sports
LEAGUE_IDS = {
    "NCAAF": "4479",
    "NFL": "4391",
    "MLB": "4424"
}


class TheSportsDBClient:
    def __init__(self):
        self.api_key = get_setting("thesportsdb_api_key")
        if not self.api_key:
            logger.warning("TheSportsDB API key not configured")
        self.base_url = f"{BASE_URL}/{self.api_key}" if self.api_key else None

    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    async def _request(self, endpoint: str) -> dict:
        """Make a request to TheSportsDB API."""
        if not self.api_key:
            return {"error": "API key not configured"}

        url = f"{self.base_url}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"TheSportsDB API error: {e}")
            return {"error": str(e)}

    async def get_sports(self) -> list:
        """Get all sports from TheSportsDB."""
        data = await self._request("all_sports.php")
        return data.get("sports", [])

    async def get_leagues(self, sport_name: str) -> list:
        """Get leagues for a specific sport."""
        data = await self._request(f"search_all_leagues.php?s={sport_name}")
        return data.get("leagues", [])

    async def get_teams(self, league_id: str) -> list:
        """Get teams for a specific league."""
        data = await self._request(f"lookup_all_teams.php?id={league_id}")
        return data.get("teams", [])

    async def get_events_by_league(self, league_id: str, season: str) -> list:
        """Get events for a league and season."""
        data = await self._request(f"eventsseason.php?id={league_id}&s={season}")
        return data.get("events", [])

    async def sync_sport(self, sport_slug: str, sport_name: str) -> dict:
        """Sync a specific sport and its data."""
        if not self.is_configured():
            return {"success": False, "error": "API key not configured"}

        conn = get_connection()
        try:
            # Get the sport ID from database or create it
            sport = conn.execute(
                "SELECT id FROM sports WHERE slug = ?", (sport_slug,)
            ).fetchone()

            if not sport:
                cursor = conn.execute(
                    "INSERT INTO sports (slug, name) VALUES (?, ?)",
                    (sport_slug, sport_name)
                )
                conn.commit()
                sport_id = cursor.lastrowid  # ← FIXED: use cursor.lastrowid
            else:
                sport_id = sport["id"]

            # Get the known league ID for this sport
            league_id = LEAGUE_IDS.get(sport_slug)
            if not league_id:
                return {"success": False, "error": f"No league ID for {sport_slug}"}

            # Get teams for this league directly
            teams = await self.get_teams(league_id)
            team_count = 0
            
            for team in teams:
                team_name = team.get("strTeam")
                if team_name:
                    conn.execute(
                        """INSERT OR IGNORE INTO teams (name, sport_id, external_id)
                           VALUES (?, ?, ?)""",
                        (team_name, sport_id, team.get("idTeam"))
                    )
                    team_count += 1
            
            conn.commit()
            logger.info(f"Synced {team_count} teams for {sport_slug}")
            return {"success": True, "teams_found": team_count}

        except Exception as e:
            logger.error(f"Failed to sync sport {sport_slug}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    async def sync_events(self, sport_slug: str, year: int) -> dict:
    async def sync_events(self, sport_slug: str, year: int) -> dict:
        """Sync events for a sport and year using known league IDs."""
        if not self.is_configured():
            return {"success": False, "error": "API key not configured"}

        # Known league IDs
        league_ids = {
            "NCAAF": "4479",
            "NFL": "4391",
            "MLB": "4424"
        }
    
        league_id = league_ids.get(sport_slug)
        if not league_id:
            return {"success": False, "error": f"No league ID for {sport_slug}"}

        conn = get_connection()
        try:
            sport = conn.execute(
                "SELECT id FROM sports WHERE slug = ?", (sport_slug,)
            ).fetchone()

            if not sport:
                return {"success": False, "error": f"Sport {sport_slug} not found"}

            sport_id = sport["id"]

            # Get events directly from API using the known league ID
            events = await self.get_events_by_league(league_id, str(year))
            events_added = 0

            for event in events:
                home_team = event.get("strHomeTeam")
                away_team = event.get("strAwayTeam")
                event_date = event.get("dateEvent")  # Format: 2026-08-27
                event_time = event.get("strTime") or event.get("strTimeLocal") or ""

                if not home_team or not away_team or not event_date:
                    continue

                # Get or create team IDs
                home = conn.execute(
                    "SELECT id FROM teams WHERE name = ? AND sport_id = ?",
                    (home_team, sport_id)
                ).fetchone()
            
                # If team doesn't exist, create it
                if not home:
                    cursor = conn.execute(
                        "INSERT INTO teams (name, sport_id) VALUES (?, ?)",
                        (home_team, sport_id)
                    )
                    conn.commit()
                    home_id = cursor.lastrowid
                else:
                    home_id = home["id"]

                away = conn.execute(
                    "SELECT id FROM teams WHERE name = ? AND sport_id = ?",
                    (away_team, sport_id)
                ).fetchone()
            
                if not away:
                    cursor = conn.execute(
                        "INSERT INTO teams (name, sport_id) VALUES (?, ?)",
                        (away_team, sport_id)
                    )
                    conn.commit()
                    away_id = cursor.lastrowid
                else:
                    away_id = away["id"]

                # Insert or update game
                conn.execute(
                    """INSERT OR REPLACE INTO games 
                       (sport_id, home_team_id, away_team_id, event_date, event_time, year, external_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (sport_id, home_id, away_id, event_date, event_time, year, event.get("idEvent"))
                )
                events_added += 1

            conn.commit()
            logger.info(f"Synced {events_added} events for {sport_slug} {year}")
            return {"success": True, "events_added": events_added}

        except Exception as e:
            logger.error(f"Failed to sync events for {sport_slug} {year}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()