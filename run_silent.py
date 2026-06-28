import subprocess, os

installer = r"C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe"
logfile = r"C:\Users\tchic\lexio-player\installer\silent_log.txt"

# Run silently with log
r = subprocess.run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", f"/LOG={logfile}"], 
                   capture_output=True, text=True, timeout=60)
print(f"RC: {r.returncode}")
print(f"stdout: {r.stdout}")
print(f"stderr: {r.stderr}")

if os.path.exists(logfile):
    with open(logfile) as f:
        print("LOG:")
        print(f.read()[:2000])
else:
    print("NO LOG FILE")
