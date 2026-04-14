# ProxMon — Proxmox Desktop Monitor

A lightweight Windows desktop widget for monitoring your Proxmox VE server.
Think CPU-Z, but for your Proxmox node.

![Status: Beta](https://img.shields.io/badge/status-beta-blue)

## Features

- **Real-time gauges** — CPU, RAM, and Swap usage with color-coded bars
- **Storage overview** — All storage pools with usage percentages
- **VM & Container lists** — Status, CPU, and RAM per guest
- **System tray** — Minimizes to tray with tooltip showing CPU/RAM
- **Auto-refresh** — Configurable polling interval (2–60 seconds)
- **Dark theme** — Easy on the eyes for always-on monitoring
- **API Token auth** — No password stored, just a revocable token

## Screenshots

```
┌─────────────────────────────────────┐
│  PROXMON            ● Connected     │
│  pve@192.168.1.100 • PVE 8.x       │
│─────────────────────────────────────│
│  CPU     ████████░░░░░░░░  32.5%    │
│  MEMORY  ██████████████░░  87.2%    │
│  SWAP    ██░░░░░░░░░░░░░░  12.0%    │
│                                     │
│  Uptime: 14d 8h 23m  Load: 2.1/1.8 │
│  ┌──────────────────────────────┐   │
│  │ Storage │ VMs │ Containers │  │   │
│  │ local      dir   45.2%      │   │
│  │ local-lvm  lvm   78.1%      │   │
│  │ nas-share  nfs   22.0%      │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

## Requirements

- Python 3.10+
- Windows 10/11 (also works on Linux with Qt)
- Network access to your Proxmox host on port 8006

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Proxmox API Token

In the Proxmox web UI:

1. Go to **Datacenter → Permissions → API Tokens**
2. Click **Add**
3. User: `root@pam` (or any user with read access)
4. Token ID: `proxmon` (or whatever you like)
5. **Uncheck** "Privilege Separation" (so the token inherits user permissions)
6. Click **Add** and **copy the secret** — you won't see it again

The Token ID will look like: `root@pam!proxmon`
The Secret will be a UUID like: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### 3. Run ProxMon

```bash
python proxmox_monitor.py
```

On first launch, the Settings dialog will open. Enter your:
- Proxmox host IP
- Node name (usually `pve` for single-node setups)
- API Token ID and Secret
- Refresh interval

Settings are saved to `~/.proxmon/config.json`.

### 4. (Optional) Create a Windows Shortcut

Create a `.bat` file or shortcut:

```bat
@echo off
pythonw proxmox_monitor.py
```

Using `pythonw` instead of `python` hides the console window.

## Configuration

Settings are stored in `%USERPROFILE%\.proxmon\config.json`:

```json
{
  "host": "192.168.1.100",
  "port": 8006,
  "token_id": "root@pam!proxmon",
  "token_secret": "your-token-uuid-here",
  "node": "pve",
  "refresh_interval": 5,
  "verify_ssl": false,
  "start_minimized": false,
  "dark_mode": true
}
```

## Security Notes

- API tokens are stored in plaintext in the config file. Treat it like a password.
- `verify_ssl: false` is needed for Proxmox's default self-signed cert.
  To use proper SSL, upload a real cert to Proxmox and set this to `true`.
- For least-privilege, create a dedicated PVE user with `PVEAuditor` role
  instead of using `root@pam`.

## Least-Privilege Setup (Recommended)

```bash
# On Proxmox shell:
pveum user add proxmon@pve
pveum aclmod / -user proxmon@pve -role PVEAuditor
pveum user token add proxmon@pve monitor --privsep=0
```

This creates a read-only user that can only view stats, not modify anything.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Connection refused" | Check host IP and that port 8006 is open |
| "401 Unauthorized" | Verify token ID format is `user@realm!tokenname` |
| "SSL error" | Set `verify_ssl` to `false` in settings |
| No VMs showing | Token needs `PVEAuditor` role on `/` path |
| High CPU on client | Increase refresh interval to 10+ seconds |

## Built With

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Desktop GUI
- [Requests](https://requests.readthedocs.io/) — HTTP client
- [Proxmox VE API](https://pve.proxmox.com/wiki/Proxmox_VE_API) — Data source

## Author

Cloud Ninja — [cloudninja.us](https://cloudninja.us)

---
*ProxMon is not affiliated with Proxmox Server Solutions GmbH.*
