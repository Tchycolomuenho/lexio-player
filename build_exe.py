import subprocess, os

workdir = r"C:\Users\tchic\lexio-player"
spec_path = r"C:\Users\tchic\lexio-player\LexioStudyPlayer.spec"
py = r"C:\Python314\python.exe"

cmd = [py, "-m", "PyInstaller", spec_path, "--noconfirm", "--clean"]
result = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=300)
print("EXIT:", result.returncode)
print("DONE" if result.returncode == 0 else "FAILED")
