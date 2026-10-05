# 🏈 Gametimarr

**A self-hosted watcher for Torznab feed that automatically grabs the games you care about and copies them to a folder you can watch from — while leaving the original torrent seeding.**

You give it a list of teams. It scans the tracker through Jackett every 90 minutes. When it finds a game from today or yesterday that matches a team on your list, it hands the torrent to qBittorrent. When the download finishes, it copies the video file to a destination folder. The seeding copy stays put.

---

## What It Does

- Watches **Tracker** through Jackett's Torznab API, one query per team name and alias
- **Filters by date** — only games dated today or yesterday (in your local timezone) are considered
- **Filters by team** — case-insensitive substring match against your watchlist, with optional per-entry sport prefix (NCAAF, NCAAB, MLB, etc.) to avoid cross-sport false positives
- **Filters by broadcast network** — each watchlist entry can exclude networks your DVR already records (e.g. `ABC, CBS, NBC, FOX`), so only games you can't record get grabbed
- **Grabs ranked-vs-ranked CFB games** — add a watchlist entry with the team name `Top 25` and sport `NCAAF` to grab college football games where **both** teams are ranked
- **Grabs NFL primetime games** — add a watchlist entry with the team name `ALL` and sport `NFL` to grab any NFL game, then use the exclude networks list to skip the ones your DVR can record
- **Deduplicates by Torznab GUID** so the same game is never grabbed twice
- **Skips games your Channels DVR already recorded** — if Channels has it, gametimarr doesn't grab it
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
- **Channels DVR URL** — optional, e.g. `http://192.168.0.34:8089`. Leave empty to disable the Channels integration.
- **Destination** — `/watch` (this is the container path, not the host path)

Click **Test** on both. Click **Save Settings**.

### 5. Add teams to the watchlist

In the **Watchlist** panel:

- **Team** — the name that appears in the tracker's titles (e.g. `New York Yankees`, `South Florida`, `Syracuse`)
- **Aliases** — optional, comma-separated search terms (e.g. `Yankees, NYY`)
- **Sport** — optional, a prefix filter (e.g. `NCAAF`, `NCAAB`, `MLB`)
- **Exclude networks** — optional, comma-separated networks your DVR can already record (e.g. `ABC, CBS, NBC, FOX`). Games on these networks are skipped. Leave empty to grab everything for this team.
- **DVR name** — optional, the name Channels DVR uses for this team in its guide data. Only needed when the tracker name and the guide name differ, which is common for college teams (`Miami Hurricanes` in the tracker, `Miami` in the guide). Leave empty to fall back to the team name.

Click **Add**.

**About the DVR name:** Channels DVR uses full names for NFL teams (`Buffalo Bills`) and school names for college teams (`Miami`, `Auburn`). The tracker uses nicknames for NFL (`Bills`) and school-plus-mascot for college (`Miami Hurricanes`). The scanner matches the DVR name against Channels' event titles using word-boundary matching, so `Bills` matches `Buffalo Bills` automatically. College entries need the DVR name set: `Miami Hurricanes` won't match `Miami` without it.

To grab **ranked-vs-ranked college football games** regardless of team, add an entry with:

- **Team** — `Top 25`
- **Sport** — `NCAAF` (required — the entry is ignored otherwise)
- **Exclude networks** — same as any other entry

This matches any title starting with `NCAAF ` where **both** teams carry a `(NN)` ranking prefix. Games where only one team is ranked — typically a ranked team playing a lower-tier opponent — are skipped.

Click **Add**.

To grab **NFL games on networks your DVR can't record** (Thursday Night Football on Prime, Monday Night Football on ESPN, and similar), add an entry with:

- **Team** — `ALL`
- **Sport** — `NFL` (required — the entry is ignored otherwise)
- **Exclude networks** — the networks you *can* record, e.g. `ABC, CBS, NBC, FOX`

This matches any NFL game, then skips the ones on your exclude list. Since most NFL games air on ABC/CBS/NBC/FOX, excluding those four leaves the streaming and cable primetime games.

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

### Top 25 Filter

