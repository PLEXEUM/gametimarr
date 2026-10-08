"""
channels.py - Channels DVR client.

Fetches the list of completed sports recordings from a Channels DVR
server so the scanner can skip releases the DVR already has.

Endpoint: GET <url>/api/v1/episodes
Returns a JSON array. Real DVR sports recordings have "Sports event" in
their categories array and an event_title like "Miami at Clemson".
gametimarr's own imports into the Sports folder do NOT have "Sports event"
in categories, so they are filtered out.
"""

import logging
import httpx

from app.database import get_setting

logger = logging.getLogger("gametimarr.channels")

TIMEOUT = 30


class ChannelsClient:
    def __init__(self):
        self.url = (get_setting("channels_url", "") or "").rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.url)

    # -----------------------------------------------------------------------
    # Public: connection test
    # -----------------------------------------------------------------------

    async def test_connection(self, url: str = None) -> dict:
        test_url = (url or self.url or "").rstrip("/")

        if not test_url:
            return {"success": False, "message": "URL is required"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{test_url}/dvr/files?all=true")
                response.raise_for_status()
                data = response.json()

            if not isinstance(data, list):
                return {"success": False, "message": "Unexpected response format"}

            return {"success": True, "message": "Connected to Channels DVR"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return {"success": False, "message": "Authentication failed"}
            return {"success": False, "message": f"Server error: {e.response.status_code}"}
        except httpx.ConnectError:
            return {"success": False, "message": "Could not reach server (check URL)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # -----------------------------------------------------------------------
    # Public: fetch recorded games
    # -----------------------------------------------------------------------

    async def get_recorded_games(self) -> list:
        """
        Return a list of team-name lists, one per Channels DVR sports
        recording. Each inner list has two lowercased team names.

        Example:
            [
                ["miami", "clemson"],
                ["new england patriots", "buffalo bills"],
            ]

        Returns [] on any failure so the scanner can proceed without
        the DVR check.
        """
        if not self.url:
            return []

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(f"{self.url}/dvr/files?all=true")
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"Channels fetch failed: {e}")
            return []

        if not isinstance(data, list):
            logger.warning("Channels response was not a JSON array")
            return []

        games = []

        for entry in data:
            categories = entry.get("categories") or []
            if "Sports event" not in categories:
                continue

            event_title = entry.get("event_title") or ""
            if not event_title:
                continue

            teams = self._split_event_title(event_title)
            if teams:
                games.append(teams)

        return games

    # -----------------------------------------------------------------------
    # Internal: parse event_title into team names
    # -----------------------------------------------------------------------

    def _split_event_title(self, event_title: str) -> list:
        """
        Split "New England Patriots at Buffalo Bills" into
        ["new england patriots", "buffalo bills"].

        Tries " at " first, then " vs ", then returns the whole string
        as a single-element list. Each token is lowercased and stripped.
        """
        lowered = event_title.lower()

        for separator in (" at ", " vs "):
            if separator in lowered:
                parts = [p.strip() for p in lowered.split(separator) if p.strip()]
                if len(parts) == 2:
                    return parts

        # No recognized separator — return the whole title as one token
        stripped = lowered.strip()
        return [stripped] if stripped else []