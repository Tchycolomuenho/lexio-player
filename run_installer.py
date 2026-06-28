import subprocess, time, os

installer = r"C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe"

# Method 1: PowerShell Start-Process with RunAs
cmd = f'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "Start-Process -FilePath \'{installer}\' -Verb RunAs -Wait"'
print(f"Running: {cmd[:80]}...")
r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
print(f"RC: {r.returncode}")
print(f"stdout: {r.stdout[:500]}")
print(f"stderr: {r.stderr[:500]}")
print("DONE")
