#!/usr/bin/env python3
"""
Skript zur Live-Analyse des Filamentverbrauchs beim Druck auf einem Prusa MK4 mit MMU3.

Features:
- Ohne Argument: Download des aktuellen Druckjobs (.bgcode/.gcode) von Prusa-Link API (wartet, bis G-Code verfügbar ist)
- Mit Argument: Verwendung lokaler Datei
- Automatische Konvertierung von .bgcode → .gcode via CLI-Tool 'bgcode'
- Einlesen von Metadaten aus dem G-Code-Header:
  - filament_density (Liste für Tools 0–5)
  - filament_stamping_distance (Liste für Tools 0–5)
  - filament used [g] (Liste für Tools 0–5)
- Hintergrund-Thread zur Abfrage von Status/Job-API:
  - Wartet auf Zustand 'PRINTING' oder 'PAUSED'
  - Pflegt `tool_progress` und aktuelles Tool
- Download-Thread startet parallel zum Monitoring und wartet bei Sperre
- Segmentweises Parsen des G-Codes gemäß aktuellem Fortschritt:
  - Extrusion (E-Werte) summieren
  - Stamping-Distance bei Werkzeugwechsel
- Unterstützung für Tools 0–4 (MMU3) und Tool 5 (Direktdruck)
- Live-Ausgabe und Speicherung in usage_history für Visualisierung
- Beim Druckende (>=100%): Vergleich berechneter vs. slicer-basierter Verbrauchswerte
"""
import os
import re
import sys
import time
import threading
import tempfile
import subprocess
import requests
from collections import defaultdict
from requests.auth import HTTPDigestAuth
from pygcode import Line
import settings

# ----- Konfiguration -----

POLL_INTERVAL = 5    # Sekunden
settings.tool_count = 5       # Tools 0–4: MMU3, Tool 5: Direktdruck

# Globale Zustände

stop_event = threading.Event()
# usage_history = []

# ----- API-Funktionen -----

def get_current_status():
    try:
        r = requests.get(f"{settings.API_URL}/status", auth=settings.AUTH, timeout=5)
        r.raise_for_status()
        return r.json() if r.status_code != 204 else None
    except requests.RequestException:
        return None


def get_current_job():
    try:
        r = requests.get(f"{settings.API_URL}/job", auth=settings.AUTH, timeout=5)
        r.raise_for_status()
        return r.json() if r.status_code != 204 else None
    except requests.RequestException:
        return None

# ----- Download-Thread -----

def ProgressMonitor_thread_fn():
    global stop_event
    tool_state_old = "unk"
    tool_job_old = None
    tool_progress_old = None
    while not stop_event.is_set(): 
        status = get_current_status()
        if status is not None:
            settings.tool_state = status['printer'].get('state') #status.get('printer').get('state')
            #settings.tool_state = state
        else:
        	settings.tool_state = "unknown"
        if not settings.tool_state in tool_state_old:
              print (f"PRINTER STATE : {settings.tool_state}")
              tool_state_old = settings.tool_state
        job = get_current_job()
        if job and 'progress' in job:
            comp = job.get('progress')#.get('completion')
            if comp is not None:
                if (settings.tool_progress is not None):
                    if (comp < settings.tool_progress) and settings.tool_progress is not None:
                      print(f"!!!!!!!!!Progress failure!!!!!!!!!") #MAYBE SET FLAG AND HANDLE THIS LATER
                      settings.reboot_analzye = True
                      break
                settings.tool_progress = comp
                if (settings.tool_job != job['file']['display_name']) and (settings.tool_job is not None):
                  print(f"!!!!!!!!!!Job failure!!!!!!!!") #MAYBE SET FLAG AND HANDLE THIS LATER
                  settings.reboot_analzye = True
                  break
                settings.tool_job = job['file']['display_name']    
                if tool_progress_old != settings.tool_progress:
                  print(f"PRINTER PROGRESS WATCH: {settings.tool_progress:.1f}%. State: {settings.tool_state}. File {settings.tool_job}")
                  tool_progress_old = settings.tool_progress
        else:
        	settings.tool_job = None
        time.sleep(POLL_INTERVAL)

