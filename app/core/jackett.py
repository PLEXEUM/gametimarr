import httpx
from urllib.parse import quote
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class JackettClient:
    def __init__(self):
        self.base_url = get_setting("jackett_url") or get_setting("prowlarr_url")
        self.api_key = get_setting("jackett_api_key") or get_setting("prowlarr_api_key")
        
        if not self.base_url or not self.api_key:
            logger.warning("Jackett not configured")

    def is_configured(self) -> bool:
        """Check if Jackett is configured."""
        return bool(self.base_url and self.api_key)

    async def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make a request to Jackett API."""
        if not self.is_configured():
            return {"error": "Jackett not configured"}

        url = f"{self.base_url}/api/v2.0/{endpoint}"
        headers = {"X-Api-Key": self.api_key}
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Jackett API error: {e}")
            return {"error": str(e)}

    async def search(self, query: str, category: list = None) -> list:
        """
        Search for releases.
        
        Args:
            query: Search query (e.g., "Auburn Baylor")
            category: List of category IDs (e.g., [5000] for Sports)
        
        Returns:
            List of release results
        """
        if not self.is_configured():
            return []

        params = {
            "Query": query,
            "Trackers": "all"
        }
        if category:
            params["Category"] = category

        data = await self._request("indexers/all/results", params)
        
        if isinstance(data, dict):
            return data.get("Results", [])
        
        return []

    async def search_sport_event(self, home_team: str, away_team: str, year: int = None) -> list:
        """
        Build a search query for a sports event.
        
        Examples:
            - "Auburn Baylor"
            - "Auburn vs Baylor 2026"
        """
        query_parts = [home_team, away_team]
        if year:
            query_parts.append(str(year))
        
        query = " ".join(query_parts)
        
        # Sports category (Jackett uses 5000 for Sports)
        results = await self.search(query, category=[5000])
        
        # If no results, try with "vs" format
        if not results:
            query = f"{home_team} vs {away_team}"
            if year:
                query += f" {year}"
            results = await self.search(query, category=[5000])
        
        return results

    async def get_release_download_url(self, release: dict) -> str:
        """Extract download URL from a release."""
        # Jackett returns different fields than Prowlarr
        download_url = release.get("Link")
        if download_url:
            return download_url
        
        magnet_url = release.get("MagnetUri")
        if magnet_url:
            return magnet_url
        
        guid = release.get("Guid")
        if guid and guid.startswith("http"):
            return guid
        
        return ""