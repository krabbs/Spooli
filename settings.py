from requests.auth import HTTPDigestAuth
from datetime import datetime
def init(pw, ip):
    global tool_progress, tool_state, tool_job, tool_live, tool_mmu, tool_count,tool_count_mmu, USERNAME, PASSWORD, PRUSA_IP, API_URL, FILES_URL, AUTH, prusa_usage, noti, densities, slicing_g,reboot, reboot_analzye
    print(f"[INIT {datetime.now().strftime('%H:%M:%S')} ] SETTINGS INIT")
    tool_progress = None
    tool_state = "unknown"   # PRINTING, PAUSED, etc.
    tool_job = None # file
    tool_live = "no"
    tool_mmu = False
    tool_count = 6
    tool_count_mmu = 5
    
    noti = "Starting"
    prusa_usage = False
    
    USERNAME = "maker"
    PASSWORD = pw 
    PRUSA_IP = ip 
    API_URL = f"http://{PRUSA_IP}/api/v1"
    FILES_URL = f"http://{PRUSA_IP}/usb"
    AUTH = HTTPDigestAuth(USERNAME, PASSWORD)
    
    densities = []          # wird in main() gesetzt
    slicing_g = []          # aus G-Code-Metadaten
    
    reboot = False
    reboot_analzye = False