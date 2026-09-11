# 🏈 Gametimarr

**A self-hosted watcher for 720pier.ru that automatically grabs the games you care about and copies them to a folder you can watch from — while leaving the original torrent seeding.**

You give it a list of teams. It scans the tracker through Jackett every 90 minutes. When it finds a game from today or yesterday that matches a team on your list, it hands the torrent to qBittorrent. When the download finishes, it copies the video file to a destination folder. The seeding copy stays put.

---

## What It Does

- Watches **Tracker** through Jackett's Torznab API, one query per team name and alias
- **Filters by date** — only games dated today or yesterday (in your local timezone) are considered
- **Filters by team** — case-insensitive substring match against your watchlist, with optional per-entry sport prefix (NCAAF, NCAAB, MLB, etc.) to avoid cross-sport false positives
- **Deduplicates by Torznab GUID** so the same game is never grabbed twice
- Sends to **qBittorrent** with the `gametimarr` category
- **Copies completed files** to a destination folder while the original stays seeding
- **Runs on a schedule** — scanner every 90 minutes, monitor every 60 minutes
- Single **web UI** at `http://<host>:7667` for configuration and manual triggers

---

## Requirements

- **Docker** (Docker Desktop on Windows, or Docker on Linux/macOS)
- **Jackett** running with the indexer configured and logged in
- **qBittorrent** with Web UI enabled (API v2, qBittorrent 4.1+)
- Network access from the gametimarr container to both Jackett and qBittorrent
- A folder for completed copies — local drive, mapped drive, or network share

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/plexeum/gametimarr.git
cd gametimarr
```

### 2. Set up the compose file

Copy the example and edit it with your real paths:

```bash
cp docker/docker-compose.example.yml docker/docker-compose.yml
```

The important parts to change:

```yaml
services:
  gametimarr:
    image: plexeum/gametimarr:latest
    container_name: gametimarr
    restart: unless-stopped
    environment:
      - TZ=America/New_York              # your timezone
      - WEB_PORT=7667
    volumes:
      - ./data:/data                     # SQLite database (persistent)
      - ./logs:/logs                     # daily rotating logs
      - qbit_downloads:/downloads        # qBittorrent's download folder
      - I:\Folder\Sports:/watch   # destination for copies
    ports:
      - "7667:7667"

volumes:
  qbit_downloads:
    driver: local
    driver_opts:
      type: cifs
      device: "//192.168.1.1/Folder/qBit Files"
      o: "username=guest,password=,vers=2.1,uid=1000,gid=1000,file_mode=0777,dir_mode=0777"
```

### 3. Start it

```bash
docker compose up -d
docker logs -f gametimarr
```

Expected startup output:

```
=== gametimarr starting ===
Data directory OK: /data
Download path OK: /downloads
Destination path OK: /watch
Log directory OK: /logs
Database initialized at /data/gametimarr.db
Scanner thread started (interval: 90 min)
Monitor thread started (interval: 60 min)
Web server starting on port 7667
```

If any of those checks fail, the container exits with a clear error — fix the path and restart.

### 4. Configure via the web UI

Open `http://<your-host>:7667` and fill in:

- **Jackett Torznab URL** — from your Jackett dashboard
- **qBittorrent** — host, port, username, password
- **Destination** — `/watch` (this is the container path, not the host path)

Click **Test** on both. Click **Save Settings**.

### 5. Add teams to the watchlist

In the **Watchlist** panel:

- **Team** — the name that appears in the tracker's titles (e.g. `New York Yankees`, `South Florida`, `Syracuse`)
- **Aliases** — optional, comma-separated search terms (e.g. `Yankees, NYY`)
- **Sport** — optional, a prefix filter (e.g. `NCAAF`, `NCAAB`, `MLB`)

Click **Add**.

### 6. Test it

Click **Run Scan Now** in the Manual Run panel. Watch the log:

```bash
docker logs gametimarr --tail 20
```

If a matching game from today or yesterday exists, you'll see:

```
Grabbed: MLB 2026 / RS / 09.09.2026 / Cincinnati Reds @ Los Angeles Dodgers (3/3) [...]
```

When the torrent finishes in qBittorrent, click **Run Monitor Now** to trigger the copy immediately. You'll see:

```
Copied: MLB 2026 / RS / 09.09.2026 / Cincinnati Reds @ Los Angeles Dodgers (3/3)
```

And the file appears in your destination folder.

---

## How the Matching Works

### Date Filter

The scanner extracts a date from each title using a regex for `DD.MM.YYYY`. It matches against a set of two dates: **today** and **yesterday**, in the container's local timezone. A game dated `09.09.2026` will match on September 9th or 10th, but not on the 11th.

The "yesterday" tolerance is there to catch games posted after midnight for a game that started the previous evening. Because the dedup table prevents re-grabbing, including yesterday doesn't cause duplicate downloads.

### Team Filter

For each watchlist entry, the scanner checks:

