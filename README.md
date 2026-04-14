# ProxMon — Proxmox Desktop Monitor

A lightweight desktop widget for real-time Proxmox VE server monitoring.  
Think **CPU-Z**, but for your Proxmox hypervisor.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![PyQt6](https://img.shields.io/badge/gui-PyQt6-green.svg)](https://pypi.org/project/PyQt6/)

## Features

- **Real-time gauges** — CPU, RAM, Swap/Root Disk with color-coded gradient bars
- **VM & Container tables** — Status, CPU%, RAM, Disk I/O rates, Network I/O rates, Uptime
- **Storage pools** — All pools with color-coded usage percentages (green/yellow/red)
- **Right-click power controls** — Start, Shutdown, Reboot, Force Stop VMs and containers
- **System tray icon** — Shows live CPU % with color coding (cyan → yellow → red)
- **Tray notifications** — Alerts when VMs/containers change state (started/stopped)
- **Event log** — Timestamped connection events, state changes, errors (with optional file logging)
- **Multi-node support** — Auto-detected, each node gets its own tab
- **Dark / Light theme** — Toggle with one click, persists across sessions
- **Zero third-party HTTP deps** — Uses Python stdlib `http.client` + `ssl` for API calls
- **Proxmox 596 workaround** — Uses `/cluster/resources` endpoint to avoid `pveproxy → pvedaemon` SSL issues

## Screenshots

> *Add your screenshots here*

## Quick Start

### 1. Install

```bash
pip install PyQt6
```

### 2. Create a Proxmox API Token

In the Proxmox web UI:

1. Go to **Datacenter → Permissions → API Tokens**
2. Click **Add**
3. User: `root@pam` (or a dedicated audit user)
4. Token ID: `proxmon`
5. **Uncheck** "Privilege Separation"
6. Click **Add** and **copy the secret UUID** — you only see it once

For least-privilege (recommended):

```bash
pveum user add proxmon@pve
pveum aclmod / -user proxmon@pve -role PVEAuditor
pveum user token add proxmon@pve monitor --privsep=0
```

### 3. Run

```bash
python proxmox_monitor.py
```

On first launch, the Settings dialog opens. Enter your Proxmox host, node name, and API token.

### 4. Build Standalone .exe (Optional)

```bash
# Windows
build.bat

# Or manually
pip install pyinstaller
pyinstaller --onefile --windowed --name ProxMon proxmox_monitor.py
```

### 5. Auto-Start on Login

**Option A — Startup folder (easiest):**
1. Press `Win+R`, type `shell:startup`, hit Enter
2. Copy `ProxMon.exe` (or a shortcut to `pythonw proxmox_monitor.py`) into that folder

**Option B — Task Scheduler:**
1. Open Task Scheduler → Create Basic Task
2. Trigger: "When I log on"
3. Action: Start `ProxMon.exe` or `pythonw C:\path\to\proxmox_monitor.py`

## Configuration

Settings are stored in `~/.proxmon/config.json`:

```json
{
  "host": "192.168.1.99",
  "port": 8006,
  "token_id": "root@pam!proxmon",
  "token_secret": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "node": "proxmox",
  "refresh_interval": 5,
  "verify_ssl": false,
  "start_minimized": true,
  "dark_mode": true,
  "notifications_enabled": true,
  "log_to_file": false
}
```

## VM / Container Power Controls

Right-click any VM or container in the table to:

| Status | Available Actions |
|--------|------------------|
| Running | Shutdown, Reboot, Force Stop |
| Stopped | Start |

Actions require confirmation and are logged in the event panel.

> **Note:** Power actions route through per-node endpoints (`/nodes/{node}/qemu/{vmid}/status/{action}`). If your Proxmox has the 596 SSL issue, these may fail. The monitoring itself is unaffected.

## Architecture

ProxMon uses only **pveproxy-safe API endpoints** that don't trigger the known `pveproxy → pvedaemon` internal SSL issue (HTTP 596) present in some Proxmox configurations:

| Endpoint | Purpose | Route |
|----------|---------|-------|
| `/api2/json/nodes` | Node summary (CPU, RAM, disk, uptime) | pveproxy only ✓ |
| `/api2/json/version` | PVE version info | pveproxy only ✓ |
| `/api2/json/cluster/resources` | All VMs, CTs, storage | pveproxy only ✓ |
| `/api2/json/nodes/{node}/status` | Detailed node stats (optional) | pvedaemon ⚠ |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Connection refused" | Check host IP, ensure port 8006 is open |
| "401 invalid token" | Verify token ID format: `user@realm!tokenname` |
| "HTTP 596 SSL" | Known PVE issue — monitoring works via fallback endpoints |
| No VMs showing | Token needs `PVEAuditor` role on `/` path |
| Tray icon not visible | Check Windows notification area settings → show all icons |
| High CPU on client | Increase refresh interval to 10+ seconds |

## Requirements

- Python 3.10+ (tested on 3.12, 3.13, 3.14)
- PyQt6 (only dependency)
- Network access to Proxmox host on port 8006
- Works on Windows 10/11 and Linux with Qt

## Built With

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Desktop GUI framework
- [Proxmox VE API](https://pve.proxmox.com/wiki/Proxmox_VE_API) — Data source
- Python stdlib `http.client` + `ssl` — HTTP client (no requests/urllib3 needed)

## Author

**Cloud Ninja** — [cloudninja.us](https://cloudninja.us)  
GitHub: [@Ranksolo](https://github.com/Ranksolo)

## Support ProxMon

If ProxMon saves you time, consider supporting development:

| Method | Address / Link |
|--------|---------------|
| ☀ **Solana (SOL)** | `ECGjCFfp7e2Y7roqotidRPFeDwzuMcyGg9qrp3JTau7H` |
| ⭐ **GitHub** | Star this repo — it helps with visibility! |

## License

MIT — see [LICENSE](LICENSE)

---

*ProxMon is not affiliated with Proxmox Server Solutions GmbH.*
