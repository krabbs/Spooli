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
TARE_WEIGHT_G = 200

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
              "data": { "remaining_g": INITIAL_WEIGHT_G, "tare_weight_g": TARE_WEIGHT_G, "first_used": None, "last_used": None },
              "usage": { "slot": i }  # Werkzeug‑Slot direkt zuweisen
            }
            for i in range(settings.tool_count)
        ]

        save_spool_db(spool_db)

    
def refill_spools(usage_history, densities):
    """
    Aktualisiert die Mini‑DB (spool_db) für alle Spulen basierend auf dem zuletzt
    erfassten Druckverbrauch.
    """
    global spool_db
    
    print("\n[refill_spools] Starte Aktualisierung der Spulen")
    
    if not usage_history:
        print("[refill_spools] Keine usage_history – Abbruch")
        return spool_db

    progress, last_usage = usage_history[-1]
    print(f"[refill_spools] Letzter Fortschritt: {progress}%")
    print(f"[refill_spools] Letzte Verwendung (mm): {last_usage}")
    
    now = datetime.now(ZoneInfo("Europe/Berlin"))

    for entry in spool_db:
        slot = entry['usage']['slot']
        if slot is None:
            print(f"[refill_spools] Spule {entry['id']} hat keinen Slot – übersprungen")
            continue

        used_mm = last_usage.get(slot, 0.0)
        if used_mm < 1:
            print(f"[refill_spools] Slot {slot} hat nur {used_mm}mm – ignoriert")
            continue

        used_g = mm_to_g(used_mm, densities[slot] if isinstance(densities, list) else densities)
        old = entry['data']['remaining_g']
        new_value = max(0.0, old - used_g)

        print(f"[refill_spools] Spule {entry['id']} – Slot {slot}")
        print(f"    Verbrauch: {used_mm} mm → {used_g:.2f} g")
        print(f"    Vorher: {old:.2f} g → Nachher: {new_value:.2f} g")

        entry['data']['remaining_g'] = new_value

        if entry['data']['first_used'] is None:
            entry['data']['first_used'] = now.strftime('%Y-%m-%dT%H:%M%z')
        entry['data']['last_used'] = now.strftime('%Y-%m-%dT%H:%M%z')

    save_spool_db(spool_db)
    print("[refill_spools] Speicherung abgeschlossen")
    return spool_db
    
