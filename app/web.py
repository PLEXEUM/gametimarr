"""
web.py - Single-screen web UI.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import (
    get_all_settings,
    set_setting,
    get_watchlist,
    add_team,
    remove_team,
)
from app.jackett import JackettClient
from app.qbittorrent import QBittorrentClient

app = FastAPI()


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gametimarr</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #111; color: #ddd; margin: 0; padding: 20px;
    max-width: 800px; margin: 0 auto;
  }
  h1 { font-size: 20px; margin: 0 0 20px; color: #fff; font-weight: 600; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;
       color: #888; margin: 24px 0 8px; font-weight: 600; }
  .panel { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 6px;
           padding: 16px; }
  label { display: block; font-size: 12px; color: #999; margin: 8px 0 4px; }
  input[type=text], input[type=password] {
    width: 100%; padding: 8px; background: #0d0d0d; border: 1px solid #333;
    border-radius: 4px; color: #eee; font-size: 13px; font-family: inherit;
  }
  input:focus { outline: none; border-color: #4a7; }
  button {
    padding: 8px 14px; background: #2a2a2a; border: 1px solid #3a3a3a;
    border-radius: 4px; color: #ddd; font-size: 13px; cursor: pointer;
    font-family: inherit;
  }
  button:hover { background: #333; }
  button.primary { background: #2d5; border-color: #2d5; color: #000; font-weight: 600; }
  button.primary:hover { background: #3e6; }
  button.small { padding: 4px 8px; font-size: 11px; }
  .row { display: flex; gap: 8px; align-items: flex-end; margin-bottom: 8px; }
  .row > div { flex: 1; }
  .row > button { flex: 0 0 auto; }
  .status { font-size: 12px; margin-top: 6px; min-height: 16px; }
  .ok { color: #3e6; } .err { color: #e55; }
  .team { display: flex; justify-content: space-between; align-items: center;
          padding: 6px 0; border-bottom: 1px solid #222; font-size: 13px; }
  .team:last-child { border-bottom: none; }
  .team .aliases { color: #666; font-size: 11px; margin-left: 8px; }
  .muted { color: #666; font-size: 12px; }
</style>
</head>
<body>

<h1>gametimarr</h1>

<h2>Jackett</h2>
<div class="panel">
  <label>Torznab URL</label>
  <div class="row">
    <div><input type="text" id="jackett_url" placeholder="http://jackett:9117/api/v2.0/indexers/.../results/torznab/api?apikey=..."></div>
    <button onclick="testJackett()">Test</button>
  </div>
  <div class="status" id="jackett_status"></div>
</div>

<h2>qBittorrent</h2>
<div class="panel">
  <div class="row">
    <div><label>Host</label><input type="text" id="qbit_host" placeholder="192.168.0.XX"></div>
    <div><label>Port</label><input type="text" id="qbit_port" placeholder="8012"></div>
  </div>
  <div class="row">
    <div><label>Username</label><input type="text" id="qbit_username" placeholder="admin"></div>
    <div><label>Password</label><input type="password" id="qbit_password"></div>
  </div>
  <button onclick="testQbit()">Test</button>
  <div class="status" id="qbit_status"></div>
</div>

<h2>Destination</h2>
<div class="panel">
  <label>Folder where completed games are copied</label>
  <input type="text" id="destination_path" placeholder="/watch">
</div>

<h2>Manual Run</h2>
<div class="panel">
  <button onclick="runScan()">Run Scan Now</button>
  <button onclick="runMonitor()">Run Monitor Now</button>
  <div class="status" id="run_status"></div>
</div>

<div style="margin-top: 16px;">
  <button class="primary" onclick="saveConfig()">Save Settings</button>
  <span class="status" id="save_status"></span>
</div>

<h2>Watchlist</h2>
<div class="panel">
  <div class="row">
    <div><input type="text" id="new_team" placeholder="Team name"></div>
    <div><input type="text" id="new_aliases" placeholder="Aliases (comma-separated)"></div>
    <button onclick="addTeam()">Add</button>
  </div>
  <div id="watchlist"></div>
</div>

<script>
let initialLoadDone = false;

async function loadStatus() {
  const res = await fetch('/status');
  const data = await res.json();

  // Only populate the settings fields once, on the very first load.
  // After that, never touch them again, so typing isn't interrupted.
  if (!initialLoadDone) {
    const s = data.settings || {};
    document.getElementById('jackett_url').value = s.jackett_torznab_url || '';
    document.getElementById('qbit_host').value = s.qbit_host || '';
    document.getElementById('qbit_port').value = s.qbit_port || '';
    document.getElementById('qbit_username').value = s.qbit_username || '';
    document.getElementById('qbit_password').value = s.qbit_password || '';
    document.getElementById('destination_path').value = s.destination_path || '';
    initialLoadDone = true;
  }

  // Always refresh the watchlist (it's not editable inline, so it's safe).
  const wl = document.getElementById('watchlist');
  if (!data.watchlist || data.watchlist.length === 0) {
    wl.innerHTML = '<div class="muted">No teams yet.</div>';
  } else {
    wl.innerHTML = data.watchlist.map(t =>
      `<div class="team">
        <span>${escapeHtml(t.team)}${t.aliases ? `<span class="aliases">(${escapeHtml(t.aliases)})</span>` : ''}</span>
        <button class="small" onclick="removeTeam('${escapeAttr(t.team)}')">Remove</button>
      </div>`
    ).join('');
  }
}

async function saveConfig() {
  const status = document.getElementById('save_status');
  status.textContent = 'Saving...';
  status.className = 'status';

  const body = {
    jackett_torznab_url: document.getElementById('jackett_url').value,
    qbit_host: document.getElementById('qbit_host').value,
    qbit_port: document.getElementById('qbit_port').value,
    qbit_username: document.getElementById('qbit_username').value,
    qbit_password: document.getElementById('qbit_password').value,
    destination_path: document.getElementById('destination_path').value,
  };

  const res = await fetch('/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();
  status.textContent = data.success ? 'Saved.' : 'Error: ' + data.error;
  status.className = 'status ' + (data.success ? 'ok' : 'err');
  setTimeout(() => status.textContent = '', 3000);

  // Allow the fields to be refreshed from the server on the next poll
  // in case anything was normalized.
  initialLoadDone = false;
}

async function testJackett() {
  const status = document.getElementById('jackett_status');
  status.textContent = 'Testing...';
  status.className = 'status';

  const res = await fetch('/test/jackett', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url: document.getElementById('jackett_url').value}),
  });
  const data = await res.json();
  status.textContent = data.message;
  status.className = 'status ' + (data.success ? 'ok' : 'err');
}

async function testQbit() {
  const status = document.getElementById('qbit_status');
  status.textContent = 'Testing...';
  status.className = 'status';

  const res = await fetch('/test/qbit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      host: document.getElementById('qbit_host').value,
      port: document.getElementById('qbit_port').value,
      username: document.getElementById('qbit_username').value,
      password: document.getElementById('qbit_password').value,
    }),
  });
  const data = await res.json();
  status.textContent = data.message;
  status.className = 'status ' + (data.success ? 'ok' : 'err');
}

async function addTeam() {
  const team = document.getElementById('new_team').value.trim();
  const aliases = document.getElementById('new_aliases').value.trim();
  if (!team) return;

  await fetch('/watchlist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'add', team, aliases}),
  });
  document.getElementById('new_team').value = '';
  document.getElementById('new_aliases').value = '';
  loadStatus();
}

async function removeTeam(team) {
  await fetch('/watchlist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'remove', team}),
  });
  loadStatus();
}

async function runScan() {
  const status = document.getElementById('run_status');
  status.textContent = 'Running scan...';
  status.className = 'status';

  const res = await fetch('/run/scan', { method: 'POST' });
  const data = await res.json();

  if (data.success) {
    const r = data.result;
    status.textContent = `Scan done: ${r.items} items, ${r.matched} matched, ${r.grabbed} grabbed`;
    status.className = 'status ok';
  } else {
    status.textContent = 'Error: ' + data.error;
    status.className = 'status err';
  }
  setTimeout(() => status.textContent = '', 15000);
}

async function runMonitor() {
  const status = document.getElementById('run_status');
  status.textContent = 'Running monitor...';
  status.className = 'status';

  const res = await fetch('/run/monitor', { method: 'POST' });
  const data = await res.json();

  if (data.success) {
    const r = data.result;
    status.textContent = `Monitor done: ${r.copied} copied, ${r.skipped} skipped`;
    status.className = 'status ok';
  } else {
    status.textContent = 'Error: ' + data.error;
    status.className = 'status err';
  }
  setTimeout(() => status.textContent = '', 15000);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function escapeAttr(s) {
  return String(s).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

loadStatus();
setInterval(loadStatus, 10000);
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML


@app.get("/status")
async def status():
    return JSONResponse({
        "settings": get_all_settings(),
        "watchlist": get_watchlist(),
    })


@app.post("/config")
async def save_config(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

    allowed = {
        "jackett_torznab_url",
        "qbit_host",
        "qbit_port",
        "qbit_username",
        "qbit_password",
        "destination_path",
    }

    for key, value in body.items():
        if key in allowed:
            set_setting(key, value or "")

    return JSONResponse({"success": True})


@app.post("/watchlist")
async def update_watchlist(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

    action = body.get("action")
    team = (body.get("team") or "").strip()

    if not team:
        return JSONResponse({"success": False, "error": "Team name required"})

    if action == "add":
        aliases = (body.get("aliases") or "").strip()
        add_team(team, aliases)
    elif action == "remove":
        remove_team(team)
    else:
        return JSONResponse({"success": False, "error": "Unknown action"})

    return JSONResponse({"success": True})


@app.post("/test/jackett")
async def test_jackett(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)})

    client = JackettClient()
    result = await client.test_connection(body.get("url", ""))
    return JSONResponse(result)


@app.post("/test/qbit")
async def test_qbit(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)})

    client = QBittorrentClient()
    result = await client.test_connection(
        host=body.get("host"),
        port=body.get("port"),
        username=body.get("username"),
        password=body.get("password"),
    )
    return JSONResponse(result)

@app.post("/run/scan")
async def run_scan():
    from app.scanner import scan_once
    try:
        result = await scan_once()
        return JSONResponse({"success": True, "result": result})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/run/monitor")
async def run_monitor():
    from app.postprocess import check_completed
    try:
        result = await check_completed()
        return JSONResponse({"success": True, "result": result})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})