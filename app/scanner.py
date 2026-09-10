"""
scanner.py - The scan loop.

Orchestrates one scan:
    1. Query Jackett with each configured broad term.
    2. Filter results by date (today or yesterday, local timezone).
    3. Filter results by team (case-insensitive substring against watchlist).
    4. Dedup by GUID.
    5. Hand matching releases to qBittorrent.

All date and team logic lives here. No HTTP code in this file.
"""

import re
from datetime import date, datetime, timedelta

from app.database import (
    get_setting,
    get_watchlist,
    is_grabbed,
    record_grab,
    expire_old_grabs,
    log_event,
)
from app.jackett import JackettClient
from app.qbittorrent import QBittorrentClient


# Default broad query terms if none are configured
DEFAULT_QUERIES = ["NFL", "NCAAF", "MLB", "NBA", "NHL"]

# Matches DD.MM.YYYY anywhere in a title
DATE_PATTERN = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


# ---------------------------------------------------------------------------
# Date logic
# ---------------------------------------------------------------------------

def target_dates() -> set:
    """
    Return the set of date strings to match against: today and yesterday,
    formatted as DD.MM.YYYY in the container's local timezone.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    return {
        today.strftime("%d.%m.%Y"),
        yesterday.strftime("%d.%m.%Y"),
    }


def parse_date(title: str) -> str:
    """
    Extract the DD.MM.YYYY date string from a title, or return "".
    Only the first match is used.
    """
    match = DATE_PATTERN.search(title)
    return match.group(1) if match else ""


def matches_date(title: str) -> bool:
    """True if the title contains a date that's today or yesterday."""
    parsed = parse_date(title)
    if not parsed:
        return False
    return parsed in target_dates()


# ---------------------------------------------------------------------------
# Team logic
# ---------------------------------------------------------------------------

def matches_team(title: str) -> bool:
    """
    True if the title contains any watchlist team name or alias.

    Matching is case-insensitive substring. Each watchlist entry may have
    comma-separated aliases. If the watchlist is empty, nothing matches.
    """
    entries = get_watchlist()
    if not entries:
        return False

    title_lower = title.lower()

    for entry in entries:
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
    """
    Run a single scan. Returns a summary dict for logging:
        {"items": int, "matched": int, "grabbed": int, "errors": int}
    """
    summary = {"items": 0, "matched": 0, "grabbed": 0, "errors": 0}

    jackett = JackettClient()
    if not jackett.is_configured():
        log_event("Scan skipped: Jackett not configured")
        return summary

    qbit = QBittorrentClient()
    if not qbit.is_configured():
        log_event("Scan skipped: qBittorrent not configured")
        return summary

    log_event("Scan started")

    # Prune old dedup entries once per scan
    expire_old_grabs()

    # Load broad query terms from settings, or use defaults
    queries_raw = get_setting("query_terms", "")
    queries = [q.strip() for q in queries_raw.split(",") if q.strip()] or DEFAULT_QUERIES

    # Collect all releases across queries, dedup by GUID in memory
    seen_guids = set()
    candidates = []

    for query in queries:
        releases = await jackett.recent_releases(query)
        for release in releases:
            guid = release.get("guid", "")
            if not guid or guid in seen_guids:
                continue
            seen_guids.add(guid)
            candidates.append(release)

    summary["items"] = len(candidates)

    if not candidates:
        log_event("Scan complete: no results from Jackett")
        return summary

    # Filter: date first, then team, then dedup
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
        log_event(f"Scan complete: {summary['items']} items, 0 new matches")
        return summary

    # Hand each match to qBittorrent
    for release in matched:
        title = release.get("title", "")
        guid = release.get("guid", "")
        download_url = jackett.get_download_url(release)

        if not download_url:
            log_event(f"No download URL for: {title[:60]}")
            summary["errors"] += 1
            continue

        # Record the grab before sending, so a crash mid-send doesn't cause
        # a double-grab on the next scan.
        record_grab(guid, title)

        result = await qbit.add_torrent(download_url, label="gametimarr")

        if result.get("success"):
            # Update the row with the torrent hash now that we have it
            torrent_hash = result.get("hash", "")
            if torrent_hash:
                record_grab(guid, title, torrent_hash)
            log_event(f"Grabbed: {title[:70]}")
            summary["grabbed"] += 1
        else:
            log_event(f"qBittorrent rejected: {title[:50]} - {result.get('error', 'unknown')}")
            summary["errors"] += 1

    log_event(
        f"Scan complete: {summary['items']} items, "
        f"{summary['matched']} matched, {summary['grabbed']} grabbed"
    )

    return summary