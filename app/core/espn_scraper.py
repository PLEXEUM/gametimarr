import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from app.utils.logger import get_logger

logger = get_logger()

# TeamRankings schedule URLs
SPORT_URLS = {
    "NCAAF": "https://www.teamrankings.com/ncf/schedules/season/",
    "NFL": "https://www.teamrankings.com/nfl/schedules/season/",
    "MLB": "https://www.teamrankings.com/mlb/schedules/season/"
}


class ESPNScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def fetch_page(self, url: str) -> str:
        """Fetch the HTML content of a page."""
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Failed to fetch page {url}: {e}")
            return ""

    async def get_events(self, sport_slug: str) -> list:
        """Fetch and parse events for a sport from TeamRankings."""
        url = SPORT_URLS.get(sport_slug)
        if not url:
            logger.error(f"Unknown sport: {sport_slug}")
            return []

        logger.info(f"Fetching schedule for {sport_slug} from {url}")
        html = await self.fetch_page(url)

        if not html:
            logger.error(f"Failed to fetch schedule for {sport_slug}")
            return []

        games = self._parse_teamrankings(html, sport_slug)

        # No filter - keep all games from the full season
        filtered = games

        logger.info(f"Found {len(filtered)} games for {sport_slug} (filtered from {len(games)})")
        return filtered

    def _parse_teamrankings(self, html: str, sport_slug: str) -> list:
        """Parse TeamRankings schedule HTML."""
        soup = BeautifulSoup(html, "html.parser")
        games = []
        current_date = None

        table = soup.find("table", class_="tr-table")
        if not table:
            logger.error("Could not find schedule table")
            return games

        theads = table.find_all("thead")
        for thead in theads:
            date_th = thead.find("th")
            if date_th:
                date_text = date_th.get_text(strip=True)
                current_date = self._parse_date_teamrankings(date_text)
                if not current_date:
                    continue

            tbody = thead.find_next_sibling("tbody")
            if not tbody:
                continue

            for row in tbody.find_all("tr"):
                game = self._parse_game_row_teamrankings(row, current_date, sport_slug)
                if game:
                    games.append(game)

        return games

    def _parse_date_teamrankings(self, date_text: str) -> str:
        """Parse date from TeamRankings format: 'Wed Mar 25'."""
        try:
            date_text = re.sub(r'^[A-Za-z]{3}\s+', '', date_text)
            current_year = datetime.now().year
            date_str = f"{date_text} {current_year}"
            dt = datetime.strptime(date_str, "%b %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            logger.warning(f"Could not parse date: {date_text}")
            return ""

    def _parse_game_row_teamrankings(self, row: BeautifulSoup, date: str, sport_slug: str) -> dict:
        """Parse a single game row from TeamRankings."""
        try:
            cols = row.find_all("td")
            if len(cols) < 3:
                return None

            teams_text = cols[0].get_text(strip=True)
            if not teams_text or " vs " not in teams_text and " @ " not in teams_text:
                return None

            if " @ " in teams_text:
                away_team, home_team = teams_text.split(" @ ", 1)
            elif " vs " in teams_text:
                home_team, away_team = teams_text.split(" vs ", 1)
            else:
                return None

            time = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            location = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            # Determine status based on date
            status = self._determine_status_by_date(date)

            return {
                "home_team": home_team.strip(),
                "away_team": away_team.strip(),
                "date": date,
                "time": time,
                "location": location,
                "status": status
            }

        except Exception as e:
            logger.error(f"Error parsing game row: {e}")
            return None

    def _determine_status_by_date(self, date_str: str) -> str:
        """Determine game status based on date."""
        if not date_str:
            return "Scheduled"

        try:
            game_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = datetime.now().date()

            if game_date < today:
                return "Completed"
            else:
                return "Scheduled"

        except ValueError:
            return "Scheduled"