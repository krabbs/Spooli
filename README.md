# 📄 Prusa MMU3 Filament Monitor – System Overview & Installation Guide

![Dashboard Overview](images/dashboard.png)
![Spool Table](images/spool_table.png)

This project provides a local monitoring and filament management solution for Prusa 3D printers using MMU3.

Unlike standard printer APIs, this system does not read filament usage directly from the printer, as this data is not exposed by the PrusaLink API. Instead, it achieves accurate tracking through a combination of synchronized live parsing and spool deduction.

When a print starts, the `app.py` backend downloads the active G-code file (as `.bgcode`), parses it line-by-line, and calculates the extrusion per tool. It identifies tool changes and accumulates usage over time. This parsing is done in a dedicated thread and kept synchronized with the live print progress and state received via PrusaLink.

The result: filament usage per tool is accurately tracked and deducted from assigned spools — both for successful and aborted prints.

If the file is streamed directly (e.g. from PrusaSlicer without saving to USB), the `.bgcode` file is not available during print, and live parsing will be "blocked". Once the file becomes available again, usage will be reconstructed based on known progress and comparison to expected values.

A lightweight internal database manages all spools, their remaining weights, material, and color. Each slot (0–4 for MMU tools, 5 for direct mode) can be manually or automatically assigned.

The backend API is designed for easy integration via JSON-based GET and POST endpoints, allowing other tools or interfaces to hook into the spool data.

## 🛠 Current Assumptions
- Designed for Prusa MMU3 systems
- Tested with PrusaSlicer 2.9.2
- Default setup supports 5 MMU slots + 1 fallback slot (non-MMU)

## ✅ Features
- Live parsing of `.bgcode` for per-tool filament usage
- Inline editable spool database (adding and deleting)
- Remaining spool weight deduction with historical log
- Forecasting logic to detect insufficient filament early
- Filterable print history with spool consumption breakdown

## 🚧 Planned / Missing
- Better logging support for system
- Dynamic reassignment of spools during print
- Merging of spools post-print
- MQTT integration
- Prusa Connect API integration (waiting for API docs)
- Frontend settings panel
- G-code compatibility checks

## 🐞 Known Bugs
- Forecasts can be delayed
- Unexpected restarts or network failures may cause looping

---

## 🧩 Components Overview

The system consists of three main parts:

### 1. `app.py` – Flask Web Backend
- Hosts the UI and APIs
- Manages spool database
- Controls threading and monitoring

### 2. `monitor.py` – Live Print Analyzer
- Downloads and parses G-code
- Tracks tool changes and filament usage
- Feeds usage data to the frontend and database

### 3. `index.html` – Frontend UI
- Displays progress and active tools
- Allows manual editing of spools
- Presents history and forecasting

---

## 🔧 Installation Instructions

```bash
git clone https://github.com/youruser/filament-monitor.git
cd filament-monitor
pip install flask requests pygcode
```

```bash
git clone https://github.com/prusa3d/bgcode.git
cd bgcode
make
sudo cp bgcode /usr/local/bin
```

```bash
export PASSWORD="your_prusa_password"
export PRUSA_IP="192.168.1.48"
```

---

## 🚀 Running the Monitor

```bash
python3 app.py
```

---

## 📦 Data Files

- `data/spool_db.json`
- `data/print_history.json`

---

## 🔁 Print History Example

```json
{
  "timestamp": "2025-06-16T13:22+0200",
  "file": "example.gcode",
  "progress": 100,
  "status": "FINISHED",
  "spools": {
    "AB12": 57.4,
    "CD34": 12.1
  }
}
```

---

## 🧭 Backend API Reference

| Endpoint                       | Method | Description |
|-------------------------------|--------|-------------|
| `/`                           | GET    | UI |
| `/status`                    | GET    | Printer state |
| `/data`                      | GET    | Usage history |
| `/spools`                    | GET    | Spool list |
| `/spool_weights`             | GET    | Active spool weights |
| `/add_spool`                 | POST   | Add spool |
| `/delete_spool/<id>`         | POST   | Delete spool |
| `/update_spool`              | POST   | Update spool field |
| `/set_spool_weight/<slot>/<g>` | POST | Set slot weight |
| `/refill`                    | POST   | Apply usage data |
| `/reset`                     | GET    | Reset weights |
| `/history`                   | GET    | Full history |
| `/history_by_spool/<id>`     | GET    | History by spool |
| `/noti`                      | GET    | Notification |
| `/prognosis`                 | GET    | Forecast remaining weight |

### 🔧 POST Request Examples

```json
{
  "id": "AB12",
  "field": "remaining_g",
  "value": "435.0"
}
```

---

## 🚩 Systemd Autostart

```ini
[Unit]
Description=Prusa MMU3 Filament Monitor
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/filament-monitor/app.py
WorkingDirectory=/path/to/filament-monitor
Environment=PRUSA_IP=192.168.1.48
Environment=PASSWORD=your_password
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

---

## 🖼 Frontend Walkthrough

![Active Spools](images/dashboard.png)
![Spool Table](images/spool_table.png)
![Print History](images/animationUI.gif)
![Live Graph](images/lastPrintUI.png)
![Spool DB](images/SpoolDatabaseUI.png)
![History Table](images/history_table.png)

---

## ⚠️ Notes

- Real-time syncing requires `tool_live = 'live'`
- `bgcode` required for parsing
- Works for MMU3 and single-tool setups
- Data polling every 5 seconds

---

## 📜 License

MIT License

---

## 🙋 Feedback

Submit issues or PRs via GitHub.
