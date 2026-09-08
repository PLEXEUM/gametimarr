import httpx
from urllib.parse import quote, urlparse, parse_qs
import xml.etree.ElementTree as ET
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class JackettClient:
    def __init__(self):
        self.torznab_url = get_setting("jackett_torznab_url")
        
        if not self.torznab_url:
            logger.warning("Jackett Torznab URL not configured")

    def is_configured(self) -> bool:
        """Check if Jackett is configured."""
        return bool(self.torznab_url)

    async def _request(self, url: str) -> bytes:
        """Make a request to the Torznab URL."""
        if not self.is_configured():
            return b""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Jackett Torznab request error: {e}")
            return b""

    async def search(self, query: str) -> list:
        """
        Search for releases using Torznab.
        
        Args:
            query: Search query (e.g., "Auburn Baylor")
        
        Returns:
            List of release results
        """
        if not self.is_configured():
            return []

        # Build the Torznab URL with the query
        if "?" in self.torznab_url:
            url = f"{self.torznab_url}&t=search&q={quote(query)}"
        else:
            url = f"{self.torznab_url}?t=search&q={quote(query)}"
        
        logger.info(f"Jackett Torznab search: {query}")
        content = await self._request(url)
        
        if not content:
            return []
        
        # Parse the XML response
        return self._parse_torznab_response(content)

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
        results = await self.search(query)
        
        # If no results, try with "vs" format
        if not results:
            query = f"{home_team} vs {away_team}"
            if year:
                query += f" {year}"
            results = await self.search(query)
        
        return results

    def _parse_torznab_response(self, content: bytes) -> list:
        """
        Parse a Torznab XML response into a list of releases.
        
        Torznab format:
        <rss>
          <channel>
            <item>
              <title>Release Name</title>
              <guid>http://...</guid>
              <link>magnet:...</link>
              <size>123456789</size>
              <seeders>10</seeders>
              <leechers>2</leechers>
              <torznab:attr name="category" value="5000"/>
            </item>
          </channel>
        </rss>
        """
        releases = []
        
        try:
            # Parse XML
            root = ET.fromstring(content)
            
            # Find all item elements (search in default namespace)
            # Torznab RSS uses standard RSS namespaces
            namespace = {"torznab": "http://torznab.com/schemas/2015/feed"}
            
            for item in root.findall(".//item"):
                release = {}
                
                # Get title
                title_elem = item.find("title")
                if title_elem is not None and title_elem.text:
                    release["title"] = title_elem.text
                else:
                    continue
                
                # Get GUID (used as unique identifier)
                guid_elem = item.find("guid")
                if guid_elem is not None and guid_elem.text:
                    release["guid"] = guid_elem.text
                
                # Get link (magnet or download URL)
                link_elem = item.find("link")
                if link_elem is not None and link_elem.text:
                    release["link"] = link_elem.text
                
                # Get size
                size_elem = item.find("size")
                if size_elem is not None and size_elem.text:
                    try:
                        release["size"] = int(size_elem.text)
                    except ValueError:
                        release["size"] = 0
                else:
                    # Try torznab:attr for size
                    for attr in item.findall("torznab:attr", namespaces=namespace):
                        if attr.get("name") == "size":
                            try:
                                release["size"] = int(attr.get("value", "0"))
                            except ValueError:
                                release["size"] = 0
                            break
                    if "size" not in release:
                        release["size"] = 0
                
                # Get seeders
                seeders_elem = item.find("seeders")
                if seeders_elem is not None and seeders_elem.text:
                    try:
                        release["seeders"] = int(seeders_elem.text)
                    except ValueError:
                        release["seeders"] = 0
                else:
                    # Try torznab:attr for seeders
                    for attr in item.findall("torznab:attr", namespaces=namespace):
                        if attr.get("name") == "seeders":
                            try:
                                release["seeders"] = int(attr.get("value", "0"))
                            except ValueError:
                                release["seeders"] = 0
                            break
                    if "seeders" not in release:
                        release["seeders"] = 0
                
                # Get leechers
                leechers_elem = item.find("leechers")
                if leechers_elem is not None and leechers_elem.text:
                    try:
                        release["leechers"] = int(leechers_elem.text)
                    except ValueError:
                        release["leechers"] = 0
                else:
                    # Try torznab:attr for leechers
                    for attr in item.findall("torznab:attr", namespaces=namespace):
                        if attr.get("name") == "leechers":
                            try:
                                release["leechers"] = int(attr.get("value", "0"))
                            except ValueError:
                                release["leechers"] = 0
                            break
                    if "leechers" not in release:
                        release["leechers"] = 0
                
                # Get category
                for attr in item.findall("torznab:attr", namespaces=namespace):
                    if attr.get("name") == "category":
                        release["category"] = attr.get("value", "")
                        break
                if "category" not in release:
                    release["category"] = ""
                
                # Get publish date
                pub_date_elem = item.find("pubDate")
                if pub_date_elem is not None and pub_date_elem.text:
                    release["publish_date"] = pub_date_elem.text
                
                releases.append(release)
                
        except ET.ParseError as e:
            logger.error(f"Failed to parse Torznab response: {e}")
        except Exception as e:
            logger.error(f"Error parsing Torznab response: {e}")
        
        return releases

    async def get_release_download_url(self, release: dict) -> str:
        """Extract download URL from a release."""
        # Try link field
        download_url = release.get("link")
        if download_url:
            return download_url
        
        # Try guid
        guid = release.get("guid")
        if guid and guid.startswith("http"):
            return guid
        
        return ""

    async def test_connection(self, torznab_url: str = None) -> dict:
        """
        Test the Jackett Torznab connection.
        
        Args:
            torznab_url: Torznab URL (optional, uses saved if not provided)
        
        Returns:
            dict with success and message
        """
        # Use provided URL or fall back to saved setting
        test_url = torznab_url or self.torznab_url
        
        if not test_url:
            return {"success": False, "message": "Torznab URL is required"}
        
        try:
            # Add a test query to the URL
            if "?" in test_url:
                url = f"{test_url}&t=search&q=test&limit=1"
            else:
                url = f"{test_url}?t=search&q=test&limit=1"
            
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                # Check if it looks like a valid Torznab response (XML with RSS)
                content = response.text.lower()
                if "rss" in content and "item" in content:
                    return {"success": True, "message": "Connected to Jackett (Torznab)"}
                elif "error" in content:
                    # Try to get error message from XML
                    try:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(response.content)
                        error_elem = root.find(".//error")
                        if error_elem is not None:
                            msg = error_elem.get("description", "Authentication failed")
                            return {"success": False, "message": f"Error: {msg}"}
                    except:
                        pass
                    return {"success": False, "message": "Authentication failed (check API key)"}
                else:
                    return {"success": True, "message": "Connected to Jackett (Torznab)"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"success": False, "message": "Authentication failed (check API key)"}
            return {"success": False, "message": f"Server error: {e.response.status_code}"}
        except httpx.ConnectError:
            return {"success": False, "message": "Could not reach server (check URL)"}
        except Exception as e:
            return {"success": False, "message": str(e)}