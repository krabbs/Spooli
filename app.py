from flask import Flask, jsonify, render_template, request
import threading
from datetime import datetime
from zoneinfo import ZoneInfo  
import os
import json
import time
import settings
import sys
from monitor import get_current_status, prepare_gcode, parse_gcode_metadata, live_analyze_gen, get_current_job, init_wait_for_job, mm_to_g, ProgressMonitor_thread_fn, add_slicer_to_usage, stop_event
import logging
import random

# Configuration
WEB_PORT = 5000
SPOOL_DB_FILE = os.path.join('data', 'spool_db.json')
username = "maker" #os.getenv("USERNAME") 
password = os.getenv("PASSWORD")
ip = os.getenv("PRUSA_IP")

def load_spool_db():
    if not os.path.exists(SPOOL_DB_FILE):
        return []
    with open(SPOOL_DB_FILE, 'r') as f:
        return json.load(f)

def save_spool_db(db):
    with open(SPOOL_DB_FILE, 'w') as f:
        json.dump(db, f, indent=2)

INITIAL_WEIGHT_G = 1000.0  # 1 kg pro Spule

#GLOBALS
spool_db = []
gcode_path = ""
meta = ""
slicing =  ""
densities = ""
stamping =  ""
usage_history = []  # runtime data populated by monitor
#tool_progress = 0.0
#TOOLSTATE = "unknown"   # PRINTING, PAUSED, etc.

POLL_INTERVAL = 5    # Sekunden


app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True
log.disabled = True
        
def init_spools():
    global spool_db
    spool_db = load_spool_db()
    if not spool_db:
        # Beispiel-Initialisierung mit 5 Spulen
        spool_db = [
            {
              "id": f"{random.randint(0,0xFFFF):04X}",
              "name": f"Spule {i}",
              "material": "PLA",
              "color": "Weiß",
              "data": { "remaining_g": INITIAL_WEIGHT_G, "first_used": None, "last_used": None },
              "usage": { "slot": i }  # Werkzeug‑Slot direkt zuweisen
            }
            for i in range(settings.tool_count)
        ]

        save_spool_db(spool_db)

   
def refill_spools(usage_history, densities):
    """
    Aktualisiert die Mini‑DB (spool_db) für alle Spulen basierend auf dem zuletzt
    erfassten Druckverbrauch.
    
    Args:
      usage_history (list of tuple): Liste der Zwischenergebnisse 
          [(progress_percent, {tool_index: used_mm, ...}), ...]
      densities (list of float): Dichte (g/cm³) je Toolindex
      
    Returns:
      list of dict: Aktualisierte spool_db-Liste
    """
    global spool_db  # Deine zentrale „Datenbank“-Liste aus load_spool_db()
    
    # 1) Falls kein Druck gelaufen ist, nichts tun
    if not usage_history:
        return spool_db

    # 2) Nimm nur das letzte Element (100% oder Abbruch)  
    #    (progress, usage_dict)  
    progress, last_usage = usage_history[-1]
    
    # 3) Erzeuge aktuellen Zeitstempel (UTC ISO)
    now = datetime.now(ZoneInfo("Europe/Berlin"))

    # 4) Für jede Spule in spool_db:
    for entry in spool_db:
        slot = entry['usage']['slot']  # Werkzeug‑Slot (0–4) oder None

        # Nur, wenn diese Spule aktuell belegt war
        if slot is None:
            continue

        # 5) Berechne Verbrauch in Gramm:
        used_mm = last_usage.get(slot, 0.0)
        if used_mm < 1: continue 
        # mm → g: Volumen = Π·r²·mm /1000, dann · density
        if settings.tool_mmu:
          used_g = mm_to_g(used_mm, densities[slot])
        else:
          used_g = mm_to_g(used_mm, densities)
        # 6) Ziehe ab und aktualisiere remaining_g
        old = entry['data']['remaining_g']
        entry['data']['remaining_g'] = max(0.0, old - used_g)
        
        # 7) Pflege first_used / last_used
        if entry['data']['first_used'] is None:
            entry['data']['first_used'] = now.strftime('%Y-%m-%dT%H:%M%z')
        entry['data']['last_used'] = now.strftime('%Y-%m-%dT%H:%M%z')

    # 8) Speichere die geänderte DB
    save_spool_db(spool_db)
    return spool_db
    
