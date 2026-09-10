"""
qbittorrent.py - qBittorrent API v2 client.
"""

import logging
import httpx
import asyncio
import re
from urllib.parse import urljoin

from app.database import get_setting

logger = logging.getLogger("gametimarr.qbittorrent")

CATEGORY = "gametimarr"
TIMEOUT = 30


class QBittorrentClient:
    def __init__(self):
        self.host = get_setting("qbit_host", "localhost") or "localhost"
        self.port = get_setting("qbit_port", "8012") or "8012"
        self.username = get_setting("qbit_username", "admin") or "admin"
        self.password = get_setting("qbit_password", "") or ""

        self.base_url = f"http://{self.host}:{self.port}"
        self.client = httpx.AsyncClient(timeout=TIMEOUT)
        self._logged_in = False

    def is_configured(self) -> bool:
        return bool(self.host and self.port and self.username)

    # -----------------------------------------------------------------------
    # Public: connection test
    # -----------------------------------------------------------------------

    async def test_connection(
        self,
        host: str = None,
        port: str = None,
        username: str = None,
        password: str = None,
    ) -> dict:
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
    # Internal: auth
    # -----------------------------------------------------------------------

    async def _login(self) -> bool:
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

            logger.warning(f"qBittorrent login failed: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"qBittorrent login error: {e}")
            return False

    # -----------------------------------------------------------------------
    # Public: add torrent
    # -----------------------------------------------------------------------

    async def add_torrent(self, torrent_url: str, label: str = CATEGORY) -> dict:
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

        torrent_hash = await self._find_hash_by_url(torrent_url)
        return {"success": True, "hash": torrent_hash}

    # -----------------------------------------------------------------------
    # Internal: hash lookup
    # -----------------------------------------------------------------------

    async def _find_hash_by_url(self, torrent_url: str) -> str:
        if "magnet:" in torrent_url:
            match = re.search(r"btih:([a-fA-F0-9]{40})", torrent_url)
            if match:
                return match.group(1).lower()

        await asyncio.sleep(1)

        torrents = await self.get_torrents(filter_category=CATEGORY)
        if not torrents:
            return ""

        torrents.sort(key=lambda t: t.get("added_on", 0), reverse=True)
        return torrents[0].get("hash", "")

    # -----------------------------------------------------------------------
    # Public: query torrents
    # -----------------------------------------------------------------------

    async def get_torrents(self, filter_category: str = None) -> list:
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
            logger.error(f"qBittorrent get_torrents error: {e}")

        return []

    async def get_torrent_status(self, torrent_hash: str) -> dict:
        torrents = await self.get_torrents()
        for torrent in torrents:
            if torrent.get("hash") == torrent_hash:
                return torrent
        return {}

    async def is_torrent_complete(self, torrent_hash: str) -> bool:
        status = await self.get_torrent_status(torrent_hash)
        return status.get("progress", 0) >= 1.0

    async def get_torrent_files(self, torrent_hash: str) -> list:
        if not await self._login():
            return []

        url = urljoin(self.base_url, "/api/v2/torrents/files")
        try:
            response = await self.client.get(url, params={"hash": torrent_hash})
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"qBittorrent get_torrent_files error: {e}")

        return []