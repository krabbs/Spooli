# 📄 Prusa MMU3 Filament Monitor – System Overview & Installation Guide

![Dashboard Overview](images/dashboard.png)
![Spool Table](images/spool_table.png)



This project provides a local monitoring and filament management solution for Prusa 3D printers using MMU3.

Unlike standard printer APIs, this system does not read filament usage directly from the printer, as this data is not exposed by the PrusaLink API. Instead, it achieves accurate tracking through a combination of synchronized live parsing and spool deduction.

When a print starts, the app.py backend downloads the active G-code file (as .bgcode), parses it line-by-line, and calculates the extrusion per tool. It identifies tool changes and accumulates usage over time. This parsing is done in a dedicated thread and kept synchronized with the live print progress and state received via PrusaLink.

The result: filament usage per tool is accurately tracked and deducted from assigned spools — both for successful and aborted prints.

If the file is streamed directly (e.g. from PrusaSlicer without saving to USB), the .bgcode file is not available during print, and live parsing will be "blocked". Once the file becomes available again, usage will be reconstructed based on known progress and comparison to expected values.

A lightweight internal database manages all spools, their remaining weights, material, and color. Each slot (0–4 for MMU tools, 5 for direct mode) can be manually or automatically assigned.

The backend API is designed for easy integration via JSON-based GET and POST endpoints, allowing other tools or interfaces to hook into the spool data.

🛠 Current assumptions:

Designed for Prusa MMU3 systems

Tested with PrusaSlicer 2.9.2

Default setup supports 5 MMU slots + 1 fallback slot (non-MMU)


✅ Features:

Live parsing of .bgcode for per-tool filament usage
(Delayed parsing if bgcode is blocked while printing (prusa streams the code))

Inline editable spool database ( adding and deleting)

Remaining spool weight deduction with historical log

Forecasting logic to detect insufficient filament early

Filterable print history with spool consumption breakdown


🚧 Planned / missing:

Better logging support for system

Dynamic reassignment of spools during print

Merging of spools post-print (manual assignment supported if negative consumption occurs)

MQTT integration 

Maybe Prusa Connect API ( i couldn't get anything working at the moment)

Settings Frontend for some parameters 

gcode compatible check 


Known Bugs

-forecast can be delayed 
-some events (like printer reset ot network fails) results in looping without outputs 


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

git clone https://github.com/youruser/filament-monitor.git
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

...


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
![active spools](images/dashboard.png)
Top Cards: Show active spools and live chart of filament usage (mm vs. % progress)
Bottom shows spools and history 

![active spools](images/spool_table.png)
![Print History](images/animationUI.gif)
Forecasting: /prognosis returns expected consumption to warn early if filament is insufficient
The black line indicates the usage for 100% of the current print 
White Red bars highlights negative spools. means there was an calculation error or another spool joined the tool. this can be manually solved with the spool database weight manipulation.
White Red Blinking bars means the print with this specific spool will result in an end of spool BEFORE print ends.
![active print](images/lastPrintUI.png)
This graphic is the main output of the consumption algorithm and can be used as a live visualization or print overview 

![Spool Database](images/SpoolDatabaseUI.png)
Slot Mapping amd spool database: Maps internal slots 0–5 to frontend view 1–6 (slot 5 → "non-mmu")
Inline Editing: Supports editing fields like remaining weight, name, color. simple +/- formulas are allowed in the weight cell.

![Print History](images/history_table.png)
Csn be expanded by clicking 
History Table: Stores and displays past print jobs with filterable spool ID, status, file


Warning Banner: /noti dynamically shows info banners like "no sync", "analyze offline", etc.

Progress Indicators(at the very top) Frontend highlights blocked state and informs printing status. Note: if the live status calls "blocked" than the gcode is locked by prusa printer and will be available after the printing. means your consumption will be tracked after the print finished or aborted 



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