def log_print_history(filename, usage, densities, slotmap):
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    record = {
        "timestamp": now.strftime('%Y-%m-%dT%H:%M%z'),
        "file": filename,
        "progress": settings.tool_progress,
        "status": settings.tool_state,  # <- neuer Eintrag für Druckstatus
        "spools": {}
    }

    for slot, used_mm in usage.items():
        used_g = mm_to_g(used_mm, densities[slot]) if isinstance(densities, list) else mm_to_g(used_mm, densities)
        for spool in spool_db:
            if spool["usage"]["slot"] == slot:
                record["spools"][spool["id"]] = round(used_g, 2)
    try:
        with open('data/print_history.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = []
    data.append(record)
    with open('data/print_history.json', 'w') as f:
        json.dump(data, f, indent=2)


@app.route("/spools")
def get_spool_list():
    return jsonify(spool_db)  # Liste von Spulen-Objekten für die DB-Anzeige

@app.route("/spool_weights")
def get_spool_weights():
    return jsonify({ s["usage"]["slot"]: s["data"]["remaining_g"] for s in spool_db if s["usage"]["slot"] is not None })

#@app.route('/poll')
#def poll():
#    # Beispiel: Werte aus deinem Tool-Status-Tracking
#    return jsonify({
#        'state': tool_state,
#        'progress': tool_progress,
#        'job': tool_job
 #   })


@app.route('/status')
def status():
    return jsonify({
        'tool_state': settings.tool_state,
        'tool_progress': settings.tool_progress,
        'tool_job': settings.tool_job,
        'tool_live': settings.tool_live,
        'tool_mmu': settings.tool_mmu
    })

        
@app.route('/refill', methods=['POST'])
def refill_endpoint():
    global usage_history, densities
    new_state = refill_spools(usage_history, densities)
    return jsonify(new_state), 200


@app.route('/reset')
def refillforce_endpoint():
    # Falls „Reset“ das Gewicht zurücksetzen soll (z. B. auf 1000g):
    global spool_db
    for entry in spool_db:
        entry['data']['remaining_g'] = INITIAL_WEIGHT_G
        entry['data']['first_used'] = None
        entry['data']['last_used'] = None
    save_spool_db(spool_db)
    return jsonify(spool_db), 200
    
@app.route('/')
def index():
    """
    Hauptansicht:
    - Aktive Spulen oben links (spool_state)
    - Live-Chart rechts
    - Alle Spulen unten (spool_db)
    - Statusbar am unteren Rand
    """
    # 1) Mapping aktive Spulen: slot -> Restgewicht
    active_spools = {}
    for entry in spool_db:
        slot = entry['usage']['slot']
        if slot is not None:
            active_spools[slot] = entry['data']['remaining_g']

    # 2) Nur diese Slots für Chart/Color
    tool_indices = list(active_spools.keys())
    tool_colors = {t: f"{(t*100000)%0xFFFFFF:06x}" for t in tool_indices}

    return render_template(
        "index.html",
        spool_state=active_spools,
        tool_indices=tool_indices,
        tool_colors=tool_colors,
        max_weight=1000,
        spool_db=spool_db,
        tool_state=settings.tool_state,
        tool_live=settings.tool_live,
        tool_progress=settings.tool_progress,
        tool_job=settings.tool_job,
        tool_mmu=settings.tool_mmu
    )


@app.route('/data')
def data():
    return jsonify(usage_history)
    
@app.route('/delete_spool/<id>', methods=['POST'])
def delete_spool(id):
    global spool_db
    before = len(spool_db)
    spool_db = [s for s in spool_db if s['id'] != id]
    if len(spool_db) < before:
        save_spool_db(spool_db)
        return '', 204
    else:
        return 'Spule nicht gefunden', 404
    
@app.route('/add_spool', methods=['POST'])
def add_spool():
    global spool_db
    new_spool = {
        "id": f"{random.randint(0,0xFFFF):04X}",
        "name": "Neue Spule",
        "material": "PLA",
        "color": "#cccccc",
        "data": { 
            "remaining_g": INITIAL_WEIGHT_G, 
            "first_used": None, 
            "last_used": None 
        },
        "usage": { "slot": None }
    }
    spool_db.append(new_spool)
    save_spool_db(spool_db)
    return jsonify(new_spool), 201
    
@app.route('/update_spool', methods=['POST'])
def update_spool():
    global spool_db
    data = request.get_json()
    id = data.get("id")
    field = data.get("field")
    value = data.get("value")

    target_spool = next((s for s in spool_db if s['id'] == id), None)
    if not target_spool:
        return 'Spule nicht gefunden', 404

    if field in ('name', 'material', 'color'):
        target_spool[field] = value
    elif field == 'remaining_g':
        try:
            target_spool['data']['remaining_g'] = float(value)
        except ValueError:
            return "Ungültiger Wert für Gewicht", 400
    elif field == 'slot':
        try:
            new_slot = int(value)
            if not (0 <= new_slot < settings.tool_count):
                return f"Slot muss zwischen 0 und {settings.tool_count-1} sein.", 400
        except (ValueError, TypeError):
            new_slot = None

        if new_slot is not None:
            conflicting = next((s for s in spool_db if s['usage']['slot'] == new_slot and s['id'] != id), None)
            if conflicting:
                conflicting['usage']['slot'] = None
        target_spool['usage']['slot'] = new_slot
    else:
        return "Ungültiges Feld", 400
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    target_spool['data']['last_used'] = now.strftime('%Y-%m-%dT%H:%M%z')
    save_spool_db(spool_db)
    return '', 204
@app.route('/set_spool_weight/<int:tool>/<weight>', methods=['POST'])
def set_spool_weight(tool, weight):
    try:
        w = float(weight)
    except ValueError:
        return "Ungültiges Gewicht", 400

    global spool_db
    updated = False
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    for entry in spool_db:
        if entry['usage']['slot'] == tool:
            entry['data']['remaining_g'] = w
            entry['data']['first_used'] = entry['data']['first_used'] or now.strftime('%Y-%m-%dT%H:%M%z')
            entry['data']['last_used'] = now.strftime('%Y-%m-%dT%H:%M%z')
            updated = True

    if updated:
        save_spool_db(spool_db)
        return ('', 204)
    else:
        return f"Kein Eintrag mit Slot {tool} gefunden", 404
        
@app.route('/history')
def get_history():
    with open('data/print_history.json', 'r') as f:
        return jsonify(json.load(f))

@app.route('/history_by_spool/<spool_id>')
def get_history_by_spool(spool_id):
    with open('data/print_history.json', 'r') as f:
        all_jobs = json.load(f)
    relevant = [job for job in all_jobs if spool_id in job.get("spools", {})]
    return jsonify(relevant)
    
@app.route('/noti')
def get_notification():
    return jsonify({ "noti": settings.noti })

@app.route('/prognosis')
def get_prognosis():
    try:
        #if not usage_history or not settings.tool_state == "PRINTING" or settings.tool_live in ('file', 'blocked'):
        #    return jsonify({})
        if not settings.tool_state == "PRINTING" or settings.tool_live in ('file', 'blocked'):
            return jsonify({})
            
        # Letzter Stand aus usage_history: bisher verbraucht in mm pro Tool
        last_progress, usage = usage_history[-1]
        if last_progress == 0:
            return jsonify({})

        # slicer-Verbrauch aus Metadaten (g)
        slicing_g = settings.slicing_g  # zuvor in settings gesetzt

        # bisher verbraucht
        if settings.tool_mmu:
            prognosis = {}
            for slot in range(len(slicing_g)):
                total_g = slicing_g[slot] if slot < len(slicing_g) else 0.0
                used_g = sum(
                    mm_to_g(u, settings.densities[slot])
                    for p, u_dict in usage_history
                    for s, u in u_dict.items()
                    if s == slot
                )
                rest_g = max(0.0, total_g - used_g)
                # aktuelle Spule finden
                for spool in spool_db:
                    if spool["usage"]["slot"] == slot:
                        actual = spool["data"]["remaining_g"]
                        prognosis[slot] = actual - rest_g
                        prognosis[slot] = actual - (total_g) # - used_g)
        else:
            total_g = slicing_g if isinstance(slicing_g, float) else sum(slicing_g)
            used_g = sum(mm_to_g(u, settings.densities)
                         for _, u_dict in usage_history
                         for u in u_dict.values())
            rest_g = max(0.0, total_g - used_g)
            # Spule finden
            for spool in spool_db:
                if spool["usage"]["slot"] is not None:
                    actual = spool["data"]["remaining_g"]
                    prognosis = { spool["usage"]["slot"]: actual - rest_g }
                    break
        return jsonify(prognosis)
    except Exception as e:
        print("Fehler in /prognosis:", e)
        return jsonify({})


#stop_event = threading.Event()
def main():
    global usage_history
    init_spools()
    pm = None
    #global tool_progress
    #global TOOLSTATE
    # Starte Webserver im Hintergrund
    threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':WEB_PORT}, daemon=True).start()
    #threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':WEB_PORT,'debug':True,'use_reloader':True}, daemon=True).start()
    print(f"Webserver läuft auf http://0.0.0.0:{WEB_PORT}")
    run_looping = True
    settings.reboot = False
    if len(sys.argv)==2: 
      file_analyse = True
    else:
      file_analyse = False
    while run_looping and not settings.reboot:
        gcode_path = ""
        meta = ""
        slicing =  ""
        densities = ""
        stamping =  ""

        settings.init(password, ip)
        # Starte ProgressMonitor-Thread
        #pm = ProgressMonitor()
        #pm.start()
        #ProgressMonitor_thread_fn
        if pm is None or not pm.is_alive():
            pm = threading.Thread(target = ProgressMonitor_thread_fn)
            pm.start()
        else:
            print("ProgressMonitor_thread_fn already running")
        # G-Code-Datei ermitteln und vorbereiten
        if file_analyse:
            inp=sys.argv[1]; filename=os.path.basename(inp); dl=False
            settings.tool_live = 'file'
            file_analyse = False
        else:
            settings.noti = "" 
            job_init = init_wait_for_job()
            filename = job_init['file']['display_name']
            dl=True
            inp=None
            #filename = job_init.get('file').get('display_name')
        settings.noti = "" 
        gcode_path = prepare_gcode(inp, filename, use_download=dl)

        print(f"State {settings.tool_state}  ")
        # Metadaten einlesen
        meta = parse_gcode_metadata(gcode_path)
        
        tools = meta['nozzle_diameter']
        settings.slicing_g = meta['filament used [g]']
        slicing_m = meta['filament used [mm]']
        settings.densities = meta['filament_density']
        stamping = meta['filament_stamping_distance']

        if type(tools) != float:    
            settings.tool_mmu = True
        else:
            settings.tool_mmu = False
        print(f"{type(tools)} Tools used for this print {tools}. MMU is {settings.tool_mmu}")
        
        # Aufruf des Generators live_analyze:
        # live_analyze yieldet fortlaufend (progress, usage_dict).
        usage_history = []  # runtime data populated by monitor
        
        if settings.tool_live in ('file', 'blocked') or not dl:
          doSync = False
          settings.noti = "no sync"
        else:
          doSync = True
        
        
        #if dl or settings.tool_live=='blocked':
       #   doSync = True
     #   else:
      #    doSync = False
          
          
        gen = live_analyze_gen(gcode_path, slicing_m, densities, stamping, sync=doSync)
        for progress, usage in gen:
            # Hier wird der Generator konsumiert!
            # Zwischenstände landen in usage_history via yield und Flask-/Data-Endpoint.
            usage_history.append((progress, usage))
            #print(f"Generator liefert: {progress:.1f}% - {usage}. State {settings.tool_state}")

          # Externen Abbruch erkennen:
            if (doSync) and (settings.tool_state in ('CANCELLED', 'ERROR', 'IDLE','FINISHED', 'STOPPED')):
                if (settings.tool_state in ( 'FINISHED')): settings.tool_progress=100
                print(f"{settings.tool_state} erkannt, beende Live-Analyse!")
                gen.close()   # wirft GeneratorExit INSIDE dem Generator
                break
            if settings.reboot or settings.reboot_analzye:
                print(f"settings.reboot {settings.reboot} settings.reboot_analzye {settings.reboot_analzye} erkannt, beende Live-Analyse!")
                gen.close()   # wirft GeneratorExit INSIDE dem Generator
                break              
        if settings.noti=="Analyse Offline" or settings.noti=="Analyse Online": settings.noti=""
        print("LIVE END")
        print("\nDruck beendet. Vergleich:")
        if settings.tool_mmu:
          tool_range = range(settings.tool_count_mmu)
          for t in range(settings.tool_count_mmu):
            calc_g=mm_to_g(usage.get(t,0.0),settings.densities[t]); sl_g=settings.slicing_g[t] if t<len(settings.slicing_g) else 0.0
            print(f" T{t}: berechnet {calc_g:.1f}g vs slicer {sl_g:.1f}g diff {calc_g-sl_g:+.1f}g")
            calc_m=usage.get(t,0.0); sl_m=slicing_m[t] #if t<len(slicing_m) else 0.0
            print(f" T{t}: berechnet {calc_m:.1f}mm vs slicer {sl_m:.1f}mm diff {calc_m-sl_m:+.1f}mm")
        else:
            calc_g=mm_to_g((list(usage.values())[-1]),settings.densities); sl_g=settings.slicing_g if t<len(settings.slicing_g) else 0.0
            print(f" T{settings.tool_count}: berechnet {calc_g:.1f}g vs slicer {sl_g:.1f}g diff {calc_g-sl_g:+.1f}g")
            calc_m=(list(usage.values())[-1]); sl_m=slicing_m #if t<len(slicing_m) else 0.0
            print(f" T{settings.tool_count}: berechnet {calc_m:.1f}mm vs slicer {sl_m:.1f}mm diff {calc_m-sl_m:+.1f}mm")

        
        if ((settings.tool_state in ('FINISHED')) or (progress >= 100) or (not  doSync)) and settings.prusa_usage: # Extrude purge line is not included in Prusa Slicer Concumptions. Dont use this for the moment 
          print(f"Printer is {progress} and marked as {settings.tool_state}. Not synchronise anymore")  
          usage_history = add_slicer_to_usage(usage_history, slicing_m, densities)
          print(f"finally add slicer values {usage_history}") 
        refill_spools(usage_history, settings.densities)
        log_print_history(filename, usage, settings.densities, [s["usage"]["slot"] for s in spool_db])
        settings.noti = ""

    # Cleanup
    stop_event.set()
    print("Stop")
    pm.join()
    print("END")
    settings.tool_progress = "-"
    settings.tool_state = "NO MONITORING"   # PRINTING, PAUSED, etc.
    settings.tool_job = "NO MONITORING" # file
    settings.tool_live = "NO MONITORING"

if __name__ == '__main__':
    main()
