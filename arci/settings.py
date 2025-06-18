def init():
    global tool_progress, tool_state, tool_job, tool_live
    tool_progress = None
    tool_state = "unknown"   # PRINTING, PAUSED, etc.
    tool_job = None # file
    tool_live = "no"
    tool_mmu = False
    tool_count = 5
