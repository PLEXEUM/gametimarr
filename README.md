# 🏈 Gametimarr

**Sports event downloader for NCAA Football, MLB, and NFL.**

Gametimarr lets you select sports games from TheSportsDB schedule, search Prowlarr/Jackett for releases, and download them directly to qBittorrent.

---

## Features

- **Schedule Viewer** - Browse upcoming games by sport and year
- **Game Selection** - Check the games you want to download
- **Automatic Search** - Searches Prowlarr/Jackett for releases
- **qBittorrent Integration** - Sends torrents directly to your download client
- **File Management** - Automatically copies completed downloads to your sports folders
- **Scheduled Scans** - Runs on a schedule like Sonarr/Radarr
- **Manual Search** - Search selected games on demand

---

## Quick Start

### Docker Compose

```bash
# Clone the repository
git clone https://github.com/PLEXEUM/gametimarr.git
cd gametimarr

# Start the container
docker-compose up -d

# Open the web UI
# → http://localhost:7667
```

### Docker Run

```bash
docker run -d \
  --name gametimarr \
  -p 7227:7227 \
  -v ./config:/app/config \
  -v ./logs:/app/logs \
  -v /path/to/sports:/media/sports \
  plexeum/gametimarr:latest
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | America/New_York | Timezone for scheduling |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Settings (via Web UI)

The following settings are configured through the web interface:

- **TheSportsDB API Key** - Required for schedule data
- **Prowlarr URL & API Key** - For searching releases
- **qBittorrent Host, Port, Username, Password** - Download client
- **Sport Folders** - Where to store downloads per sport
- **Search Schedule** - How often to run automated searches

---

## Roadmap

- [ ] TheSportsDB integration (schedule sync)
- [ ] Prowlarr/Jackett search
- [ ] qBittorrent download management
- [ ] Schedule viewer with game selection
- [ ] Automated search scheduling
- [ ] File copy to sport folders

---

## Tech Stack

- **Backend**: FastAPI + Python
- **Frontend**: HTMX + Tailwind CSS
- **Database**: SQLite
- **Scheduler**: APScheduler
- **Container**: Docker + Docker Compose

---

## License

GNU GPL v3 - see [LICENSE](LICENSE) for details.

---

**Gametimarr** – Never miss the game. 🏈