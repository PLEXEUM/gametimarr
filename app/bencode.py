"""
bencode.py - Minimal bencode parser and torrent info-hash extractor.

Torrent files are bencoded dicts. The info-hash is the SHA-1 of the bencoded
"info" sub-dict. This module parses just enough bencode to extract that hash.

Bencode types:
    i<number>e         -> integer
    <length>:<bytes>   -> byte string
    l<items>e          -> list
    d<key><value>...e  -> dictionary (keys sorted, strings)
"""

import hashlib


def _decode(data: bytes, pos: int):
    """Decode one bencoded value starting at pos. Returns (value, new_pos)."""
    if pos >= len(data):
        raise ValueError("Unexpected end of data")

    ch = data[pos:pos + 1]

    if ch == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1:end]), end + 1

    if ch == b"l":
        pos += 1
        items = []
        while data[pos:pos + 1] != b"e":
            item, pos = _decode(data, pos)
            items.append(item)
        return items, pos + 1

    if ch == b"d":
        pos += 1
        result = {}
        while data[pos:pos + 1] != b"e":
            key, pos = _decode(data, pos)
            value, pos = _decode(data, pos)
            result[key] = value
        return result, pos + 1

    if ch.isdigit():
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        start = colon + 1
        return data[start:start + length], start + length

    raise ValueError(f"Invalid bencode at position {pos}: {ch!r}")


def get_torrent_info_hash(torrent_bytes: bytes) -> str:
    """
    Extract the info-hash from a .torrent file's bytes.
    Returns the SHA-1 hex string, or '' on failure.

    The info-hash is the SHA-1 of the bencoded "info" dictionary. Because we
    re-encode nothing and instead slice the original bytes, the hash matches
    what qBittorrent and every other client computes.
    """
    try:
        # Find the "info" key, then find where its value ends by decoding it
        # and using the returned position. Slice the original bytes between
        # those positions to get the exact bencoded info dict.
        marker = b"4:info"
        idx = torrent_bytes.find(marker)
        if idx == -1:
            return ""

        value_start = idx + len(marker)
        _, value_end = _decode(torrent_bytes, value_start)

        info_bytes = torrent_bytes[value_start:value_end]
        return hashlib.sha1(info_bytes).hexdigest()
    except Exception:
        return ""