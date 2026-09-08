import httpx
from urllib.parse import quote
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class ProwlarrClient:
    def __init__(self):
        self.base_url = get_setting("prowlarr_url")
        self.api_key = get_setting("prowlarr_api_key")
        
        if not self.base_url or not self.api_key:
            logger.warning("Prowlarr not configured")

    def is_configured(self) -> bool:
        """Check if Prowlarr is configured."""
        return bool(self.base_url and self.api_key)

    async def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make a request to Prowlarr API."""
        if not self.is_configured():
            return {"error": "Prowlarr not configured"}

        url = f"{self.base_url}/api/v1/{endpoint}"
        headers = {"X-Api-Key": self.api_key}
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Prowlarr API error: {e}")
            return {"error": str(e)}

    async def search(self, query: str, categories: list = None) -> list:
        """
        Search for releases.
        
        Args:
            query: Search query (e.g., "Auburn Baylor")
            categories: List of category IDs (e.g., [5000] for Sports)
        
        Returns:
            List of release results
        """
        if not self.is_configured():
            return []

        params = {"query": query}
        if categories:
            params["categories"] = ",".join(str(c) for c in categories)

        data = await self._request("search", params)
        
        if isinstance(data, list):
            return data
        
        # Some Prowlarr versions return with a 'results' key
        if isinstance(data, dict):
            return data.get("results", [])
        
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
        
        # Sports category (common ID is 5000, but we'll try without filter first)
        results = await self.search(query)
        
        # If no results, try with "vs" format
        if not results:
            query = f"{home_team} vs {away_team}"
            if year:
                query += f" {year}"
            results = await self.search(query)
        
        # If still no results, try with sport prefix
        if not results:
            # Try adding sport prefix (NCAAF, NFL, etc.)
            # This will be handled by the caller passing the sport
            pass
        
        return results

    async def get_release_download_url(self, release: dict) -> str:
        """Extract download URL from a release."""
        # Try different possible fields
        download_url = release.get("downloadUrl")
        if download_url:
            return download_url
        
        magnet_url = release.get("magnetUrl")
        if magnet_url:
            return magnet_url
        
        guid = release.get("guid")
        if guid and guid.startswith("http"):
            return guid
        
        return ""