import subprocess, os, sys

installer = r"C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe"

# Try multiple approaches to launch
print(f"Launching: {installer}")
print(f"File exists: {os.path.exists(installer)}")
print(f"File size: {os.path.getsize(installer)}")

# Method 1: direct subprocess
try:
    r = subprocess.Popen([installer], shell=True)
    print(f"Popen launched, pid={r.pid}")
except Exception as e:
    print(f"Popen error: {e}")

# Method 2: os.startfile
try:
    os.startfile(installer)
    print("startfile launched")
except Exception as e:
    print(f"startfile error: {e}")