def download_thread_fn(filename, dest):
    global stop_event
    """Versucht Download, wartet bei Sperre bis Datei verfügbar."""
    url = f"{settings.FILES_URL}/{filename}"
    print(f"⤵️ Starte Download-Thread für {url}")
    blocked_noti_flag = True
    while not stop_event.is_set():
        try:
            r = requests.get(url, auth=settings.AUTH, timeout=10)
            if r.status_code == 404:
                # Datei gesperrt, Druck läuft
                settings.tool_live = 'blocked'
                if blocked_noti_flag:
                  print("Datei gesperrt, warte... (Druckstatus: %s)" % (settings.tool_state))
                  settings.noti = " Datei gesperrt, warte..." 
                  blocked_noti_flag = False
            else:
                r.raise_for_status()
                with open(dest, 'wb') as f:
                    f.write(r.content)
                print("Download erfolgreich")
                if settings.noti == " Datei gesperrt, warte...": settings.noti = ""  
                if not settings.tool_live in ('file', 'blocked'): settings.tool_live = 'live'
                return
        except requests.RequestException as e:
            print(f"Download-Fehler: {e}")
            settings.tool_live = 'error'
        time.sleep(POLL_INTERVAL)

# ----- G-Code Vorbereitung -----

def convert_bgcode(path):
    out = os.path.splitext(path)[0] + '.gcode'
    print(f"Konvertiere {path} → {out}")
    subprocess.run(['bgcode', path, out], check=True)
    return out


def prepare_gcode(input_path, filename, use_download):
    #global settings.tool_state
    tmp = tempfile.gettempdir()
    dest = os.path.join(tmp, filename)
    if use_download:
        # Download in eigenem Thread starten
        dt = threading.Thread(target=download_thread_fn, args=(filename, dest), daemon=True)
        dt.start()
        # Warte bis Zustand PRINTING, dann fortlaufend
        if settings.tool_state not in ('PRINTING', 'PAUSED'):  print(f"⏳ Warte auf Druckstart... aktueller Zustand: {settings.tool_state}",end="")
        while (settings.tool_state not in ('PRINTING', 'PAUSED')) and (settings.tool_live not in ('file')): # and not stop_event.is_set():
            #print(f"Warte auf Druckstart... aktueller Zustand: {settings.tool_state}",end="")
            print(".", end="")
            time.sleep(POLL_INTERVAL)
        # Warte auf Abschluss des Download-Threads
        dt.join()
    else:
        subprocess.run(['cp', input_path, dest], check=True)
    ext = os.path.splitext(dest)[1].lower()
    return convert_bgcode(dest) if ext == '.bgcode' else dest

# ----- Metadaten einlesen -----

