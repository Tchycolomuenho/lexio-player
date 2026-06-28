import subprocess, os, time, sys

installer = r"C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe"
logfile = r"C:\Users\tchic\lexio-player\installer\silent_log2.txt"

# Remove old log
if os.path.exists(logfile):
    os.remove(logfile)

# Launch via startfile (runs with default verb, typically shows UAC)
print(f"Launching via startfile: {installer}")
os.startfile(installer)
print("Launched!")
