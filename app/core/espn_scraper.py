import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from app.utils.logger import get_logger

logger = get_logger()

# ESPN schedule URLs (automatically redirect to current season)
SPORT_URLS = {
    "NCAAF": "https://www.espn.com/college-football/schedule",
    "NFL": "https://www.espn.com/nfl/schedule/",
    "MLB": "https://www.espn.com/mlb/schedule/"
}


class ESPNScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    async def fetch_page(self, url: str) -> str:
        """Fetch the HTML content of a page with browser-like headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=headers,
                http2=True
            ) as client:
                # First, visit the main page to get cookies
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Failed to fetch page {url}: {e}")
            return ""

    def parse_games(self, html: str, sport: str) -> list:
        """Parse games from ESPN schedule HTML."""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        games = []

        # Find all schedule tables or containers
        # ESPN uses different structures for different sports
        if sport == "MLB":
            games = self._parse_mlb_schedule(soup)
        else:
            games = self._parse_standard_schedule(soup)

        return games

    def _parse_standard_schedule(self, soup: BeautifulSoup) -> list:
        """Parse standard ESPN schedule format (NCAAF, NFL)."""
        games = []
        current_date = None

        # Find all date headers and game containers
        # ESPN uses <div class="Schedule__Date"> and <section class="Schedule__Games">
        for date_div in soup.find_all("div", class_=re.compile(r"Schedule__Date")):
            date_text = date_div.get_text(strip=True)
            if date_text:
                current_date = self._parse_date(date_text)

            # Find games under this date
            games_container = date_div.find_next("div", class_=re.compile(r"Schedule__Games"))
            if not games_container:
                continue

            for game_row in games_container.find_all("section", class_=re.compile(r"Schedule__Game")):
                game = self._parse_game_row(game_row, current_date)
                if game:
                    games.append(game)

        return games

    def _parse_mlb_schedule(self, soup: BeautifulSoup) -> list:
        """Parse MLB schedule format (different from other sports)."""
        games = []
        current_date = None

        # MLB schedule uses a table structure
        # Look for date headers and game rows
        for date_header in soup.find_all("div", class_=re.compile(r"Schedule__Date")):
            date_text = date_header.get_text(strip=True)
            if date_text:
                current_date = self._parse_date(date_text)

            # MLB uses a table for games
            table = date_header.find_next("table")
            if not table:
                continue

            for row in table.find_all("tr"):
                # Skip header rows
                if row.find("th"):
                    continue

                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                # MLB rows often have team names with logos
                game = self._parse_mlb_row(cols, current_date)
                if game:
                    games.append(game)

        return games

    def _parse_date(self, date_text: str) -> str:
        """Parse a date string into YYYY-MM-DD format."""
        try:
            # Handle various date formats
            # "Friday, September 11, 2026" or "Sep 11, 2026"
            date_text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_text)
            dt = datetime.strptime(date_text, "%A, %B %d, %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            try:
                dt = datetime.strptime(date_text, "%B %d, %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                logger.warning(f"Could not parse date: {date_text}")
                return ""

    def _parse_game_row(self, game_row: BeautifulSoup, date: str) -> dict:
        """Parse a single game row."""
        try:
            # Find team names
            home_team = None
            away_team = None

            # ESPN uses <span class="Team__Name"> or <abbr>
            team_spans = game_row.find_all("span", class_=re.compile(r"Team__Name"))
            if len(team_spans) >= 2:
                away_team = team_spans[0].get_text(strip=True)
                home_team = team_spans[1].get_text(strip=True)

            # Fallback: look for abbr tags
            if not home_team or not away_team:
                abbrs = game_row.find_all("abbr")
                if len(abbrs) >= 2:
                    away_team = abbrs[0].get("title") or abbrs[0].get_text(strip=True)
                    home_team = abbrs[1].get("title") or abbrs[1].get_text(strip=True)

            if not home_team or not away_team:
                return None

            # Clean team names
            home_team = home_team.strip()
            away_team = away_team.strip()

            # Extract time
            time = ""
            time_span = game_row.find("span", class_=re.compile(r"GameTime__Time"))
            if time_span:
                time = time_span.get_text(strip=True)

            # Determine status
            status = "Scheduled"
            status_span = game_row.find("span", class_=re.compile(r"GameStatus__Text"))
            if status_span:
                status_text = status_span.get_text(strip=True).lower()
                if "postponed" in status_text:
                    status = "Postponed"
                elif "canceled" in status_text:
                    status = "Canceled"
                elif "final" in status_text or "completed" in status_text:
                    status = "Completed"
                # Note: We intentionally ignore scores

            return {
                "home_team": home_team,
                "away_team": away_team,
                "date": date or "",
                "time": time,
                "status": status
            }

        except Exception as e:
            logger.error(f"Error parsing game row: {e}")
            return None

    def _parse_mlb_row(self, cols: list, date: str) -> dict:
        """Parse an MLB game row."""
        try:
            # MLB rows: col0 = away team, col1 = home team
            away_cell = cols[0]
            home_cell = cols[1]

            away_team = self._extract_team_name(away_cell)
            home_team = self._extract_team_name(home_cell)

            if not home_team or not away_team:
                return None

            # Extract time (might be in a separate column or span)
            time = ""
            if len(cols) > 2:
                time_span = cols[2].find("span", class_=re.compile(r"GameTime__Time"))
                if time_span:
                    time = time_span.get_text(strip=True)

            status = "Scheduled"
            # MLB might show game status in a different way

            return {
                "home_team": home_team,
                "away_team": away_team,
                "date": date or "",
                "time": time,
                "status": status
            }

        except Exception as e:
            logger.error(f"Error parsing MLB row: {e}")
            return None

    def _extract_team_name(self, cell: BeautifulSoup) -> str:
        """Extract team name from a cell."""
        # Try to find team name in span
        name_span = cell.find("span", class_=re.compile(r"Team__Name"))
        if name_span:
            return name_span.get_text(strip=True)

        # Try abbr title
        abbr = cell.find("abbr")
        if abbr:
            return abbr.get("title") or abbr.get_text(strip=True)

        # Fallback: get text and clean
        text = cell.get_text(strip=True)
        # Remove common noise
        text = re.sub(r"\d+-\d+", "", text)  # Remove records like "1-1"
        text = text.strip()
        return text

    async def get_events(self, sport_slug: str) -> list:
        """Fetch and parse events for a sport."""
        url = SPORT_URLS.get(sport_slug)
        if not url:
            logger.error(f"Unknown sport: {sport_slug}")
            return []

        logger.info(f"Fetching schedule for {sport_slug} from {url}")
        html = await self.fetch_page(url)

        if not html:
            logger.error(f"Failed to fetch schedule for {sport_slug}")
            return []

        games = self.parse_games(html, sport_slug)

        # Filter: only keep games from season start to today + 30 days
        filtered = []
        today = datetime.now().date()
        max_date = today + timedelta(days=30)

        for game in games:
            if game["date"]:
                try:
                    game_date = datetime.strptime(game["date"], "%Y-%m-%d").date()
                    # Keep all games from season start (which is before today) to today + 30 days
                    # For NCAAF, season start is around August
                    if game_date <= max_date:
                        filtered.append(game)
                except ValueError:
                    # If date parsing fails, keep the game
                    filtered.append(game)
            else:
                # Games without a date are kept
                filtered.append(game)

        logger.info(f"Found {len(filtered)} games for {sport_slug} (filtered from {len(games)})")
        return filtered