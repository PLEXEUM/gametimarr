"""
qbittorrent.py - qBittorrent API v2 client.

Owns all communication with qBittorrent. Nothing else in the app makes HTTP
calls to qBittorrent.

Targets qBittorrent 4.1+ (API v2). Not compatible with older versions.
"""

import httpx
import asyncio
from urllib.parse import urljoin

from app.database import get_setting, log_event


# Category/tag applied to all torrents this app manages
CATEGORY = "gametimarr"

# HTTP timeout in seconds
TIMEOUT = 30


class QBittorrentClient:
    def __init__(self):
        # Config is read fresh from settings on each instance, so changes in
        # the UI take effect on the next scan without a restart.
        self.host = get_setting("qbit_host", "localhost") or "localhost"
        self.port = get_setting("qbit_port", "8080") or "8080"
        self.username = get_setting("qbit_username", "admin") or "admin"
        self.password = get_setting("qbit_password", "") or ""

        self.base_url = f"http://{self.host}:{self.port}"
        self.client = httpx.AsyncClient(timeout=TIMEOUT)
        self._logged_in = False

    # -----------------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------------

    def is_configured(self) -> bool:
        """True if host, port, and username are present."""
        return bool(self.host and self.port and self.username)

    # -----------------------------------------------------------------------
    # Public: connection test (used by the web UI's Test button)
    # -----------------------------------------------------------------------

    async def test_connection(
        self,
        host: str = None,
        port: str = None,
        username: str = None,
        password: str = None,
    ) -> dict:
        """
        Test a connection with the provided credentials without saving them.
        Used by the settings panel so the user can verify before saving.
        """
        test_host = host or self.host
        test_port = port or self.port
        test_username = username or self.username
        test_password = password or self.password

        if not test_host or not test_port:
            return {"success": False, "message": "Host and port are required"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                url = f"http://{test_host}:{test_port}/api/v2/auth/login"
                response = await client.post(
                    url, data={"username": test_username, "password": test_password}
                )

            if response.status_code == 200 and "Ok" in response.text:
                return {"success": True, "message": "Connected to qBittorrent"}
            return {"success": False, "message": "Login failed - check credentials"}

        except httpx.ConnectError:
            return {"success": False, "message": "Could not reach server (check host/port)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # -----------------------------------------------------------------------
    # Internal: authentication
    # -----------------------------------------------------------------------

    async def _login(self) -> bool:
        """Log in to qBittorrent. Cached for the life of the client instance."""
        if self._logged_in:
            return True

        try:
            url = urljoin(self.base_url, "/api/v2/auth/login")
            response = await self.client.post(
                url, data={"username": self.username, "password": self.password}
            )

            if response.status_code == 200 and "Ok" in response.text:
                self._logged_in = True
                return True

            log_event(f"qBittorrent login failed: {response.status_code}")
            return False
        except Exception as e:
            log_event(f"qBittorrent login error: {e}")
            return False

    # -----------------------------------------------------------------------
    # Public: add torrent
    # -----------------------------------------------------------------------

    async def add_torrent(self, torrent_url: str, label: str = CATEGORY) -> dict:
        """
        Add a torrent by URL (magnet or .torrent HTTP URL).

        After adding, looks up the torrent by name to retrieve its hash.
        Returns {"success": bool, "hash": str, "error": str}.
        """
        if not await self._login():
            return {"success": False, "error": "Not logged in"}

        url = urljoin(self.base_url, "/api/v2/torrents/add")

        data = {"urls": torrent_url}
        if label:
            data["category"] = label
            data["tags"] = label

        try:
            response = await self.client.post(url, data=data)
            if response.status_code != 200 or "Ok" not in response.text:
                return {"success": False, "error": f"Add failed: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        # Look up the hash by fetching recent torrents and matching names.
        # This works for both magnet links and .torrent URLs, because we never
        # have to parse the infohash ourselves.
        torrent_hash = await self._find_hash_by_url(torrent_url)
        return {"success": True, "hash": torrent_hash}

    # -----------------------------------------------------------------------
    # Internal: hash lookup
    # -----------------------------------------------------------------------

    async def _find_hash_by_url(self, torrent_url: str) -> str:
        """
        After adding a torrent, find its hash by comparing the torrent list
        against the URL we just added.

        Strategy:
            1. If the URL is a magnet, parse the btih hash directly.
            2. Otherwise, give qBittorrent a moment, then find the newest
               torrent in our category and return its hash.

        This isn't perfect if two torrents are added in the same second, but
        for a personal tool with a 90-minute scan interval, that's fine.
        """
        # Magnet: parse directly
        if "magnet:" in torrent_url:
            import re
            match = re.search(r"btih:([a-fA-F0-9]{40})", torrent_url)
            if match:
                return match.group(1).lower()

        # .torrent URL: give qBittorrent a moment to register the torrent
        await asyncio.sleep(1)

        torrents = await self.get_torrents(filter_category=CATEGORY)
        if not torrents:
            return ""

        # Sort by added_on descending, return the newest
        torrents.sort(key=lambda t: t.get("added_on", 0), reverse=True)
        return torrents[0].get("hash", "")

    # -----------------------------------------------------------------------
    # Public: query torrents
    # -----------------------------------------------------------------------

    async def get_torrents(self, filter_category: str = None) -> list:
        """Return the list of torrents, optionally filtered by category."""
        if not await self._login():
            return []

        url = urljoin(self.base_url, "/api/v2/torrents/info")
        params = {}
        if filter_category:
            params["category"] = filter_category

        try:
            response = await self.client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            log_event(f"qBittorrent get_torrents error: {e}")

        return []

    async def get_torrent_status(self, torrent_hash: str) -> dict:
        """Return the status dict for a single torrent, or {} if not found."""
        torrents = await self.get_torrents()
        for torrent in torrents:
            if torrent.get("hash") == torrent_hash:
                return torrent
        return {}

    async def is_torrent_complete(self, torrent_hash: str) -> bool:
        """True if the torrent is at 100% progress."""
        status = await self.get_torrent_status(torrent_hash)
        return status.get("progress", 0) >= 1.0

    async def get_torrent_files(self, torrent_hash: str) -> list:
        """
        Return the list of files for a torrent.
        Each entry has: name, size, progress, priority, is_seed, piece_range, availability
        """
        if not await self._login():
            return []

        url = urljoin(self.base_url, "/api/v2/torrents/files")
        try:
            response = await self.client.get(url, params={"hash": torrent_hash})
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            log_event(f"qBittorrent get_torrent_files error: {e}")

        return []