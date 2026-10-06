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
    is_game_grabbed,
)
from app.jackett import JackettClient
from app.qbittorrent import QBittorrentClient
from app.channels import ChannelsClient

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
# Network logic
# ---------------------------------------------------------------------------

LANGUAGE_CODES = {"en", "de", "fr", "pt", "es", "it", "nl", "ru", "ja", "ko", "zh"}


def parse_network(title: str) -> str:
    """Extract the network from the trailing [...] bracket of a title.

    Returns '' if no network can be determined.
    """
    match = re.search(r"\[([^\]]*)\]\s*$", title)
    if not match:
        return ""

    contents = match.group(1)
    tokens = re.split(r"[,/]", contents)
    tokens = [t.strip() for t in tokens if t.strip()]

    if not tokens:
        return ""

    candidate = tokens[-1]

    # Reject language codes (EN, DE, FR, ...)
    if len(candidate) <= 3 and candidate.lower() in LANGUAGE_CODES:
        return ""

    return candidate


def parse_teams(title: str) -> tuple:
    """Extract the two team names from the title, normalized.

    Returns (team_a, team_b, ranked) where team_a/team_b are sorted
    alphabetically and ranked is the count of teams that carried a (NN)
    prefix (0, 1, or 2). Returns ("", "", 0) if the matchup can't be
    parsed.
    """
    match = re.search(r" / (\d{2}\.\d{2}\.\d{4}) / (.+?) \[", title)
    if not match:
        return ("", "", 0)

    matchup = match.group(2)

    if " @ " in matchup:
        away, home = matchup.split(" @ ", 1)
    elif " vs " in matchup:
        away, home = matchup.split(" vs ", 1)
    else:
        return ("", "", 0)

    def has_rank(name: str) -> bool:
        return bool(re.match(r"^\(\d+\)\s*", name))

    ranked = int(has_rank(away)) + int(has_rank(home))

    def normalize(name: str) -> str:
        name = re.sub(r"^\(\d+\)\s*", "", name)   # strip (11)
        return name.strip().lower()

    teams = sorted([normalize(away), normalize(home)])
    return (teams[0], teams[1], ranked)

def build_game_key(parsed_date: str, team_a: str, team_b: str) -> str:
    """Build the dedup key: date + both teams.

    Returns '' if any component is missing, which makes the caller
    skip the game-key check for that release.
    """
    if not parsed_date or not team_a or not team_b:
        return ""
    return f"{parsed_date}|{team_a}|{team_b}"


# ---------------------------------------------------------------------------
# Team logic
# ---------------------------------------------------------------------------


def matches_teams(title: str) -> list:
    """Return ALL watchlist entries that match this title.

    A release can match multiple entries (e.g. 'All' plus an individual
    team). Each matching entry is evaluated independently when deciding
    whether to grab; this function does not pick a winner.
    """
    entries = get_watchlist()
    if not entries:
        return []

    title_lower = title.lower()
    matched = []

    for entry in entries:
        sport = entry.get("sport", "").strip().lower()
        if sport and not title_lower.startswith(sport + " "):
            continue

        team = entry.get("team", "").strip()
        team_lower = team.lower()

        # Reserved keyword: Top 25
        if team_lower == "top 25":
            if sport != "ncaaf":
                continue  # invalid, already warned at query build
            _, _, ranked = parse_teams(title)
            if ranked == 2:
                matched.append(entry)
            continue

        # Reserved keyword: ALL
        if team_lower == "all":
            if sport != "nfl":
                continue  # invalid, already warned at query build
            team_a, team_b, _ = parse_teams(title)
            if team_a and team_b:
                matched.append(entry)
            continue

        if team_lower and team_lower in title_lower:
            matched.append(entry)
            continue

        aliases = entry.get("aliases", "")
        for alias in aliases.split(","):
            alias = alias.strip().lower()
            if alias and alias in title_lower:
                matched.append(entry)
                break

    return matched


# ---------------------------------------------------------------------------
# Channels DVR matching
# ---------------------------------------------------------------------------

def _dvr_has_game(matched_entries: list, channels_games: list) -> str:
    """Return the matched Channels event title if any matching watchlist entry
    maps to a Channels DVR recording, else ''.

    Skips 'All' and 'Top 25' keyword entries. Uses word-boundary matching so
    short team names ('Bills') don't false-match inside longer words.
    """
    for entry in matched_entries:
        team_lower = entry.get("team", "").strip().lower()
        if team_lower in ("all", "top 25"):
            continue

        dvr_name = (entry.get("dvr_name") or "").strip().lower()
        if not dvr_name:
            dvr_name = team_lower

        if not dvr_name:
            continue

        pattern = re.compile(r"\b" + re.escape(dvr_name) + r"\b")

        for teams in channels_games:
            for team in teams:
                if pattern.search(team):
                    return " at ".join(teams)

    return ""


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

