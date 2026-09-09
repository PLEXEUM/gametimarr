import httpx
from urllib.parse import urljoin
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class QBittorrentClient:
    def __init__(self):
        self.host = get_setting("qbit_host") or "localhost"
        self.port = get_setting("qbit_port") or "8080"
        self.username = get_setting("qbit_username") or "admin"
        self.password = get_setting("qbit_password") or ""
        self.base_url = f"http://{self.host}:{self.port}"
        self.client = httpx.AsyncClient(timeout=30)
        self._logged_in = False

    def is_configured(self) -> bool:
        """Check if qBittorrent is configured."""
        return bool(self.host and self.port and self.username)

    
    async def test_connection(self, host: str = None, port: int = None, username: str = None, password: str = None) -> dict:
        """Test qBittorrent connection with provided credentials."""
        # Use provided values or fall back to saved settings
        test_host = host or self.host
        test_port = port or self.port
        test_username = username or self.username
        test_password = password or self.password
    
        if not test_host or not test_port:
            return {"success": False, "message": "Host and port are required"}
    
        try:
            # Create a temporary client with the test credentials
            temp_client = httpx.AsyncClient(timeout=10)
            url = f"http://{test_host}:{test_port}/api/v2/auth/login"
            data = {"username": test_username, "password": test_password}
        
            response = await temp_client.post(url, data=data)
            await temp_client.aclose()
        
            if response.status_code == 200 and "Ok" in response.text:
                return {"success": True, "message": "Connected to qBittorrent"}
            else:
                return {"success": False, "message": "Login failed - check credentials"}
        except httpx.ConnectError:
            return {"success": False, "message": "Could not reach server (check host/port)"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    
    async def _login(self) -> bool:
        """Login to qBittorrent API."""
        if self._logged_in:
            return True

        try:
            url = urljoin(self.base_url, "/api/v2/auth/login")
            data = {"username": self.username, "password": self.password}
            
            response = await self.client.post(url, data=data)
            
            if response.status_code == 200 and "Ok" in response.text:
                self._logged_in = True
                logger.info("qBittorrent login successful")
                return True
            else:
                logger.error(f"qBittorrent login failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"qBittorrent login error: {e}")
            return False

    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make a request to qBittorrent API."""
        if not await self._login():
            return {"error": "Not logged in"}

        url = urljoin(self.base_url, endpoint)
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(url)
            else:
                response = await self.client.post(url, data=data)
            
            if response.status_code == 200:
                return response.json() if response.text else {"success": True}
            else:
                return {"error": f"Request failed: {response.status_code}"}
        except Exception as e:
            logger.error(f"qBittorrent request error: {e}")
            return {"error": str(e)}

    async def add_torrent(self, torrent_url: str, save_path: str = None, label: str = None) -> dict:
        """
        Add a torrent to qBittorrent.
        
        Args:
            torrent_url: Magnet link or torrent URL
            save_path: Directory to save the download
            label: Category/label for the torrent
        
        Returns:
            dict with success status and hash
        """
        if not await self._login():
            return {"success": False, "error": "Not logged in"}

        url = urljoin(self.base_url, "/api/v2/torrents/add")
        
        data = {"urls": torrent_url}
        if save_path:
            data["savepath"] = save_path
        if label:
            data["category"] = label
            data["tags"] = label

        try:
            response = await self.client.post(url, data=data)
            
            if response.status_code == 200 and "Ok" in response.text:
                logger.info(f"Torrent added: {torrent_url}")
                return {"success": True, "hash": await self._get_torrent_hash(torrent_url)}
            else:
                return {"success": False, "error": f"Add failed: {response.text}"}
        except Exception as e:
            logger.error(f"Add torrent error: {e}")
            return {"success": False, "error": str(e)}

    async def _get_torrent_hash(self, torrent_url: str) -> str:
        """Extract torrent hash from magnet or URL."""
        import re
        if "magnet:" in torrent_url:
            match = re.search(r'btih:([a-fA-F0-9]{40})', torrent_url)
            if match:
                return match.group(1).lower()
        return ""

    async def get_torrents(self, status_filter: str = None) -> list:
        """Get list of torrents."""
        if not await self._login():
            return []

        url = urljoin(self.base_url, "/api/v2/torrents/info")
        params = {}
        if status_filter:
            params["filter"] = status_filter

        try:
            response = await self.client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Get torrents error: {e}")
        
        return []

    async def get_torrent_status(self, torrent_hash: str) -> dict:
        """Get status of a specific torrent."""
        torrents = await self.get_torrents()
        for torrent in torrents:
            if torrent.get("hash") == torrent_hash:
                return torrent
        return {}

    async def is_torrent_complete(self, torrent_hash: str) -> bool:
        """Check if a torrent is complete."""
        status = await self.get_torrent_status(torrent_hash)
        return status.get("progress", 0) >= 1.0

    async def get_torrent_download_path(self, torrent_hash: str) -> str:
        """Get the download path of a completed torrent."""
        status = await self.get_torrent_status(torrent_hash)
        if status.get("progress", 0) >= 1.0:
            return status.get("save_path", "")
        return ""

    async def test_connection(self) -> dict:
        """Test qBittorrent connection."""
        try:
            if await self._login():
                return {"success": True, "message": "Connected to qBittorrent"}
            else:
                return {"success": False, "message": "Login failed - check credentials"}
        except Exception as e:
            return {"success": False, "message": str(e)}