A watchlist entry with the team name `Top 25` is a reserved keyword, not a team. It matches any title that:

1. Starts with `NCAAF ` (so the sport must be `NCAAF`)
2. Contains a parseable `Away @ Home` matchup
3. Has a `(NN)` ranking prefix on **both** of the two teams

The date filter, network filter, and game dedup all apply as normal. If the entry's sport is anything other than `NCAAF`, the entry is ignored and a warning is logged once per scan.

A game can match both the `Top 25` entry and an individual team entry. Both entries are evaluated independently, and each applies its own exclude list. If either entry allows the game, it is grabbed. The dedup layer ensures it is only grabbed once.

**Note:** the rank is read from the title. If the tracker post omits the `(NN)` prefix, a ranked game will look unranked and won't match. This is a known limitation of title-based detection.

### ALL Filter

A watchlist entry with the team name `ALL` is a reserved keyword, not a team. It matches any title that:

1. Starts with `NFL ` (so the sport must be `NFL`)
2. Contains a parseable `Away @ Home` matchup

Unlike `Top 25`, there is no ranking requirement — any NFL game matches. The entry's exclude list then does the real work: games on excluded networks are skipped by this entry, and games not on that list are grabbed by it.

The `ALL` entry is intended as a catch-all. Its exclude list should contain the networks your DVR can already record (`ABC`, `CBS`, `NBC`, `FOX`), so it picks up only the games you can't get otherwise. Individual team entries then act as overrides — a team entry with no exclusions will grab that team's games even when `ALL` would have skipped them.

The date filter and game dedup apply as normal. If the entry's sport is anything other than `NFL`, the entry is ignored and a warning is logged once per scan.

**Note:** `ALL` is scoped to NFL. It queries Jackett for `NFL Football`, which is specific enough to return a usable result set. Other sports are not supported by this keyword.

### Grab Always Wins

The watchlist is a set of independent rules, not a priority list. When a release matches more than one entry, each entry is evaluated on its own:

- Each entry applies **its own** exclude list.
- A release is grabbed if **at least one** matching entry does not exclude it.
- If **every** matching entry excludes it, the release is skipped.
- Dedup (by GUID and game key) ensures it's grabbed at most once, no matter how many entries matched.

This means an exclude list is a veto *within a rule*, never a global block. A narrow entry can override a broad one: `ALL` with `ABC, CBS, NBC, FOX` excluded skips broadcast games, but a `Chiefs` entry with no exclusions will still grab a Chiefs game on CBS.

The practical consequence: the exclude list on a catch-all entry like `ALL` is load-bearing. If you empty it, every NFL game is grabbed and no team entry can narrow that down, because `ALL` will always vote to grab. Team entries only matter when the catch-all's exclude list actually covers the game in question.

The Channels DVR check is a separate filter that runs after the exclude-list check. It doesn't participate in the "grab always wins" rule — it's a global veto. If Channels has the game, it's skipped, no matter how many watchlist entries want it. See the Channels DVR Check section below.

### Channels DVR Check

If a Channels DVR URL is configured, the scanner queries it once per scan and builds a list of every sports recording the DVR has. Before grabbing a release that passed the network filter, the scanner checks whether any game in that list matches. If it does, the release is skipped.

The check is a **global veto**, independent of the network filter. A release is only grabbed if it passes both:

1. At least one matching watchlist entry does not exclude the network.
2. Channels DVR does not already have the game.

**How the matching works:** Channels exposes an `event_title` field for real DVR recordings (e.g. `"New England Patriots at Buffalo Bills"`, `"Miami at Clemson"`). The scanner pulls these titles, filters to entries with `"Sports event"` in their categories — which excludes gametimarr's own imports into the Sports folder — and splits each title into its two team names.

For each candidate release, the scanner takes the effective DVR name for each matching watchlist entry (`dvr_name` if set, otherwise the team name), and checks whether it appears as a whole word in any Channels team name. If it does, the DVR has the game.

