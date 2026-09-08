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

        # Filter: only keep games from season start to today + 30 days
        filtered = []
        today = datetime.now().date()
        max_date = today + timedelta(days=30)

        for game in games:
            if game["date"]:
                try:
                    game_date = datetime.strptime(game["date"], "%Y-%m-%d").date()
                    # Keep games from season start to today + 30 days
                    if game_date <= max_date:
                        filtered.append(game)
                except ValueError:
                    filtered.append(game)
            else:
                filtered.append(game)

        logger.info(f"Found {len(filtered)} games for {sport_slug} (filtered from {len(games)})")
        return filtered

    def _parse_teamrankings(self, html: str, sport_slug: str) -> list:
        """Parse TeamRankings schedule HTML."""
        soup = BeautifulSoup(html, "html.parser")
        games = []
        current_date = None

        # Find the main table
        table = soup.find("table", class_="tr-table")
        if not table:
            logger.error("Could not find schedule table")
            return games

        # Find all thead sections (each contains a date header)
        theads = table.find_all("thead")
        for thead in theads:
            # Get the date from the th
            date_th = thead.find("th")
            if date_th:
                date_text = date_th.get_text(strip=True)
                current_date = self._parse_date_teamrankings(date_text)
                if not current_date:
                    continue

            # Find the tbody that follows this thead
            tbody = thead.find_next_sibling("tbody")
            if not tbody:
                continue

            # Parse each game row
            for row in tbody.find_all("tr"):
                game = self._parse_game_row_teamrankings(row, current_date, sport_slug)
                if game:
                    games.append(game)

        return games

    def _parse_date_teamrankings(self, date_text: str) -> str:
        """Parse date from TeamRankings format: 'Thu Sep 10'."""
        try:
            # Remove day of week (e.g., "Thu ")
            date_text = re.sub(r'^[A-Za-z]{3}\s+', '', date_text)
            # Add current year (TeamRankings doesn't include year in header)
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

            # Column 0: Teams (e.g., "Florida A&M @ Miami")
            teams_text = cols[0].get_text(strip=True)
            if not teams_text or " vs " not in teams_text and " @ " not in teams_text:
                return None

            # Parse teams
            if " @ " in teams_text:
                away_team, home_team = teams_text.split(" @ ", 1)
            elif " vs " in teams_text:
                home_team, away_team = teams_text.split(" vs ", 1)
            else:
                return None

            # Column 1: Time (e.g., "8:00 PM")
            time = cols[1].get_text(strip=True) if len(cols) > 1 else ""

            # Column 2: Location (e.g., "Hard Rock Stadium")
            location = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            # Determine status
            status = self._get_game_status(row, sport_slug)

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

    def _get_game_status(self, row: BeautifulSoup, sport_slug: str) -> str:
        """Determine game status from row context."""
        # Check for status indicators in the row
        row_text = row.get_text().lower()

        # Look for common status indicators
        if "final" in row_text:
            return "Completed"
        if "postponed" in row_text:
            return "Postponed"
        if "canceled" in row_text or "cancelled" in row_text:
            return "Canceled"
        if "scheduled" in row_text:
            return "Scheduled"

        # Check for score indicators (e.g., "24-21")
        # TeamRankings may show scores for completed games
        if re.search(r'\d+\s*-\s*\d+', row_text):
            # This likely means the game has a score (completed)
            return "Completed"

        # Check if there's a result link with score
        score_link = row.find("a", href=re.compile(r"/college-football/matchup/"))
        if score_link:
            # Check if the link text contains a score or "Final"
            link_text = score_link.get_text().lower()
            if "final" in link_text or re.search(r'\d+\s*-\s*\d+', link_text):
                return "Completed"

        # Default to Scheduled if no indicators found
        return "Scheduled"