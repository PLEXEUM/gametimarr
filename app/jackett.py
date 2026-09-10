"""
jackett.py - Torznab client for querying Jackett.
"""

import logging
import httpx
import xml.etree.ElementTree as ET
from urllib.parse import quote

from app.database import get_setting

logger = logging.getLogger("gametimarr.jackett")

TORZNAB_NS = {"torznab": "http://torznab.com/schemas/2015/feed"}
RESULT_LIMIT = 100
TIMEOUT = 30


class JackettClient:
    def __init__(self):
        pass

    def _torznab_url(self) -> str:
        return get_setting("jackett_torznab_url", "") or ""

    def is_configured(self) -> bool:
        return bool(self._torznab_url())

    # -----------------------------------------------------------------------
    # Public: discovery
    # -----------------------------------------------------------------------

    async def recent_releases(self, query: str) -> list:
        base = self._torznab_url()
        if not base:
            logger.warning("Jackett: not configured, skipping query")
            return []

        separator = "&" if "?" in base else "?"
        url = f"{base}{separator}t=search&q={quote(query)}&limit={RESULT_LIMIT}"

        content = await self._request(url)
        if not content:
            return []

        return self._parse_torznab_response(content)

    # -----------------------------------------------------------------------
    # Public: connection test
    # -----------------------------------------------------------------------

    async def test_connection(self, torznab_url: str) -> dict:
        if not torznab_url:
            return {"success": False, "message": "Torznab URL is required"}

        separator = "&" if "?" in torznab_url else "?"
        url = f"{torznab_url}{separator}t=search&q=test&limit=1"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url)
                response.raise_for_status()

            text = response.text.lower()
            if "<rss" in text or "<item" in text:
                return {"success": True, "message": "Connected to Jackett"}
            if "<error" in text:
                return {"success": False, "message": "Jackett returned an error (check API key)"}
            return {"success": True, "message": "Connected to Jackett"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"success": False, "message": "Authentication failed (check API key)"}
            return {"success": False, "message": f"Server error: {e.response.status_code}"}
        except httpx.ConnectError:
            return {"success": False, "message": "Could not reach server (check URL)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # -----------------------------------------------------------------------
    # Internal: HTTP
    # -----------------------------------------------------------------------

    async def _request(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Jackett request error: {e}")
            return b""

    # -----------------------------------------------------------------------
    # Internal: XML parsing
    # -----------------------------------------------------------------------

    def _parse_torznab_response(self, content: bytes) -> list:
        releases = []

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            logger.error(f"Jackett XML parse error: {e}")
            return []

        for item in root.findall(".//item"):
            release = {}

            title_elem = item.find("title")
            if title_elem is None or not title_elem.text:
                continue
            release["title"] = title_elem.text

            guid_elem = item.find("guid")
            release["guid"] = guid_elem.text if guid_elem is not None and guid_elem.text else ""

            link_elem = item.find("link")
            release["link"] = link_elem.text if link_elem is not None and link_elem.text else ""

            release["size"] = self._int_field(item, "size")
            release["seeders"] = self._int_field(item, "seeders")
            release["leechers"] = self._int_field(item, "leechers")
            release["category"] = self._category_field(item)

            releases.append(release)

        return releases

    def _int_field(self, item, name: str) -> int:
        elem = item.find(name)
        if elem is not None and elem.text:
            try:
                return int(elem.text)
            except ValueError:
                pass

        for attr in item.findall("torznab:attr", namespaces=TORZNAB_NS):
            if attr.get("name") == name:
                try:
                    return int(attr.get("value", "0"))
                except ValueError:
                    pass

        return 0

    def _category_field(self, item) -> str:
        for attr in item.findall("torznab:attr", namespaces=TORZNAB_NS):
            if attr.get("name") == "category":
                return attr.get("value", "")
        return ""

    # -----------------------------------------------------------------------
    # Public: extract download URL
    # -----------------------------------------------------------------------

    def get_download_url(self, release: dict) -> str:
        link = release.get("link", "")
        if link:
            return link

        guid = release.get("guid", "")
        if guid.startswith("http"):
            return guid

        return ""