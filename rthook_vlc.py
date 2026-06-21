# PyInstaller runtime hook — corre ANTES de `import vlc`.
# No Windows o libVLC encontra os plugins ao lado do .exe sozinho; em macOS e
# Linux o python-vlc carrega o libvlc por ctypes e o libVLC precisa que lhe
# digam onde estão os plugins (VLC_PLUGIN_PATH) e onde está a própria lib.
import os
import sys

# Base do bundle: one-dir → pasta da app; one-file → _MEIPASS.
_base = getattr(sys, "_MEIPASS", None)
if not _base:
    _base = os.path.dirname(sys.executable)

# Os plugins do VLC são empacotados na pasta 'plugins' (Tree(prefix='plugins')).
for _cand in (
    os.path.join(_base, "plugins"),
    os.path.join(_base, "_internal", "plugins"),
):
    if os.path.isdir(_cand):
        os.environ.setdefault("VLC_PLUGIN_PATH", _cand)
        break

# Garante que o loader dinâmico encontra libvlc/libvlccore empacotados.
if sys.platform == "darwin":
    os.environ["DYLD_LIBRARY_PATH"] = (
        _base + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
    )
elif sys.platform.startswith("linux"):
    os.environ["LD_LIBRARY_PATH"] = (
        _base + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
    )
