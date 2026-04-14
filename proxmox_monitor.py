#!/usr/bin/env python3
"""
ProxMon — Proxmox Desktop Monitor
A lightweight desktop widget for real-time Proxmox VE server monitoring.
Think CPU-Z, but for your Proxmox hypervisor.

Features:
  - Real-time CPU, RAM, Disk gauges with color-coded bars
  - VM & Container tables with status, CPU, RAM, Disk I/O, Network I/O
  - Storage pool overview with usage percentages
  - Right-click VM/CT context menu for Start/Stop/Reboot
  - System tray icon showing live CPU percentage
  - Tray notifications when VMs/CTs change state
  - Event log panel (connection events, state changes, alerts)
  - Multi-node support (auto-detected)
  - Dark / Light theme toggle
  - Configurable refresh interval

Author: Cloud Ninja (cloudninja.us)
GitHub: https://github.com/Ranksolo/ProxMon
License: MIT
"""

__version__ = "1.0.0"
__author__ = "Cloud Ninja"

import sys
import json
import time
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QTableWidget, QTableWidgetItem,
    QSystemTrayIcon, QMenu, QFrame, QGridLayout, QHeaderView,
    QDialog, QLineEdit, QPushButton, QCheckBox, QMessageBox,
    QGroupBox, QTextEdit, QSplitter, QSizePolicy,
    QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize,
)
from PyQt6.QtGui import (
    QIcon, QFont, QColor, QPixmap, QPainter, QAction,
    QLinearGradient, QBrush, QTextCursor,
)

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════
CONFIG_FILE = Path.home() / ".proxmon" / "config.json"
LOG_FILE = Path.home() / ".proxmon" / "proxmon.log"
MAX_LOG_LINES = 200