**Word-boundary matching:** `Bills` matches `Buffalo Bills` but not `billsgate`. `Miami` matches `Miami` but not `Miami (OH)` — wait, it does match `Miami (OH)`. The match is a whole word against the Channels team name, so a school with a disambiguating suffix in the guide could produce a false positive. In practice, the guide uses the plain school name for major programs, so this is rare.

**Fail-open behavior:** if Channels is unreachable or returns an error, the check is skipped for that scan, and the network filter is the only gate. This means a Channels outage never blocks grabs. You might get a duplicate if the DVR actually has the game and Channels was down, but you never miss a game.

**Timing:** by the time a torrent exists on the tracker, the DVR recording is always already complete. A game airs, the DVR records it, and only hours later does someone upload it. So a completed-recordings check is sufficient; there's no window where the DVR is going to record something the tracker already has.

### Network Filter

Each watchlist entry can list networks to exclude — typically the broadcast networks your DVR can already record (`ABC`, `CBS`, `NBC`, `FOX`). The scanner extracts the network from the trailing bracket of the torrent title (the last token after the language list, e.g. `EN/ESPNU` → `ESPNU`, or `EN, NBC` → `NBC`).

If the parsed network is in that team's exclude list, the release is skipped and logged. If the network can't be determined, the release is grabbed anyway — the filter never silently drops a game it doesn't understand.

Leave the field empty for teams you want to grab regardless of network, such as out-of-market NFL games on broadcast networks your DVR can't receive.

**To stop excluding a network later** (e.g. FOX becomes DRM-locked and your DVR can no longer record it), edit the exclude list on each watchlist entry that contains it and remove `FOX`.

### Game Filter

Two releases of the same game — say a 4K upload and a 720p upload — have different Torznab GUIDs, so GUID dedup alone won't stop the second one. The scanner also builds a **game key** from the title: the date plus both team names, normalized (lowercase, ranking prefix stripped, sorted).

- `12.09.2026 / (11) Oklahoma Sooners @ Michigan Wolverines` → `12.09.2026|michigan wolverines|oklahoma sooners`
- `12.09.2026 / Oklahoma Sooners @ Michigan Wolverines` → same key

If any release with that key has already been grabbed, the new one is skipped regardless of quality. The date is part of the key so that a playoff series — the same two teams on consecutive days — is treated as separate games.

**Known limitation:** a same-day doubleheader (same two teams, same date, two games) produces the same key, so the second game would be skipped. This is rare, and not handled.

### Query Strategy

The scanner queries Jackett once per watchlist term — the team name plus each alias. This is necessary because Torznab's Feed search is token-based and doesn't respond to league abbreviations like `MLB` or `NFL`. Querying the actual team name (`Yankees`) returns the right games.

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
3. **Jackett isn't logged in to 720pier.** Test the Torznab Feed URL in the UI. If the connection test fails, check Jackett's dashboard.

### Cross-sport false positives

If you follow a college team that plays multiple sports, use the **sport** field to scope the entry. For example, `South Florida` with sport `NCAAF` will only match football games, not basketball (NCAAM) or any other sport.

### A game was skipped but I wanted it

Check the watchlist entry's **exclude networks** field. If the game aired on a network listed there, it was skipped intentionally. Remove that network from the field to grab it next time. Note that the skip happens at scan time, so a game already skipped won't be re-evaluated — it only affects future scans.

### The Top 25 entry isn't grabbing anything

Three things to check:

1. **Sport must be `NCAAF`.** Any other value (or empty) causes the entry to be ignored, with a warning in the log.
2. **The game must actually be ranked.** Titles only carry a `(NN)` prefix when at least one team is ranked. Unranked games won't match.
3. **The tracker post must include the rank.** If the uploader omitted the `(NN)`, the game won't match even if the teams are ranked.

### A game matched both a team entry and the Top 25 entry

Both entries match the release, and both are evaluated independently. The release is grabbed if **either** entry allows it — each entry's exclude list is a per-entry veto, not a global block. The dedup layer ensures it's only grabbed once.

The same applies to a game matching both the `ALL` entry and an individual team entry. If `ALL` excludes CBS but the team entry has no exclusions, the CBS game is grabbed, because the team entry wants it. That's the intended behavior: `ALL` is the baseline rule, team entries are overrides.

