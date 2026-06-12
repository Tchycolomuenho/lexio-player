# -*- mode: python ; coding: utf-8 -*-
# Self-contained build: bundles VLC (libvlc + libvlccore + plugins) so the user
# needs NOTHING else installed. One-DIR layout (COLLECT) — faster startup than
# one-file (no 150 MB re-extraction to %TEMP% on every launch).
import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Pronúncia natural: edge-tts (voz neural Microsoft) + as suas deps async.
# Import preguiçoso no código → garantir que o PyInstaller os empacota à mão.
_tts_hidden = (collect_submodules('edge_tts')
               + ['aiohttp', 'certifi', 'multidict', 'yarl', 'frozenlist',
                  'aiosignal', 'attr', 'attrs', 'async_timeout'])
_tts_datas = collect_data_files('edge_tts') + collect_data_files('certifi')

# VLC to bundle. Override with LEXIO_VLC_DIR if installed elsewhere (e.g. CI).
VLC_DIR = os.environ.get("LEXIO_VLC_DIR", r"C:\Program Files\VideoLAN\VLC")
_libvlc     = os.path.join(VLC_DIR, "libvlc.dll")
_libvlccore = os.path.join(VLC_DIR, "libvlccore.dll")
_plugins    = os.path.join(VLC_DIR, "plugins")
for _need in (_libvlc, _libvlccore, _plugins):
    if not os.path.exists(_need):
        raise SystemExit(
            f"\n[LexioStudyPlayer.spec] VLC not found: {_need}\n"
            f"Install the 64-bit VLC (choco install vlc) or set LEXIO_VLC_DIR.\n")

a = Analysis(
    ['lexio_player.py'],
    pathex=[],
    binaries=[
        (_libvlc, '.'),
        (_libvlccore, '.'),
    ],
    datas=[
        ('icon.ico', '.'),
        ('icon.png', '.'),
        ('fonts/Inter.ttf', 'fonts'),
    ] + _tts_datas,
    hiddenimports=['vlc', 'i18n'] + _tts_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'numpy', 'pandas',
        'PIL', 'cv2', 'cryptography', 'lxml', 'zmq', 'pygments'
    ],
    noarchive=False,
    optimize=0,
)

# The VLC plugins tree (~130 MB) — VLC scans this folder at runtime via
# VLC_PLUGIN_PATH, so it ships as data files (not Python imports).
a.datas += Tree(_plugins, prefix='plugins')

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # one-dir: keep binaries/datas beside the exe
    name='LexioStudyPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX is slow on 360+ plugin DLLs and can break them
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LexioStudyPlayer',
)
