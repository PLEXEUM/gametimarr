import httpx
from datetime import datetime, timedelta
from app.utils.logger import get_logger
from app.utils.database import get_connection, get_setting

logger = get_logger()

# ESPN API Base URL
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

# Sport mappings
SPORT_MAPPINGS = {
    "NCAAF": "football/college-football",
    "NFL": "football/nfl",
    "MLB": "baseball/mlb"
}

# Season start dates (month/day for each sport)
SEASON_STARTS = {
    "NCAAF": (8, 27),   # August 27
    "NFL": (9, 5),      # September 5
    "MLB": (3, 30)      # March 30
}


class ESPNClient:
    def __init__(self):
        self.base_url = BASE_URL

    async def _request(self, url: str) -> dict:
        """Make a request to ESPN API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"ESPN API error: {e}")
            return {"error": str(e)}

    def get_season_start(self, sport_slug: str, year: int) -> datetime:
        """Get the season start date for a sport."""
        month, day = SEASON_STARTS.get(sport_slug, (8, 27))
        return datetime(year, month, day)

    async def get_events(self, sport_slug: str, year: int) -> list:
        """
        Fetch events for a sport from season start to today + 30 days.
        Returns list of events with no score data.
        """
        sport_path = SPORT_MAPPINGS.get(sport_slug)
        if not sport_path:
            logger.error(f"Unknown sport: {sport_slug}")
            return []

        all_events = []
        seen = set()

        # Calculate date range
        start_date = self.get_season_start(sport_slug, year)
        end_date = datetime.now() + timedelta(days=30)

        # If today is before season start, start from season start
        if datetime.now() < start_date:
            start_date = datetime.now()

        # Loop through each day
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            url = f"{self.base_url}/{sport_path}/scoreboard?dates={date_str}"
            
            logger.info(f"Fetching events for {sport_slug} on {date_str}")
            data = await self._request(url)
            
            if "error" in data:
                break

            events = data.get("events", [])
            for event in events:
                event_id = event.get("id")
                if event_id and event_id not in seen:
                    seen.add(event_id)
                    parsed = self._parse_event(event, sport_slug)
                    if parsed:
                        all_events.append(parsed)

            current += timedelta(days=1)

        logger.info(f"Total events found for {sport_slug}: {len(all_events)}")
        return all_events

    def _parse_event(self, event: dict, sport_slug: str) -> dict:
        """
        Parse an ESPN event, extracting only:
        - Teams (home/away)
        - Date
        - Time
        - Status (scheduled, postponed, completed)
        No scores!
        """
        try:
            # Get competition data
            competitions = event.get("competitions", [])
            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                return None

            # Determine home and away
            home_team = None
            away_team = None
            for team in competitors:
                if team.get("homeAway") == "home":
                    home_team = team
                elif team.get("homeAway") == "away":
                    away_team = team

            if not home_team or not away_team:
                return None

            # Extract team names
            home_name = home_team.get("team", {}).get("displayName", "Unknown")
            away_name = away_team.get("team", {}).get("displayName", "Unknown")

            # Extract date and time
            event_date = event.get("date", "")
            event_time = ""
            if event_date:
                try:
                    dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                    event_date_str = dt.strftime("%Y-%m-%d")
                    event_time_str = dt.strftime("%I:%M %p").lstrip("0")
                    event_time = event_time_str
                except:
                    event_date_str = event_date.split("T")[0] if "T" in event_date else event_date
                    event_time = ""
            else:
                event_date_str = ""

            # Extract status
            status = "Scheduled"
            status_data = event.get("status", {})
            status_type = status_data.get("type", {})
            status_desc = status_type.get("description", "").lower()

            if status_desc == "postponed":
                status = "Postponed"
            elif status_desc == "canceled":
                status = "Canceled"
            elif status_desc in ["final", "completed", "done"]:
                status = "Completed"
            elif status_desc in ["scheduled", "upcoming"]:
                status = "Scheduled"
            else:
                status = "Scheduled"

            return {
                "id": event.get("id"),
                "home_team": home_name,
                "away_team": away_name,
                "date": event_date_str,
                "time": event_time,
                "status": status,
                "sport": sport_slug,
                "external_id": event.get("id")
            }

        except Exception as e:
            logger.error(f"Error parsing event: {e}")
            return None