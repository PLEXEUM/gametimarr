"""
postprocess.py - Completion monitor.

Runs every 60 minutes. Finds completed torrents in the gametimarr category,
copies their files to the destination folder, and marks them as copied.

The original files stay in qBittorrent's download folder so seeding continues
unaffected. This module only reads from there and writes to the destination.
"""

import os
import shutil

from app.database import (
    get_setting,
    get_uncopied,
    record_copy,
    log_event,
)
from app.qbittorrent import QBittorrentClient, CATEGORY


# Video file extensions worth copying. Everything else in a torrent (nfo,
# samples, images) is skipped.
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".wmv"}


async def check_completed() -> dict:
    """
    Run one monitor cycle. Returns a summary dict:
        {"checked": int, "copied": int, "skipped": int, "errors": int}
    """
    summary = {"checked": 0, "copied": 0, "skipped": 0, "errors": 0}

    destination = get_setting("destination_path", "") or ""
    if not destination:
        log_event("Monitor skipped: destination path not configured")
        return summary

    if not os.path.isdir(destination):
        log_event(f"Monitor skipped: destination not found ({destination})")
        return summary

    qbit = QBittorrentClient()
    if not qbit.is_configured():
        log_event("Monitor skipped: qBittorrent not configured")
        return summary

    # Ask qBittorrent for its current gametimarr torrents
    torrents = await qbit.get_torrents(filter_category=CATEGORY)
    if not torrents:
        return summary

    # Build a hash -> torrent dict for quick lookup
    torrents_by_hash = {t.get("hash", ""): t for t in torrents}

    # Fetch all grabbed rows that haven't been copied yet
    pending = get_uncopied()
    if not pending:
        return summary

    for row in pending:
        summary["checked"] += 1

        torrent_hash = row.get("torrent_hash", "")
        title = row.get("title", "")
        guid = row.get("guid", "")

        if not torrent_hash:
            # No hash means qBittorrent never confirmed the add. Skip.
            summary["skipped"] += 1
            continue

        torrent = torrents_by_hash.get(torrent_hash)
        if not torrent:
            # Torrent not in qBittorrent anymore (deleted by user). Skip.
            summary["skipped"] += 1
            continue

        if torrent.get("progress", 0) < 1.0:
            # Still downloading. Try again next cycle.
            continue

        # Torrent is complete. Copy its files.
        try:
            copied_files = await _copy_torrent_files(qbit, torrent, destination)
            if copied_files:
                record_copy(guid)
                log_event(f"Copied: {title[:70]}")
                summary["copied"] += 1
            else:
                log_event(f"No video files found for: {title[:50]}")
                summary["skipped"] += 1
        except Exception as e:
            log_event(f"Copy failed for {title[:40]}: {e}")
            summary["errors"] += 1

    if summary["copied"]:
        log_event(f"Monitor complete: {summary['copied']} copied")

    return summary


# ---------------------------------------------------------------------------
# Internal: copy logic
# ---------------------------------------------------------------------------

async def _copy_torrent_files(qbit: QBittorrentClient, torrent: dict, destination: str) -> list:
    """
    Copy the video files of a completed torrent to the destination folder.
    Returns the list of destination paths that were written.

    Hardlinks are attempted first when the source and destination are on the
    same filesystem. Falls back to a full copy otherwise.
    """
    torrent_hash = torrent.get("hash", "")
    save_path = torrent.get("save_path", "")
    torrent_name = torrent.get("name", "")

    if not save_path:
        return []

    files = await qbit.get_torrent_files(torrent_hash)
    if not files:
        return []

    copied = []

    for file_entry in files:
        rel_name = file_entry.get("name", "")
        if not rel_name:
            continue

        ext = os.path.splitext(rel_name)[1].lower()
        if ext not in VIDEO_EXTENSIONS:
            continue

        source = os.path.join(save_path, rel_name)
        if not os.path.isfile(source):
            continue

        # Flatten the path: use only the filename, not any subdirectories the
        # torrent may have created.
        filename = os.path.basename(rel_name)

        # Prefix with the torrent name to keep things identifiable, unless the
        # filename already starts with it.
        if not filename.lower().startswith(torrent_name.lower()[:20]):
            filename = f"{_safe_filename(torrent_name)} - {filename}"

        target = os.path.join(destination, filename)
        target = _unique_path(target)

        _hardlink_or_copy(source, target)
        copied.append(target)

    return copied


def _hardlink_or_copy(source: str, target: str) -> None:
    """
    Try to hardlink source to target. Fall back to copying if the filesystems
    differ or hardlinks aren't supported.
    """
    try:
        os.link(source, target)
        return
    except OSError:
        pass

    shutil.copy2(source, target)


def _unique_path(path: str) -> str:
    """If the path exists, append (1), (2), etc. until it doesn't."""
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{base} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _safe_filename(name: str) -> str:
    """Strip characters that are illegal in Windows filenames."""
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".")