async def scan_once() -> dict:
    summary = {"items": 0, "matched": 0, "grabbed": 0, "errors": 0, "skipped_dvr": 0}

    jackett = JackettClient()
    if not jackett.is_configured():
        logger.warning("Scan skipped: Jackett not configured")
        return summary

    qbit = QBittorrentClient()
    if not qbit.is_configured():
        logger.warning("Scan skipped: qBittorrent not configured")
        return summary

    channels = ChannelsClient()
    channels_games = []
    if channels.is_configured():
        channels_games = await channels.get_recorded_games()
        logger.info(f"Channels: {len(channels_games)} recorded sports events")

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
        sport = entry.get("sport", "").strip().lower()

        if team.lower() == "top 25":
            if sport != "ncaaf":
                logger.warning(
                    "Ignoring 'Top 25' entry: sport must be NCAAF (found: %r)",
                    entry.get("sport", ""),
                )
                continue
            query_terms.append("NCAAF")
            continue

        if team.lower() == "all":
            if sport != "nfl":
                logger.warning(
                    "Ignoring 'ALL' entry: sport must be NFL (found: %r)",
                    entry.get("sport", ""),
                )
                continue
            query_terms.append("NFL Football")
            continue

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
    seen_game_keys = set()

    for release in candidates:
        title = release.get("title", "")
        if not matches_date(title):
            continue

        if "condensed" in title.lower():
            logger.info(f"Skipped (condensed game): {title[:70]}")
            continue

        matched_entries = matches_teams(title)
        if not matched_entries:
            continue

        network = parse_network(title)

        # Grab always wins: if ANY matching entry does not exclude this
        # network, the release is eligible. Exclude lists are per-entry
        # vetoes, never a global block.
        deciding_entry = None
        for entry in matched_entries:
            exclude_raw = entry.get("exclude_networks", "") or ""
            exclude_list = [n.strip().lower() for n in exclude_raw.split(",") if n.strip()]
            if not (network and network.lower() in exclude_list):
                deciding_entry = entry
                break

        if not deciding_entry:
            entry_names = ", ".join(e.get("team", "") for e in matched_entries)
            logger.info(
                f"Skipped (network '{network}' excluded by all matching entries "
                f"[{entry_names}]): {title[:70]}"
            )
            continue

        if channels_games:
            dvr_match = _dvr_has_game(matched_entries, channels_games)
            if dvr_match:
                logger.info(
                    f"Skipped (already on Channels DVR: \"{dvr_match}\"): {title[:70]}"
                )
                summary["skipped_dvr"] += 1
                continue

        guid = release.get("guid", "")
        if is_grabbed(guid):
            continue

        parsed_date = parse_date(title)
        team_a, team_b, _ranked = parse_teams(title)
        game_key = build_game_key(parsed_date, team_a, team_b)

        if game_key:
            if is_game_grabbed(game_key):
                logger.info(f"Skipped (game already grabbed): {title[:70]}")
                continue
            if game_key in seen_game_keys:
                logger.info(f"Skipped (game already queued this scan): {title[:70]}")
                continue
            seen_game_keys.add(game_key)

        release["_deciding_entry"] = deciding_entry.get("team", "")
        release["_matched_entries"] = [e.get("team", "") for e in matched_entries]
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

        parsed_date = parse_date(title)
        team_a, team_b, _ranked = parse_teams(title)
        game_key = build_game_key(parsed_date, team_a, team_b)

        result = await qbit.add_torrent(download_url, label="gametimarr")

        if result.get("success"):
            torrent_hash = result.get("hash", "")
            if not torrent_hash:
                logger.error(f"qBittorrent accepted but returned no hash, will retry next scan: {title[:60]}")
                summary["errors"] += 1
                continue
            record_grab(guid, title, torrent_hash, game_key=game_key)
            matched_names = release.get("_matched_entries", [])
            deciding = release.get("_deciding_entry", "")
            if matched_names:
                logger.info(
                    f"Grabbed: {title[:70]} "
                    f"(matched: {', '.join(matched_names)}; grabbed by {deciding})"
                )
            else:
                logger.info(f"Grabbed: {title[:70]}")
            summary["grabbed"] += 1
        else:
            logger.error(f"qBittorrent rejected: {title[:50]} - {result.get('error', 'unknown')}")
            summary["errors"] += 1

    logger.info(
        f"Scan complete: {summary['items']} items, "
        f"{summary['matched']} matched, {summary['grabbed']} grabbed, "
        f"{summary['skipped_dvr']} skipped by DVR"
    )

    return summary