1. If a sport is set, the title must start with that prefix (`NCAAF` with a trailing space, so `NCAAF` doesn't match a hypothetical `NCAAFX`).
2. The title must contain the team name or any alias, case-insensitive.

If either check fails, the entry is skipped and the next one is tried.

### Query Strategy

The scanner queries Jackett once per watchlist term — the team name plus each alias. This is necessary because 720pier's tracker search is token-based and doesn't respond to league abbreviations like `MLB` or `NFL`. Querying the actual team name (`Yankees`) returns the right games.

---

## File Locations

| What | Where (container) | Where (host, with default compose) |
|------|-------------------|-------------------------------------|
| SQLite database | `/data/gametimarr.db` | `./data/gametimarr.db` |
| Daily logs | `/logs/YYYY-MM-DD.log` | `./logs/YYYY-MM-DD.log` |
| qBittorrent downloads | `/downloads` | Mounted from the MyCloud SMB share |
| Completed copies | `/watch` | The host path you set in the compose file |

Logs are kept for **5 days**. Older files are deleted automatically when a new day's log is created.

---

## Common Issues

### "Download path OK" but the folder is empty

Docker Desktop on Windows can't bind-mount UNC paths directly. If you see the path valid but no files inside, the mount didn't actually connect. The fix is a **CIFS volume** in the compose file, using the NAS's IP address instead of a hostname:

```yaml
volumes:
  qbit_downloads:
    driver: local
    driver_opts:
      type: cifs
      device: "//192.168.1.1/Folder/qBit Files"
      o: "username=guest,password=,vers=2.1,uid=1000,gid=1000,file_mode=0777,dir_mode=0777"
```

CIFS mounts on Windows with passwordless shares can be finicky. If `vers=2.1` fails, try `vers=3.0` or `vers=1.0`. If the share requires credentials, add `username=` and `password=` to the `o:` string.

### Monitor says "Source file not found"

qBittorrent reports download paths in the format it sees them, which may be a Windows path (`G:\qBit Files - Cloud 2`). The container sees that same folder at `/downloads`. The monitor translates the path in `postprocess.py`. If you've moved qBittorrent's download folder, update the `qbit_root` variable in that file to match.

### Scan finds nothing

Three common causes:

1. **No games on the tracker for today or yesterday.** The filter is strict. If the season is over, or no games are scheduled, nothing matches.
2. **Team name doesn't appear in the tracker's titles.** The tracker uses specific formats like `New York Yankees` (full name) or `Syracuse Orange` (with nickname). If your watchlist entry is just `Syracuse`, it'll match. If it's `Syracuse Football`, it won't. Use the shortest distinguishing term as the team name or add an alias.
3. **Jackett isn't logged in to 720pier.** Test the Torznab URL in the UI. If the connection test fails, check Jackett's dashboard.

### Cross-sport false positives

If you follow a college team that plays multiple sports, use the **sport** field to scope the entry. For example, `South Florida` with sport `NCAAF` will only match football games, not basketball (NCAAM) or any other sport.

### The same game was grabbed twice

This shouldn't happen because of the GUID dedup, but if it does, check whether the tracker re-posted the game with a different thread ID. GUIDs are based on the thread URL, so a re-post gets a new GUID and looks like a new game. The date and title would be identical though, so it's easy to spot in the qBittorrent list.

---

## API Endpoints

All endpoints are on port **7667**. None require authentication — keep the container on a trusted network or put it behind a reverse proxy with auth.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | The single-screen UI |
| GET | `/status` | Current settings and watchlist (JSON) |
| POST | `/config` | Save settings |
| POST | `/watchlist` | Add or remove a team |
| POST | `/test/jackett` | Test a Torznab URL without saving |
| POST | `/test/qbit` | Test qBittorrent credentials without saving |
| POST | `/run/scan` | Trigger a scan immediately |
| POST | `/run/monitor` | Trigger a monitor cycle immediately |

---

## Architecture Notes

The app runs three things in one container:

1. **Scanner thread** — runs every 90 minutes. Queries Jackett, filters, dedups, hands matches to qBittorrent.
2. **Monitor thread** — runs every 60 minutes. Checks completed torrents in qBittorrent, copies files to the destination.
3. **Web server** — FastAPI + Uvicorn on port 7667.

The two background threads share an SQLite connection with `check_same_thread=False` and a lock in `database.py`.

State lives in three places:

- **SQLite** (`/data/gametimarr.db`) — settings, watchlist, dedup rows.
- **Log files** (`/logs/`) — daily rotating, 5-day retention.
- **qBittorrent** — the actual torrents and their files.

The app never modifies or moves qBittorrent's files. It reads them, computes the info-hash from the `.torrent` bytes, and copies to the destination. The original torrent continues seeding unaffected.

---

## File Tree

```
gametimarr/
├── app/
│   ├── __init__.py
│   ├── main.py               # Entry point, threads, path validation
│   ├── database.py           # SQLite schema and helpers
│   ├── jackett.py            # Torznab client
│   ├── scanner.py            # Scan loop, date/team/sport filters
│   ├── qbittorrent.py        # qBittorrent API v2 client
│   ├── bencode.py            # Torrent info-hash extraction
│   ├── postprocess.py        # Completion monitor, file copy
│   └── web.py                # Single-screen UI + routes
├── data/                     # SQLite database (gitignored)
├── logs/                     # Daily log files (gitignored)
├── docker/
│   └── docker-compose.example.yml
├── Dockerfile
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Contributing

Issues and pull requests are welcome. The codebase is deliberately small — about 700 lines of Python across seven files. The scanner and monitor are the pieces most likely to need adjustments, since trackers and API behaviors change.

If you're adding a feature, keep the "single container, single screen, single job" ethos. This is meant to be a personal tool, not a general-purpose media manager.

---

## License

MIT

---

**Gametimarr** – Grab the games, keep the seeds. 🏈