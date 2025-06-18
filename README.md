📄 Prusa MMU3 Filament Monitor – System Overview & Installation Guide


---

🧩 Components Overview

The system consists of three main parts:

1. app.py – Flask Web Backend

Responsible for hosting the user interface and APIs.

Starts a web server on port 5000.

Loads and manages the spool database (spool_db.json).

Tracks active job, usage history, and tool state via shared settings.

Calls the monitor.py logic to perform live print analysis.


2. monitor.py – Live Print Analyzer

Responsible for extracting live filament usage from the currently printing file.

Retrieves the file via PrusaLink API.

Parses G-code line-by-line.

Tracks extrusion per tool and tool changes.

Produces usage history for frontend graph and spool deduction.


3. index.html – Frontend UI

Provides a responsive dashboard:

Displays live chart of filament use.

Shows current spool weight (with warning if insufficient).

Lets users edit spool entries inline (name, material, weight).

Automatically reloads via polling every 2 seconds.

Tracks full print history, including final status (FINISHED, CANCELLED, ERROR, etc.).



---

🔧 Installation Instructions

1. Clone Repository

git clone https://github.com/krabbs/spooli.git
cd filament-monitor

2. Install Required Python Libraries

pip install flask requests pygcode

3. Install bgcode (required for .bgcode conversion)

Prusa sometimes stores jobs as .bgcode files which need to be converted.

git clone https://github.com/prusa3d/bgcode.git
cd bgcode
make
sudo cp bgcode /usr/local/bin

> bgcode must be available in your PATH.



4. Set Environment Variables

Set these before launching the server (e.g. in .env or systemd service):

export PASSWORD="your_prusa_password"
export PRUSA_IP="192.168.1.48"


---

🚀 Running the Monitor

python3 app.py

You should now be able to open:

http://localhost:5000

Or over LAN using the IP of the device hosting it.


---

📦 Data Files

data/spool_db.json – spool inventory and slot assignment

data/print_history.json – historical prints with file, progress, state and usage



---

🔁 Print History Example (JSON)

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


---

🧭 Backend API Reference

Endpoint	Method	Description

/	GET	Serves index.html template
/status	GET	Returns current printer state (tool_progress, tool_state, etc.)
/data	GET	Returns the full print progress/usage history (for graphing)
/spools	GET	Returns the entire spool database
/spool_weights	GET	Returns active spools with current weight by slot
/add_spool	POST	Adds a new spool to the DB
/delete_spool/<id>	POST	Deletes the spool with matching ID
/update_spool	POST	Updates a specific spool field (weight, name, slot, etc.)
/set_spool_weight/<slot>/<g>	POST	Manually sets weight of a specific slot
/refill	POST	Triggers weight update based on latest usage history
/reset	GET	Resets all spool weights to initial values
/history	GET	Returns complete print history
/history_by_spool/<id>	GET	Returns print jobs that used the specified spool ID
/noti	GET	Returns current notification banner text
/prognosis	GET	Returns forecasted remaining weight after current job


🔧 POST Request Payload Examples

/update_spool

{
  "id": "AB12",
  "field": "remaining_g",
  "value": "435.0"
}

/set_spool_weight/1/500  → sets slot 1 to 500g

/add_spool – no body required

/delete_spool/AB12 – just call with POST, no body required

/refill – no body required; updates spool weights from usage_history


---

🚩 Systemd Autostart Setup

Create a service file at /etc/systemd/system/filament-monitor.service:

[Unit]
Description=Prusa MMU3 Filament Monitor
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/filament-monitor/app.py
WorkingDirectory=/path/to/filament-monitor
Environment=PRUSA_IP=192.168.1.XX
Environment=PASSWORD=your_password
Restart=always
User=pi

[Install]
WantedBy=multi-user.target

Enable and start:

sudo systemctl daemon-reexec
sudo systemctl enable filament-monitor.service
sudo systemctl start filament-monitor.service

Logs can be viewed with:

journalctl -u filament-monitor.service -f


---

🖼 Frontend Explained

Top Cards: Show active spools and live chart of filament usage (mm vs. % progress)

Slot Mapping: Maps internal slots 0–5 to frontend view 1–6 (slot 5 → "non-mmu")

History Table: Stores and displays past print jobs with filterable spool ID, status, file

Inline Editing: Supports editing fields like remaining weight, name, color

Forecasting: /prognosis returns expected consumption to warn early if filament is insufficient

Warning Banner: /noti dynamically shows info banners like "no sync", "analyze offline", etc.

Progress Indicators: Frontend highlights blocked state and animates printing status



---

⚠️ Notes

Only tracks filament usage if synced with live print (tool_live = 'live')

Parsing .bgcode requires bgcode tool from Prusa

Works both for MMU (slots 0–4) and direct prints (slot 5)

Progress & printer state are polled every 5 seconds from PrusaLink



---

📜 License

MIT – free for personal and commercial use.

🙋 Feedback

Please open issues or send improvements via pull request!