def parse_gcode_metadata(filepath):
    metadata = {}
    print(filepath)
    with open(filepath, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line.startswith(";"):
                match = re.match(r";\s*(.+?)\s*=\s*(.+)", line)
                if match:
                    key, value = match.groups()

                    if ',' in value:
                        try:
                            values = [float(x.strip()) for x in value.split(',')]
                            metadata[key] = values
                        except ValueError:
                            metadata[key] = value.strip()
                    else:
                        try:
                            if '.' in value:
                                metadata[key] = float(value)
                            else:
                                metadata[key] = int(value)
                        except ValueError:
                            metadata[key] = value.strip()
    return metadata

# ----- Umrechnung mm → g -----

def mm_to_g(mm, density, dia=1.75):
    r = dia/2; vol = mm*3.14159*r*r/1000
    return vol*density
    
# ----- Live-Analyse -----

def live_analyze_gen(path, slicer, densities, stamping, sync=True):
    #global usage_history, tool_progress
    lines = open(path, encoding='utf-8', errors='ignore').readlines()
    total = len([l for l in lines if l.strip() and not l.startswith(';')])
    total = len(lines)
    idx = 0; usage = defaultdict(float)
    first_tool_change = True
    prog = 0
    if settings.tool_mmu == False:
      cur_tool=5
    else:
      cur_tool=0
    
    if not sync: 
      prog = 0
      print(f"Start  view {prog} Lines: {total}")
      settings.noti="Analyse Offline"
    else:
      print(f"Start Live view {settings.tool_live} Lines: {total}")
      settings.noti="Analyse Online"
    settings.reboot = False
    settings.reboot_analzye = False
    while not settings.reboot and not settings.reboot_analzye: # not stop_event.is_set():
        if (prog == settings.tool_progress) or (settings.tool_progress is None): print(f"wait for progress printer is {settings.tool_state}")
        while ((prog == settings.tool_progress) or (settings.tool_progress is None)) and sync:
          time.sleep(POLL_INTERVAL)
          if settings.noti=="Analyse Offline" or settings.noti=="Analyse Online": settings.noti=""
          print('.', end="")
          #print(f"wait for progress printer is {settings.tool_state}")
          if (settings.tool_state in ('CANCELLED', 'ERROR', 'FINISHED', 'STOPPED','unknown')) or (not sync): break
        if sync:
          #print("SYNC SET ON")
          prog = settings.tool_progress
          target = int(total*prog/100)
        else:
          #print("SYNC SET OFF")
          prog += 1
          target = int(total*prog/100)# total
        
        if target>idx:
            print(f"Line {idx} -> {target}")
            segment = lines[idx:target]
            for raw in segment:
                s=raw.strip()
                if not s or s.startswith(';') or s.startswith('M'): continue
                try: ln=Line(raw)
                except: continue
                fw=ln.block.words[0] if ln.block.words else None
                if fw and fw.letter=='T':
                    print(f"Tool change \n {raw}")
                    if not first_tool_change: 
                      #no real tool change but mmu is active 
                      if settings.tool_mmu == False:
                        print("ERROR MMU RECOGNIZED BUT THERE SHOULD BE NONE!")
                      usage[cur_tool]+=stamping[cur_tool]
                    first_tool_change = False
                    cur_tool=int(fw.value)
                for w in ln.block.words:
                    if w.letter=='E':
                        #print(ln) DEBUG: FOUND ; Extrude purge line is not included in Prusa Slicer Concumptions. 
                        if ((float(w.value)>0) or float(w.value)<0) and (usage[cur_tool]+float(w.value)>0): usage[cur_tool]+=float(w.value)
                        break
                if cur_tool in usage and usage[cur_tool] < 0: usage[cur_tool]=0
            idx=target#+1
        #usage_history.append((prog,dict(usage)))
        yield prog, dict(usage)
        print(f"Fortschritt calc: {prog:.1f}%")
        for t,mm in usage.items(): 
          #print(f" T{t}: {mm:.1f}mm(~{mm_to_g(mm,densities[t]):.1f}g)")
          print(f" T{t}: {mm:.1f}mm")
        #if not sync: break
        if prog>=100: 
          print("\n SYNC BREAK IN LOOP 100P")
          #usage_history = add_slicer_to_usage(usage_history, slicer, densities)
          break
        #time.sleep(POLL_INTERVAL)
    print("\n SYNC BREAK out of looP")
    if settings.noti=="Analyse Offline" or settings.noti=="Analyse Online": settings.noti=""
    #print("\nDruck beendet. Vergleich:")
    #for t in range(settings.tool_count):
    #    calc=mm_to_g(usage.get(t,0.0),densities[t]); sl=slicer[t] if t<len(slicer) else 0.0
    #    print(f" T{t}: berechnet {calc:.1f}g vs slicer {sl:.1f}g diff {calc-sl:+.1f}g")
    #return prog, dict(usage)
    
def add_slicer_to_usage(usage_history, slicer, densities):
  usage = defaultdict(float)
  for t in range(settings.tool_count):
    usage[t]+=float(slicer[t])
    #usage[t]=float(slicer[t])
    print(f" T{t}: from slicer added {usage[t]} to end")
  usage_history.append((100 ,dict(usage)))
  return usage_history
  
def init_wait_for_job():
    #global settings.tool_state
    job=get_current_job();
  
    if not job or 'file' not in job:
      wait_for_job = True
      msgflag = True
      while wait_for_job:
        status_api = get_current_status()
        if not status_api:
          machine_state='offline'
          time.sleep(POLL_INTERVAL)
        else:
          machine_state=status_api.get('printer').get('state')
          time.sleep(POLL_INTERVAL)
          job=get_current_job();
          if not job or 'file' not in job:
            wait_for_job = True
          else:
            wait_for_job = False
          if msgflag:
            print(f"Kein Job {machine_state}"); 
            msgflag = False
          else:
          	print('.', end='')
    return job
