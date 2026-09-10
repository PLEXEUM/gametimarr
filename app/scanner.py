"""
scanner.py - The scan loop.

Orchestrates one scan:
    1. Query Jackett for each watchlist team name and alias.
    2. Filter results by date (today or yesterday, local timezone).
    3. Filter results by team (case-insensitive substring against watchlist).
    4. Dedup by GUID.
    5. Hand matching releases to qBittorrent.
"""

import re
import logging
from datetime import date, timedelta

from app.database import (
    get_watchlist,
    is_grabbed,
    record_grab,
    expire_old_grabs,
)
from app.jackett import JackettClient
from app.qbittorrent import QBittorrentClient

logger = logging.getLogger("gametimarr.scanner")

DATE_PATTERN = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


# ---------------------------------------------------------------------------
# Date logic
# ---------------------------------------------------------------------------

def target_dates() -> set:
    today = date.today()
    yesterday = today - timedelta(days=1)
    return {
        today.strftime("%d.%m.%Y"),
        yesterday.strftime("%d.%m.%Y"),
    }


def parse_date(title: str) -> str:
    match = DATE_PATTERN.search(title)
    return match.group(1) if match else ""


def matches_date(title: str) -> bool:
    parsed = parse_date(title)
    if not parsed:
        return False
    return parsed in target_dates()


# ---------------------------------------------------------------------------
# Team logic
# ---------------------------------------------------------------------------


def matches_team(title: str) -> bool:
    entries = get_watchlist()
    if not entries:
        return False

    title_lower = title.lower()

    for entry in entries:
        sport = entry.get("sport", "").strip().lower()
        if sport and not title_lower.startswith(sport + " "):
            continue

        team = entry.get("team", "").strip().lower()
        if team and team in title_lower:
            return True

        aliases = entry.get("aliases", "")
        for alias in aliases.split(","):
            alias = alias.strip().lower()
            if alias and alias in title_lower:
                return True

    return False

# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

async def scan_once() -> dict:
    summary = {"items": 0, "matched": 0, "grabbed": 0, "errors": 0}

    jackett = JackettClient()
    if not jackett.is_configured():
        logger.warning("Scan skipped: Jackett not configured")
        return summary

    qbit = QBittorrentClient()
    if not qbit.is_configured():
        logger.warning("Scan skipped: qBittorrent not configured")
        return summary

    logger.info("Scan started")

    expire_old_grabs()

    
    # Build query terms from the watchlist: each team name plus each alias.
    watchlist = get_watchlist()
    if not watchlist:
        logger.info("Scan skipped: watchlist is empty")
        return summary

    query_terms = []
    for entry in watchlist:
        team = entry.get("team", "").strip()
        if team:
            query_terms.append(team)

        aliases = entry.get("aliases", "")
        for alias in aliases.split(","):
            alias = alias.strip()
            if alias:
                query_terms.append(alias)

    # Deduplicate query terms (in case a team name is also an alias)
    query_terms = list(dict.fromkeys(query_terms))

    logger.info(f"Queries this scan: {query_terms}")

    # Collect all releases across queries, dedup by GUID in memory
    seen_guids = set()
    candidates = []

    for query in query_terms:
        releases = await jackett.recent_releases(query)
        for release in releases:
            guid = release.get("guid", "")
            if not guid or guid in seen_guids:
                continue
            seen_guids.add(guid)
            candidates.append(release)

    summary["items"] = len(candidates)

    logger.info(f"Watchlist at scan time: {[w['team'] for w in get_watchlist()]}")
    for r in candidates[:5]:
        logger.info(f"DEBUG title: {r.get('title','')[:90]}")
    
    if not candidates:
        logger.info("Scan complete: no results from Jackett")
        return summary

    matched = []
    for release in candidates:
        title = release.get("title", "")
        if not matches_date(title):
            continue
        if not matches_team(title):
            continue
        guid = release.get("guid", "")
        if is_grabbed(guid):
            continue
        matched.append(release)

    summary["matched"] = len(matched)

    if not matched:
        logger.info(f"Scan complete: {summary['items']} items, 0 new matches")
        return summary

    for release in matched:
        title = release.get("title", "")
        guid = release.get("guid", "")
        download_url = jackett.get_download_url(release)

        if not download_url:
            logger.warning(f"No download URL for: {title[:60]}")
            summary["errors"] += 1
            continue

        record_grab(guid, title)

        result = await qbit.add_torrent(download_url, label="gametimarr")

        if result.get("success"):
            torrent_hash = result.get("hash", "")
            if torrent_hash:
                record_grab(guid, title, torrent_hash)
            logger.info(f"Grabbed: {title[:70]}")
            summary["grabbed"] += 1
        else:
            logger.error(f"qBittorrent rejected: {title[:50]} - {result.get('error', 'unknown')}")
            summary["errors"] += 1

    logger.info(
        f"Scan complete: {summary['items']} items, "
        f"{summary['matched']} matched, {summary['grabbed']} grabbed"
    )

    return summary