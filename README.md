# 🧵 Prusa MMU3 Filament Monitor

This project monitors filament usage for MMU-enabled (and non-MMU) 3D printers using live G-code analysis. It provides a responsive web interface for managing spool data and viewing real-time progress.

![Screenshot of Main Dashboard](images/dashboard.png)

---

## 🔧 Features

- Real-time progress tracking via PrusaLink API
- Automatic G-code analysis with filament usage per tool
- Slot management and spool database with history
- UI highlighting for current state and blocked file access
- Support for both MMU (slots 0–4) and direct drive (slot 5)

---

## 🚀 How It Works

1. **Backend**:
   - `Flask` server (`app.py`) serves the frontend and handles API endpoints.
   - `monitor.py` reads live print data and parses G-code files.
   - `settings.py` configures credentials and printer access via PrusaLink.

2. **Frontend**:
   - Built with HTML/CSS/JS.
   - Visualizes active spool weights, print progress, and history.
   - Allows editing spool properties inline.
   - Slot dropdown maps MMU slots (1–5) + “non-mmu” (slot 6 → backend slot 5).

3. **Spool Management**:
   - Spool data is saved in `data/spool_db.json`.
   - Print history is logged in `data/print_history.json`.

---

## 📦 Folder Structure

```
.
├── app.py                 # Flask application
├── monitor.py             # G-code analyzer and printer monitor
├── settings.py            # PrusaLink configuration
├── index.html             # Main frontend UI
├── indey.html             # (Legacy version or experimental view)
├── data/
│   ├── spool_db.json      # Spool state database
│   └── print_history.json # Print job history
```

---

## 🛠️ Installation

```bash
git clone https://github.com/youruser/filament-monitor.git
cd filament-monitor

# Set up environment variables
export PASSWORD='your_prusalink_password'
export PRUSA_IP='192.168.1.48'

# Start the monitor
python3 app.py
```

---

## 🖼️ Screenshots

_Add your own screenshots here:_

- Filament progress chart  
  `![Progress Chart](images/chart.png)`
- Editable spool table  
  `![Spool Table](images/spools.png)`

---

## 🧠 Notes

- This tool supports MMU3 and direct printing.
- Automatically maps slot 6 (non-mmu) to backend slot 5.
- Flask API updates the UI every 2 seconds.

---

## 📜 License

MIT License – feel free to use, modify, and share.

---

## 💬 Feedback & Contributions

Pull requests and feedback welcome!
