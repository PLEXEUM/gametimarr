import httpx
from urllib.parse import quote, urlparse, parse_qs
import xml.etree.ElementTree as ET
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class JackettClient:
    def __init__(self):
        logger.info("=== JackettClient INIT ===")
        
        # Load the Torznab URL from database
        self.torznab_url = get_setting("jackett_torznab_url")
        logger.info(f"[INIT] raw torznab_url from DB: '{self.torznab_url}'")
        
        if self.torznab_url:
            logger.info(f"[INIT] torznab_url length: {len(self.torznab_url)}")
            logger.info(f"[INIT] first 100 chars: {self.torznab_url[:100]}")
        else:
            logger.warning("[INIT] torznab_url is EMPTY or None")

        if not self.torznab_url:
            logger.warning("Jackett Torznab URL not configured")

    def is_configured(self) -> bool:
        """Check if Jackett is configured."""
        result = bool(self.torznab_url)
        logger.info(f"[is_configured] returning {result} (torznab_url: '{self.torznab_url[:30] if self.torznab_url else 'EMPTY'}')")
        return result

    async def _request(self, url: str) -> bytes:
        """Make a request to the Torznab URL."""
        logger.info(f"[_request] URL: {url[:100]}...")
        
        if not self.is_configured():
            logger.warning("[_request] Not configured, returning empty")
            return b""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                logger.info(f"[_request] Response status: {response.status_code}, content length: {len(response.content)}")
                return response.content
        except Exception as e:
            logger.error(f"[_request] Request error: {e}")
            return b""

    async def search(self, query: str) -> list:
        """
        Search for releases using Torznab.
        
        Args:
            query: Search query (e.g., "Auburn Baylor")
        
        Returns:
            List of release results
        """
        logger.info(f"=== JackettClient.search() called with query: '{query}' ===")
        
        if not self.is_configured():
            logger.warning("[search] Not configured, returning empty list")
            return []

        # Build the Torznab URL with the query
        if "?" in self.torznab_url:
            url = f"{self.torznab_url}&t=search&q={quote(query)}"
        else:
            url = f"{self.torznab_url}?t=search&q={quote(query)}"
        
        logger.info(f"[search] Full URL: {url[:150]}...")
        
        content = await self._request(url)
        
        if not content:
            logger.warning("[search] No content received from _request")
            return []
        
        # Parse the XML response
        logger.info("[search] Parsing Torznab response...")
        results = self._parse_torznab_response(content)
        logger.info(f"[search] Found {len(results)} results")
        return results

    async def search_sport_event(self, home_team: str, away_team: str, year: int = None) -> list:
        """
        Build a search query for a sports event.
        
        Examples:
            - "Auburn Baylor"
            - "Auburn vs Baylor 2026"
        """
        logger.info(f"=== search_sport_event: {home_team} vs {away_team}, year={year} ===")
        
        query_parts = [home_team, away_team]
        if year:
            query_parts.append(str(year))
        
        query = " ".join(query_parts)
        logger.info(f"[search_sport_event] Query 1: '{query}'")
        results = await self.search(query)
        
        # If no results, try with "vs" format
        if not results:
            query = f"{home_team} vs {away_team}"
            if year:
                query += f" {year}"
            logger.info(f"[search_sport_event] Query 2 (vs format): '{query}'")
            results = await self.search(query)
        else:
            logger.info(f"[search_sport_event] Query 1 returned {len(results)} results, skipping vs format")
        
        logger.info(f"[search_sport_event] Final results: {len(results)}")
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
        logger.info("=== _parse_torznab_response ===")
        
        releases = []
        
        try:
            # Parse XML
            root = ET.fromstring(content)
            logger.info("[parse] XML parsed successfully")
            
            # Find all item elements
            namespace = {"torznab": "http://torznab.com/schemas/2015/feed"}
            items = root.findall(".//item")
            logger.info(f"[parse] Found {len(items)} items in XML")
            
            for idx, item in enumerate(items):
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
                logger.debug(f"[parse] Item {idx+1}: '{release.get('title', 'Unknown')[:50]}...'")
                
        except ET.ParseError as e:
            logger.error(f"[parse] Failed to parse Torznab response: {e}")
            logger.error(f"[parse] Content preview: {content[:500]}")
        except Exception as e:
            logger.error(f"[parse] Error parsing Torznab response: {e}")
        
        logger.info(f"[parse] Returning {len(releases)} releases")
        return releases

    async def get_release_download_url(self, release: dict) -> str:
        """Extract download URL from a release."""
        logger.info(f"[get_release_download_url] Release title: {release.get('title', 'Unknown')[:50]}...")
        
        # Try link field
        download_url = release.get("link")
        if download_url:
            logger.info(f"[get_release_download_url] Found link: {download_url[:50]}...")
            return download_url
        
        # Try guid
        guid = release.get("guid")
        if guid and guid.startswith("http"):
            logger.info(f"[get_release_download_url] Found guid: {guid[:50]}...")
            return guid
        
        logger.warning("[get_release_download_url] No download URL found")
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
        logger.info(f"=== test_connection: test_url = '{test_url[:50] if test_url else 'EMPTY'}' ===")
        
        if not test_url:
            return {"success": False, "message": "Torznab URL is required"}
        
        try:
            # Add a test query to the URL
            if "?" in test_url:
                url = f"{test_url}&t=search&q=test&limit=1"
            else:
                url = f"{test_url}?t=search&q=test&limit=1"
            
            logger.info(f"[test_connection] Request URL: {url[:150]}...")
            
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.text.lower()
                logger.info(f"[test_connection] Response status: {response.status_code}, content length: {len(response.content)}")
                
                if "rss" in content and "item" in content:
                    logger.info("[test_connection] Success: Valid RSS response with items")
                    return {"success": True, "message": "Connected to Jackett (Torznab)"}
                elif "error" in content:
                    logger.warning("[test_connection] Error detected in response")
                    try:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(response.content)
                        error_elem = root.find(".//error")
                        if error_elem is not None:
                            msg = error_elem.get("description", "Authentication failed")
                            logger.warning(f"[test_connection] Error message: {msg}")
                            return {"success": False, "message": f"Error: {msg}"}
                    except:
                        pass
                    return {"success": False, "message": "Authentication failed (check API key)"}
                else:
                    logger.info("[test_connection] Response received but not standard RSS")
                    return {"success": True, "message": "Connected to Jackett (Torznab)"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("[test_connection] 401 Unauthorized")
                return {"success": False, "message": "Authentication failed (check API key)"}
            logger.error(f"[test_connection] HTTP error: {e.response.status_code}")
            return {"success": False, "message": f"Server error: {e.response.status_code}"}
        except httpx.ConnectError:
            logger.error("[test_connection] Connection error")
            return {"success": False, "message": "Could not reach server (check URL)"}
        except Exception as e:
            logger.error(f"[test_connection] Unexpected error: {e}")
            return {"success": False, "message": str(e)}