def log_print_history(filename, usage, densities, slotmap):
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    record = {
        "timestamp": now.strftime('%Y-%m-%dT%H:%M%z'),
        "file": filename,
        "progress": settings.tool_progress,
        "status": settings.tool_state,
        "spools": {}
    }

    print(f"\n[log_print_history] Datei: {filename}")
    print(f"[log_print_history] Status: {settings.tool_state}, Fortschritt: {settings.tool_progress}%")
    print(f"[log_print_history] Usage (mm): {usage}")

    for slot, used_mm in usage.items():
        used_g = mm_to_g(used_mm, densities[slot] if isinstance(densities, list) else densities)
        print(f"[log_print_history] Slot {slot} → {used_mm} mm = {used_g:.2f} g")

        for spool in spool_db:
            if spool["usage"]["slot"] == slot:
                record["spools"][spool["id"]] = round(used_g, 2)
                print(f"  → zugewiesen an Spule {spool['id']}")

    try:
        with open('data/print_history.json', 'r') as f:
            data = json.load(f)
        print("[log_print_history] Bestehende Historie geladen")
    except FileNotFoundError:
        data = []
        print("[log_print_history] Keine bestehende Historie – neue Datei wird erstellt")

    data.append(record)
    with open('data/print_history.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[log_print_history] Historie aktualisiert\n")

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
        "data": { "remaining_g": INITIAL_WEIGHT_G, "tare_weight_g": TARE_WEIGHT_G, "first_used": None, "last_used": None },
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
    elif field == 'tare_weight_g':
        try:
            target_spool['data']['tare_weight_g'] = float(value)
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
        # Prognose nur bei aktivem Druck sinnvoll
        if not settings.tool_state == "PRINTING" or settings.tool_live in ('file', 'blocked'):
            return jsonify({})

        if not settings.slicing_g:
            print("⚠️  Keine Prognose möglich – keine Slicer-Metadaten gefunden.")
            return jsonify({})

        # Prüfen, ob Live-Daten verfügbar sind
        used_available = settings.tool_live == 'live'
        if used_available and usage_history:
            last_progress, usage = usage_history[-1]

        slicing_g = settings.slicing_g  # Verbrauch laut Slicer (g)

        prognosis = {}

        if settings.tool_mmu:
            # MMU-Fall: Prognose pro Slot (0–4)
            for slot in range(len(slicing_g)):
                total_g = slicing_g[slot] if slot < len(slicing_g) else 0.0
                # Verbrauch bisher berechnen
                if used_available:
                    used_g = sum(
                        mm_to_g(u, settings.densities[slot])
                        for p, u_dict in usage_history
                        for s, u in u_dict.items()
                        if s == slot
                    )
                    rest_g = max(0.0, total_g - used_g)

                # Prognose berechnen für belegte Spule an diesem Slot
                for spool in spool_db:
                    if spool["usage"]["slot"] == slot:
                        actual = spool["data"]["remaining_g"]
                        # Prognose = aktueller Rest - geplanter Gesamtverbrauch
                        prognosis[slot] = actual - total_g
        else:
            # Kein MMU: nur ein Werkzeug aktiv → Slot 5 ("non-mmu" im Frontend)
            total_g = slicing_g if isinstance(slicing_g, float) else sum(slicing_g)

            # optional: bisher verbraucht (nicht zwingend verwendet)
            if used_available:
                used_g = sum(mm_to_g(u, settings.densities)
                             for _, u_dict in usage_history
                             for u in u_dict.values())
                rest_g = max(0.0, total_g - used_g)

            # Spule mit Slot 5 suchen (non-mmu)
            non_mmu_spool = next((s for s in spool_db if s["usage"]["slot"] == 5), None)
            if non_mmu_spool:
                actual = non_mmu_spool["data"]["remaining_g"]
                prognosis[5] = actual - total_g

        return jsonify(prognosis)

    except Exception as e:
        print("❌ Fehler in /prognosis:", e)
        return jsonify({})
        
def main():
    global usage_history
    init_spools()
    pm = None
    # Starte Webserver im Hintergrund
    threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':WEB_PORT}, daemon=False).start()
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
            #run_looping = False
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
        try:
            if settings.tool_mmu:
              tool_range = range(settings.tool_count_mmu)
              for t in range(settings.tool_count_mmu):
                calc_g=mm_to_g(usage.get(t,0.0),settings.densities[t]); sl_g=settings.slicing_g[t] if t<len(settings.slicing_g) else 0.0
                print(f" T{t}: berechnet {calc_g:.1f}g vs slicer {sl_g:.1f}g diff {calc_g-sl_g:+.1f}g")
                calc_m=usage.get(t,0.0); sl_m=slicing_m[t] #if t<len(slicing_m) else 0.0
                print(f" T{t}: berechnet {calc_m:.1f}mm vs slicer {sl_m:.1f}mm diff {calc_m-sl_m:+.1f}mm")
            else:
                calc_g=mm_to_g((list(usage.values())[-1]),settings.densities); sl_g=settings.slicing_g
                print(f" T{settings.tool_count}: berechnet {calc_g:.1f}g vs slicer {sl_g:.1f}g diff {calc_g-sl_g:+.1f}g")
                calc_m=(list(usage.values())[-1]); sl_m=slicing_m
                print(f" T{settings.tool_count}: berechnet {calc_m:.1f}mm vs slicer {sl_m:.1f}mm diff {calc_m-sl_m:+.1f}mm")
        except Exception as e:
                print("❌ error in Main final:", e)    
        
        #if ((settings.tool_state in ('FINISHED')) or (progress >= 100) or (not  doSync)) and settings.prusa_usage: # Extrude purge line is not included in Prusa Slicer Concumptions. Dont use this for the moment 
        #  print(f"Printer is {progress} and marked as {settings.tool_state}. Not synchronise anymore")  
        #  usage_history = add_slicer_to_usage(usage_history, slicing_m, densities)
        #  print(f"finally add slicer values {usage_history}")
        old_job_progressed = settings.tool_job
        print(f"[main {datetime.now().strftime('%H:%M:%S')} ] DO REFILL")
        refill_spools(usage_history, settings.densities)
        print(f"[main {datetime.now().strftime('%H:%M:%S')} ]  DO LOGS")
        log_print_history(filename, usage, settings.densities, [s["usage"]["slot"] for s in spool_db])
        usage_history = []
        print(f"[main {datetime.now().strftime('%H:%M:%S')} ]  usage_history geleert")
        settings.noti = "CleanUp"
        print(f"[main {datetime.now().strftime('%H:%M:%S')} ] CLEAN UP")
        if settings.tool_job is not None or old_job_progressed == settings.tool_job:
          print(f"[main {datetime.now().strftime('%H:%M:%S')} ] WAIT MORE TO CLEAN UP")
          time.sleep(10)
        if settings.tool_job is not None or old_job_progressed == settings.tool_job:
          print(f"[main {datetime.now().strftime('%H:%M:%S')} ] WAIT EVEN MORE TO CLEAN UP")
          time.sleep(25)
        settings.noti = ""
        print(f"[main {datetime.now().strftime('%H:%M:%S')} ] Resume Monitoring. Old Job: {old_job_progressed}. New Job: {settings.tool_job}")
        

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