DEFAULT_CONFIG = {
    "host": "192.168.1.100",
    "port": 8006,
    "token_id": "root@pam!proxmon",
    "token_secret": "",
    "node": "pve",
    "refresh_interval": 5,
    "verify_ssl": False,
    "start_minimized": False,
    "dark_mode": True,
    "notifications_enabled": True,
    "log_to_file": False,
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# Themes
# ═══════════════════════════════════════════════════════════════════════
THEMES = {
    "dark": {
        "bg": "#0d1117", "surface": "#1a1f2e", "border": "#2d3548",
        "text": "#e0e6ed", "text_dim": "#8b95a5", "text_faint": "#5a6577",
        "accent": "#00d4ff", "accent_hover": "#00b8e6",
        "green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444",
        "purple": "#a855f7",
        "tray_bg": "#0d1117", "tray_text": "#00d4ff",
        "tab_bg": "#1a1f2e", "tab_selected": "#0d1117",
        "table_grid": "#1a1f2e", "table_selected": "#1a2744",
        "gauge_track": "#0d1117", "log_bg": "#0a0e14",
    },
    "light": {
        "bg": "#f8f9fa", "surface": "#ffffff", "border": "#dee2e6",
        "text": "#212529", "text_dim": "#6c757d", "text_faint": "#adb5bd",
        "accent": "#0077cc", "accent_hover": "#005fa3",
        "green": "#198754", "yellow": "#fd7e14", "red": "#dc3545",
        "purple": "#7c3aed",
        "tray_bg": "#ffffff", "tray_text": "#0077cc",
        "tab_bg": "#e9ecef", "tab_selected": "#ffffff",
        "table_grid": "#e9ecef", "table_selected": "#a8d4f0",
        "gauge_track": "#e9ecef", "log_bg": "#f1f3f5",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Proxmox API Client (stdlib only — no requests/urllib3 needed)
# ═══════════════════════════════════════════════════════════════════════
class ProxmoxAPI:
    def __init__(self, host, port, token_id, token_secret, verify_ssl=False):
        import ssl as _ssl
        self.host = host
        self.port = port
        self.auth_header = f"PVEAPIToken={token_id}={token_secret}"
        self.timeout = 15
        if not verify_ssl:
            self.ssl_ctx = _ssl.create_default_context()
            self.ssl_ctx.check_hostname = False
            self.ssl_ctx.verify_mode = _ssl.CERT_NONE
        else:
            self.ssl_ctx = _ssl.create_default_context()

    def _request(self, method, endpoint, timeout=None):
        import http.client
        t = timeout or self.timeout
        conn = http.client.HTTPSConnection(
            self.host, self.port, context=self.ssl_ctx, timeout=t,
        )
        try:
            headers = {
                "Authorization": self.auth_header,
                "Accept": "application/json",
            }
            if method == "POST":
                headers["Content-Length"] = "0"
            conn.request(method, f"/api2/json{endpoint}", headers=headers)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status not in (200, 202):
                raise Exception(f"HTTP {resp.status} {resp.reason}: {body[:200]}")
            return json.loads(body).get("data", {})
        finally:
            conn.close()

    def _get(self, endpoint, timeout=None):
        return self._request("GET", endpoint, timeout)

    def _post(self, endpoint, timeout=None):
        return self._request("POST", endpoint, timeout)

    def get_nodes(self):
        return self._get("/nodes")

    def get_version(self):
        return self._get("/version")

    def get_cluster_resources(self):
        return self._get("/cluster/resources")

    def get_node_status(self, node):
        return self._get(f"/nodes/{node}/status", timeout=4)

    def vm_action(self, node, vmid, action):
        return self._post(f"/nodes/{node}/qemu/{vmid}/status/{action}", timeout=10)

    def ct_action(self, node, vmid, action):
        return self._post(f"/nodes/{node}/lxc/{vmid}/status/{action}", timeout=10)


# ═══════════════════════════════════════════════════════════════════════
# I/O Rate Calculator
# ═══════════════════════════════════════════════════════════════════════
class IOTracker:
    def __init__(self):
        self._prev = {}

    def update(self, vmid, diskread, diskwrite, netin, netout):
        now = time.time()
        key = str(vmid)
        prev = self._prev.get(key)
        self._prev[key] = {
            "diskread": diskread, "diskwrite": diskwrite,
            "netin": netin, "netout": netout, "ts": now,
        }
        if prev is None:
            return None
        dt = now - prev["ts"]
        if dt <= 0:
            return None
        return {
            "disk_read_rate": max(0, (diskread - prev["diskread"]) / dt),
            "disk_write_rate": max(0, (diskwrite - prev["diskwrite"]) / dt),
            "net_in_rate": max(0, (netin - prev["netin"]) / dt),
            "net_out_rate": max(0, (netout - prev["netout"]) / dt),
        }


# ═══════════════════════════════════════════════════════════════════════
# Background Worker
# ═══════════════════════════════════════════════════════════════════════
class PollWorker(QThread):
    data_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._running = True

    def run(self):
        while self._running:
            try:
                api = ProxmoxAPI(
                    self.config["host"], self.config["port"],
                    self.config["token_id"], self.config["token_secret"],
                    self.config["verify_ssl"],
                )
                nodes_list = api.get_nodes()
                version = {}
                try:
                    version = api.get_version()
                except Exception:
                    pass

                all_resources = []
                try:
                    all_resources = api.get_cluster_resources()
                except Exception:
                    pass

                nodes_data = {}
                if isinstance(nodes_list, list):
                    for n in nodes_list:
                        name = n.get("node", "unknown")
                        nodes_data[name] = {
                            "summary": n, "vms": [], "containers": [],
                            "storage": [], "status": None,
                        }

                if isinstance(all_resources, list):
                    for r in all_resources:
                        rnode = r.get("node", "")
                        rtype = r.get("type", "")
                        if rnode not in nodes_data:
                            continue
                        if rtype == "qemu" and not r.get("template", 0):
                            nodes_data[rnode]["vms"].append(r)
                        elif rtype == "lxc":
                            nodes_data[rnode]["containers"].append(r)
                        elif rtype == "storage":
                            nodes_data[rnode]["storage"].append(r)

                for nname in nodes_data:
                    try:
                        nodes_data[nname]["status"] = api.get_node_status(nname)
                    except Exception:
                        pass

                self.data_ready.emit({
                    "nodes": nodes_data, "version": version,
                    "timestamp": time.time(),
                })
            except Exception as e:
                self.error_occurred.emit(f"{type(e).__name__}: {e}")

            for _ in range(self.config.get("refresh_interval", 5) * 10):
                if not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def fmt_bytes(b, decimals=1):
    if b is None or b == 0:
        return "0 B"
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(b) < 1024:
            return f"{b:.{decimals}f} {unit}"
        b /= 1024
    return f"{b:.{decimals}f} PiB"


def fmt_rate(bps):
    if bps is None:
        return "—"
    if bps < 1:
        return "0 B/s"
    for unit in ["B/s", "KiB/s", "MiB/s", "GiB/s"]:
        if abs(bps) < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TiB/s"


def fmt_uptime(seconds):
    if not seconds:
        return "—"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    return f"{hours}h {mins}m"


def ts_str():
    return datetime.now().strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════════
# Custom Widgets
# ═══════════════════════════════════════════════════════════════════════
class GaugeBar(QWidget):
    def __init__(self, label, color_start="#00d4ff", color_end="#0080ff",
                 theme=None, parent=None):
        super().__init__(parent)
        self.label_text = label
        self.color_start = color_start
        self.color_end = color_end
        self.theme = theme or THEMES["dark"]
        self._value = 0
        self._max_val = 100
        self._detail = ""
        self.setMinimumHeight(56)
        self.setMaximumHeight(56)

    def set_value(self, value, max_val=100, detail=""):
        self._value = min(value, max_val)
        self._max_val = max_val
        self._detail = detail
        self.update()

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = self.theme

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["surface"]))
        painter.drawRoundedRect(0, 0, w, h, 8, 8)

        pct = self._value / self._max_val if self._max_val > 0 else 0
        fill_w = int((w - 16) * pct)
        bar_y, bar_h = 30, 16

        if fill_w > 0:
            grad = QLinearGradient(8, bar_y, 8 + fill_w, bar_y)
            grad.setColorAt(0, QColor(self.color_start))
            grad.setColorAt(1, QColor(self.color_end))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(8, bar_y, fill_w, bar_h, 4, 4)

        painter.setBrush(QColor(t["gauge_track"]))
        painter.drawRoundedRect(8 + fill_w, bar_y, (w - 16) - fill_w, bar_h, 4, 4)

        painter.setPen(QColor(t["text_dim"]))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(10, 20, self.label_text)

        pct_text = f"{pct * 100:.1f}%"
        painter.setPen(QColor(t["text"]))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        fm = painter.fontMetrics()
        painter.drawText(w - fm.horizontalAdvance(pct_text) - 10, 20, pct_text)

        if self._detail:
            painter.setPen(QColor(t["text_faint"]))
            painter.setFont(QFont("Segoe UI", 7))
            fm2 = painter.fontMetrics()
            dw = fm2.horizontalAdvance(self._detail)
            painter.drawText(w // 2 - dw // 2, h - 2, self._detail)
        painter.end()


class StatusDot(QWidget):
    def __init__(self, color="#22c55e", size=10, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, c):
        self._color = c
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(0, 0, self.width(), self.height())
        p.end()


# ═══════════════════════════════════════════════════════════════════════
# Settings Dialog
# ═══════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.setWindowTitle("ProxMon Settings")
        self.setFixedSize(440, 540)
        t = THEMES["dark"] if config.get("dark_mode", True) else THEMES["light"]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {t['bg']}; color: {t['text']}; }}
            QLabel {{ color: {t['text']}; font-size: 12px; }}
            QLineEdit {{
                background-color: {t['surface']}; border: 1px solid {t['border']};
                border-radius: 4px; color: {t['text']}; padding: 4px 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {t['accent']}; }}
            QPushButton {{
                background-color: {t['accent']}; color: {t['bg']};
                border: none; border-radius: 4px; padding: 7px 20px;
                font-weight: bold; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
            QPushButton#cancel {{
                background-color: {t['surface']}; color: {t['text_dim']};
                border: 1px solid {t['border']};
            }}
            QCheckBox {{ color: {t['text']}; font-size: 12px; spacing: 6px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QGroupBox {{
                color: {t['accent']}; font-weight: bold; font-size: 12px;
                border: 1px solid {t['border']};
                border-radius: 6px; margin-top: 10px; padding-top: 14px;
            }}
            QGroupBox::title {{ padding: 0 8px; }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 12, 16, 12)

        H = 30  # Input field height

        def make_row(label_text, widget):
            """Label + input on one line, with fixed height widget."""
            widget.setFixedHeight(H)
            container = QWidget()
            container.setFixedHeight(H)
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            lbl.setFixedHeight(H)
            row.addWidget(lbl)
            row.addWidget(widget)
            return container

        # Connection
        conn = QGroupBox("Connection")
        cl = QVBoxLayout()
        cl.setSpacing(6)
        cl.setContentsMargins(12, 16, 12, 12)

        self.host_input = QLineEdit(self.config["host"])
        cl.addWidget(make_row("Host / IP:", self.host_input))

        self.port_input = QLineEdit(str(self.config["port"]))
        self.port_input.setPlaceholderText("8006")
        cl.addWidget(make_row("Port:", self.port_input))

        self.node_input = QLineEdit(self.config["node"])
        cl.addWidget(make_row("Node Name:", self.node_input))

        conn.setLayout(cl)
        layout.addWidget(conn)

        # API Token
        auth = QGroupBox("API Token")
        al = QVBoxLayout()
        al.setSpacing(6)
        al.setContentsMargins(12, 16, 12, 12)

        self.token_id_input = QLineEdit(self.config["token_id"])
        self.token_id_input.setPlaceholderText("user@realm!tokenname")
        al.addWidget(make_row("Token ID:", self.token_id_input))

        self.token_secret_input = QLineEdit(self.config["token_secret"])
        self.token_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_secret_input.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        al.addWidget(make_row("Token Secret:", self.token_secret_input))

        auth.setLayout(al)
        layout.addWidget(auth)

        # Options
        opts = QGroupBox("Options")
        ol = QVBoxLayout()
        ol.setSpacing(6)
        ol.setContentsMargins(12, 16, 12, 12)

        self.refresh_input = QLineEdit(str(self.config["refresh_interval"]))
        self.refresh_input.setPlaceholderText("5")
        ol.addWidget(make_row("Refresh (sec):", self.refresh_input))

        self.ssl_check = QCheckBox("Verify SSL Certificate")
        self.ssl_check.setChecked(self.config.get("verify_ssl", False))
        ol.addWidget(self.ssl_check)
        self.tray_check = QCheckBox("Start Minimized to Tray")
        self.tray_check.setChecked(self.config.get("start_minimized", False))
        ol.addWidget(self.tray_check)
        self.notify_check = QCheckBox("Enable Tray Notifications")
        self.notify_check.setChecked(self.config.get("notifications_enabled", True))
        ol.addWidget(self.notify_check)
        self.logfile_check = QCheckBox("Write Log to File (~/.proxmon/proxmon.log)")
        self.logfile_check.setChecked(self.config.get("log_to_file", False))
        ol.addWidget(self.logfile_check)

        opts.setLayout(ol)
        layout.addWidget(opts)

        # Buttons
        layout.addStretch()
        bl = QHBoxLayout()
        bl.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.reject)
        bl.addWidget(cancel)
        save = QPushButton("Save & Connect")
        save.clicked.connect(self._save)
        bl.addWidget(save)
        layout.addLayout(bl)

    def _save(self):
        self.config["host"] = self.host_input.text().strip()
        try:
            self.config["port"] = int(self.port_input.text().strip())
        except ValueError:
            self.config["port"] = 8006
        self.config["node"] = self.node_input.text().strip()
        self.config["token_id"] = self.token_id_input.text().strip()
        self.config["token_secret"] = self.token_secret_input.text().strip()
        try:
            self.config["refresh_interval"] = max(2, min(60, int(self.refresh_input.text().strip())))
        except ValueError:
            self.config["refresh_interval"] = 5
        self.config["verify_ssl"] = self.ssl_check.isChecked()
        self.config["start_minimized"] = self.tray_check.isChecked()
        self.config["notifications_enabled"] = self.notify_check.isChecked()
        self.config["log_to_file"] = self.logfile_check.isChecked()
        self.accept()


# ═══════════════════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════════════════
class ProxMonWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.worker = None
        self.last_data = None
        self.io_tracker = IOTracker()
        self.prev_guest_states = {}
        self.log_lines = []
        self.node_tabs = {}
        self._current_theme_name = "dark" if self.config.get("dark_mode", True) else "light"

        self.setWindowTitle("ProxMon — Proxmox Monitor")
        self.setMinimumSize(560, 700)
        self.resize(640, 800)

        self._apply_theme()
        self._build_ui()
        self._build_tray()

        if self.config.get("token_secret"):
            self._start_polling()
        else:
            self._show_settings()

    @property
    def theme(self):
        return THEMES[self._current_theme_name]

    def _toggle_theme(self):
        self._current_theme_name = "light" if self._current_theme_name == "dark" else "dark"
        self.config["dark_mode"] = (self._current_theme_name == "dark")
        save_config(self.config)
        self._apply_theme()
        self._update_gauge_themes()
        self.theme_btn.setText("☀" if self._current_theme_name == "dark" else "☾")
        if self.last_data:
            self._on_data(self.last_data)

    def _apply_theme(self):
        t = self.theme
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {t['bg']}; }}
            QWidget {{ color: {t['text']}; font-family: 'Segoe UI', sans-serif; }}
            QTabWidget::pane {{
                border: 1px solid {t['border']}; border-radius: 6px;
                background-color: {t['bg']};
            }}
            QTabWidget::tab-bar {{
                left: 0px;
            }}
            QTabBar {{
                background-color: {t['bg']};
            }}
            QTabBar::tab {{
                background-color: {t['tab_bg']}; color: {t['text_dim']};
                padding: 8px 18px; border: none;
                border-bottom: 2px solid transparent;
                font-size: 11px; font-weight: bold;
            }}
            QTabBar::tab:selected {{
                color: {t['accent']}; border-bottom: 2px solid {t['accent']};
                background-color: {t['tab_selected']};
            }}
            QTabBar::tab:hover {{ color: {t['text']}; }}
            QTableWidget {{
                background-color: {t['bg']}; border: none;
                gridline-color: {t['table_grid']}; font-size: 11px;
                selection-background-color: {t['table_selected']};
                selection-color: {t['text']};
            }}
            QTableWidget::item {{
                padding: 4px 8px; border-bottom: 1px solid {t['table_grid']};
            }}
            QTableWidget::item:selected {{
                background-color: {t['table_selected']};
                color: {t['text']};
            }}
            QHeaderView::section {{
                background-color: {t['surface']}; color: {t['text_dim']};
                border: none; padding: 6px 8px; font-weight: bold; font-size: 10px;
            }}
            QScrollBar:vertical {{
                background: {t['bg']}; width: 8px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {t['border']}; border-radius: 4px; min-height: 30px;
            }}
            QTextEdit {{
                background-color: {t['log_bg']}; color: {t['text_dim']};
                border: 1px solid {t['border']}; border-radius: 4px;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 10px; padding: 4px;
            }}
            QSplitter::handle {{ background-color: {t['border']}; height: 2px; }}
        """)

    def _update_gauge_themes(self):
        t = self.theme
        for nname, widgets in self.node_tabs.items():
            for g in [widgets["cpu_gauge"], widgets["ram_gauge"], widgets["swap_gauge"]]:
                g.set_theme(t)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 12)
        main_layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("PROXMON")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {self.theme['accent']}; letter-spacing: 3px;"
        )
        header.addWidget(title)
        self.status_dot = StatusDot("#ef4444")
        header.addWidget(self.status_dot)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet(f"color: {self.theme['text_dim']}; font-size: 11px;")
        header.addWidget(self.status_label)
        header.addStretch()

        btn_style = f"""
            QPushButton {{
                background: {self.theme['surface']}; border: 1px solid {self.theme['border']};
                border-radius: 4px; color: {self.theme['text_dim']}; font-size: 16px;
            }}
            QPushButton:hover {{ background: {self.theme['border']}; color: {self.theme['accent']}; }}
        """
        self.theme_btn = QPushButton("☀" if self._current_theme_name == "dark" else "☾")
        self.theme_btn.setFixedSize(30, 30)
        self.theme_btn.setToolTip("Toggle theme")
        self.theme_btn.setStyleSheet(btn_style)
        self.theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(self.theme_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(30, 30)
        settings_btn.setStyleSheet(btn_style)
        settings_btn.clicked.connect(self._show_settings)
        header.addWidget(settings_btn)
        main_layout.addLayout(header)

        self.host_info = QLabel("")
        self.host_info.setStyleSheet(f"color: {self.theme['text_faint']}; font-size: 10px; padding: 2px 0;")
        main_layout.addWidget(self.host_info)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self.theme['surface']};")
        main_layout.addWidget(sep)

        # Splitter: nodes + log
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        self.node_tab_widget = QTabWidget()
        self.node_tab_widget.setDocumentMode(True)
        self.splitter.addWidget(self.node_tab_widget)

        # Log panel
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 4, 0, 0)
        log_layout.setSpacing(2)

        log_header = QHBoxLayout()
        log_title = QLabel("EVENT LOG")
        log_title.setStyleSheet(
            f"color: {self.theme['text_dim']}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        log_header.addWidget(log_title)
        log_header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(20)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {self.theme['surface']}; border: 1px solid {self.theme['border']};
                border-radius: 3px; color: {self.theme['text_dim']};
                font-size: 9px; padding: 2px 8px;
            }}
            QPushButton:hover {{ color: {self.theme['accent']}; }}
        """)
        clear_btn.clicked.connect(self._clear_log)
        log_header.addWidget(clear_btn)
        log_layout.addLayout(log_header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        self.splitter.addWidget(log_container)

        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter)

        footer = QLabel(f"ProxMon v{__version__} • Cloud Ninja")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(f"color: {self.theme['border']}; font-size: 9px; padding: 4px;")
        main_layout.addWidget(footer)

    def _create_node_tab(self, node_name):
        t = self.theme
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        cpu_gauge = GaugeBar("CPU", "#00d4ff", "#0066cc", t)
        ram_gauge = GaugeBar("MEMORY", "#a855f7", "#7c3aed", t)
        swap_gauge = GaugeBar("SWAP", "#f59e0b", "#d97706", t)
        layout.addWidget(cpu_gauge)
        layout.addWidget(ram_gauge)
        layout.addWidget(swap_gauge)

        info_style = (
            f"color: {t['text_dim']}; font-size: 11px; background: {t['surface']};"
            f"border-radius: 4px; padding: 6px 10px;"
        )
        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        uptime_label = QLabel("Uptime: —")
        uptime_label.setStyleSheet(info_style)
        info_row.addWidget(uptime_label)
        guests_label = QLabel("VMs: —")
        guests_label.setStyleSheet(info_style)
        info_row.addWidget(guests_label)
        cpu_model_label = QLabel("CPU: —")
        cpu_model_label.setStyleSheet(info_style)
        info_row.addWidget(cpu_model_label)
        layout.addLayout(info_row)

        sub_tabs = QTabWidget()
        sub_tabs.setDocumentMode(True)

        def make_table(columns, narrow_cols=None):
            tbl = QTableWidget()
            tbl.setColumnCount(len(columns))
            tbl.setHorizontalHeaderLabels(columns)
            tbl.verticalHeader().setVisible(False)
            tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            # Set narrow columns to fixed, rest to stretch
            header = tbl.horizontalHeader()
            header.setStretchLastSection(True)
            for i in range(len(columns)):
                if narrow_cols and i in narrow_cols:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            return tbl

        # ID, Status, CPU are narrow; Name, RAM, Disk I/O, Net I/O, Uptime stretch
        storage_table = make_table(["Storage", "Type", "Usage", "Used / Total"])
        sub_tabs.addTab(storage_table, "Storage")

        vm_table = make_table(
            ["VMID", "Name", "Status", "CPU", "RAM", "Disk I/O", "Net I/O", "Uptime"],
            narrow_cols={0, 2, 3}  # VMID, Status, CPU
        )
        vm_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        vm_table.customContextMenuRequested.connect(
            lambda pos, n=node_name, tbl=vm_table: self._vm_context_menu(pos, n, tbl, "qemu")
        )
        sub_tabs.addTab(vm_table, "VMs")

        ct_table = make_table(
            ["CTID", "Name", "Status", "CPU", "RAM", "Disk I/O", "Net I/O", "Uptime"],
            narrow_cols={0, 2, 3}  # CTID, Status, CPU
        )
        ct_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        ct_table.customContextMenuRequested.connect(
            lambda pos, n=node_name, tbl=ct_table: self._vm_context_menu(pos, n, tbl, "lxc")
        )
        sub_tabs.addTab(ct_table, "Containers")

        layout.addWidget(sub_tabs)

        widgets = {
            "cpu_gauge": cpu_gauge, "ram_gauge": ram_gauge, "swap_gauge": swap_gauge,
            "uptime_label": uptime_label, "guests_label": guests_label,
            "cpu_model_label": cpu_model_label,
            "storage_table": storage_table, "vm_table": vm_table, "ct_table": ct_table,
        }
        self.node_tabs[node_name] = widgets
        self.node_tab_widget.addTab(tab, node_name)
        return widgets

    # --- VM/CT Context Menu ---
    def _vm_context_menu(self, pos, node_name, table, guest_type):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        vmid_item = table.item(row, 0)
        name_item = table.item(row, 1)
        status_item = table.item(row, 2)
        if not vmid_item:
            return
        vmid = vmid_item.text()
        name = name_item.text() if name_item else vmid
        status = status_item.text() if status_item else "unknown"

        t = self.theme
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {t['surface']}; color: {t['text']};
                border: 1px solid {t['border']}; border-radius: 4px; padding: 4px;
            }}
            QMenu::item {{ padding: 6px 20px; border-radius: 3px; }}
            QMenu::item:selected {{ background-color: {t['table_selected']}; }}
            QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
        """)

        label = menu.addAction(f"{name} (ID: {vmid})")
        label.setEnabled(False)
        menu.addSeparator()

        if status == "running":
            a = menu.addAction("Shutdown")
            a.triggered.connect(lambda: self._guest_action(node_name, vmid, name, guest_type, "shutdown"))
            a = menu.addAction("Reboot")
            a.triggered.connect(lambda: self._guest_action(node_name, vmid, name, guest_type, "reboot"))
            menu.addSeparator()
            a = menu.addAction("Force Stop")
            a.triggered.connect(lambda: self._guest_action(node_name, vmid, name, guest_type, "stop"))
        else:
            a = menu.addAction("Start")
            a.triggered.connect(lambda: self._guest_action(node_name, vmid, name, guest_type, "start"))

        menu.exec(table.viewport().mapToGlobal(pos))

    def _guest_action(self, node, vmid, name, guest_type, action):
        t = self.theme
        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Action")
        msg.setText(f"{action.title()} {name} (ID: {vmid})?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setStyleSheet(f"""
            QMessageBox {{ background-color: {t['surface']}; }}
            QMessageBox QLabel {{ color: {t['text']}; font-size: 13px; }}
            QPushButton {{
                background-color: {t['accent']}; color: {t['bg']};
                border: none; border-radius: 4px; padding: 6px 18px;
                font-weight: bold; font-size: 12px; min-width: 60px;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        """)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            api = ProxmoxAPI(
                self.config["host"], self.config["port"],
                self.config["token_id"], self.config["token_secret"],
                self.config["verify_ssl"],
            )
            if guest_type == "qemu":
                api.vm_action(node, vmid, action)
            else:
                api.ct_action(node, vmid, action)
            self._log(f"ACTION: {action.upper()} {name} ({vmid})", "accent")
        except Exception as e:
            self._log(f"FAILED: {action} {name} — {e}", "red")
            err_msg = QMessageBox(self)
            err_msg.setWindowTitle("Action Failed")
            err_msg.setText(str(e))
            err_msg.setIcon(QMessageBox.Icon.Warning)
            err_msg.setStyleSheet(f"""
                QMessageBox {{ background-color: {t['surface']}; }}
                QMessageBox QLabel {{ color: {t['text']}; font-size: 13px; }}
                QPushButton {{
                    background-color: {t['accent']}; color: {t['bg']};
                    border: none; border-radius: 4px; padding: 6px 18px;
                    font-weight: bold; font-size: 12px; min-width: 60px;
                }}
            """)
            err_msg.exec()

    # --- Tray ---
    def _build_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self._update_tray_icon(0)
        self.setWindowIcon(self.tray_icon.icon())

        tray_menu = QMenu()
        tray_menu.addAction("Show", self._show_from_tray)
        tray_menu.addAction("Settings", self._show_settings)
        tray_menu.addSeparator()
        tray_menu.addAction("Quit", self._quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _update_tray_icon(self, cpu_pct):
        size = 128  # Larger canvas for crisp text
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme

        if cpu_pct >= 90:
            bg, fg = QColor(t["red"]), QColor("#ffffff")
        elif cpu_pct >= 70:
            bg, fg = QColor(t["yellow"]), QColor("#0d1117")
        else:
            bg, fg = QColor(t["tray_bg"]), QColor(t["tray_text"])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(2, 2, size - 4, size - 4, 16, 16)
        painter.setPen(fg)
        cpu_int = int(round(cpu_pct))
        if cpu_int >= 100:
            fs = 40
        elif cpu_int >= 10:
            fs = 52
        else:
            fs = 64
        painter.setFont(QFont("Segoe UI", fs, QFont.Weight.Black))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, str(cpu_int))
        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "ProxMon", "Minimized to tray. Double-click to restore.",
            QSystemTrayIcon.MessageIcon.Information, 2000,
        )

    def _show_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config = dlg.config
            save_config(self.config)
            self._start_polling()

    def _start_polling(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
        self.status_label.setText("Connecting...")
        self.status_dot.set_color("#f59e0b")
        self._log("Connecting to Proxmox...", "accent")
        self.worker = PollWorker(self.config)
        self.worker.data_ready.connect(self._on_data)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    # --- Logging ---
    def _log(self, message, color_key="text_dim"):
        t = self.theme
        color = t.get(color_key, t["text_dim"])
        timestamp = ts_str()
        line = (
            f'<span style="color:{t["text_faint"]}">[{timestamp}]</span> '
            f'<span style="color:{color}">{message}</span>'
        )
        self.log_lines.append(line)
        if len(self.log_lines) > MAX_LOG_LINES:
            self.log_lines = self.log_lines[-MAX_LOG_LINES:]
        self.log_text.setHtml("<br>".join(self.log_lines))
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

        if self.config.get("log_to_file", False):
            try:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(LOG_FILE, "a") as f:
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass

    def _clear_log(self):
        self.log_lines.clear()
        self.log_text.clear()

    # --- Data Handler ---
    def _on_data(self, data):
        self.last_data = data
        self.status_dot.set_color("#22c55e")
        self.status_label.setText("Connected")

        nodes = data.get("nodes", {})
        version = data.get("version", {})
        pve_ver = version.get("version", "?")

        if not self.prev_guest_states:
            self._log(f"Connected — PVE {pve_ver} — {len(nodes)} node(s)", "green")

        host = self.config["host"]
        self.host_info.setText(f"{', '.join(nodes.keys())}@{host}  •  PVE {pve_ver}")

        primary_node = self.config.get("node", "").lower()
        primary_cpu = None
        primary_mem_used = 0
        primary_mem_total = 1

        for nname, ndata in nodes.items():
            if nname not in self.node_tabs:
                self._create_node_tab(nname)
            w = self.node_tabs[nname]
            ns = ndata.get("summary", {})
            status = ndata.get("status")

            # CPU
            if status:
                cpu_pct = status.get("cpu", 0) * 100
                ci = status.get("cpuinfo", {})
                cores, sockets = ci.get("cores", "?"), ci.get("sockets", "?")
                model = ci.get("model", "Unknown CPU")
                w["cpu_gauge"].set_value(cpu_pct, 100, f"{cores} cores × {sockets} socket(s)")
                if len(model) > 42:
                    model = model[:40] + "…"
                w["cpu_model_label"].setText(f"CPU: {model}")
            else:
                cpu_pct = ns.get("cpu", 0) * 100
                maxcpu = ns.get("maxcpu", "?")
                w["cpu_gauge"].set_value(cpu_pct, 100, f"{maxcpu} threads")
                w["cpu_model_label"].setText(f"CPU: {maxcpu} threads")

            if nname.lower() == primary_node or primary_cpu is None:
                primary_cpu = cpu_pct

            # Memory
            if status:
                mu = status.get("memory", {}).get("used", 0)
                mt = status.get("memory", {}).get("total", 1)
            else:
                mu, mt = ns.get("mem", 0), ns.get("maxmem", 1)
            w["ram_gauge"].set_value(mu, mt, f"{fmt_bytes(mu)} / {fmt_bytes(mt)}")

            if nname.lower() == primary_node or primary_mem_total == 1:
                primary_mem_used = mu
                primary_mem_total = mt

            # Swap / Root Disk
            if status:
                su = status.get("swap", {}).get("used", 0)
                st_total = status.get("swap", {}).get("total", 1)
                if st_total > 0:
                    w["swap_gauge"].label_text = "SWAP"
                    w["swap_gauge"].color_start = "#f59e0b"
                    w["swap_gauge"].color_end = "#d97706"
                    w["swap_gauge"].set_value(su, st_total, f"{fmt_bytes(su)} / {fmt_bytes(st_total)}")
                    w["swap_gauge"].show()
                else:
                    w["swap_gauge"].hide()
            else:
                du, dt = ns.get("disk", 0), ns.get("maxdisk", 1)
                if dt > 0:
                    w["swap_gauge"].label_text = "ROOT DISK"
                    w["swap_gauge"].color_start = "#22c55e"
                    w["swap_gauge"].color_end = "#16a34a"
                    w["swap_gauge"].set_value(du, dt, f"{fmt_bytes(du)} / {fmt_bytes(dt)}")
                    w["swap_gauge"].show()

            # Uptime
            up = status.get("uptime", 0) if status else ns.get("uptime", 0)
            w["uptime_label"].setText(f"Uptime: {fmt_uptime(up)}")

            # Guest counts
            vms = ndata.get("vms", [])
            cts = ndata.get("containers", [])
            vr = sum(1 for v in vms if v.get("status") == "running")
            cr = sum(1 for c in cts if c.get("status") == "running")
            w["guests_label"].setText(f"VMs: {vr}/{len(vms)}  •  CTs: {cr}/{len(cts)}")

            # Detect state changes
            for guest, gtype in [(v, "VM") for v in vms] + [(c, "CT") for c in cts]:
                vid = str(guest.get("vmid", "?"))
                gname = guest.get("name", vid)
                gs = guest.get("status", "unknown")
                prev = self.prev_guest_states.get(vid)
                if prev is not None and prev != gs:
                    color = "green" if gs == "running" else "red" if gs == "stopped" else "yellow"
                    self._log(f"{gtype} {gname} ({vid}) → {gs.upper()}", color)
                    if self.config.get("notifications_enabled", True):
                        icon = (QSystemTrayIcon.MessageIcon.Warning if gs == "stopped"
                                else QSystemTrayIcon.MessageIcon.Information)
                        self.tray_icon.showMessage(f"ProxMon — {gtype} {gname}",
                                                    f"Status: {gs}", icon, 3000)
                self.prev_guest_states[vid] = gs

            # Storage table
            sl = ndata.get("storage", [])
            stbl = w["storage_table"]
            stbl.setRowCount(len(sl))
            for i, s in enumerate(sorted(sl, key=lambda x: x.get("storage", x.get("id", "")))):
                sname = s.get("storage", s.get("id", "?"))
                if sname.startswith("storage/"):
                    sname = sname[8:]
                stbl.setItem(i, 0, QTableWidgetItem(sname))
                stbl.setItem(i, 1, QTableWidgetItem(s.get("plugintype", s.get("type", "?"))))
                used = s.get("disk", s.get("used", 0)) or 0
                total = s.get("maxdisk", s.get("total", 1)) or 1
                pct = (used / total * 100) if total > 0 else 0
                pi = QTableWidgetItem(f"{pct:.1f}%")
                c = self.theme["red"] if pct > 90 else self.theme["yellow"] if pct > 75 else self.theme["green"]
                pi.setForeground(QColor(c))
                stbl.setItem(i, 2, pi)
                stbl.setItem(i, 3, QTableWidgetItem(f"{fmt_bytes(used)} / {fmt_bytes(total)}"))

            # VM table
            vtbl = w["vm_table"]
            vms_s = sorted(vms, key=lambda x: x.get("vmid", 0))
            vtbl.setRowCount(len(vms_s))
            for i, vm in enumerate(vms_s):
                vid = vm.get("vmid", "?")
                vtbl.setItem(i, 0, QTableWidgetItem(str(vid)))
                vtbl.setItem(i, 1, QTableWidgetItem(vm.get("name", "—")))
                vs = vm.get("status", "unknown")
                si = QTableWidgetItem(vs)
                c = self.theme["green"] if vs == "running" else self.theme["red"] if vs == "stopped" else self.theme["yellow"]
                si.setForeground(QColor(c))
                vtbl.setItem(i, 2, si)
                vtbl.setItem(i, 3, QTableWidgetItem(f"{vm.get('cpu', 0) * 100:.1f}%"))
                vtbl.setItem(i, 4, QTableWidgetItem(f"{fmt_bytes(vm.get('mem', 0))} / {fmt_bytes(vm.get('maxmem', 1))}"))
                rates = self.io_tracker.update(vid, vm.get("diskread", 0), vm.get("diskwrite", 0),
                                                vm.get("netin", 0), vm.get("netout", 0))
                if rates:
                    vtbl.setItem(i, 5, QTableWidgetItem(f"R:{fmt_rate(rates['disk_read_rate'])} W:{fmt_rate(rates['disk_write_rate'])}"))
                    vtbl.setItem(i, 6, QTableWidgetItem(f"↓{fmt_rate(rates['net_in_rate'])} ↑{fmt_rate(rates['net_out_rate'])}"))
                else:
                    vtbl.setItem(i, 5, QTableWidgetItem("—"))
                    vtbl.setItem(i, 6, QTableWidgetItem("—"))
                vtbl.setItem(i, 7, QTableWidgetItem(fmt_uptime(vm.get("uptime", 0))))

            # Container table
            ctbl = w["ct_table"]
            cts_s = sorted(cts, key=lambda x: x.get("vmid", 0))
            ctbl.setRowCount(len(cts_s))
            for i, ct in enumerate(cts_s):
                cid = ct.get("vmid", "?")
                ctbl.setItem(i, 0, QTableWidgetItem(str(cid)))
                ctbl.setItem(i, 1, QTableWidgetItem(ct.get("name", "—")))
                cs = ct.get("status", "unknown")
                si = QTableWidgetItem(cs)
                c = self.theme["green"] if cs == "running" else self.theme["red"] if cs == "stopped" else self.theme["yellow"]
                si.setForeground(QColor(c))
                ctbl.setItem(i, 2, si)
                ctbl.setItem(i, 3, QTableWidgetItem(f"{ct.get('cpu', 0) * 100:.1f}%"))
                ctbl.setItem(i, 4, QTableWidgetItem(f"{fmt_bytes(ct.get('mem', 0))} / {fmt_bytes(ct.get('maxmem', 1))}"))
                rates = self.io_tracker.update(cid, ct.get("diskread", 0), ct.get("diskwrite", 0),
                                                ct.get("netin", 0), ct.get("netout", 0))
                if rates:
                    ctbl.setItem(i, 5, QTableWidgetItem(f"R:{fmt_rate(rates['disk_read_rate'])} W:{fmt_rate(rates['disk_write_rate'])}"))
                    ctbl.setItem(i, 6, QTableWidgetItem(f"↓{fmt_rate(rates['net_in_rate'])} ↑{fmt_rate(rates['net_out_rate'])}"))
                else:
                    ctbl.setItem(i, 5, QTableWidgetItem("—"))
                    ctbl.setItem(i, 6, QTableWidgetItem("—"))
                ctbl.setItem(i, 7, QTableWidgetItem(fmt_uptime(ct.get("uptime", 0))))

        # Tray
        if primary_cpu is None:
            primary_cpu = 0
        self._update_tray_icon(primary_cpu)
        mp = (primary_mem_used / primary_mem_total * 100) if primary_mem_total > 0 else 0
        self.tray_icon.setToolTip(f"ProxMon — CPU: {primary_cpu:.0f}% | RAM: {mp:.0f}%")

    def _on_error(self, error_msg):
        self.status_dot.set_color("#ef4444")
        short = error_msg[:80] + "…" if len(error_msg) > 80 else error_msg
        self.status_label.setText(f"Error: {short}")
        self._log(f"ERROR: {error_msg}", "red")


# ═══════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = ProxMonWindow()
    if not load_config().get("start_minimized", False):
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
