# -*- mode: python ; coding: utf-8 -*-
# Self-contained build: bundles VLC (libvlc + libvlccore + plugins) so the user
# needs NOTHING else installed. One-DIR layout (COLLECT) — faster startup than
# one-file (no 150 MB re-extraction to %TEMP% on every launch).
#
# Multi-plataforma: Windows (.dll), macOS (.dylib em /Applications/VLC.app) e
# Linux (.so do pacote vlc do sistema). Override dos caminhos com LEXIO_VLC_DIR.
import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

PLAT = sys.platform  # 'win32' | 'darwin' | 'linux'

# Pronúncia natural: edge-tts (voz neural Microsoft) + as suas deps async.
# Import preguiçoso no código → garantir que o PyInstaller os empacota à mão.
_tts_hidden = (collect_submodules('edge_tts')
               + ['aiohttp', 'certifi', 'multidict', 'yarl', 'frozenlist',
                  'aiosignal', 'attr', 'attrs', 'async_timeout'])
_tts_datas = collect_data_files('edge_tts') + collect_data_files('certifi')


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


# ─── Localizar o VLC a empacotar, por plataforma ───
if PLAT == 'win32':
    VLC_DIR = os.environ.get("LEXIO_VLC_DIR", r"C:\Program Files\VideoLAN\VLC")
    _libvlc     = os.path.join(VLC_DIR, "libvlc.dll")
    _libvlccore = os.path.join(VLC_DIR, "libvlccore.dll")
    _plugins    = os.path.join(VLC_DIR, "plugins")
    _icon       = 'icon.ico'
elif PLAT == 'darwin':
    VLC_DIR = os.environ.get("LEXIO_VLC_DIR", "/Applications/VLC.app/Contents/MacOS")
    _libvlc     = _first_existing(os.path.join(VLC_DIR, "lib", "libvlc.dylib"),
                                  os.path.join(VLC_DIR, "lib", "libvlc.5.dylib"))
    _libvlccore = _first_existing(os.path.join(VLC_DIR, "lib", "libvlccore.dylib"),
                                  os.path.join(VLC_DIR, "lib", "libvlccore.9.dylib"))
    _plugins    = os.path.join(VLC_DIR, "plugins")
    _icon       = _first_existing('icon.icns')
else:  # linux
    VLC_DIR = os.environ.get("LEXIO_VLC_DIR", "/usr/lib/x86_64-linux-gnu")
    _libvlc     = _first_existing(os.path.join(VLC_DIR, "libvlc.so.5"),
                                  os.path.join(VLC_DIR, "libvlc.so"))
    _libvlccore = _first_existing(os.path.join(VLC_DIR, "libvlccore.so.9"),
                                  os.path.join(VLC_DIR, "libvlccore.so"))
    _plugins    = _first_existing(os.path.join(VLC_DIR, "vlc", "plugins"),
                                  "/usr/lib/x86_64-linux-gnu/vlc/plugins",
                                  "/usr/lib/vlc/plugins")
    _icon       = None

for _need in (_libvlc, _libvlccore, _plugins):
    if not _need or not os.path.exists(_need):
        raise SystemExit(
            f"\n[LexioStudyPlayer.spec] VLC não encontrado em '{VLC_DIR}'.\n"
            f"Instala o VLC 64-bit (win: choco install vlc · mac: brew install --cask vlc · "
            f"linux: apt install vlc libvlc-dev) ou define LEXIO_VLC_DIR.\n"
            f"Em falta: {_need}\n")

_datas = [
    ('icon.png', '.'),
    ('fonts/Inter.ttf', 'fonts'),
] + _tts_datas
if os.path.exists('icon.ico'):
    _datas.append(('icon.ico', '.'))
# Traduções de UI pré-geradas (todas as línguas oferecidas) — offline, no instalador.
if os.path.isdir('i18n-bundled'):
    import glob as _glob
    for _f in _glob.glob(os.path.join('i18n-bundled', 'ui_*.json')):
        _datas.append((_f, 'i18n-bundled'))

a = Analysis(
    ['lexio_player.py'],
    pathex=[],
    binaries=[
        (_libvlc, '.'),
        (_libvlccore, '.'),
    ],
    datas=_datas,
    hiddenimports=['vlc', 'i18n'] + _tts_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_vlc.py'],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'numpy', 'pandas',
        'PIL', 'cv2', 'cryptography', 'lxml', 'zmq', 'pygments'
    ],
    noarchive=False,
    optimize=0,
)

# A árvore de plugins do VLC (~130 MB) — o VLC procura-a em runtime via
# VLC_PLUGIN_PATH (definido no rthook), por isso vai como data files.
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
    icon=_icon,
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

# macOS: empacota o one-dir num .app (necessário para abrir como app gráfica
# e para gerar o .dmg). Gatekeeper avisará por não estar assinado/notarizado.
if PLAT == 'darwin':
    app = BUNDLE(
        coll,
        name='Lexio Study Player.app',
        icon=_icon,
        bundle_identifier='com.lexio.studyplayer',
        info_plist={
            'CFBundleName': 'Lexio Study Player',
            'CFBundleDisplayName': 'Lexio Study Player',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
        },
    )