### The ALL entry isn't grabbing anything

Two things to check:

1. **Sport must be `NFL`.** Any other value (or empty) causes the entry to be ignored, with a warning in the log.
2. **The exclude list may be doing its job.** If every NFL game in the window is on a network you excluded, nothing will be grabbed — which is correct. Check the log for `Skipped (network ...)` lines.

### The ALL entry is grabbing too much

If you're getting games you can already record, add those networks to the exclude list. `ALL` grabs everything that isn't excluded, so the exclude list is the only thing narrowing it down.

### A game was grabbed that my DVR also recorded

The network filter relies on the network appearing in the torrent title. If the title omits it, or the network is spelled differently than in your exclude list (e.g. `ACC Network` vs `ACCN`), the release won't match and will be grabbed. Check the log for the parsed network value and adjust the exclude list to match.

### The same game was grabbed twice

This shouldn't happen because of the GUID dedup, but if it does, check whether the tracker re-posted the game with a different thread ID. GUIDs are based on the thread URL, so a re-post gets a new GUID and looks like a new game. The date and title would be identical though, so it's easy to spot in the qBittorrent list.

### The same game was grabbed twice in different qualities

This is prevented by the game filter, which keys on the date and both team names. If it happens anyway, check the log for the parsed game key on both grabs — a mismatch usually means the team names were normalized differently (e.g. an alias or a spelling variant between releases). Adding the variant as an alias on the watchlist entry will align them.

### A game in a playoff series was skipped

The game key includes the date, so consecutive games in a series are treated separately. If a game was skipped, check whether the tracker posted it with a date that doesn't match the title's own date field — the scanner reads the date from the title, and a mis-dated upload will produce a different key than expected.

### I configured Channels DVR but nothing is being skipped

Three things to check:

1. **College entries need a DVR name.** The tracker name (`Miami Hurricanes`) won't match Channels' guide name (`Miami`) without it. Add `Miami` as the DVR name on that watchlist entry. NFL entries usually don't need this — `Bills` is a whole word in `Buffalo Bills`, so the fallback works.
2. **The DVR might genuinely not have the game.** If you didn't record it, or the recording failed, the check correctly returns no match and the game gets grabbed. Check the Channels UI to confirm.
3. **The game might not be in Channels' `Sports event` category.** Some recordings land in `Sports non-event` or other categories if the guide data is unusual. Check the raw API response with `curl http://<channels-ip>:8089/api/v1/episodes | grep event_title` to see what the scanner sees.

### A game was grabbed that Channels DVR already had

The matching is name-based, so a spelling mismatch will cause a miss. Check the log for the tracker title and look up what Channels calls the same game in its UI. If they differ (e.g. `Miami (FL)` vs `Miami`), set the DVR name on the watchlist entry to the Channels-side spelling.

### Channels is unreachable

The scan proceeds without the DVR check. The network filter still runs, and the exclude lists do their job. You'll see `Channels fetch failed:` in the log with the reason. The next scan retries. Nothing breaks — you just lose the extra filter during the outage.

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
| POST | `/test/channels` | Test a Channels DVR URL without saving |
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

- **SQLite** (`/data/gametimarr.db`) — settings, watchlist, and grab rows used for both GUID-level and game-level dedup.
- **Log files** (`/logs/`) — daily rotating, 5-day retention.
- **qBittorrent** — the actual torrents and their files.
- **Channels DVR** — read-only. Queried once per scan to see what recordings exist; never modified.

The app never modifies or moves qBittorrent's files. It reads them, computes the info-hash from the `.torrent` bytes, and copies to the destination. The original torrent continues seeding unaffected.

---

## File Tree

```
gametimarr/
├── app/
│   ├── __init__.py
│   ├── main.py               # Entry point, threads, path validation
│   ├── database.py           # SQLite schema and helpers, grab dedup
│   ├── jackett.py            # Torznab feed url
│   ├── channels.py           # Channels DVR client for DVR-exclusion matching
│   ├── scanner.py            # Scan loop, date/team/sport/network/game filters
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