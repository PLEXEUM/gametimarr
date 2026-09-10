"""
postprocess.py - Completion monitor.

Finds completed torrents in the gametimarr category, copies their files to
the destination folder, and marks them as copied.
"""

import os
import shutil
import logging

from app.database import (
    get_setting,
    get_uncopied,
    record_copy,
)
from app.qbittorrent import QBittorrentClient, CATEGORY

logger = logging.getLogger("gametimarr.postprocess")

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".wmv"}


async def check_completed() -> dict:
    summary = {"checked": 0, "copied": 0, "skipped": 0, "errors": 0}

    destination = get_setting("destination_path", "") or ""
    if not destination:
        logger.warning("Monitor skipped: destination path not configured")
        return summary

    if not os.path.isdir(destination):
        logger.warning(f"Monitor skipped: destination not found ({destination})")
        return summary

    qbit = QBittorrentClient()
    if not qbit.is_configured():
        logger.warning("Monitor skipped: qBittorrent not configured")
        return summary

    torrents = await qbit.get_torrents(filter_category=CATEGORY)
    if not torrents:
        return summary

    torrents_by_hash = {t.get("hash", ""): t for t in torrents}

    logger.info(f"Monitor: {len(torrents)} gametimarr torrents in qBittorrent")
    for t in torrents:
        logger.info(f"  qbit hash={t.get('hash','')[:12]}... name={t.get('name','')[:60]}")

    pending = get_uncopied()
    logger.info(f"Monitor: {len(pending)} rows pending copy in DB")

    if not pending:
        return summary

    for row in pending:
        summary["checked"] += 1

        torrent_hash = row.get("torrent_hash", "")
        title = row.get("title", "")
        guid = row.get("guid", "")

        if not torrent_hash:
            logger.info(f"Monitor skip: no hash for {title[:50]}")
            summary["skipped"] += 1
            continue

        torrent = torrents_by_hash.get(torrent_hash)
        if not torrent:
            logger.info(f"Monitor skip: hash not in qBittorrent for {title[:50]}")
            summary["skipped"] += 1
            continue

        if torrent.get("progress", 0) < 1.0:
            logger.info(f"Monitor skip: progress {torrent.get('progress')} for {title[:50]}")
            continue

        try:
            copied_files = await _copy_torrent_files(qbit, torrent, destination)
            if copied_files:
                record_copy(guid)
                logger.info(f"Copied: {title[:70]}")
                summary["copied"] += 1
            else:
                logger.warning(f"No video files found for: {title[:50]}")
                summary["skipped"] += 1
        except Exception as e:
            logger.error(f"Copy failed for {title[:40]}: {e}")
            summary["errors"] += 1

    if summary["copied"]:
        logger.info(f"Monitor complete: {summary['copied']} copied")

    return summary


# ---------------------------------------------------------------------------
# Internal: copy logic
# ---------------------------------------------------------------------------

async def _copy_torrent_files(qbit: QBittorrentClient, torrent: dict, destination: str) -> list:
    torrent_hash = torrent.get("hash", "")
    save_path = torrent.get("save_path", "")
    torrent_name = torrent.get("name", "")

    if not save_path:
        return []

    files = await qbit.get_torrent_files(torrent_hash)
    if not files:
        return []

    logger.info(f"Copy debug: save_path = {save_path}")
    logger.info(f"Copy debug: torrent name = {torrent_name}")
    logger.info(f"Copy debug: {len(files)} files returned from qBittorrent")
    for f in files:
        logger.info(f"  file entry: name='{f.get('name','')}' size={f.get('size',0)}")

    copied = []

    for file_entry in files:
        rel_name = file_entry.get("name", "")
        if not rel_name:
            continue

        ext = os.path.splitext(rel_name)[1].lower()
        if ext not in VIDEO_EXTENSIONS:
            logger.info(f"  skip: '{rel_name}' extension '{ext}' not in video list")
            continue

        source = os.path.join(save_path, rel_name)
        logger.info(f"  checking source: {source}")
        logger.info(f"  isfile: {os.path.isfile(source)}")

        if not os.path.isfile(source):
            continue

        filename = os.path.basename(rel_name)

        if not filename.lower().startswith(torrent_name.lower()[:20]):
            filename = f"{_safe_filename(torrent_name)} - {filename}"

        target = os.path.join(destination, filename)
        target = _unique_path(target)

        _hardlink_or_copy(source, target)
        copied.append(target)

    return copied


def _hardlink_or_copy(source: str, target: str) -> None:
    try:
        os.link(source, target)
        return
    except OSError:
        pass

    shutil.copy2(source, target)


def _unique_path(path: str) -> str:
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
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".")