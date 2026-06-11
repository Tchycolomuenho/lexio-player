#!/usr/bin/env python3
"""
Lexio Study Player v3.1 — VLC embutido + Vocab Overlay + Chat IA
"""
import os, sys, json, webbrowser, subprocess, threading, re, traceback, time
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

LOG = Path.home() / '.lexio-player' / 'debug.log'
LOG.parent.mkdir(exist_ok=True)

def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except: pass

log("=== LEXIO PLAYER v3.1 === (pyinstaller-friendly)")

# ── VLC path — search more locations ──
_VLC_PATH = None
for _p in [
    r"C:\Program Files\VideoLAN\VLC",
    r"C:\Program Files (x86)\VideoLAN\VLC",
    str(Path.home() / "AppData" / "Local" / "Programs" / "VLC"),
]:
    dll = os.path.join(_p, "libvlc.dll")
    if os.path.exists(dll):
        _VLC_PATH = _p
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
        os.environ["VLC_PLUGIN_PATH"] = os.path.join(_p, "plugins")
        # Try multiple methods to register DLL path
        try: os.add_dll_directory(_p)
        except: pass
        try:
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(_p)
        except: pass
        log(f"VLC found: {_p}")
        break
if not _VLC_PATH:
    log("VLC NOT FOUND")
    log(f"PATH={os.environ.get('PATH','')[:200]}")
    # Try winget paths too
    for _p in [str(Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links")]:
        dll = os.path.join(_p, "libvlc.dll")
        if os.path.exists(dll):
            _VLC_PATH = _p
            os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
            log(f"VLC found (winget): {_p}")
            break

# ── Imports with early error display ──
try:
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QRect, QPoint, QUrl, QEvent, QFileInfo
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QIcon, QCursor, QRadialGradient, QLinearGradient, QFontMetrics, QFontInfo
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QFileDialog, QListWidget, QListWidgetItem,
        QMenu, QMessageBox, QTextEdit, QLineEdit,
        QTabWidget, QStatusBar, QScrollArea, QSizePolicy, QDialog,
        QGraphicsOpacityEffect, QStyle, QStyleOptionSlider, QFileIconProvider, QComboBox
    )
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage
    from PyQt5.QtWebChannel import QWebChannel
    import vlc
    log(f"vlc OK, python-vlc: {getattr(vlc, '__version__', '?')}")
except Exception as e:
    err = f"IMPORT FAILED: {e}\n{traceback.format_exc()}"
    log(err)
    # Try to show a message box even before app exists
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        _qa = QApplication(sys.argv)
        mb = QMessageBox()
        mb.setIcon(QMessageBox.Critical)
        mb.setWindowTitle("Lexio Player - Erro de importação")
        mb.setText(f"Falhou ao carregar o VLC:\n{e}")
        mb.setDetailedText(traceback.format_exc())
        mb.exec_()
    except:
        input(f"\n*** ERRO: {e}\nPrima Enter para sair...")
    raise

# ── Theme (Premium monochrome — true black, white accent, no colour) ──
BG = "#000000"       # true black stage
SRF = "#0a0a0a"      # panels / chrome
ELV = "#161616"      # elevated surfaces (cards, inputs, bubbles)
HVR = "#222222"      # hover
BRD = "#2a2a2a"      # borders / dividers
TXT = "#fafafa"      # primary text
TS2 = "#ffffff"      # strong text (subtitles)
TMT = "#8a8a8a"      # muted secondary text
ACC = "#ffffff"      # white accent (controls)
ACC_HOVER = "#cfcfcf"  # dimmer white on hover
ON_ACC = "#000000"   # text/icon ON white accent

APP_NAME = "Lexio Study Player"
APP_VERSION = "3.1.0"
DATA_DIR = Path.home() / '.lexio-player'; DATA_DIR.mkdir(exist_ok=True)
RECENT_FILE = DATA_DIR / 'recent.json'
STUDY_FILE = DATA_DIR / 'study-data.json'
TOKEN_FILE = DATA_DIR / 'auth-token.json'

SUPPORTED_VID = {'.mp4','.avi','.mkv','.mov','.wmv','.flv','.webm','.m4v','.mpg','.mpeg','.3gp','.ogv','.ts','.mts'}
SUPPORTED_AUD = {'.mp3','.wav','.flac','.ogg','.m4a','.aac','.wma'}
SUPPORTED = SUPPORTED_VID | SUPPORTED_AUD

LEXIO_API = "https://lexio-app-five.vercel.app"
SUPABASE_URL = "https://lobwdstwpcbuljferyyo.supabase.co"
SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxvYndkc3R3cGNidWxqZmVyeXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3NDI5MTIsImV4cCI6MjA5NTMxODkxMn0.GvJRLDE6yLhgDQUq-ckjgRZWbpvS4eKsUZglNyBsjSA"

# ── i18n: UI traduzida; a língua é ESCOLHIDA pelo utilizador no player e fica
# guardada localmente. Conteúdo (dicionário/chat) herda a língua nativa da conta.
import i18n
from i18n import T, set_lang, set_native, native_language_name

i18n.set_cache_dir(str(DATA_DIR / 'i18n-cache'))   # traduções IA on-demand ficam aqui
_UI_LANG_FILE = DATA_DIR / 'ui-lang.txt'

def load_ui_lang():
    """Língua da UI: a escolhida pelo utilizador (ficheiro), senão a do SO, senão EN."""
    try:
        if _UI_LANG_FILE.exists():
            code = _UI_LANG_FILE.read_text(encoding='utf-8').strip()
            if code:
                return code
    except Exception:
        pass
    try:
        import locale
        loc = (locale.getdefaultlocale()[0] or "").split("_")[0].lower()
        if loc:
            return loc
    except Exception:
        pass
    return "en"

def save_ui_lang(code):
    try:
        _UI_LANG_FILE.write_text(str(code), encoding='utf-8')
    except Exception as e:
        log(f"save ui lang: {e}")

def translate_ui_via_ai(code):
    """Traduz TODAS as strings da UI para `code` via IA (deepseek) e guarda em
    cache, para o player suportar qualquer língua. Devolve True se conseguiu."""
    try:
        lang_en = i18n.language_en_name(code)
        base = i18n.base_strings()
        sys_p = (
            "You are a professional software UI translator. You receive a JSON object "
            f"of UI strings. Translate every VALUE into {lang_en}. Keep every KEY exactly "
            "as-is. Preserve placeholders such as {where}, {text}, {err} verbatim. Keep "
            "translations short (these are buttons, labels, tooltips). Reply with ONLY the "
            "translated JSON object — no markdown, no prose.")
        body = json.dumps({"model": "deepseek-chat", "max_tokens": 4000, "temperature": 0.1,
            "messages": [{"role": "system", "content": sys_p},
                         {"role": "user", "content": json.dumps(base, ensure_ascii=False)}]}).encode()
        r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                            headers={"Content-Type": "application/json"}), timeout=90)
        d = json.loads(r.read().decode())
        raw = (d.get("text") or "").strip()
        if not raw and d.get("choices"):
            raw = d["choices"][0].get("message", {}).get("content", "")
        raw = raw.strip().strip("`")
        mapping = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        mapping = {k: str(v) for k, v in mapping.items() if k in base and v}
        if len(mapping) >= len(base) // 2:   # tradução suficientemente completa
            i18n.register_translations(code, mapping)
            return True
    except Exception as e:
        log(f"ui translate {code}: {e}")
    return False

set_lang(load_ui_lang())   # aplica antes de construir a UI
set_native(load_ui_lang())  # conteúdo (dicionário/chat) na língua escolhida; conta pode sobrepor no login

def FMT(sec):
    s = max(0, int(sec)); h,s = divmod(s,3600); m,s = divmod(s,60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def yt_btn(text="", icon="", tip="", accent=False, small=False):
    b = QPushButton(icon + (" " + text if icon else text))
    b.setToolTip(tip); b.setCursor(QCursor(Qt.PointingHandCursor))
    s = f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:{'4' if small else '6'}px;padding:{'3px 8px' if small else '5px 12px'};font-size:{'11' if small else '12'}px;}}QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
    if accent:
        s = f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:{'4' if small else '6'}px;padding:{'3px 10px' if small else '6px 16px'};font-size:{'11' if small else '12'}px;font-weight:bold;}}QPushButton:hover{{background:{ACC_HOVER};}}"
    b.setStyleSheet(s); return b


def fade_in(widget, dur=180):
    """Smooth opacity fade-in for a Qt widget (panels, popups) — adds polish."""
    try:
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setDuration(dur); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        widget._fade_anim = anim   # keep a reference so it isn't GC'd
        anim.start()
    except Exception:
        pass


def showToast(msg, style="", duration=2000):
    """Show a temporary overlay message on all windows"""
    try:
        app = QApplication.instance()
        if not app: return
        for w in app.topLevelWidgets():
            if isinstance(w, QMainWindow):
                sb = w.statusBar()
                if sb:
                    sb.showMessage(msg, duration)
                    return
    except: pass


# ═══════════════════════════════════════════════════════════════════════════
# SEEK SLIDER (click-to-seek)
# ═══════════════════════════════════════════════════════════════════════════

class SeekSlider(QSlider):
    """QSlider that jumps to the clicked position instead of stepping toward it.
    A plain QSlider only moves by a page-step when the groove is clicked; for a
    video scrub bar the user expects the playhead to jump straight to where they
    click (and to be able to keep dragging from there).

    It also paints A/B loop markers on the groove so the user can see exactly
    where the manual loop starts and ends."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._marks = {}   # label -> value (in slider units, i.e. seconds)

    def set_mark(self, key, value):
        if value is None:
            self._marks.pop(key, None)
        else:
            self._marks[key] = value
        self.update()

    def clear_marks(self):
        if self._marks:
            self._marks = {}
            self.update()

    def _x_for(self, value):
        opt = QStyleOptionSlider(); self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        span = groove.width() - handle.width()
        off = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), int(value), span)
        return groove.x() + handle.width() // 2 + off

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._marks or self.maximum() <= self.minimum():
            return
        from PyQt5.QtGui import QPainter, QColor, QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        a = self._marks.get('A'); b = self._marks.get('B')
        # Shade the looped region between A and B.
        if a is not None and b is not None and b > a:
            xa, xb = self._x_for(a), self._x_for(b)
            p.fillRect(QRect(int(xa), h // 2 - 4, int(xb - xa), 8),
                       QColor(255, 255, 255, 60))
        f = QFont("Inter", 7, QFont.Bold)
        for key, col in (('A', QColor("#9EE6A0")), ('B', QColor("#FFB27A"))):
            v = self._marks.get(key)
            if v is None:
                continue
            x = int(self._x_for(v))
            p.setPen(QColor(col)); p.setBrush(QColor(col))
            p.drawRect(QRect(x - 1, 1, 2, h - 2))
            p.setFont(f)
            p.drawText(QRect(x - 6, h - 9, 12, 9), Qt.AlignCenter, key)
        p.end()

    def _value_at(self, pos):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        if self.orientation() == Qt.Horizontal:
            span = groove.width() - handle.width()
            x = pos.x() - groove.x() - handle.width() // 2
            return QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), x, span)
        span = groove.height() - handle.height()
        y = pos.y() - groove.y() - handle.height() // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), y, span, upsideDown=True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > self.minimum():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(
                QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            if not handle.contains(e.pos()):
                self.setValue(self._value_at(e.pos()))
                self.sliderMoved.emit(self.value())
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════
# SRT PARSER
# ═══════════════════════════════════════════════════════════════════════════

class SubEntry:
    __slots__ = ('start', 'end', 'text')
    def __init__(self, start, end, text):
        self.start = start; self.end = end; self.text = text

# A single timestamp: optional hours, then MM:SS,mmm (SRT) or MM:SS.mmm (VTT).
_TS_RE = re.compile(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})')

def _ts_to_sec(m):
    h = int(m.group(1) or 0)
    return (h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4).ljust(3, '0')) / 1000.0)

def parse_srt(content):
    """Parse SRT/VTT into SubEntry list with FLOAT-second timings.
    The previous version truncated milliseconds (rounding every cue down to a
    whole second), which made subtitles show up to ~1s early — the sync bug."""
    entries = []
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.split('\n')
        # Locate the timecode line (handles an optional index line, WEBVTT, etc.)
        tline = next((l for l in lines if '-->' in l), None)
        if not tline:
            continue
        left, _, right = tline.partition('-->')
        m1, m2 = _TS_RE.search(left), _TS_RE.search(right)
        if not m1 or not m2:
            continue
        s, e = _ts_to_sec(m1), _ts_to_sec(m2)
        if e < s:
            continue
        tidx = lines.index(tline)
        text = ' '.join(lines[tidx + 1:])
        text = re.sub(r'<[^>]+>', '', text)        # strip <i>, <font…>, etc.
        text = re.sub(r'\{\\[^}]*\}', '', text)     # strip SSA/ASS overrides
        text = text.strip()
        if text:
            entries.append(SubEntry(s, e, text))
    return entries

def find_subtitle(video_path):
    """Look for .srt/.vtt next to video file"""
    base = Path(video_path).with_suffix('')
    for ext in ['.srt', '.SRT', '.vtt', '.VTT']:
        p = Path(str(base) + ext)
        if p.exists(): return p
    # Also check Downloads folder with same name
    dl = Path.home() / 'Downloads'
    for ext in ['.srt', '.SRT']:
        p = dl / (Path(video_path).stem + ext)
        if p.exists(): return p
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PLAYER ENGINE — VLC + Vocab Overlay
# ═══════════════════════════════════════════════════════════════════════════

class PlayerEngine(QWidget):
    position_changed = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    playing_changed = pyqtSignal(bool)
    media_ended = pyqtSignal()
    vocab_triggered = pyqtSignal(str)
    subtitle_changed = pyqtSignal(str)  # current subtitle text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};border:none;")
        self.setMinimumHeight(360)
        self.setFocusPolicy(Qt.StrongFocus)

        self._inst = None; self._player = None; self._media = None
        self._path = None; self._duration = 0
        self._subs = []        # SubEntry list
        self._played_ids = set()  # track which subs already shown
        # ── Language-learning practice state ──
        self._loop = None       # (start, end) seconds, or None — A-B loop
        self._loop_a = None     # manual A point (seconds) waiting for B
        self._autopause = False # pause at the end of each subtitle (shadowing)
        self._ap_armed = False  # armed while inside a subtitle
        self._ap_last = -1      # last subtitle index we were inside
        self._last_sub = ""     # last non-empty subtitle text (stays on pause)

        self.ph = QLabel("", self)
        self.ph.setAlignment(Qt.AlignCenter)
        self.ph.setStyleSheet(f"color:{TMT};font-size:15px;background:transparent;")
        self._show_ph()

        # Poll often so subtitles flip the instant the cue starts (≈1 video
        # frame), not up to 200ms late — that lag read as "out of sync".
        self._poll_ms = 40
        self._timer = QTimer(); self._timer.timeout.connect(self._poll)
        self._init_vlc()

    def _show_ph(self):
        self.ph.setText("Lexio Study Player\n\nCtrl+O  abrir\nEspaco  play/pause")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.ph.setGeometry((self.width()-250)//2, (self.height()-60)//2, 250, 60)

    def _init_vlc(self):
        try:
            if not _VLC_PATH:
                self.ph.setText("VLC nao encontrado\nhttps://videolan.org"); return
            self._inst = vlc.Instance(["--no-xlib","--quiet","--no-video-title-show",
                "--intf","dummy","--no-osd","--no-stats","--avcodec-hw=none",
                "--network-caching=300","--file-caching=300",
                "--text-renderer=freetype"])
            self._player = self._inst.media_player_new()
            if sys.platform == "win32": self._player.set_hwnd(int(self.winId()))
            ev = self._player.event_manager()
            ev.event_attach(vlc.EventType.MediaPlayerEndReached, lambda _: self.media_ended.emit())
            ev.event_attach(vlc.EventType.MediaPlayerLengthChanged, lambda _: self._upd_dur())
            ev.event_attach(vlc.EventType.MediaPlayerPaused, lambda _: self.playing_changed.emit(False))
            ev.event_attach(vlc.EventType.MediaPlayerPlaying, lambda _: self.playing_changed.emit(True))
            ev.event_attach(vlc.EventType.MediaPlayerStopped, lambda _: self.playing_changed.emit(False))
            self._timer.start(self._poll_ms)
            log("VLC OK")
        except Exception as e:
            log(f"VLC init: {e}"); self.ph.setText(f"Erro VLC: {e}")

    def _poll(self):
        if not self._player: return
        try:
            p = self._player.get_time() / 1000.0
            is_playing = self._player.is_playing()
            if is_playing:
                self.position_changed.emit(p)
            # Find current subtitle — keep last active visible when paused
            current_sub = ""
            for sub in self._subs:
                if sub.start <= p <= sub.end:
                    current_sub = sub.text
                    break
            if current_sub:
                self._last_sub = current_sub
            elif not is_playing and self._last_sub:
                current_sub = self._last_sub
            self.subtitle_changed.emit(current_sub)
            # ── A-B loop of the current line ──
            if self._loop and is_playing and p > self._loop[1] + 0.05:
                log(f"loop back {p:.1f}s -> {self._loop[0]:.1f}s")
                self.seek(self._loop[0])
            # ── Auto-pause at the end of each subtitle (shadowing) ──
            elif self._autopause and is_playing:
                inside = -1
                for i, s in enumerate(self._subs):
                    if s.start <= p <= s.end:
                        inside = i; break
                if inside >= 0:
                    if self._ap_last >= 0 and inside != self._ap_last:
                        self._player.pause()            # back-to-back lines → pause at boundary
                    self._ap_last = inside; self._ap_armed = True
                elif self._ap_armed:
                    self._ap_armed = False; self._player.pause()  # entered the gap → pause
            # Check subs for vocab overlay (only while playing)
            if is_playing:
                for i, sub in enumerate(self._subs):
                    if i in self._played_ids: continue
                    if sub.start <= p <= sub.end:
                        self._played_ids.add(i)
                        self.vocab_triggered.emit(sub.text)
        except: pass

    def _upd_dur(self):
        if self._player:
            d = self._player.get_length() // 1000
            self._duration = d; self.duration_changed.emit(float(d))

    def open(self, path):
        if not self._player: return
        self.stop()
        self._path = path
        self._subs = []; self._played_ids = set(); self._last_sub = ""
        if not Path(path).exists(): return
        # Load subtitles - auto detect .srt file
        sub_path = find_subtitle(path)
        if sub_path:
            try:
                self._subs = parse_srt(sub_path.read_text(encoding='utf-8', errors='replace'))
                log(f"Loaded {len(self._subs)} subs from {sub_path.name}")
            except Exception as e:
                log(f"sub parse fail: {e}")
        try:
            self._media = self._inst.media_new(path)
            # Add subtitle to VLC via media options (native, most reliable)
            if sub_path and sub_path.exists():
                try:
                    self._media.add_options(f':sub-file={sub_path}')
                    log(f"VLC native sub via media: {sub_path.name}")
                except Exception as e:
                    log(f"VLC media sub fail: {e}")
            self._player.set_media(self._media)
            self._player.play()
            self.ph.hide()
            QTimer.singleShot(300, lambda: self._player and self._player.set_hwnd(int(self.winId())))
            log(f"Playing: {path}")
        except Exception as e: log(f"open: {e}")

    def load_srt(self, srt_path):
        """Load subtitle file manually"""
        if not self._player: return False
        try:
            self._subs = parse_srt(Path(srt_path).read_text(encoding='utf-8', errors='replace'))
            self._played_ids = set()
            log(f"Loaded {len(self._subs)} subs from {srt_path}")
            # Also add to VLC natively for reliable rendering
            try:
                self._player.video_set_subtitle_file(str(srt_path))
                # Enable the subtitle track
                spu_count = self._player.video_get_spu_count()
                if spu_count and spu_count > 0:
                    self._player.video_set_spu(1)
                log(f"VLC native sub loaded: {srt_path}")
            except Exception as e:
                log(f"VLC sub-file load fail: {e}")
            return True
        except Exception as e:
            log(f"load_srt fail: {e}")
            return False

    def cycle_sub_track(self):
        """Cycle through VLC subtitle tracks (embedded)"""
        if not self._player: return -1
        try:
            count = self._player.video_get_spu_count()
            current = self._player.video_get_spu()
            if count is None or count <= 0:
                # If no tracks or SRT loaded, toggle external subs on/off
                has_subs = len(self._subs) > 0
                if has_subs:
                    old = self._subs
                    self._subs = [] if self._played_ids else old
                    self._played_ids = set()
                    return 0 if self._subs else -1
                return -1
            # Cycle through embedded tracks
            tracks = self._player.video_get_spu()
            next_track = current + 1 if current < count - 1 else -1  # -1 = off
            self._player.video_set_spu(next_track)
            return next_track
        except:
            return -1

    def sub_count(self):
        """Returns number of loaded .srt subs"""
        return len(self._subs)

    def sub_track_count(self):
        """Returns number of VLC embedded sub tracks"""
        if not self._player: return 0
        try: return self._player.video_get_spu_count() or 0
        except: return 0

    def toggle(self):
        if not self._player: return
        if self._player.is_playing(): self._player.pause()
        else: self._player.play()

    def stop(self):
        self._timer.stop()
        if self._player:
            self._player.stop(); self._media = None
        self._path = None; self._duration = 0; self._subs = []; self._played_ids = set()
        self._last_sub = ""
        self._show_ph()
        self._timer.start(self._poll_ms)

    def seek(self, sec):
        if self._player:
            try: self._player.set_time(int(sec*1000))
            except: pass

    def seek_rel(self, d):
        if self._player:
            try: self._player.set_time(max(0, self._player.get_time()+int(d*1000)))
            except: pass

    # ── Subtitle-aware navigation (language practice) ──
    def _sub_idx_at(self, p):
        """Index of the subtitle at time p, else the last that started before p."""
        idx = -1
        for i, s in enumerate(self._subs):
            if s.start <= p <= s.end:
                return i
            if s.start <= p:
                idx = i
            else:
                break
        return idx

    def replay_sub(self):
        if not self._subs: return
        i = self._sub_idx_at(self.get_pos())
        if i < 0: i = 0
        self.seek(self._subs[i].start)
        if self._player and not self._player.is_playing():
            try: self._player.play()
            except: pass

    def prev_sub(self):
        if not self._subs: return
        p = self.get_pos(); i = self._sub_idx_at(p)
        if i < 0: i = 0
        # If already >0.6s into the line, restart it; otherwise step back one.
        elif p - self._subs[i].start < 0.6 and i > 0:
            i -= 1
        self.seek(self._subs[i].start)

    def next_sub(self):
        if not self._subs: return
        i = self._sub_idx_at(self.get_pos())
        nxt = min((i + 1) if i >= 0 else 0, len(self._subs) - 1)
        self.seek(self._subs[nxt].start)

    def toggle_loop(self):
        """Loop the current subtitle line until toggled off. Returns new bool state."""
        if self._loop:
            self._loop = None; self._loop_a = None; log("loop OFF"); return False
        if not self._subs:
            log("loop: no subtitles loaded"); return False
        pos = self.get_pos()
        i = self._sub_idx_at(pos)
        if i < 0:
            log(f"loop: no subtitle at pos {pos:.1f}s"); return False
        s = self._subs[i]; self._loop = (s.start, s.end); self.seek(s.start)
        log(f"loop ON {s.start:.1f}-{s.end:.1f}s : {s.text[:40]}")
        if self._player and not self._player.is_playing():
            try: self._player.play()
            except: pass
        return True

    def set_autopause(self, b):
        self._autopause = bool(b); self._ap_armed = False; self._ap_last = -1

    # ── Manual A-B loop (mark A, then B) ──
    def set_loop_a(self):
        self._loop_a = self.get_pos()
        log(f"loop A = {self._loop_a:.1f}s")
        return self._loop_a

    def set_loop_b(self):
        if self._loop_a is None:
            return None
        b = self.get_pos()
        if b <= self._loop_a + 0.3:
            return None
        self._loop = (self._loop_a, b); self.seek(self._loop_a)
        log(f"manual loop {self._loop_a:.1f}-{b:.1f}s")
        if self._player and not self._player.is_playing():
            try: self._player.play()
            except: pass
        return self._loop

    def is_playing(self): return bool(self._player and self._player.is_playing())
    def get_pos(self):
        if self._player:
            try: return self._player.get_time()/1000.0
            except: return 0
        return 0
    def get_dur(self):
        if self._duration: return float(self._duration)
        if self._player:
            try: return self._player.get_length()/1000.0
            except: return 0
        return 0
    def path(self): return self._path
    def subs_loaded(self): return len(self._subs) > 0
    def set_vol(self, v):
        if self._player: self._player.audio_set_volume(max(0,min(200,v)))
    def set_rate(self, r):
        if self._player: self._player.set_rate(max(0.25,min(4.0,r)))

    def cleanup(self):
        self._timer.stop(); self.stop()
        if self._player: self._player.release()
        if self._inst: self._inst.release()


# ═══════════════════════════════════════════════════════════════════════════
# VIDEO OVERLAY — Janela OS independente (frameless, top-level)
# Nenhum widget Qt consegue ficar por cima do VLC DirectX.
# Esta janela é um OS window separado — Windows DWM compõe por cima.
# ═══════════════════════════════════════════════════════════════════════════

TWITCH_COLORS = [
    "#ff0000", "#0000ff", "#00ff00", "#ff00ff", "#ffff00",
    "#ff69b4", "#00ffff", "#ff4500", "#7b68ee", "#32cd32",
    "#ff1493", "#1e90ff", "#ffd700", "#00fa9a", "#ff6347",
]

# Soft, high-contrast palette to tint only the KEY words inside a subtitle line
# (content words) — the rest of the line stays white, so it's legible, not a
# rainbow. Each word keeps a stable colour across the whole video.
SUB_WORD_COLORS = [
    "#7EC8FF", "#FFD479", "#9EE6A0", "#FF9EB1", "#C9A6FF",
    "#FFB27A", "#86E5D4", "#F2A6E8",
]
# Common short function words that should NOT be highlighted (kept white)
_STOPWORDS = set("""
the a an and or but of to in on at for with as is are was were be been am do does did
o a os as um uma e ou de da do das dos em no na nos nas que por para com se já não sim
el la los las un una y o de del al en es son por para con que se no sí su sus lo le
le la les des du de et ou un une en au aux que ne pas se sur avec pour dans
der die das und oder ein eine zu in den dem des im ist sind war auf mit für
""".split())

# ── Smart subtitle marking ──────────────────────────────────────────────────
# Three visual categories, each a distinct colour so the learner can tell at a
# glance what kind of item a word is:
#   • GROUP    — multi-word expressions (phrasal verbs, idioms, collocations)
#   • LEVEL    — single content words around the learner's level
#   • ADVANCED — rarer / harder single words worth extra attention
MARK_GROUP = "#C9A6FF"     # violet  — expressions
MARK_LEVEL = "#9EE6A0"     # green   — your level
MARK_ADV   = "#FFB27A"     # amber   — advanced

# Common multi-word expressions (lowercase, contiguous). Matched longest-first
# so "look forward to" beats "look forward". Offline, no AI call per line.
EXPRESSIONS = set("""
look forward to|give up|give in|give away|pick up|pick out|put off|put up with|
take off|take over|take care of|carry on|carry out|come up with|come across|
get up|get along|get rid of|get over|run out of|run into|figure out|find out|
break down|break up|bring up|set up|set off|show up|turn on|turn off|turn out|
turn down|work out|hang out|hang on|hold on|make up|make out|point out|
look after|look for|look up|look into|go on|go through|go over|end up|
fill in|fill out|check out|check in|back up|calm down|cut off|deal with|
keep up|keep on|let down|move on|pass out|put down|sort out|stand out|
throw away|wake up|warm up|wear out|drop off|grow up|account for|catch up|
once in a while|on the other hand|as well as|in spite of|on purpose|
for good|by heart|out of the blue|piece of cake|under the weather|
break the ice|hit the sack|make up your mind|as a matter of fact|
at the end of the day|in the long run|sooner or later|so far|of course|
no matter what|in order to|as long as|even though|as if|rather than
""".replace("\n", "").split("|"))
EXPRESSIONS = set(e.strip() for e in EXPRESSIONS if e.strip())
_EXPR_MAXLEN = 4

# Frequent words that look hard (long) but the learner likely knows → keep them
# at "your level" green instead of flagging them as advanced.
_EASY_LONG = set("""
because everything something anything someone everyone nothing important
beautiful different remember together favourite favorite probably actually
yesterday tomorrow understand interesting wonderful family people morning
""".split())
# Short words that are nonetheless advanced/worth attention.
_ADV_SHORT = set("""
albeit thus hence amid akin wary deem cease yield vast keen lure grit
""".split())

def _clean_core(w):
    return ''.join(ch for ch in w if ch.isalpha()).lower()

def mark_tokens(words):
    """Classify a list of whitespace-split tokens for highlighting.
    Returns a list aligned to `words`, each item a dict:
      {color: hex or None, underline: bool, key: bool, click: str}
    Multi-word expressions are detected first and share the GROUP colour."""
    cores = [_clean_core(w) for w in words]
    n = len(words)
    out = [None] * n
    i = 0
    while i < n:
        if not cores[i]:
            out[i] = {"color": None, "underline": False, "key": False, "click": ""}
            i += 1
            continue
        # Longest-first expression match starting at i.
        matched = 0
        for L in range(min(_EXPR_MAXLEN, n - i), 1, -1):
            seg = cores[i:i + L]
            if all(seg) and " ".join(seg) in EXPRESSIONS:
                matched = L
                break
        if matched:
            phrase = " ".join(cores[i:i + matched])
            for j in range(i, i + matched):
                out[j] = {"color": MARK_GROUP, "underline": True, "key": True, "click": phrase}
            i += matched
            continue
        # Single word.
        core = cores[i]
        if core in _STOPWORDS or len(core) < 4:
            out[i] = {"color": None, "underline": False, "key": False, "click": core}
        elif core in _ADV_SHORT or (len(core) >= 9 and core not in _EASY_LONG):
            out[i] = {"color": MARK_ADV, "underline": True, "key": True, "click": core}
        else:
            out[i] = {"color": MARK_LEVEL, "underline": True, "key": True, "click": core}
        i += 1
    return out

class VocabCard:
    __slots__ = ('text', 'time', 'color', 'slide_start', 'saved', 'word_rects')
    def __init__(self, text, time, color, slide_start):
        self.text = text; self.time = time; self.color = color
        self.slide_start = slide_start; self.saved = False
        self.word_rects = []   # [(x, y, w, h, word)] of clickable key words (set in paint)

class VideoOverlay(QWidget):
    """Top-level frameless window — sits ABOVE VLC's DirectX output.
    Shows subtitles at bottom + Twitch-style vocab cards sliding from right.
    """
    add_word = pyqtSignal(str)
    ask_ai = pyqtSignal(str)
    video_clicked = pyqtSignal()
    toggle_fullscreen = pyqtSignal()
    word_clicked = pyqtSignal(str)     # underlined key word clicked → details panel
    mouse_moved = pyqtSignal()         # any movement over the video (wakes fs controls)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background:transparent;")
        self.setMouseTracking(True)
        self._cards = []
        self._hover_idx = -1
        self._current_sub = ""
        self._sub_word_rects = []  # [(x, y, w, h, word)] for bottom subtitle
        self._hide_subs = False   # active-recall: hide subtitle until mouse peeks at bottom
        self._mouse_y = 0
        self._loop_active = False  # show a LOOP badge while the A-B loop is on
        self._flash_msg = ""       # transient banner (e.g. "Guardado em Vídeos") for fullscreen
        self._flash_until = 0.0

        # Animation timer: ~60fps for fluid Twitch-style card motion
        self._anim_timer = QTimer()
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(16)

        # Reposition timer: every 300ms ensure we cover the engine
        self._pos_timer = QTimer()
        self._pos_timer.timeout.connect(self._reposition)
        self._pos_timer.start(300)

        self.show()

    def _reposition(self):
        """Find the main window and align overlay over its engine."""
        app = QApplication.instance()
        if not app: return
        for w in app.topLevelWidgets():
            if isinstance(w, QMainWindow) and hasattr(w, 'engine') and w.engine.isVisible():
                eng = w.engine
                g = eng.mapToGlobal(QPoint(0, 0))
                # Only move if size/position changed (avoid flicker)
                cur = self.geometry()
                new_rect = QRect(g.x(), g.y(), eng.width(), eng.height())
                if cur != new_rect:
                    self.setGeometry(new_rect)
                self.raise_()
                # Keep the floating transport (study mode) ABOVE this overlay so
                # its buttons stay clickable and visible over the subtitles.
                tov = getattr(w, "_transport_overlay", None)
                if tov is not None and tov.isVisible():
                    tov.raise_()
                break

    def flash(self, msg, secs=2.6):
        """Show a brief banner centred at the top of the video — the only place
        feedback is visible in fullscreen (the status-bar toast is hidden there)."""
        self._flash_msg = msg
        self._flash_until = time.time() + secs
        self.update()

    def show_subtitle(self, text):
        self._current_sub = text

    def show_vocab(self, text):
        """Called when subtitle triggers a new phrase.
        Clears old cards (>15s) on each new subtitle to prevent excessive accumulation,
        while keeping cards visible during pauses (no new triggers while paused).
        """
        now = time.time()
        # Remove cards older than 15s so only ~3-5 are visible during normal playback
        self._cards = [c for c in self._cards if now - c.time < 15]
        color = TWITCH_COLORS[hash(text) % len(TWITCH_COLORS)]
        self._cards.append(VocabCard(text, now, color, now))

    def _tick(self):
        now = time.time()
        changed = False
        # Remove old cards (safety net — show_vocab cleans on each new subtitle,
        # but this handles edge cases like seeking without new triggers).
        before = len(self._cards)
        self._cards = [c for c in self._cards if now - c.time < 60]
        if len(self._cards) != before:
            changed = True
        # Reset hover if card was removed
        if self._cards and self._hover_idx >= len(self._cards):
            self._hover_idx = -1; changed = True
        # Always repaint if we have cards (animation runs continuously)
        if self._cards or self._current_sub:
            self.update()

    def mouseMoveEvent(self, e):
        self._mouse_y = e.pos().y()
        self.mouse_moved.emit()
        idx = self._hit_test_vocab(e.pos())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        elif self._hide_subs and self._current_sub:
            self.update()   # so the subtitle reveals/hides as the mouse nears the bottom

    def mousePressEvent(self, e):
        idx = self._hit_test_vocab(e.pos())
        if idx >= 0 and idx < len(self._cards):
            card = self._cards[idx]
            mx, my = e.pos().x(), e.pos().y()
            # 1) Clicked an underlined key word → open its details panel
            for (wx, wy, ww, wh, word) in card.word_rects:
                if wx <= mx <= wx + ww and wy <= my <= wy + wh:
                    self.word_clicked.emit(word)
                    return
            # 2) Otherwise the +/AI buttons
            self._handle_vocab_click(mx, card, idx)
            return
        # Check if click hit an underlined word in the bottom subtitle
        mx, my = e.pos().x(), e.pos().y()
        for (wx, wy, ww, wh, word) in self._sub_word_rects:
            if wx <= mx <= wx + ww and wy <= my <= wy + wh:
                self.word_clicked.emit(word)
                return
        self.video_clicked.emit()

    def mouseDoubleClickEvent(self, e):
        # Double-click toggles fullscreen / study mode (and back) — works even
        # when keyboard focus is on the native video.
        self.toggle_fullscreen.emit()

    def _card_rects(self):
        """Yield (i, card, col_w, y, h, now) for visible cards, bottom→top."""
        fm = QFontMetrics(QFont("Inter", 11))
        w = self.width()
        col_w = min(350, int(w * 0.4))
        y = self.height() - 10
        now = time.time()
        for i, card in enumerate(self._cards):
            nlines = max(len(card.text.split('\n')), 1)
            h = nlines * 18 + 20
            y -= h + 4
            if y < 0:
                break
            yield (i, card, col_w, y, h, now)

    def _hit_test_vocab(self, pos):
        for i, card, cw, y, h, now in self._card_rects():
            x = self.width() - cw - 20  # match margin=20 in paintEvent
            if x <= pos.x() <= x + cw and y <= pos.y() <= y + h:
                return i
        return -1

    def _handle_vocab_click(self, mx, card, idx):
        w = self.width()
        col_w = min(350, int(w * 0.4))
        y = self.height() - 10
        for j in range(idx + 1):
            c = self._cards[j]
            cn = max(len(c.text.split('\n')), 1)
            ch = cn * 18 + 20
            y -= ch + 4
        x = w - col_w - 20
        btn_x = x + col_w - 52
        chat_x = btn_x + 24
        if btn_x <= mx <= btn_x + 22:
            card.saved = True          # instant visual feedback (✓), even in fullscreen
            self.update()
            self.add_word.emit(card.text)
        elif chat_x <= mx <= chat_x + 22:
            self.ask_ai.emit(card.text)

    def _word_color(self, word):
        """White for short/function words; a stable soft colour for key content
        words (>= 5 letters, not a stopword)."""
        core = ''.join(ch for ch in word if ch.isalpha())
        if len(core) >= 5 and core.lower() not in _STOPWORDS:
            return QColor(SUB_WORD_COLORS[hash(core.lower()) % len(SUB_WORD_COLORS)])
        return QColor(255, 255, 255)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)
        p.setRenderHint(p.TextAntialiasing)
        w = self.width()

        # ── LOOP badge (clear feedback that the A-B loop is active) ──
        if self._loop_active:
            bf = QFont("Inter", 11, QFont.Bold); p.setFont(bf)
            bw = QFontMetrics(bf).horizontalAdvance("LOOP") + 24
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 230))
            p.drawRoundedRect(16, 16, bw, 26, 13, 13)
            p.setPen(QColor(0, 0, 0)); p.drawText(QRect(16, 16, bw, 26), Qt.AlignCenter, "LOOP")

        # ── Transient flash banner (save confirmation, visible in fullscreen) ──
        if self._flash_msg and time.time() < self._flash_until:
            ff = QFont("Inter", 12, QFont.DemiBold); p.setFont(ff)
            fm2 = QFontMetrics(ff)
            fbw = fm2.horizontalAdvance(self._flash_msg) + 36
            fbx = (w - fbw) // 2
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 235))
            p.drawRoundedRect(fbx, 18, fbw, 34, 17, 17)
            p.setPen(QColor(10, 10, 10))
            p.drawText(QRect(fbx, 18, fbw, 34), Qt.AlignCenter, self._flash_msg)

        # ── 1. Subtitle at bottom center ──
        if self._current_sub:
            H = self.height()
            reveal = (not self._hide_subs) or (self._mouse_y > H - 170)
            if reveal:
                # Responsive size: scale the font to the video area so it doesn't
                # look oversized/clipped in a small (windowed) player, and WRAP to
                # up to two lines instead of truncating — far more readable.
                fs = max(13, min(20, H // 28))
                sub_font = QFont("Inter", fs, QFont.Bold)
                fm = QFontMetrics(sub_font)
                ul_sub = QFont(sub_font); ul_sub.setUnderline(True)
                space_w = fm.horizontalAdvance(" ")
                line_h = fm.height() + 2
                pad = 16
                maxw = int(w * 0.86)
                avail = max(80, maxw - 2 * pad)
                words = [x for x in self._current_sub.split(" ") if x]
                marks = mark_tokens(words)
                # Greedy word-wrap into lines.
                lines, cur, cur_w = [], [], 0
                for word, mk in zip(words, marks):
                    ww = fm.horizontalAdvance(word)
                    add = ww + (space_w if cur else 0)
                    if cur and cur_w + add > avail:
                        lines.append(cur); cur, cur_w = [], 0; add = ww
                    cur.append((word, mk)); cur_w += add
                if cur:
                    lines.append(cur)
                if len(lines) > 2:                  # cap at 2 lines, mark the cut
                    lines = lines[:2]; lines[1].append(("…", None))

                def line_width(ln):
                    return (sum(fm.horizontalAdvance(wd) for wd, _ in ln)
                            + space_w * max(0, len(ln) - 1))

                box_h = len(lines) * line_h + 14
                sw = min(maxw, max((line_width(ln) for ln in lines), default=0) + 2 * pad)
                margin_b = max(12, H // 14)         # responsive bottom gap
                sy = H - box_h - margin_b
                sx = (w - sw) // 2
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 200))
                p.drawRoundedRect(sx, sy, sw, box_h, 8, 8)

                # Draw each line centred; tint + underline KEY words (clickable).
                sub_rects = []
                for li, ln in enumerate(lines):
                    lx = (w - line_width(ln)) // 2
                    ly = sy + 7 + li * line_h
                    for word, mk in ln:
                        ww = fm.horizontalAdvance(word)
                        if mk and mk["color"]:
                            p.setPen(QColor(mk["color"]))
                            p.setFont(ul_sub if mk["underline"] else sub_font)
                            if mk.get("click") or mk.get("underline"):
                                sub_rects.append((lx, ly, ww + 4, line_h, mk.get("click") or word))
                        else:
                            p.setPen(QColor(255, 255, 255)); p.setFont(sub_font)
                        p.drawText(QRect(lx, ly, ww + 4, line_h), Qt.AlignLeft | Qt.AlignVCenter, word)
                        lx += ww + space_w
                self._sub_word_rects = sub_rects
                p.setFont(sub_font)
            else:
                # Active-recall: subtitle hidden — discreet placeholder, peek by
                # moving the mouse to the bottom of the video.
                ph = "•  •  •   (passa o rato em baixo para ver)"
                pf = QFont("Inter", 11); pfm = QFontMetrics(pf)
                pw = pfm.horizontalAdvance(ph) + 40
                px = (w - pw) // 2
                py = self.height() - 52
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 130))
                p.drawRoundedRect(px, py, pw, 26, 13, 13)
                p.setPen(QColor(200, 200, 200, 180)); p.setFont(pf)
                p.drawText(QRect(px, py, pw, 26), Qt.AlignCenter, ph)

        # ── 2. Twitch-style vocab cards — right column, slide from right ──
        if not self._cards:
            p.end()
            return

        fm = QFontMetrics(QFont("Inter", 11))
        now = time.time()
        # Fixed-width right column: max 350px or 40% of overlay
        col_w = min(350, int(w * 0.4))
        margin = 20  # right margin from edge

        for i, card, cw, y, h, _ in self._card_rects():
            age = now - card.time
            # Full opacity — no fade-out. Cards live 60s then disappear cleanly.
            # Fading during pause looked like subtitles vanishing, which confused
            # users studying paused video.
            alpha = 230
            hovering = (i == self._hover_idx)

            # Right-aligned in the overlay
            target_x = w - col_w - margin
            start_x = w  # off-screen right

            # Slide animation: 400ms ease-out
            slide_t = min(1.0, (now - card.slide_start) / 0.4)
            ease = 1.0 - (1.0 - slide_t) * (1.0 - slide_t)  # ease-out quad
            cur_x = int(start_x + (target_x - start_x) * ease)

            # Background pill
            bg_color = QColor(10, 10, 10, min(alpha, 200))
            p.setBrush(bg_color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(cur_x, y, col_w, h - 2, 8, 8)

            # Colored left bar
            col = QColor(card.color)
            col.setAlpha(alpha)
            p.setBrush(col)
            p.drawRoundedRect(cur_x, y, 4, h - 2, 2, 2)

            # Text — word by word: tint + underline KEY words (clickable for details)
            base_font = QFont("Inter", 11)
            ul_font = QFont("Inter", 11); ul_font.setUnderline(True)
            fmc = QFontMetrics(base_font)
            sp_w = fmc.horizontalAdvance(" ")
            card.word_rects = []
            lines = card.text.split('\n')
            for li, line in enumerate(lines[:2]):
                wx = cur_x + 14
                wy = y + 4 + li * 18
                words = line[:70].split(" ")
                marks = mark_tokens(words)
                for word, mk in zip(words, marks):
                    if not word:
                        wx += sp_w; continue
                    ww = fmc.horizontalAdvance(word)
                    if mk and mk["color"]:
                        c2 = QColor(mk["color"]); c2.setAlpha(alpha)
                        p.setPen(c2); p.setFont(ul_font if mk["underline"] else base_font)
                        # Clicking opens details for the whole expression (or word).
                        card.word_rects.append((wx, wy, ww, 18, mk["click"] or word))
                    else:
                        p.setPen(QColor(255, 255, 255, alpha)); p.setFont(base_font)
                    p.drawText(QRect(wx, wy, ww + 4, 18), Qt.AlignLeft | Qt.AlignVCenter, word)
                    wx += ww + sp_w
            p.setFont(base_font)

            # Persistent saved tick (visible even without hover / in fullscreen)
            if card.saved and not hovering:
                p.setPen(QColor(255, 255, 255, alpha))
                p.setFont(QFont("Inter", 11, QFont.Bold))
                p.drawText(QRect(cur_x + col_w - 30, y, 22, h), Qt.AlignCenter, "✓")

            # Buttons on hover
            if hovering:
                add_bg = QColor(255, 255, 255, min(alpha, 50)) if card.saved else QColor(255, 255, 255, min(alpha, 38))
                p.setBrush(add_bg)
                bx = cur_x + col_w - 52
                p.drawRoundedRect(bx, y + (h - 22) // 2, 20, 18, 4, 4)
                p.setPen(QColor(255, 255, 255, alpha) if card.saved else QColor(255, 255, 255, alpha))
                p.setFont(QFont("Inter", 9, QFont.Bold))
                p.drawText(QRect(bx, y + (h - 22) // 2, 20, 18), Qt.AlignCenter, "✓" if card.saved else "+")

                chat_bg = QColor(30, 30, 30, min(alpha + 30, 255))
                p.setBrush(chat_bg)
                c_bx = bx + 24
                p.drawRoundedRect(c_bx, y + (h - 22) // 2, 20, 18, 4, 4)
                p.setPen(QColor(200, 200, 200, alpha))
                p.drawText(QRect(c_bx, y + (h - 22) // 2, 20, 18), Qt.AlignCenter, "AI")

        p.end()


# ═══════════════════════════════════════════════════════════════════════════
# LOGIN DIALOG — QWebEngineView embutido para auth Google OAuth
# ═══════════════════════════════════════════════════════════════════════════

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_PROFILE_DIR = str(Path.home() / ".lexio-player" / "browser-profile")


# ═══════════════════════════════════════════════════════════════════════════
# IMAGENS — mesma config da web (src/lib/pollinations.ts + /api/media-search).
# Cadeia de robustez idêntica (tenta por ordem, há SEMPRE imagem):
#   1. /api/media-search  → fotos REAIS (Unsplash → Tavily → SerpApi → Pollinations)
#   2. Pollinations (IA, vários prompts/seeds)
#   3. LoremFlickr (fotos reais, infra independente)
#   4. Cartão local desenhado (QPixmap) — nunca falha
# ═══════════════════════════════════════════════════════════════════════════

# Mesmo hash determinístico da web (hashCode em pollinations.ts) → mesmas seeds,
# logo as MESMAS imagens geradas que o utilizador vê no site.
def _img_hashcode(s):
    h = 0
    for ch in s:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    return h

_IMG_CONCRETE = set("""
people person man woman child children baby family friend friends teacher student
doctor driver worker player house home room kitchen garden park street road city
town beach mountain river lake forest tree flower animal dog cat bird horse fish
food meal breakfast lunch dinner table chair door window book phone computer car
bus train plane bike boat school office hospital store shop market morning evening
night sun moon sky cloud rain water fire light hand face eye work job money news
story game sport team ball party event show film movie photo coffee tea bread
university class lesson exam airport station hotel restaurant cafe sea ocean island
""".split())

def _img_extract_context(text, word=""):
    """Extrai palavras visuais do exemplo, priorizando substantivos concretos —
    igual ao pollinationsImages/dynamicPrompt da web."""
    toks = [w for w in re.sub(r"[^\w\s]", " ", text or "").split()
            if len(w) > 2 and w.lower() != (word or "").lower()]
    concrete = [w for w in toks if w.lower() in _IMG_CONCRETE]
    other = [w for w in toks if w.lower() not in _IMG_CONCRETE]
    return " ".join((concrete + other)[:6])

def pollinations_image_urls(word, context="", count=4):
    from urllib.parse import quote
    safe = (word or "").strip() or "vocabulary word"
    ctx = _img_extract_context(context, word) or (context or "")[:80]
    style = "photorealistic, sharp focus, natural lighting, detailed, warm tones"
    photo = "photography, depth of field, high quality, 8K"
    prompts = [
        f"{safe} {ctx}, {style}, {photo}",
        f"{ctx}, {safe}, real life scene, {style}",
        f"{safe} in a daily life situation, people, {style}",
        f"{safe} vocabulary illustration, clean educational, {style}",
    ]
    urls = []
    for p in prompts[:max(1, count)]:
        enc = quote(p[:250]); seed = abs(_img_hashcode(p)) % 100000
        urls.append(f"https://image.pollinations.ai/prompt/{enc}"
                    f"?width=512&height=512&nologo=true&seed={seed}&referrer=lexio-player")
    return urls

def loremflickr_image_urls(word, context="", count=2):
    from urllib.parse import quote
    safe = (word or "").strip() or "vocabulary"
    ctx = ",".join([w for w in re.sub(r"[^\w\s]", " ", context or "").split() if len(w) > 2][:2])
    kw = quote(",".join([x for x in (safe, ctx) if x]))
    base = abs(_img_hashcode(safe + context))
    return [f"https://loremflickr.com/512/512/{kw}?lock={base % 90000 + i}" for i in range(count)]

def media_search_image_urls(word, example="", meaning="", image_prompt=""):
    """Chama o MESMO endpoint da web: /api/media-search (Unsplash→Tavily→SerpApi→
    Pollinations). Devolve fotos reais curadas, ou [] se falhar."""
    try:
        body = json.dumps({"type": "image", "word": word, "example": example,
                           "meaning": meaning, "imagePrompt": image_prompt,
                           "maxImages": 4}).encode()
        req = Request(f"{LEXIO_API}/api/media-search", data=body,
                      headers={"Content-Type": "application/json", "User-Agent": CHROME_UA})
        d = json.loads(urlopen(req, timeout=20).read().decode())
        return [u for u in (d.get("images") or []) if u]
    except Exception as e:
        log(f"media-search: {e}")
        return []

def build_image_candidates(word, example="", meaning="", image_prompt=""):
    """Lista ordenada de URLs candidatas (sem o cartão local, que é desenhado se
    todas falharem). Reais → Pollinations → LoremFlickr."""
    ctx = example or meaning
    real = media_search_image_urls(word, example, meaning, image_prompt)
    out, seen = [], set()
    for u in real + pollinations_image_urls(word, ctx) + loremflickr_image_urls(word, ctx):
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def local_card_pixmap(word, context="", w=400, h=240):
    """Cartão garantido desenhado localmente (nunca falha) — equivalente ao
    localCardDataUri (SVG) da web. Gradiente + palavra + LEXIO."""
    pm = QPixmap(w, h); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
    hh = abs(_img_hashcode(word or "x"))
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor.fromHsl(hh % 360, 115, 56))
    g.setColorAt(1.0, QColor.fromHsl((hh + 40) % 360, 140, 31))
    p.setPen(Qt.NoPen); p.setBrush(g); p.drawRoundedRect(0, 0, w, h, 10, 10)
    p.setBrush(QColor(255, 255, 255, 16)); p.drawEllipse(w // 2 - 70, 28, 140, 140)
    wd = ((word or "Lexio").strip())[:22]
    fs = 30 if len(wd) > 14 else (38 if len(wd) > 9 else 46)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Inter", fs, QFont.Bold))
    p.drawText(QRect(8, 0, w - 16, h - 34), Qt.AlignCenter, wd)
    p.setPen(QColor(255, 255, 255, 120)); p.setFont(QFont("Inter", 10, QFont.Bold))
    p.drawText(QRect(0, h - 28, w, 20), Qt.AlignCenter, "L E X I O")
    p.end()
    return pm


class LoginDialog(QDialog):
    """Embedded browser for Google OAuth login — captures Supabase JWT automatically."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("login_title"))
        self.setMinimumSize(500, 720)
        self.setStyleSheet(f"background:{BG};")
        self._auth_data = None

        lo = QVBoxLayout(self); lo.setContentsMargins(0,0,0,0)

        # ── Top bar ──
        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12,0,12,0)
        title = QLabel(T("login_google"))
        title.setStyleSheet(f"color:{TXT};font-size:13px;font-weight:bold;background:transparent;")
        hl.addWidget(title)
        hl.addStretch()
        close_btn = QPushButton("X")
        close_btn.setFixedSize(24,24)
        close_btn.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TS2};font-size:13px;font-weight:bold;}}QPushButton:hover{{color:{TXT};}}")
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        lo.addWidget(hdr)

        # ── WebEngine com perfil persistente + User-Agent de Chrome real ──
        # Perfil persistente: cookies ficam guardados entre sessões
        # O utilizador faz login uma vez — nas seguintes apenas seleciona a conta
        self._profile = QWebEngineProfile("lexio_google_auth")
        self._profile.setPersistentStoragePath(BROWSER_PROFILE_DIR)
        self._profile.setCachePath(BROWSER_PROFILE_DIR + "/cache")
        self._profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        # User-Agent de Chrome — evita bloqueio do Google a WebViews
        self._profile.setHttpUserAgent(CHROME_UA)

        page = QWebEnginePage(self._profile, self)
        page.urlChanged.connect(self._on_url)

        self.browser = QWebEngineView()
        self.browser.setPage(page)
        lo.addWidget(self.browser, 1)

        # ── Status bar ──
        self.status = QLabel(T("login_loading"))
        self.status.setFixedHeight(28)
        self.status.setStyleSheet(f"color:{TMT};font-size:11px;padding:4px 12px;background:{SRF};border-top:1px solid {BRD};")
        lo.addWidget(self.status)

        # ── Start the flow ──
        QTimer.singleShot(200, self._start_flow)

    def _start_flow(self):
        """Step 1: get Google OAuth URL from the Lexio API, then navigate."""
        try:
            self.status.setText(T("login_contacting"))
            r = urlopen(Request(f"{LEXIO_API}/api/auth", headers={"User-Agent": APP_NAME}), timeout=10)
            data = json.loads(r.read().decode())
            url = data.get("url")
            if url:
                self.status.setText("A redirecionar para Google...")
                self.browser.setUrl(QUrl(url))
            else:
                self.status.setText("Erro: URL de login nao encontrado")
        except Exception as e:
            self.status.setText(f"Erro de rede: {e}")
            log(f"LoginDialog: {e}")

    def _on_url(self, url):
        """Monitor URL changes — catch the redirect with access_token."""
        url_str = url.toString()
        log(f"LoginDialog URL: {url_str[:120]}...")

        # Check if we landed on the app URL with hash fragment containing tokens
        fragment = url.fragment()
        if fragment and "access_token=" in fragment:
            self.status.setText("Autenticacao recebida!")
            log("LoginDialog: access_token detected in URL fragment")

            # Parse the hash fragment
            params = {}
            for pair in fragment.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

            access_token = params.get("access_token", "")
            refresh_token = params.get("refresh_token", "")
            expires_in = params.get("expires_in", "3600")

            if access_token:
                self._auth_data = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": int(expires_in),
                    "expires_at": (datetime.now().timestamp() + int(expires_in)),
                    "saved": datetime.now().isoformat(),
                }
                log("LoginDialog: token captured successfully")
                QTimer.singleShot(500, self.accept)
            else:
                self.status.setText("Token vazio — tenta novamente")
                log("LoginDialog: empty access_token")

        # Also check for error in URL query
        if "error=" in url_str and "lexio-app-five.vercel.app" in url_str:
            self.status.setText("Erro de autenticacao")
            log(f"LoginDialog: auth error in URL")

    def get_auth_data(self):
        return self._auth_data

    def reject(self):
        """Override close to log it."""
        log("LoginDialog: user cancelled")
        super().reject()


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM-BROWSER OAUTH (loopback) — Google blocks embedded webviews, so we open
# the user's real browser and catch the redirect on a tiny local HTTP server.
# ═══════════════════════════════════════════════════════════════════════════

_LOGIN_DONE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Lexio Player</title><style>
html,body{height:100%;margin:0}
body{background:#121212;color:#fff;font-family:'Inter',system-ui,sans-serif;
display:flex;align-items:center;justify-content:center}
.card{text-align:center;padding:40px 48px;border:1px solid rgba(255,255,255,.1);
border-radius:14px;background:#1a1a1a}
.t{font-size:22px;font-weight:600;letter-spacing:.3px}
.s{color:rgba(255,255,255,.6);margin-top:10px;font-size:14px}
</style></head><body><div class="card">
<div class="t">Sessao iniciada com sucesso</div>
<div class="s">Podes fechar este separador e voltar ao Lexio Player.</div>
</div></body></html>"""


class _OAuthCatcher:
    """Local loopback server that catches the OAuth redirect from the Lexio backend.

    The backend, when given state="desktop:<port>", redirects the browser to
    http://127.0.0.1:<port>/callback?access_token=...&refresh_token=...&expires_in=...
    (RFC 8252 native-app loopback flow). We read those tokens here.
    """
    def __init__(self):
        self._auth = None
        self._event = threading.Event()
        self._srv = HTTPServer(("127.0.0.1", 0), self._make_handler())
        self.port = self._srv.server_address[1]

    def _make_handler(self):
        catcher = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass  # silence default stderr logging

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                q = parse_qs(parsed.query)
                at = (q.get("access_token") or [""])[0]
                if at:
                    try:
                        exp = int((q.get("expires_in") or ["3600"])[0] or 3600)
                    except ValueError:
                        exp = 3600
                    catcher._auth = {
                        "access_token": at,
                        "refresh_token": (q.get("refresh_token") or [""])[0],
                        "expires_in": exp,
                        "expires_at": datetime.now().timestamp() + exp,
                        "saved": datetime.now().isoformat(),
                    }
                    log("OAuthCatcher: access_token received on loopback")
                body = _LOGIN_DONE_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                catcher._event.set()

        return Handler

    def start(self):
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self.port

    def wait(self, timeout=300):
        self._event.wait(timeout)
        return self._auth

    def stop(self):
        try: self._srv.shutdown()
        except Exception: pass
        try: self._srv.server_close()
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# CHAT IA
# ═══════════════════════════════════════════════════════════════════════════

class ChatPanel(QWidget):
    # Emitted from worker threads → delivered on the GUI thread (queued connection).
    login_result = pyqtSignal(object, object)          # (auth_data | None, error | None)
    chat_result = pyqtSignal(object, object, object, bool)  # (resp, err, loader, relogin)
    promote_result = pyqtSignal(object, object)        # (word, error | None) — add-to-main-vocab
    user_ctx_ready = pyqtSignal(object)                # (dict) — perfil + atividade lidos da conta

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages = []
        self._token = self._load_token()
        self._user_name = ""           # nome do utilizador (perfil da web)
        self._user_target = ""         # língua-alvo da conta
        self._activity_summary = ""    # resumo da atividade (player+web) p/ a IA "conhecer" o user
        self._setup_ui()
        self._ai_thread = None
        self.login_result.connect(self._on_login_done)
        self.chat_result.connect(self._on_chat_result)
        self.promote_result.connect(self._on_promote_result)
        self.user_ctx_ready.connect(self._on_user_ctx)
        # Se já há sessão guardada, conhece o utilizador logo ao arrancar.
        if self._token and self._token.get("access_token"):
            QTimer.singleShot(800, self._fetch_user_context)

    def _load_token(self):
        """Load full auth data from token file."""
        try:
            if TOKEN_FILE.exists():
                data = json.loads(TOKEN_FILE.read_text())
                # Support both old (simple token) and new (full auth) formats
                if "access_token" in data:
                    return data
                token = data.get("token")
                if token and token != "connected":
                    # Migrate old format to new
                    auth_data = {"access_token": token, "saved": data.get("saved", "")}
                    self._save_token_data(auth_data)
                    return auth_data
        except: pass
        return None

    def _save_token_data(self, auth_data):
        """Save full auth data to token file."""
        try:
            TOKEN_FILE.write_text(json.dumps(auth_data, indent=2))
            self._token = auth_data
        except: pass

    def _save_token(self, t):
        """Legacy: save simple token string — used internally."""
        try:
            TOKEN_FILE.write_text(json.dumps({"token": t, "saved": datetime.now().isoformat()}))
            self._token = {"access_token": t, "saved": datetime.now().isoformat()}
        except: pass

    def _clear_token(self):
        try:
            TOKEN_FILE.unlink()
        except: pass
        self._token = None

    def _refresh_token(self):
        """Try to refresh the Supabase JWT using refresh_token."""
        auth = self._token
        if not auth or not auth.get("refresh_token"):
            log("Token refresh: no refresh_token available")
            return False
        try:
            log("Token refresh: attempting...")
            # Supabase token refresh endpoint
            supabase_url = "https://lobwdstwpcbuljferyyo.supabase.co"
            r = urlopen(Request(
                f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
                data=json.dumps({"refresh_token": auth["refresh_token"]}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "apikey": SUPABASE_ANON,
                },
            ), timeout=15)
            data = json.loads(r.read().decode())
            if data.get("access_token"):
                new_auth = {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", auth.get("refresh_token")),
                    "expires_in": data.get("expires_in", 3600),
                    "expires_at": datetime.now().timestamp() + data.get("expires_in", 3600),
                    "saved": datetime.now().isoformat(),
                }
                self._save_token_data(new_auth)
                log("Token refresh: success")
                return True
            log(f"Token refresh: no access_token in response")
            return False
        except Exception as e:
            log(f"Token refresh failed: {e}")
            return False

    def _get_token_header(self):
        """Get Authorization header value, refreshing if needed."""
        auth = self._token
        if not auth:
            return None
        # Check expiry
        expires_at = auth.get("expires_at", 0)
        if expires_at and datetime.now().timestamp() > expires_at - 300:  # 5min buffer
            if self._refresh_token():
                auth = self._token
        token = auth.get("access_token") or auth.get("token")
        return f"Bearer {token}" if token else None

    def _setup_ui(self):
        self.setStyleSheet(f"background:{SRF};border-left:1px solid {BRD};")
        lo = QVBoxLayout(self); lo.setContentsMargins(0,0,0,0); lo.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12,0,8,0)
        title = QLabel(T("chat_ai"))
        title.setStyleSheet(f"color:{TXT};font-size:14px;font-weight:600;font-family:'Inter';background:transparent;")
        hl.addWidget(title)
        hl.addStretch()
        self.login_btn = QPushButton(T("login") if not self._token else T("account"))
        self.login_btn.setFixedSize(46,22)
        self.login_btn.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {BRD};border-radius:11px;color:{TS2};font-size:11px;}}QPushButton:hover{{background:{HVR};color:{TXT};}}")
        self.login_btn.clicked.connect(self._handle_login)
        hl.addWidget(self.login_btn)
        lo.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{SRF};border:none;}}QScrollBar:vertical{{background:{BG};width:6px;}}QScrollBar::handle:vertical{{background:{HVR};border-radius:3px;}}")
        self.mw = QWidget(); self.mw.setStyleSheet(f"background:{SRF};")
        self.ml = QVBoxLayout(self.mw); self.ml.setContentsMargins(12,12,12,12); self.ml.setSpacing(10)
        self.ml.addStretch()
        scroll.setWidget(self.mw)
        lo.addWidget(scroll, 1)

        self.welcome = QLabel(T("chat_welcome"))
        self.welcome.setStyleSheet(f"color:{TMT};font-size:12.5px;font-family:'Inter';line-height:1.6;background:transparent;padding:24px;")
        self.welcome.setWordWrap(True); self.welcome.setAlignment(Qt.AlignCenter)
        self.ml.insertWidget(0, self.welcome)

        inp = QWidget(); inp.setStyleSheet(f"background:{ELV};border-top:1px solid {BRD};")
        il = QHBoxLayout(inp); il.setContentsMargins(6,6,6,6)
        self.input = QLineEdit()
        self.input.setPlaceholderText(T("chat_placeholder"))
        self.input.setStyleSheet(f"QLineEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:19px;padding:9px 15px;font-size:12.5px;font-family:'Inter';}}QLineEdit:focus{{border-color:{ACC};background:{HVR};}}")
        self.input.returnPressed.connect(self._send)
        il.addWidget(self.input, 1)
        send = QPushButton("->")
        send.setFixedSize(36,36)
        send.setStyleSheet(f"QPushButton{{background:{ACC};border:none;border-radius:15px;color:{ON_ACC};font-size:13px;font-weight:bold;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        send.clicked.connect(self._send)
        il.addWidget(send)
        lo.addWidget(inp)

    def _handle_login(self):
        # Already have a session? Just offer logout. We must NOT call
        # _get_token_header() here — it can trigger a synchronous network token
        # refresh ON THE GUI THREAD, which froze the whole app. Token validity is
        # re-checked off-thread on the next chat request anyway.
        if self._token and self._token.get("access_token"):
            reply = QMessageBox.question(
                None, "Lexio Player",
                "Já tens sessão iniciada.\n\nDesejas terminar sessão?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._clear_token()
                self.login_btn.setText("Login")
                self._add_msg(T("session_ended"), "system")
            return

        # System-browser OAuth: Google blocks login inside embedded webviews, so we
        # open the user's real browser and capture the redirect on a loopback server.
        self.login_btn.setEnabled(False)
        self.welcome.hide()
        self._add_msg(T("login_open_browser"), "system")
        threading.Thread(target=self._login_flow, daemon=True).start()

    def _login_flow(self):
        """Runs off the GUI thread: start loopback server, open browser, wait for token."""
        catcher = None
        try:
            catcher = _OAuthCatcher()
            port = catcher.start()
            req = Request(f"{LEXIO_API}/api/auth?state=desktop:{port}",
                          headers={"User-Agent": APP_NAME})
            url = json.loads(urlopen(req, timeout=15).read().decode()).get("url")
            if not url:
                raise RuntimeError("URL de login não recebido do servidor")
            log(f"Login: opening system browser (loopback port {port})")
            webbrowser.open(url)
            auth = catcher.wait(timeout=300)
            # Persist the token here on the worker thread (file write is safe and does
            # not need the GUI), so the chat is authenticated even if the GUI update lags.
            if auth and auth.get("access_token"):
                self._save_token_data(auth)
                log("Login: token saved to disk")
            else:
                log("Login: no token captured (timeout/cancel)")
            # Marshal the GUI update onto the main thread via a queued signal.
            self.login_result.emit(auth, None)
        except Exception as e:
            log(f"Login flow error: {e}")
            self.login_result.emit(None, str(e))
        finally:
            if catcher:
                catcher.stop()

    def _on_login_done(self, auth, err):
        self.login_btn.setEnabled(True)
        if auth and auth.get("access_token"):
            self._save_token_data(auth)
            self.login_btn.setText(T("account"))
            self._add_msg(T("login_connected"), "system")
            log("Login: success, token saved")
            self._fetch_user_context()   # conhece o utilizador (perfil + atividade)
        elif err:
            self._add_msg(T("login_failed", err=err), "system")
        else:
            self._add_msg(T("login_cancelled"), "system")

    # ── Conhecer o utilizador: lê perfil + atividade da conta web ──
    def _fetch_user_context(self):
        header = self._get_token_header()
        if not header:
            return
        threading.Thread(target=self._user_ctx_worker, args=(header,), daemon=True).start()

    def _user_ctx_worker(self, header):
        import base64
        try:
            tok = header.split(" ", 1)[1]; pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                return
            ih = {"apikey": SUPABASE_ANON, "Authorization": header}
            info = {"name": "", "target": "", "videos": []}
            try:
                u = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{uid}&select=display_name,target_lang"
                d = json.loads(urlopen(Request(u, headers=ih), timeout=15).read().decode())
                if d:
                    info["name"] = d[0].get("display_name") or ""
                    info["target"] = d[0].get("target_lang") or ""
            except Exception as e:
                log(f"profile fetch: {e}")
            try:
                u = (f"{SUPABASE_URL}/rest/v1/player_sessions?user_id=eq.{uid}"
                     "&select=video_title&order=started_at.desc&limit=15")
                d = json.loads(urlopen(Request(u, headers=ih), timeout=15).read().decode())
                seen = set()
                for r in d:
                    v = (r.get("video_title") or "").strip()
                    if v and v not in seen:
                        seen.add(v); info["videos"].append(v)
            except Exception as e:
                log(f"sessions fetch: {e}")
            self.user_ctx_ready.emit(info)
        except Exception as e:
            log(f"user ctx: {e}")

    def _on_user_ctx(self, info):
        self._user_name = info.get("name", "") or ""
        self._user_target = info.get("target", "") or ""
        vids = (info.get("videos") or [])[:6]
        parts = []
        if self._user_target:
            parts.append(f"Their learning language is {self._user_target}.")
        if vids:
            parts.append("Recently watched on the Lexio player: " + "; ".join(vids) + ".")
        self._activity_summary = " ".join(parts)
        if self._user_name:
            self._add_msg(T("greet_user", name=self._user_name), "system")

    def _send(self):
        t = self.input.text().strip()
        if not t: return
        self.input.clear(); self._add_msg(t, "user"); self.welcome.hide()
        # Keep a rolling conversation history so the chat has memory (last ~20 turns).
        self._messages.append({"role": "user", "content": t})
        if len(self._messages) > 20:
            self._messages = self._messages[-20:]
        self._call_ai(t)

    def _add_msg(self, text, role):
        align = Qt.AlignRight if role == "user" else Qt.AlignLeft
        if role == "user":
            # WhatsApp-style outgoing bubble (right-aligned), dark grey
            bub = "background:#2b2b2b;border:none;border-radius:16px 16px 4px 16px;"; fg = TXT
        elif role == "system":
            bub = "background:transparent;border:none;"; fg = TMT
        else:
            # AI reply: no bubble, no border — plain markdown like the web chat
            bub = "background:transparent;border:none;"; fg = TXT

        # Bubble = container with the background; padding via layout margins (NOT
        # QLabel stylesheet padding, which clips word-wrapped rich text).
        bubble = QWidget(); bubble.setObjectName("bub")
        bubble.setAttribute(Qt.WA_StyledBackground, True)
        bubble.setStyleSheet(f"#bub{{{bub}}}")
        bl = QVBoxLayout(bubble); bl.setContentsMargins(13, 9, 13, 9); bl.setSpacing(0)

        msg = QLabel(); msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        msg.setOpenExternalLinks(True)
        # AI replies render as real Markdown (bold, lists, code, headings, links);
        # user/system stay plain.
        msg.setTextFormat(Qt.MarkdownText if role == "assistant" else Qt.PlainText)
        msg.setText(text)
        msg.setStyleSheet(f"QLabel{{background:transparent;color:{fg};font-size:12.5px;}}"
                          f"QLabel a{{color:{ACC};}}")
        msg.setMaximumWidth(252)
        bl.addWidget(msg)

        c = QWidget(); c.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(c); cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(bubble, 0, align)
        self.ml.insertWidget(self.ml.count() - 1, c)

    def _call_ai(self, text):
        load = QLabel(T("thinking")); load.setStyleSheet(f"color:{ACC};font-size:11px;padding:4px;background:transparent;font-weight:bold;")
        lc = QWidget(); lc.setStyleSheet("background:transparent;")
        lcl = QVBoxLayout(lc); lcl.setContentsMargins(0,0,0,0)
        lcl.addWidget(load, 0, Qt.AlignLeft)
        self.ml.insertWidget(self.ml.count()-1, lc)

        # Auto-scroll to bottom
        scroll = self.findChild(QScrollArea)
        if scroll:
            QTimer.singleShot(50, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))

        def work():
            try:
                # Contexto que faz a IA CONHECER o utilizador a partir do uso do
                # player: língua nativa, vídeo atual, e as palavras que ele guardou.
                parts = ["You are Lexio's in-player AI tutor for a language learner watching a video.",
                         f"Always reply in the user's native language ({native_language_name()}), warm and concise."]
                if self._user_name:
                    parts.append(f"The user's name is {self._user_name}.")
                if self._activity_summary:
                    parts.append("What you already know about this user (across the Lexio web app "
                                 "and desktop player): " + self._activity_summary)
                video_name = None
                if self.parent() and hasattr(self.parent(), 'engine') and self.parent().engine.path():
                    video_name = Path(self.parent().engine.path()).name
                    parts.append(f"They are currently watching: {video_name}")
                try:
                    _vf = DATA_DIR / 'saved-vocab.json'
                    if _vf.exists():
                        _saved = json.loads(_vf.read_text(encoding='utf-8'))
                        _words = [s.get('text', '') for s in _saved[-30:] if s.get('text')]
                        if _words:
                            parts.append("Words/phrases this user saved from videos (use them to "
                                         "personalise help, examples and quick reviews): " + "; ".join(_words))
                except Exception:
                    pass
                ctx = "\n".join(parts)
                hdrs = {"Content-Type":"application/json"}
                # Send real JWT if authenticated
                auth_header = self._get_token_header()
                if auth_header:
                    hdrs["Authorization"] = auth_header
                    log(f"Chat: sending request with JWT")
                else:
                    log(f"Chat: sending request without auth")
                # System prompt + rolling history (already includes the current user
                # message) so the backend sees the conversation, not a lone message.
                msgs = [{"role": "system", "content": ctx}] + self._messages[-10:]
                payload = {"model": "deepseek-chat", "max_tokens": 1500, "temperature": 0.5,
                           "feature": "chat", "messages": msgs}
                if video_name:
                    payload["videoContext"] = video_name
                body = json.dumps(payload).encode()
                log(f"Chat calling API: {text[:60]}...")
                r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body, headers=hdrs), timeout=45)
                d = json.loads(r.read().decode())
                c = d.get("text") or d.get("content") or ""
                if not c and "choices" in d: c = d["choices"][0]["message"]["content"]
                log(f"Chat got response: {c[:60] if c else 'empty'}...")
                # Deliver to the GUI thread via queued signal (QTimer from a worker
                # thread does NOT fire — it has no event loop).
                self.chat_result.emit(c.strip() or "Sem resposta", None, lc, False)
            except HTTPError as e:
                err_body = ""
                try: err_body = e.read().decode()[:200]
                except: pass
                log(f"Chat err: {e.code} {err_body}")
                if e.code == 401:
                    self._clear_token()  # file/attr op — safe off the GUI thread
                    self.chat_result.emit(None, "Faz login para usar o chat IA.", lc, True)
                elif e.code == 402:
                    self.chat_result.emit(None, "Atingiste o limite grátis de hoje. Subscreve em lexio.app para chat ilimitado.", lc, False)
                elif e.code == 403:
                    self.chat_result.emit(None, "Sem subscrição ativa. Acede a lexio.app para premium.", lc, False)
                else:
                    self.chat_result.emit(None, str(e), lc, False)
            except Exception as e:
                log(f"Chat err: {e}")
                self.chat_result.emit(None, str(e), lc, False)
        threading.Thread(target=work, daemon=True).start()

    def _on_chat_result(self, resp, err, lc, relogin):
        """Runs on the GUI thread (queued signal) — remove the loader and show the reply."""
        try: lc.deleteLater()
        except Exception: pass
        if relogin:
            self.login_btn.setText("Login")
        if err:
            self._add_msg(f"Erro: {err}", "system")
        else:
            self._add_msg(resp or "Sem resposta", "assistant")
            # Persist the assistant turn so the conversation keeps context.
            if resp:
                self._messages.append({"role": "assistant", "content": resp})
                if len(self._messages) > 20:
                    self._messages = self._messages[-20:]
        scroll = self.findChild(QScrollArea)
        if scroll:
            QTimer.singleShot(50, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))

    # ── Promote a video-vocab word to the user's MAIN account vocabulary ──
    def promote_word(self, text):
        if not text:
            return
        header = self._get_token_header()
        if not header:
            self._add_msg(T("need_login_vocab"), "system")
            return
        self._add_msg(f"A adicionar “{text[:40]}” ao teu vocabulário…", "system")
        threading.Thread(target=self._promote_worker, args=(text, header), daemon=True).start()

    def _promote_worker(self, text, header):
        import base64
        try:
            sys_p = ("You build one vocabulary study card. Reply ONLY with compact JSON, no prose: "
                     '{"word":"<lemma>","lang":"<ISO 639-1 of the word language>",'
                     '"translation":"<European Portuguese translation>",'
                     '"definition":"<short definition in the word language>","examples":["<ex1>","<ex2>"]}')
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 400, "temperature": 0.2,
                               "messages": [{"role": "system", "content": sys_p},
                                            {"role": "user", "content": f'Word or phrase: "{text}"'}]}).encode()
            hdrs = {"Content-Type": "application/json", "Authorization": header}
            r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body, headers=hdrs), timeout=45)
            d = json.loads(r.read().decode())
            raw = (d.get("text") or "").strip()
            if not raw and d.get("choices"):
                raw = d["choices"][0].get("message", {}).get("content", "")
            raw = raw.strip().strip("`")
            pack = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])

            tok = header.split(" ", 1)[1]
            pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                raise RuntimeError("sem user id no token")

            row = {
                "user_id": uid, "word": pack.get("word") or text,
                "lang": (pack.get("lang") or "en")[:5], "translation": pack.get("translation", ""),
                "type": "word", "definition": pack.get("definition", ""),
                "examples": pack.get("examples") or [], "tags": ["video"],
                "interval": 0, "ease_factor": 2.5, "repetitions": 0,
                "due_date": datetime.now().isoformat(), "status": "new",
            }
            ih = {"Content-Type": "application/json", "apikey": SUPABASE_ANON,
                  "Authorization": header, "Prefer": "return=minimal"}
            urlopen(Request(f"{SUPABASE_URL}/rest/v1/words", data=json.dumps(row).encode(), headers=ih), timeout=30)
            self.promote_result.emit(text, None)
        except HTTPError as e:
            self.promote_result.emit(text, f"HTTP {e.code}")
        except Exception as e:
            log(f"promote worker: {e}")
            self.promote_result.emit(text, str(e))

    def _on_promote_result(self, word, err):
        if err:
            self._add_msg(f"Não consegui adicionar “{word[:30]}”: {err}", "system")
        else:
            self._add_msg(f"Adicionado: “{word[:30]}” ao teu vocabulário principal.", "system")

    # ── Sync a "+"-saved word to the cloud as PENDING (table saved_words) ──
    def sync_saved_word(self, text, video=""):
        """Fire-and-forget push so the word also shows on the web as a pending
        item the user can Add-to-vocabulary or Discard. Silent (no chat spam):
        if logged out it just stays local in the Vídeos tab."""
        if not text:
            return False
        header = self._get_token_header()
        if not header:
            return False
        threading.Thread(target=self._sync_saved_worker,
                         args=(text, video, header), daemon=True).start()
        return True

    def _sync_saved_worker(self, text, video, header):
        import base64
        try:
            tok = header.split(" ", 1)[1]
            pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                return
            row = {"user_id": uid, "text": text, "word": text.split()[0] if text.split() else text,
                   "lang": "en", "source": "player", "video": video or ""}
            ih = {"Content-Type": "application/json", "apikey": SUPABASE_ANON,
                  "Authorization": header, "Prefer": "resolution=ignore-duplicates,return=minimal"}
            urlopen(Request(f"{SUPABASE_URL}/rest/v1/saved_words",
                            data=json.dumps(row).encode(), headers=ih), timeout=20)
            log(f"saved_words synced: {text[:30]}")
        except Exception as e:
            log(f"sync saved word: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# STUDY MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class StudyMgr:
    def __init__(self):
        self.d = self._load()
    def _load(self):
        try:
            if STUDY_FILE.exists(): return json.loads(STUDY_FILE.read_text(encoding='utf-8'))
        except: pass
        return {"bookmarks":{},"annotations":{}}
    def save(self):
        try: STUDY_FILE.write_text(json.dumps(self.d, indent=2, ensure_ascii=False), encoding='utf-8')
        except: pass
    def add_bm(self, v, pos, label="", note=""):
        self.d["bookmarks"].setdefault(str(v),[]).append({"pos":pos,"label":label or f"Marco {len(self.d['bookmarks'].get(str(v),[]))+1}","note":note,"created":datetime.now().isoformat()}); self.save()
    def get_bm(self, v): return self.d["bookmarks"].get(str(v),[])
    def del_bm(self, v, i):
        m=self.d["bookmarks"].get(str(v),[]);
        if 0<=i<len(m): del m[i]; self.save(); return True
    def add_an(self, v, pos, text):
        self.d["annotations"].setdefault(str(v),[]).append({"pos":pos,"text":text,"created":datetime.now().isoformat()}); self.save()
    def get_an(self, v): return self.d["annotations"].get(str(v),[])
    def del_an(self, v, i):
        a=self.d["annotations"].get(str(v),[]);
        if 0<=i<len(a): del a[i]; self.save(); return True
    def export(self, v):
        return json.dumps({"video":Path(v).name,"path":str(v),"exported":datetime.now().isoformat(),"bookmarks":self.get_bm(v),"annotations":self.get_an(v)}, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════

class WordDetailsPanel(QWidget):
    """Rich word-details panel like the web VocabSidebar: word + audio, phonetic,
    type, meaning, one example at a time (prev/next) with an image that
    illustrates THAT example, synonyms, collocations, note."""
    _ready = pyqtSignal(object, object)
    _img_ready = pyqtSignal(object)    # (example_index, image_bytes)

    def __init__(self, parent, chat):
        super().__init__(parent)
        self._chat = chat
        self._word = ""; self._lang = "en"; self._meaning = ""
        self._examples = []; self._ex_idx = 0
        self._tts_player = None
        self.setStyleSheet(f"background:{SRF};border-right:1px solid {BRD};")
        self.setMinimumWidth(330); self.setMaximumWidth(440)
        lo = QVBoxLayout(self); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)

        hdr = QWidget(); hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 10, 10, 10)
        ht = QLabel(T("details")); ht.setStyleSheet(
            f"color:{TXT};font-size:13px;font-weight:600;font-family:'Inter';background:transparent;")
        hl.addWidget(ht); hl.addStretch()
        close = QPushButton("×"); close.setFixedSize(24, 24); close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TMT};font-size:17px;}}"
                            f"QPushButton:hover{{color:{TXT};}}")
        close.clicked.connect(self.hide); hl.addWidget(close)
        lo.addWidget(hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{SRF};border:none;}}"
                             f"QScrollBar:vertical{{background:{BG};width:8px;}}"
                             f"QScrollBar::handle:vertical{{background:{HVR};border-radius:4px;}}")
        inner = QWidget(); inner.setStyleSheet(f"background:{SRF};")
        il = QVBoxLayout(inner); il.setContentsMargins(16, 14, 16, 16); il.setSpacing(8)

        wr = QHBoxLayout(); wr.setSpacing(8)
        self.word_lbl = QLabel(""); self.word_lbl.setWordWrap(True)
        self.word_lbl.setStyleSheet(
            f"color:{TXT};font-size:22px;font-weight:800;font-family:'Inter';background:transparent;")
        wr.addWidget(self.word_lbl)
        self.listen_btn = QPushButton(T("listen")); self.listen_btn.setCursor(Qt.PointingHandCursor); self.listen_btn.setFixedHeight(26)
        self.listen_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:13px;"
            f"padding:2px 12px;font-size:11px;font-family:'Inter';}}QPushButton:hover{{border-color:{ACC};color:{TXT};}}")
        self.listen_btn.clicked.connect(self._play_tts)
        wr.addWidget(self.listen_btn)
        # YouGlish button — opens the word on YouGlish in the browser
        self.yg_btn = QPushButton("YG"); self.yg_btn.setCursor(Qt.PointingHandCursor); self.yg_btn.setFixedHeight(26)
        self.yg_btn.setToolTip(T("yg_tip"))
        self.yg_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:13px;"
            f"padding:2px 8px;font-size:10px;font-family:'Inter';font-weight:700;}}"
            f"QPushButton:hover{{border-color:{ACC};color:{TXT};}}")
        self.yg_btn.clicked.connect(self._open_youglish)
        wr.addWidget(self.yg_btn); wr.addStretch()
        il.addLayout(wr)

        self.meta_lbl = QLabel(""); self.meta_lbl.setWordWrap(True)
        self.meta_lbl.setStyleSheet(f"color:{TMT};font-size:12px;font-family:'Inter';background:transparent;")
        il.addWidget(self.meta_lbl)

        self.meaning_lbl = QLabel(""); self.meaning_lbl.setWordWrap(True)
        self.meaning_lbl.setStyleSheet(f"color:{TXT};font-size:13.5px;font-family:'Inter';background:transparent;")
        il.addWidget(self.meaning_lbl)

        # ── Examples block: counter + nav, example text, and an image of it ──
        self.ex_box = QWidget(); self.ex_box.setStyleSheet("background:transparent;")
        exl = QVBoxLayout(self.ex_box); exl.setContentsMargins(0, 6, 0, 0); exl.setSpacing(6)
        exhead = QHBoxLayout(); exhead.setSpacing(6)
        exlab = QLabel(T("example")); exlab.setStyleSheet(
            f"color:{TMT};font-size:11px;font-weight:700;letter-spacing:.04em;background:transparent;")
        exhead.addWidget(exlab)
        self.ex_counter = QLabel(""); self.ex_counter.setStyleSheet(
            f"color:{TMT};font-size:11px;background:transparent;")
        exhead.addWidget(self.ex_counter); exhead.addStretch()
        def navbtn(txt):
            b = QPushButton(txt); b.setFixedSize(24, 24); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                            f"border-radius:12px;font-size:13px;}}QPushButton:hover{{border-color:{ACC};color:{TXT};}}"
                            f"QPushButton:disabled{{color:{BRD};border-color:{BRD};}}")
            return b
        self.ex_prev = navbtn("‹"); self.ex_prev.clicked.connect(lambda: self._show_example(self._ex_idx - 1))
        self.ex_next = navbtn("›"); self.ex_next.clicked.connect(lambda: self._show_example(self._ex_idx + 1))
        exhead.addWidget(self.ex_prev); exhead.addWidget(self.ex_next)
        exl.addLayout(exhead)
        self.ex_text = QLabel(""); self.ex_text.setWordWrap(True)
        self.ex_text.setStyleSheet(f"color:{TXT};font-size:13px;font-style:italic;font-family:'Inter';background:transparent;")
        exl.addWidget(self.ex_text)
        self.ex_img = QLabel(""); self.ex_img.setMinimumHeight(60)
        self.ex_img.setAlignment(Qt.AlignCenter)
        self.ex_img.setStyleSheet(f"background:{ELV};border:1px solid {BRD};border-radius:10px;color:{TMT};font-size:11px;")
        exl.addWidget(self.ex_img)
        self.ex_box.hide()
        il.addWidget(self.ex_box)

        self.extra_lbl = QLabel(""); self.extra_lbl.setWordWrap(True); self.extra_lbl.setTextFormat(Qt.RichText)
        self.extra_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse); self.extra_lbl.setAlignment(Qt.AlignTop)
        self.extra_lbl.setStyleSheet(f"color:{TXT};font-size:12.5px;font-family:'Inter';background:transparent;")
        il.addWidget(self.extra_lbl); il.addStretch()
        scroll.setWidget(inner); lo.addWidget(scroll, 1)

        ftr = QWidget(); ftr.setStyleSheet(f"background:{ELV};border-top:1px solid {BRD};")
        fl = QVBoxLayout(ftr); fl.setContentsMargins(12, 10, 12, 10)
        self.add_btn = QPushButton(T("add_vocab")); self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;padding:9px;"
            f"font-size:12px;font-weight:600;font-family:'Inter';}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.add_btn.clicked.connect(self._add)
        fl.addWidget(self.add_btn); lo.addWidget(ftr)

        self._ready.connect(self._on_ready)
        self._img_ready.connect(self._on_img)
        self.hide()

    def show_for(self, word):
        self._word = word; self._lang = "en"; self._examples = []; self._ex_idx = 0
        self.word_lbl.setText(word); self.meta_lbl.setText(""); self.meaning_lbl.setText("")
        self.extra_lbl.setText(T("loading_details")); self.ex_box.hide()
        self.show(); fade_in(self, 200)
        threading.Thread(target=self._worker, args=(word,), daemon=True).start()

    def _worker(self, word):
        try:
            nat = native_language_name()   # língua nativa do utilizador (herda da conta)
            sys_p = (
                f"You are a bilingual dictionary for a learner whose native language is {nat}. "
                "Detect the language of the given word/phrase. Reply ONLY with compact JSON, no prose:\n"
                '{"word":"<lemma>","lang":"<ISO 639-1>","phonetic":"<IPA>","type":"<noun/verb/adj/adv/phrase>",'
                '"meaning":"<clear definition in the word OWN language>",'
                '"examples":["<ex1 in the word language>","<ex2>","<ex3>"],'
                f'"synonyms":[{{"word":"<syn>","translation":"<{nat}>"}}],'
                f'"collocations":[{{"phrase":"<colloc>","translation":"<{nat}>"}}],'
                f'"note":"<short usage note in {nat}>"}}')
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 900, "temperature": 0.2,
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": f'Word/phrase: "{word}"'}]}).encode()
            r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                headers={"Content-Type": "application/json"}), timeout=45)
            d = json.loads(r.read().decode())
            raw = (d.get("text") or "").strip().strip("`")
            self._ready.emit(json.loads(raw[raw.find("{"):raw.rfind("}") + 1]), None)
        except Exception as e:
            log(f"word details: {e}")
            self._ready.emit(None, str(e))

    @staticmethod
    def _esc(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _on_ready(self, data, err):
        if err or not data:
            self.extra_lbl.setText(T("details_failed")); return
        self._lang = (data.get("lang") or "en")[:5]
        self.word_lbl.setText(self._esc(data.get("word") or self._word))
        self.meta_lbl.setText(" · ".join([x for x in [self._esc(data.get("phonetic", "")),
                                                       self._esc(data.get("type", ""))] if x]))
        self.meaning_lbl.setText(data.get("meaning", ""))
        self._meaning = data.get("meaning", "")
        self._examples = [e for e in (data.get("examples") or []) if e][:3]
        if self._examples:
            self.ex_box.show(); self._show_example(0)
        else:
            self.ex_box.hide()
        lbl = lambda t: f"<p style='color:{TMT};font-size:11px;font-weight:700;letter-spacing:.04em;margin:8px 0 4px 0'>{t}</p>"
        parts = []
        syns = data.get("synonyms") or []
        if syns:
            parts.append(lbl(T("synonyms")) + "<p style='margin:0 0 6px 0;line-height:1.7'>")
            for sy in syns[:6]:
                w = sy.get("word", "") if isinstance(sy, dict) else sy
                tr = sy.get("translation", "") if isinstance(sy, dict) else ""
                parts.append(f"<span style='color:{ACC}'>{self._esc(w)}</span>"
                             + (f" <span style='color:{TMT}'>— {self._esc(tr)}</span>" if tr else "") + "<br>")
            parts.append("</p>")
        colls = data.get("collocations") or []
        if colls:
            parts.append(lbl(T("collocations")) + "<p style='margin:0 0 6px 0;line-height:1.7'>")
            for c in colls[:6]:
                ph = c.get("phrase", "") if isinstance(c, dict) else c
                tr = c.get("translation", "") if isinstance(c, dict) else ""
                parts.append(f"{self._esc(ph)}"
                             + (f" <span style='color:{TMT}'>— {self._esc(tr)}</span>" if tr else "") + "<br>")
            parts.append("</p>")
        if data.get("note"):
            parts.append(lbl(T("note")) + f"<p style='margin:0;color:{TXT}'>{self._esc(data['note'])}</p>")
        self.extra_lbl.setText("".join(parts))

    def _show_example(self, idx):
        if not self._examples:
            return
        idx = max(0, min(idx, len(self._examples) - 1))
        self._ex_idx = idx
        ex = self._examples[idx]
        self.ex_text.setText(f"“{ex}”")
        self.ex_counter.setText(f"{idx + 1} / {len(self._examples)}")
        self.ex_prev.setEnabled(idx > 0); self.ex_next.setEnabled(idx < len(self._examples) - 1)
        self.ex_img.setPixmap(QPixmap()); self.ex_img.setText(T("gen_image"))
        threading.Thread(target=self._img_worker, args=(idx, ex), daemon=True).start()

    def _img_worker(self, idx, example):
        """Same image config as the web: ask /api/media-search for REAL photos
        (Unsplash→Tavily→SerpApi→Pollinations), then fall through Pollinations and
        LoremFlickr. Tries each candidate URL until one decodes; if the network is
        down entirely, _on_img draws the guaranteed local card."""
        # A short visual prompt built from the example (same as the web's dynamic
        # prompt) helps the real-image search return a relevant photo.
        image_prompt = _img_extract_context(example, self._word)
        candidates = build_image_candidates(self._word, example, self._meaning, image_prompt)
        for u in candidates:
            if idx != self._ex_idx:      # user navigated away — stop wasting data
                return
            try:
                req = Request(u, headers={"User-Agent": CHROME_UA, "Accept": "image/*"})
                raw = urlopen(req, timeout=30).read()
                if raw and len(raw) > 800 and idx == self._ex_idx:
                    self._img_ready.emit((idx, raw))
                    return
            except Exception as e:
                log(f"example image: {e}")
        self._img_ready.emit((idx, b""))   # all sources failed → guaranteed card

    def _on_img(self, payload):
        idx, raw = payload
        if idx != self._ex_idx:      # user already navigated away
            return
        w = max(180, self.ex_img.width() - 2)
        if raw:
            pm = QPixmap()
            if pm.loadFromData(raw):
                self.ex_img.setPixmap(pm.scaledToWidth(w, Qt.SmoothTransformation))
                self.ex_img.setText("")
                return
        # Guarantee an image (never just a blank/letter), exactly like the web's
        # local SVG card fallback.
        ex = self._examples[idx] if 0 <= idx < len(self._examples) else ""
        self.ex_img.setPixmap(local_card_pixmap(self._word, ex).scaledToWidth(w, Qt.SmoothTransformation))
        self.ex_img.setText("")

    def _play_tts(self):
        if not self._word:
            return
        threading.Thread(target=self._tts_worker, args=(self._word, self._lang or "en"), daemon=True).start()

    def _tts_worker(self, word, lang):
        try:
            import base64, tempfile
            body = json.dumps({"text": word, "languageCode": lang}).encode()
            r = urlopen(Request(f"{LEXIO_API}/api/tts", data=body,
                                headers={"Content-Type": "application/json"}), timeout=30)
            d = json.loads(r.read().decode())
            b64 = d.get("audioBase64")
            if not b64:
                return
            tmp = os.path.join(tempfile.gettempdir(), "lexio_tts.mp3")
            with open(tmp, "wb") as f:
                f.write(base64.b64decode(b64))
            import vlc
            if self._tts_player is None:
                self._tts_player = vlc.MediaPlayer()
            self._tts_player.set_mrl(tmp); self._tts_player.play()
        except Exception as e:
            log(f"tts: {e}")

    def _add(self):
        if self._chat and self._word:
            self._chat.promote_word(self._word)

    def _open_youglish(self):
        """Open the word on YouGlish for pronunciation in context."""
        if self._word:
            import urllib.parse
            query = urllib.parse.quote(self._word)
            webbrowser.open(f"https://youglish.com/pronounce/{query}/english/us")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._study_mode = False
        self._transport_overlay = None     # floating seek+controls window (study mode)
        self._transport_floating = False
        self._controls_state = {}  # save/restore visibility
        # Sessão do player → enviada p/ player_sessions (a IA da web fica a saber).
        self._session_start = None
        self._session_video = ""
        self._session_words = []
        try: self._setup()
        except Exception as e: log(f"FATAL: {e}\n{traceback.format_exc()}"); raise

    def _setup(self):
        self.video_path = None; self.mgr = StudyMgr()
        self._playlist = []; self._pl_idx = -1
        self._rate = 1.0; self._vol = 50; self._seeking = False
        self._tools_visible = True
        self._overlay_shown = False
        # Auto-hide for the fullscreen transport (seek + controls).
        self._fs_hide_timer = QTimer(self); self._fs_hide_timer.setSingleShot(True)
        self._fs_hide_timer.setInterval(2800)
        self._fs_hide_timer.timeout.connect(self._fs_hide_controls)
        self._setup_ui()
        self.engine.position_changed.connect(self._on_pos)
        self.engine.media_ended.connect(self._on_end)
        self.engine.playing_changed.connect(self._on_play)
        self.engine.duration_changed.connect(self._on_dur)
        # Wire overlay signals
        self.engine.subtitle_changed.connect(self.overlay.show_subtitle)
        self.engine.vocab_triggered.connect(self.overlay.show_vocab)
        self.overlay.add_word.connect(self._on_overlay_add)
        self.overlay.ask_ai.connect(self._on_overlay_ask)
        self.overlay.video_clicked.connect(self._toggle)
        self.overlay.toggle_fullscreen.connect(self._toggle_fs)
        self.overlay.mouse_moved.connect(self._fs_activity)
        self._load_recent()
        # Route shortcut keys app-wide (so they work even when the VLC video has
        # focus) — but never when typing in the chat / notes.
        QApplication.instance().installEventFilter(self)
        log("MainWindow ready")

    def _setup_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(900, 600); self.resize(1200, 780)
        self.setStyleSheet(f"QMainWindow{{background:{BG};color:{TXT};}}")

        c = QWidget(); self.setCentralWidget(c)
        outer = QVBoxLayout(c); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        # ═══ TOP BAR ═══
        top = QWidget(); top.setObjectName("top_bar"); top.setFixedHeight(44)
        top.setStyleSheet(f"background:{SRF};border-bottom:1px solid {BRD};")
        tl = QHBoxLayout(top); tl.setContentsMargins(16,0,12,0)
        logo = QLabel("▐█ Lexio"); logo.setStyleSheet(f"color:{ACC};font-size:15px;font-weight:bold;background:transparent;")
        tl.addWidget(logo)
        sub = QLabel(T("player")); sub.setStyleSheet(f"color:{TMT};font-size:12px;background:transparent;")
        tl.addWidget(sub); tl.addSpacing(12)
        self.tit = QLabel(""); self.tit.setStyleSheet(f"color:{TS2};font-size:12px;background:transparent;")
        tl.addWidget(self.tit, 1)

        # Chat toggle
        self.chat_toggle = QPushButton("Chat")
        self.chat_toggle.setFixedSize(50,28)
        self.chat_toggle.setToolTip(T("chat_toggle_tip"))
        self.chat_toggle.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {BRD};border-radius:14px;color:{TS2};font-size:11px;}}QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}QPushButton:checked{{background:rgba(255,255,255,0.14);border-color:{ACC};color:{ACC};}}")
        self.chat_toggle.setCheckable(True); self.chat_toggle.setChecked(True)
        self.chat_toggle.clicked.connect(self._toggle_chat)
        tl.addWidget(self.chat_toggle)

        ab = yt_btn(T("open_video"), accent=True, tip=T("open_video_tip")); ab.clicked.connect(self._open)
        tl.addWidget(ab)
        outer.addWidget(top)

        # ═══ BODY ═══
        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        body_lo = QHBoxLayout(body); body_lo.setContentsMargins(0,0,0,0); body_lo.setSpacing(0)

        left = QWidget(); left.setStyleSheet(f"background:{BG};")
        left_lo = QVBoxLayout(left); left_lo.setContentsMargins(0,0,0,0); left_lo.setSpacing(0)
        self._left_lo = left_lo   # kept so the transport can be floated/docked in study mode

        # Video engine
        self.engine = PlayerEngine()
        self.engine.setObjectName("player_engine")
        left_lo.addWidget(self.engine, 1)

        # Floating overlay — top-level frameless OS window (parent = MainWindow).
        # Sits ABOVE VLC's DirectX output within the app, not over other windows.
        self.overlay = VideoOverlay(self)
        self.overlay.setObjectName("video_overlay")
        # NOTE: do not show() here. The overlay is a top-level Qt.Tool window;
        # showing it before the main window has a native handle makes Windows
        # give it its own taskbar button (the "two apps" bug). We show it from
        # showEvent, once the main window owns it.

        # Seek bar
        sb = QWidget(); sb.setObjectName("seek_bar"); sb.setFixedHeight(34)
        sb.setStyleSheet(f"#seek_bar{{background:{SRF};}}")
        sl = QHBoxLayout(sb); sl.setContentsMargins(12,0,12,0); sl.setSpacing(8)
        self.tlbl = QLabel("0:00"); self.tlbl.setStyleSheet(f"color:{TMT};font-size:11px;min-width:38px;background:transparent;")
        sl.addWidget(self.tlbl)
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setFixedHeight(16)
        self.seek.setStyleSheet(f"QSlider::groove:horizontal{{background:{HVR};height:4px;border-radius:2px;}}QSlider::sub-page:horizontal{{background:{ACC};border-radius:2px;}}QSlider::handle:horizontal{{background:{ACC};width:14px;height:14px;margin:-5px 0;border-radius:7px;}}QSlider::handle:horizontal:hover{{background:{ACC_HOVER};}}")
        self.seek.sliderPressed.connect(lambda: setattr(self,'_seeking',True))
        self.seek.sliderReleased.connect(self._seek_to)
        self.seek.sliderMoved.connect(lambda v: self.tlbl.setText(FMT(v)))
        sl.addWidget(self.seek, 1)
        self.dlbl = QLabel("0:00"); self.dlbl.setStyleSheet(f"color:{TMT};font-size:11px;min-width:38px;background:transparent;")
        sl.addWidget(self.dlbl)
        left_lo.addWidget(sb)

        # Controls bar
        # Controls — Windows 11 Media Player style: native MDL2 icons, centred transport
        ICON_F = "'Segoe Fluent Icons','Segoe MDL2 Assets'"
        def _icn(glyph, size, fsize, tip=""):
            b = QPushButton(glyph); b.setFixedSize(size, size)
            if tip: b.setToolTip(tip)
            b.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TS2};font-family:{ICON_F};font-size:{fsize}px;border-radius:{size//2}px;}}QPushButton:hover{{background:{HVR};color:{TXT};}}")
            return b
        cb = QWidget(); cb.setObjectName("controls_bar"); cb.setFixedHeight(56)
        cb.setStyleSheet("#controls_bar{background:#1c1c1c;}")
        cl = QHBoxLayout(cb); cl.setContentsMargins(18,6,18,9); cl.setSpacing(6)

        self.pb = _icn(chr(0xE892), 38, 14, T("prev_p")); self.pb.clicked.connect(self._prev)
        self.play_btn = QPushButton(chr(0xE768)); self.play_btn.setFixedSize(46,46)
        self.play_btn.setStyleSheet(f"QPushButton{{background:{ACC};border:none;border-radius:23px;color:{ON_ACC};font-family:{ICON_F};font-size:18px;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.play_btn.clicked.connect(self._toggle)
        self.nb = _icn(chr(0xE893), 38, 14, T("next_n")); self.nb.clicked.connect(self._next)

        self.sub_btn = _icn(chr(0xE7F0), 36, 16, T("load_sub_tip"))
        self.sub_btn.clicked.connect(self._load_sub_file)
        self.sub_icon = QPushButton(""); self.sub_icon.setFixedSize(30,24)
        self.sub_icon.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TMT};font-size:10px;}}QPushButton:hover{{color:{ACC};}}")
        self.sub_icon.setToolTip(T("sub_toggle_tip"))
        self.sub_icon.clicked.connect(self._cycle_subs)

        self.vol_icon = QLabel(chr(0xE767)); self.vol_icon.setStyleSheet(f"color:{TS2};font-family:{ICON_F};font-size:15px;background:transparent;")
        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0,200); self.vol.setValue(50); self.vol.setFixedWidth(84)
        self.vol.setStyleSheet(f"QSlider::groove:horizontal{{background:{HVR};height:3px;border-radius:1.5px;}}QSlider::sub-page:horizontal{{background:{TS2};border-radius:1.5px;}}QSlider::handle:horizontal{{background:{TS2};width:11px;height:11px;margin:-4px 0;border-radius:5.5px;}}")
        self.vol.valueChanged.connect(lambda v: (self.engine.set_vol(v), setattr(self,'_vol',v)))

        self.spd = QPushButton("1.0x"); self.spd.setFixedSize(50,30)
        self.spd.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:15px;font-size:11px;font-weight:600;}}QPushButton:hover{{color:{TXT};border-color:{ACC};background:{HVR};}}")
        self.spd.clicked.connect(self._cycle_spd)

        # Chat toggle inside the controls bar too, so it's reachable in fullscreen
        # (the top-bar Chat button is hidden there). Checkable, kept in sync.
        self.chat_btn = QPushButton(chr(0xE8BD)); self.chat_btn.setFixedSize(38, 38)
        self.chat_btn.setCheckable(True); self.chat_btn.setChecked(True)
        self.chat_btn.setToolTip(T("chat_toggle_tip_c"))
        self.chat_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{TS2};font-family:{ICON_F};font-size:15px;border-radius:19px;}}"
            f"QPushButton:hover{{background:{HVR};color:{TXT};}}"
            f"QPushButton:checked{{color:{ACC};}}")
        self.chat_btn.clicked.connect(self._toggle_chat_btn)

        self.fs_btn = _icn(chr(0xE740), 38, 15, T("fullscreen_f")); self.fs_btn.clicked.connect(self._toggle_study_mode)

        # [speed] -- [prev . play . next] -- [CC . vol . chat . fullscreen]
        cl.addWidget(self.spd)
        cl.addStretch(1)
        cl.addWidget(self.pb); cl.addSpacing(6); cl.addWidget(self.play_btn); cl.addSpacing(6); cl.addWidget(self.nb)
        cl.addStretch(1)
        cl.addWidget(self.sub_btn); cl.addWidget(self.sub_icon); cl.addWidget(self.vol_icon); cl.addWidget(self.vol); cl.addWidget(self.chat_btn); cl.addWidget(self.fs_btn)
        left_lo.addWidget(cb)

        # ── Practice bar: physical buttons for the language-learning tools ──
        def prac_btn(label, tip, checkable=False):
            b = QPushButton(label); b.setToolTip(tip); b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                f"border-radius:13px;font-size:11px;padding:4px 11px;font-family:'Inter';}}"
                f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
                f"QPushButton:checked{{background:{HVR};color:{TXT};border-color:{ACC};}}")
            return b
        pbar = QWidget(); pbar.setObjectName("practice_bar"); pbar.setFixedHeight(38)
        pbar.setStyleSheet("#practice_bar{background:#141414;}")
        ppl = QHBoxLayout(pbar); ppl.setContentsMargins(16,3,16,5); ppl.setSpacing(6)
        plab = QLabel(T("practice")); plab.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;")
        ppl.addWidget(plab)
        b_rep = prac_btn(T("repeat"), "Repetir a frase atual (Z)"); b_rep.clicked.connect(self.engine.replay_sub)
        b_prev = prac_btn(T("previous"), "Frase anterior (,)"); b_prev.clicked.connect(self.engine.prev_sub)
        b_next = prac_btn(T("next"), "Frase seguinte (.)"); b_next.clicked.connect(self.engine.next_sub)
        b_a = prac_btn("A", "Marcar início do loop (manual)"); b_a.clicked.connect(self._set_loop_a)
        b_b = prac_btn("B", "Marcar fim do loop e ativar (manual)"); b_b.clicked.connect(self._set_loop_b)
        self.btn_loop = prac_btn(T("loop"), "Loop da frase atual / desligar (L)", True); self.btn_loop.clicked.connect(self._toggle_loop)
        self.btn_ap = prac_btn(T("autopause"), "Pausa no fim de cada frase — shadowing (X)", True); self.btn_ap.clicked.connect(self._toggle_autopause)
        self.btn_hide = prac_btn(T("hide_sub"), "Esconder legenda — recall ativo (H)", True); self.btn_hide.clicked.connect(self._toggle_hide_subs)
        for b in (b_rep, b_prev, b_next, b_a, b_b): ppl.addWidget(b)
        ppl.addStretch()
        for b in (self.btn_loop, self.btn_ap, self.btn_hide): ppl.addWidget(b)
        left_lo.addWidget(pbar)

        # ── Collapsible tools section ──
        self.tools_wrap = QWidget()
        self.tools_wrap.setStyleSheet(f"background:{SRF};border-top:1px solid {BRD};")
        twl = QVBoxLayout(self.tools_wrap); twl.setContentsMargins(0,0,0,0); twl.setSpacing(0)

        tabs = QTabWidget()
        self.tabs = tabs   # referenced so saving a word can jump to the Vídeos tab
        tabs.setStyleSheet(
            f"QTabWidget::pane{{background:{SRF};border:none;}}"
            f"QTabBar{{background:{SRF};qproperty-drawBase:0;}}"
            f"QTabBar::tab{{background:transparent;color:{TMT};padding:8px 16px;border:none;"
            f"font-size:11px;font-weight:600;font-family:'Inter';margin-right:2px;}}"
            f"QTabBar::tab:hover{{color:{TXT};}}"
            f"QTabBar::tab:selected{{color:{TXT};border-bottom:2px solid {ACC};}}")

        # Bookmarks
        bwt = QWidget(); bwl = QVBoxLayout(bwt); bwl.setContentsMargins(6,6,6,6)
        bhl = QHBoxLayout()
        bhl.addWidget(QLabel("Marcos")); bhl.itemAt(0).widget().setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        bhl.addStretch()
        bb = yt_btn("+", small=True, accent=True, tip="[B]"); bb.clicked.connect(self._add_bm); bhl.addWidget(bb)
        bwl.addLayout(bhl)
        self.bw = QListWidget()
        self.bw.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:4px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}")
        self.bw.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bw.customContextMenuRequested.connect(self._bm_menu)
        bwl.addWidget(self.bw)
        tabs.addTab(bwt, T("tab_bookmarks"))

        # ── Vídeos: vocabulary captured from subtitles, SEPARATE from the main
        # study vocabulary. The user opts in (right-click → add) to promote a word
        # to their real account vocabulary. ──
        vvt = QWidget(); vvl = QVBoxLayout(vvt); vvl.setContentsMargins(6,6,6,6); vvl.setSpacing(4)
        vhl = QHBoxLayout()
        self.vv_title = QLabel(T("videos_vocab_title"))
        self.vv_title.setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        vhl.addWidget(self.vv_title); vhl.addStretch()
        vvl.addLayout(vhl)
        vhint = QLabel(T("videos_hint"))
        vhint.setWordWrap(True); vhint.setStyleSheet(f"color:{TMT};font-size:10px;background:transparent;")
        vvl.addWidget(vhint)
        self.vv_list = QListWidget()
        self.vv_list.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:5px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}")
        self.vv_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vv_list.customContextMenuRequested.connect(self._vv_menu)
        vvl.addWidget(self.vv_list)
        tabs.addTab(vvt, T("tab_videos"))
        QTimer.singleShot(0, self._load_video_vocab)   # populate once UI is ready

        # Notes
        awt = QWidget(); awl = QVBoxLayout(awt); awl.setContentsMargins(6,6,6,6)
        ahl = QHBoxLayout()
        ahl.addWidget(QLabel("Notas")); ahl.itemAt(0).widget().setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        ahl.addStretch()
        ab = yt_btn("+", small=True, accent=True); ab.clicked.connect(self._add_an); ahl.addWidget(ab)
        awl.addLayout(ahl)
        self.te = QTextEdit(); self.te.setPlaceholderText(T("note_placeholder")); self.te.setFixedHeight(32)
        self.te.setStyleSheet(f"QTextEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:4px;padding:4px;font-size:11px;}}")
        awl.addWidget(self.te)
        self.aw = QListWidget()
        self.aw.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:4px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}")
        self.aw.setContextMenuPolicy(Qt.CustomContextMenu)
        self.aw.customContextMenuRequested.connect(self._an_menu)
        awl.addWidget(self.aw)
        tabs.addTab(awt, T("tab_notes"))

        # Playlist
        pwt = QWidget(); pwl = QVBoxLayout(pwt); pwl.setContentsMargins(6,6,6,6)
        phl2 = QHBoxLayout()
        phl2.addWidget(QLabel("Playlist")); phl2.itemAt(0).widget().setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        phl2.addStretch()
        pcl = yt_btn("Limpar", small=True); pcl.clicked.connect(self._clr_pl); phl2.addWidget(pcl)
        pwl.addLayout(phl2)
        self.plw = QListWidget()
        self.plw.setDragDropMode(QListWidget.InternalMove)
        self.plw.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:4px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}QListWidget::item:selected{{background:rgba(139,92,246,0.3);}}")
        self.plw.currentRowChanged.connect(self._pl_row)
        pwl.addWidget(self.plw)
        tabs.addTab(pwt, T("tab_playlist"))

        # Tools
        tw = QWidget(); tl = QVBoxLayout(tw); tl.setContentsMargins(6,6,6,6)
        tl.addWidget(QLabel(T("tab_tools"))); tl.itemAt(0).widget().setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        # ── Seletor de idioma da interface (o utilizador escolhe; suporta qualquer
        # língua — as não embutidas são traduzidas pela IA e ficam em cache) ──
        lang_lbl = QLabel(T("ui_language")); lang_lbl.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;margin-top:4px;")
        tl.addWidget(lang_lbl)
        self.lang_combo = QComboBox()
        self.lang_combo.setStyleSheet(
            f"QComboBox{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:6px;padding:4px 8px;font-size:11px;}}"
            f"QComboBox:hover{{border-color:{ACC};}}QComboBox QAbstractItemView{{background:{ELV};color:{TXT};selection-background-color:{HVR};}}")
        cur = i18n.current_lang()
        for code, name in i18n.LANGUAGE_CHOICES:
            self.lang_combo.addItem(name, code)
            if code == cur:
                self.lang_combo.setCurrentIndex(self.lang_combo.count() - 1)
        self.lang_combo.activated.connect(lambda _i: self._change_ui_language(self.lang_combo.currentData()))
        tl.addWidget(self.lang_combo)
        for txt, cb in [(T("tools_export"), self._export), (T("tools_updates"), self._check_upd), (T("tools_data_folder"), lambda: subprocess.Popen(f'explorer "{DATA_DIR}"')), (T("tools_about"), self._about)]:
            b = yt_btn(txt, small=True); b.clicked.connect(cb); tl.addWidget(b)
        tl.addStretch()
        tabs.addTab(tw, T("tab_tools"))

        twl.addWidget(tabs)
        left_lo.addWidget(self.tools_wrap)

        # ── Right: Chat ──
        self.chat = ChatPanel(self)
        self.chat.setMinimumWidth(300)
        # Floating word-details panel (click an underlined subtitle word)
        self.word_details = WordDetailsPanel(self, self.chat)
        self.overlay.word_clicked.connect(self.word_details.show_for)
        self.chat.setMaximumWidth(420)

        body_lo.addWidget(self.word_details)   # left details panel (hidden until a word is clicked)
        body_lo.addWidget(left, 1)
        body_lo.addWidget(self.chat)
        outer.addWidget(body, 1)

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet(f"QStatusBar{{background:{SRF};color:{TMT};border-top:1px solid {BRD};font-size:11px;padding:2px 12px;}}")
        self.sbl = QLabel("Pronto"); self.sbl.setStyleSheet("background:transparent;color:#717171;")
        sb.addWidget(self.sbl)
        self.plcnt = QLabel(""); self.plcnt.setStyleSheet("background:transparent;color:#717171;")
        sb.addPermanentWidget(self.plcnt)
        outer.addWidget(sb)

        self._load_recent()

    # ── Overlay positioning (top-level Tool window tracks the engine area) ──
    def _reposition_overlay(self):
        if hasattr(self, 'engine') and hasattr(self, 'overlay') and self._overlay_shown:
            g = self.engine.mapToGlobal(QPoint(0, 0))
            self.overlay.setGeometry(g.x(), g.y(), self.engine.width(), self.engine.height())
            self.overlay.raise_()
            self._reposition_transport()   # keep the floating transport glued to the video

    def showEvent(self, e):
        super().showEvent(e)
        # Show the overlay only now — the main window has a native handle, so the
        # Tool overlay is owned by it and stays OUT of the taskbar (no "two apps").
        if not self._overlay_shown:
            self._overlay_shown = True
            self.overlay.show()
        self._reposition_overlay()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition_overlay()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._reposition_overlay()

    def changeEvent(self, e):
        super().changeEvent(e)
        # Hide the floating overlay while minimized so it can never show alone;
        # restore it (correctly positioned) when the window comes back.
        if e.type() == QEvent.WindowStateChange and hasattr(self, 'overlay') and self._overlay_shown:
            if self.isMinimized():
                self.overlay.hide()
            else:
                self.overlay.show()
                QTimer.singleShot(0, self._reposition_overlay)

    # ── Toggles ──
    def _toggle_chat(self, visible):
        self.chat.setVisible(visible)
        if visible:
            fade_in(self.chat, 200)
        # Keep both toggles (top bar + controls bar) in sync.
        if hasattr(self, 'chat_toggle'): self.chat_toggle.setChecked(visible)
        if hasattr(self, 'chat_btn'): self.chat_btn.setChecked(visible)

    def _toggle_chat_btn(self):
        self._toggle_chat(self.chat_btn.isChecked())

    def _toggle_fs(self):
        """Enter/exit fullscreen reliably (used by double-click and the button)."""
        if self._study_mode or self.isFullScreen():
            self._exit_study_mode()
        else:
            self._toggle_study_mode()

    def _toggle_study_mode(self):
        """Toggle fullscreen study mode: video + overlay + chat, with the
        transport (seek + controls) auto-hiding after inactivity."""
        self._study_mode = not self._study_mode
        if self._study_mode:
            # Hide the chrome that has no place in fullscreen.
            for name in ["top_bar", "practice_bar"]:
                w = self.findChild(QWidget, name)
                if w: w.hide()
            self.tools_wrap.hide()
            self.statusBar().hide()
            # Float the seek + controls OVER the video instead of below it, so
            # auto-hide/show no longer resizes the video (the old behaviour made
            # the picture jump up/down \u2014 uncomfortable). The video keeps its size.
            self._float_transport(True)
            self.setWindowState(Qt.WindowFullScreen)
            self.fs_btn.setText("\u26F6")
            self.fs_btn.setToolTip(T("exit_fullscreen"))
            self.sbl.setText(T("study_mode_esc"))
            self._fs_activity()   # show transport, then start the hide countdown
            # Re-anchor once fullscreen geometry settles (it applies asynchronously).
            QTimer.singleShot(80, self._reposition_transport)
        else:
            self._exit_study_mode()

    def _exit_study_mode(self):
        """Restore normal UI"""
        self._study_mode = False
        self._fs_hide_timer.stop()
        self.setWindowState(Qt.WindowNoState)
        self._float_transport(False)   # dock seek + controls back into the layout
        for name in ["top_bar", "practice_bar"]:
            w = self.findChild(QWidget, name)
            if w: w.show()
        self.tools_wrap.show()
        self.statusBar().show()
        self.fs_btn.setText("\u26F6")
        self.fs_btn.setToolTip(T("fullscreen_f"))
        self.sbl.setText(T("ready"))

    # \u2500\u2500 Floating transport (fullscreen) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    def _ensure_transport_overlay(self):
        """Lazily build the frameless window that hosts the seek + controls bars
        over the bottom of the video in study mode."""
        if getattr(self, "_transport_overlay", None) is None:
            ov = QWidget(self)
            ov.setObjectName("transport_overlay")
            ov.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
            ov.setAttribute(Qt.WA_ShowWithoutActivating)
            ov.setStyleSheet("#transport_overlay{background:#0c0c0c;}")
            lo = QVBoxLayout(ov); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)
            self._transport_overlay = ov
            self._transport_lo = lo
        return self._transport_overlay

    def _float_transport(self, floating):
        """Move seek_bar + controls_bar between the docked layout and the floating
        overlay. Reparenting (not hide/show) is what stops the video resizing."""
        if floating == self._transport_floating:
            return
        self._transport_floating = floating
        sb = self.findChild(QWidget, "seek_bar")
        cb = self.findChild(QWidget, "controls_bar")
        if floating:
            ov = self._ensure_transport_overlay()
            for w in (sb, cb):
                if w: self._left_lo.removeWidget(w); self._transport_lo.addWidget(w); w.show()
            ov.show()
            self._reposition_transport()
            ov.raise_()
        else:
            ov = getattr(self, "_transport_overlay", None)
            if ov:
                for w in (sb, cb):
                    if w: self._transport_lo.removeWidget(w)
                ov.hide()
            # Restore original order under the engine: seek (1), controls (2).
            if sb: self._left_lo.insertWidget(1, sb); sb.show()
            if cb: self._left_lo.insertWidget(2, cb); cb.show()

    def _reposition_transport(self):
        """Anchor the floating transport to the bottom edge of the video."""
        ov = getattr(self, "_transport_overlay", None)
        if not ov or not ov.isVisible() or not hasattr(self, "engine"):
            return
        h = 90  # seek (34) + controls (56)
        g = self.engine.mapToGlobal(QPoint(0, 0))
        ov.setGeometry(g.x(), g.y() + self.engine.height() - h, self.engine.width(), h)
        ov.raise_()

    def _fs_activity(self):
        """Mouse/keyboard activity in fullscreen: reveal the transport and
        restart the inactivity countdown."""
        if not self._study_mode:
            return
        ov = getattr(self, "_transport_overlay", None)
        if ov and not ov.isVisible():
            ov.show()
            self._reposition_transport()
        elif ov:
            ov.raise_()
        self._fs_hide_timer.start()

    def _fs_hide_controls(self):
        if not self._study_mode:
            return
        ov = getattr(self, "_transport_overlay", None)
        # Keep it up while the pointer is over the controls themselves.
        if ov and ov.underMouse():
            self._fs_hide_timer.start()
            return
        if ov:
            ov.hide()

    def _toggle_tools(self):
        self._tools_visible = not self._tools_visible
        self.tools_wrap.setVisible(self._tools_visible)

    # ── Idioma da UI (escolhido pelo utilizador; qualquer língua via IA) ──
    def _change_ui_language(self, code):
        if not code or code == i18n.current_lang():
            return
        if i18n.has_language(code):
            self._apply_ui_language(code)
            return
        # Língua não embutida → traduzir com a IA (background) e depois aplicar.
        name = i18n.language_display_name(code)
        showToast(T("lang_translating", lang=name), "accent")
        def work():
            ok = translate_ui_via_ai(code)
            QTimer.singleShot(0, lambda: self._on_lang_translated(code, ok))
        threading.Thread(target=work, daemon=True).start()

    def _on_lang_translated(self, code, ok):
        if ok:
            self._apply_ui_language(code)
        else:
            showToast(T("lang_failed"), "accent")
            self._sync_lang_combo()

    def _apply_ui_language(self, code):
        save_ui_lang(code)
        set_lang(code)
        name = i18n.language_display_name(code)
        box = QMessageBox(self)
        box.setStyleSheet(f"QMessageBox{{background:{ELV};}}QLabel{{color:{TXT};}}")
        box.setWindowTitle(T("lang_restart_title"))
        box.setText(T("lang_restart_body", lang=name))
        yes = box.addButton(T("restart_now"), QMessageBox.AcceptRole)
        box.addButton(T("later"), QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is yes:
            self._restart_app()

    def _restart_app(self):
        try:
            args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
            subprocess.Popen([sys.executable] + list(args))
            QApplication.quit()
        except Exception as e:
            log(f"restart: {e}")

    def _sync_lang_combo(self):
        if not hasattr(self, "lang_combo"):
            return
        cur = i18n.current_lang()
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == cur:
                self.lang_combo.setCurrentIndex(i)
                break

    # ── Vocab overlay ──
    def _on_overlay_add(self, text):
        """+ on a subtitle card → save to the SEPARATE video-vocab list (Vídeos tab)
        AND push to the cloud as PENDING (saved_words) so it shows on the web, where
        the user opts in (Add to vocabulary) or discards. NOT the main vocabulary."""
        vocab_file = DATA_DIR / 'saved-vocab.json'
        try:
            video = Path(self.video_path).name if self.video_path else ""
            saved = []
            if vocab_file.exists():
                saved = json.loads(vocab_file.read_text(encoding='utf-8'))
            if not any(s.get("text") == text for s in saved):
                saved.append({"text": text, "time": datetime.now().isoformat(), "video": video})
                vocab_file.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding='utf-8')
            self._load_video_vocab()           # refresh the dedicated Vídeos tab
            if text not in self._session_words:
                self._session_words.append(text)   # entra na atividade da sessão
            # Push to the web as a pending word (silent if logged out → stays local).
            synced = self.chat.sync_saved_word(text, video) if hasattr(self, "chat") else False
            # Make it obvious WHERE the word went. The status-bar toast is hidden
            # in fullscreen, so also flash a banner over the video, and (when the
            # panel is visible) jump to the Vídeos tab so the user sees it land.
            where = T("saved_videos_web") if synced else T("saved_videos")
            self.overlay.flash(T("saved_flash", where=where))
            showToast(T("saved_toast", where=where, text=text[:24]), "accent")
            if not self._study_mode and self.tools_wrap.isVisible():
                idx = self._vv_tab_index()
                if idx is not None:
                    self.tabs.setCurrentIndex(idx)
        except Exception as e:
            log(f"save vocab: {e}")

    def _vv_tab_index(self):
        """Index of the Vídeos tab in the tools panel (or None)."""
        if not hasattr(self, "tabs"):
            return None
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == T("tab_videos"):
                return i
        return None

    def _load_video_vocab(self):
        """Populate the Vídeos tab from the separate saved-vocab.json file."""
        self._vv_entries = []
        try:
            f = DATA_DIR / 'saved-vocab.json'
            if f.exists():
                self._vv_entries = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            log(f"load video vocab: {e}")
        if not hasattr(self, 'vv_list'):
            return
        self.vv_list.clear()
        if not self._vv_entries:
            empty = QListWidgetItem(T("videos_empty"))
            empty.setFlags(Qt.NoItemFlags)   # not selectable — it's a hint
            empty.setForeground(QColor(TMT))
            self.vv_list.addItem(empty)
        for e in reversed(self._vv_entries):   # newest first
            vid = e.get("video", ""); txt = e.get("text", "")
            it = QListWidgetItem()
            self.vv_list.addItem(it)
            lbl = QLabel(self._vocab_html(txt, vid))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)  # let the list handle hover/right-click
            lbl.setStyleSheet("background:transparent;font-size:11px;padding:1px 2px;")
            self.vv_list.setItemWidget(it, lbl)
            it.setSizeHint(lbl.sizeHint())
        n = len(self._vv_entries)
        self.vv_title.setText(f"{T('videos_vocab_title')} ({n})" if n else T("videos_vocab_title"))

    @staticmethod
    def _vocab_html(text, video=""):
        """Render a saved phrase with the SAME key-word colours as the subtitles
        (expressions violet, your-level green, advanced amber); plain words stay
        near-white. So the sidebar finally has the coloured letters."""
        def esc(s):
            return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        words = text.split()
        marks = mark_tokens(words)
        out = []
        for word, mk in zip(words, marks):
            if mk and mk.get("color") and mk.get("key"):
                out.append(f'<span style="color:{mk["color"]}">{esc(word)}</span>')
            else:
                out.append(f'<span style="color:{TXT}">{esc(word)}</span>')
        html = " ".join(out)
        if video:
            html += f' <span style="color:{TMT}">·  {esc(video)}</span>'
        return html

    def _vv_menu(self, pos):
        it = self.vv_list.itemAt(pos)
        if not it:
            return
        idx = len(self._vv_entries) - 1 - self.vv_list.row(it)   # list is reversed
        if not (0 <= idx < len(self._vv_entries)):
            return
        entry = self._vv_entries[idx]
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};padding:4px;}}"
                        f"QMenu::item{{padding:6px 14px;border-radius:4px;}}QMenu::item:selected{{background:{HVR};}}")
        a_add = m.addAction(T("menu_add_vocab"))
        a_ask = m.addAction(T("ask_ai"))
        m.addSeparator()
        a_del = m.addAction(T("menu_remove"))
        chosen = m.exec_(self.vv_list.mapToGlobal(pos))
        if chosen == a_del:
            try:
                del self._vv_entries[idx]
                (DATA_DIR / 'saved-vocab.json').write_text(
                    json.dumps(self._vv_entries, indent=2, ensure_ascii=False), encoding='utf-8')
            except Exception as e:
                log(f"remove vocab: {e}")
            self._load_video_vocab()
        elif chosen == a_ask:
            self._on_overlay_ask(entry.get("text", ""))
        elif chosen == a_add and hasattr(self, 'chat'):
            self.chat_toggle.setChecked(True); self.chat.setVisible(True)
            self.chat.promote_word(entry.get("text", ""))

    def _on_overlay_ask(self, text):
        """Called when user clicks the chat icon on a vocab overlay"""
        # Send text to Chat IA
        if hasattr(self, 'chat'):
            self.chat.input.setText(f"Explica-me esta frase: \"{text}\"")
            self.chat.input.setFocus()
            # Make sure chat is visible
            self.chat_toggle.setChecked(True)
            self.chat.setVisible(True)

    # ── Language-learning practice toggles (buttons + keyboard share these) ──
    def _toggle_loop(self):
        was_on = self.engine._loop is not None
        on = self.engine.toggle_loop()
        self.overlay._loop_active = on; self.overlay.update()
        if not on: self.seek.clear_marks()
        if hasattr(self, 'btn_loop'): self.btn_loop.setChecked(on)
        if on:
            showToast(T("loop_on"), "accent")
        elif was_on:
            showToast(T("loop_off"), "accent")
        elif not self.engine.subs_loaded():
            showToast(T("loop_need_sub"), "accent")
        else:
            showToast(T("loop_no_line"), "accent")

    def _set_loop_a(self):
        if not self.video_path:
            showToast(T("open_first"), "accent"); return
        a = self.engine.set_loop_a()
        self.seek.set_mark('A', a); self.seek.set_mark('B', None)
        showToast(f"Ponto A marcado em {FMT(a)} — agora marca B", "accent")

    def _set_loop_b(self):
        lp = self.engine.set_loop_b()
        if lp:
            self.overlay._loop_active = True; self.overlay.update()
            self.seek.set_mark('A', lp[0]); self.seek.set_mark('B', lp[1])
            if hasattr(self, 'btn_loop'): self.btn_loop.setChecked(True)
            showToast(f"Loop A-B ativo: {FMT(lp[0])}–{FMT(lp[1])}", "accent")
        else:
            showToast(T("loop_mark_a"), "accent")

    def _toggle_autopause(self):
        self._autopause_on = not getattr(self, '_autopause_on', False)
        self.engine.set_autopause(self._autopause_on)
        if hasattr(self, 'btn_ap'): self.btn_ap.setChecked(self._autopause_on)
        showToast("Auto-pausa por frase: ligada" if self._autopause_on else "Auto-pausa: desligada", "accent")

    def _toggle_hide_subs(self):
        self.overlay._hide_subs = not self.overlay._hide_subs
        self.overlay.update()
        if hasattr(self, 'btn_hide'): self.btn_hide.setChecked(self.overlay._hide_subs)
        showToast("Legenda escondida (rato em baixo para ver)" if self.overlay._hide_subs else "Legenda visível", "accent")

    # ── Playback ──
    def _toggle(self):
        if not self.video_path: self._open(); return
        self.engine.toggle()

    def _on_play(self, p): self.play_btn.setText(chr(0xE769) if p else chr(0xE768))
    def _on_pos(self, p):
        if self._seeking: return
        self.tlbl.setText(FMT(p))
        self.seek.blockSignals(True); self.seek.setValue(int(p)); self.seek.blockSignals(False)
    def _on_dur(self, d):
        self.dlbl.setText(FMT(d)); self.seek.setRange(0, max(1, int(d)))
    def _on_end(self):
        self.play_btn.setText(chr(0xE768))
        if self._pl_idx < len(self._playlist)-1:
            QTimer.singleShot(1200, lambda: self.plw.setCurrentRow(self._pl_idx+1))
    def _seek_to(self):
        self.engine.seek(float(self.seek.value())); self._seeking = False

    def _open(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Abrir", "",
            f"Multimédia (*{' *'.join(sorted(SUPPORTED_VID|SUPPORTED_AUD))})")
        if paths:
            for p in paths: self._pl_add(p)
            self._open_file(paths[0])

    def _open_file(self, path):
        if not path or not Path(path).exists(): return
        self.engine.stop(); self.video_path = path
        self._roll_session(Path(path).name)   # envia a sessão anterior, começa nova
        self.seek.clear_marks()
        self._add_recent(path)
        self.setWindowTitle(f"{Path(path).name} — {APP_NAME}")
        self.tit.setText(Path(path).name)
        self.bw.clear(); self.aw.clear()
        for bm in self.mgr.get_bm(path): self._add_bm_item(bm)
        for an in self.mgr.get_an(path): self._add_an_item(an)
        self.engine.open(path)
        self._update_sub_icon()
        # Auto-load a subtitle the user picked for this video before (memory),
        # only if none was auto-detected next to the file.
        if self.engine.sub_count() == 0:
            srt = self._recall_sub(path)
            if srt and self.engine.load_srt(srt):
                self._update_sub_icon()
                self.sbl.setText(f"CC {Path(srt).name} (memória)")
                return
        self.sbl.setText(Path(path).name)

    def _load_sub_file(self):
        """Open file dialog to load .srt subtitle manually"""
        if not self.engine.path():
            self.sbl.setText("Abre um vídeo primeiro"); return
        path, _ = QFileDialog.getOpenFileName(self, "Carregar legenda", "",
            "Legendas (*.srt *.SRT *.vtt *.VTT);;Todos (*)")
        if path and self.engine.load_srt(path):
            self._remember_sub(self.engine.path(), path)   # remember for next time
            self._update_sub_icon()
            self.sbl.setText(f"CC {Path(path).name}")
        elif path:
            self.sbl.setText(T("sub_load_fail"))

    # ── Subtitle memory: remember which .srt was used for each video ──
    def _sub_memory(self):
        try:
            f = DATA_DIR / 'sub-memory.json'
            if f.exists():
                return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def _remember_sub(self, video, srt):
        if not video or not srt:
            return
        try:
            m = self._sub_memory(); m[str(video)] = str(srt)
            (DATA_DIR / 'sub-memory.json').write_text(
                json.dumps(m, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            log(f"remember sub: {e}")

    def _recall_sub(self, video):
        srt = self._sub_memory().get(str(video))
        return srt if (srt and Path(srt).exists()) else None

    def _cycle_subs(self):
        """Cycle through subtitle tracks or toggle SRT"""
        tr = self.engine.cycle_sub_track()
        self._update_sub_icon()
        if tr >= 0:
            self.sbl.setText("Legenda ativa")
        else:
            self.sbl.setText("Legendas desligadas")

    def _update_sub_icon(self):
        """Update the subtitle indicator based on loaded subs"""
        srt = self.engine.sub_count()
        vlc_tracks = self.engine.sub_track_count()
        if srt > 0:
            self.sub_icon.setText(f"CC {srt}")
            self.sub_icon.setToolTip(f"{srt} legendas carregadas")
        elif vlc_tracks > 0:
            self.sub_icon.setText(f"VLC {vlc_tracks}")
            self.sub_icon.setToolTip(f"{vlc_tracks} faixas VLC")
        else:
            self.sub_icon.setText("")
            self.sub_icon.setToolTip("Sem legendas")

    def _cycle_spd(self):
        spds = [0.5,0.75,1.0,1.25,1.5,2.0]
        i = spds.index(self._rate) if self._rate in spds else 2
        self._rate = spds[(i+1)%len(spds)]; self.engine.set_rate(self._rate); self.spd.setText(f"{self._rate}x")

    # ── Bookmarks ──
    def _add_bm(self):
        if not self.video_path: return
        bm = {"pos":self.engine.get_pos(),"label":f"Marco {len(self.mgr.get_bm(self.video_path))+1}","note":"","created":datetime.now().isoformat()}
        self.mgr.d["bookmarks"].setdefault(str(self.video_path),[]).append(bm); self.mgr.save()
        self._add_bm_item(bm); self.sbl.setText(f"Marcador {FMT(bm['pos'])}")
    def _add_bm_item(self, bm):
        self.bw.addItem(QListWidgetItem(f"{FMT(bm.get('pos',0))}  {bm.get('label','')}")); self.bw.item(self.bw.count()-1).setData(Qt.UserRole,bm)
    def _bm_menu(self, pos):
        item = self.bw.itemAt(pos)
        if not item: return
        menu = QMenu(); menu.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};}}QMenu::item{{padding:5px 14px;font-size:11px;}}QMenu::item:selected{{background:{HVR};}}")
        go = menu.addAction("Ir"); rm = menu.addAction("Remover")
        action = menu.exec_(self.bw.mapToGlobal(pos))
        if action == go:
            bm = item.data(Qt.UserRole)
            if bm: self.engine.seek(bm.get('pos',0))
        elif action == rm:
            i = self.bw.row(item)
            if self.mgr.del_bm(self.video_path, i): self.bw.takeItem(i)

    # ── Annotations ──
    def _add_an(self):
        t = self.te.toPlainText().strip()
        if not self.video_path or not t: return
        an = {"pos":self.engine.get_pos(),"text":t,"created":datetime.now().isoformat()}
        self.mgr.d["annotations"].setdefault(str(self.video_path),[]).append(an); self.mgr.save()
        self._add_an_item(an); self.te.clear(); self.sbl.setText("Nota")
    def _add_an_item(self, an):
        t = an.get('text',''); self.aw.addItem(QListWidgetItem(f"{FMT(an.get('pos',0))} {t[:50]}")); self.aw.item(self.aw.count()-1).setData(Qt.UserRole,an)
    def _an_menu(self, pos):
        item = self.aw.itemAt(pos)
        if not item: return
        menu = QMenu(); menu.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};}}QMenu::item{{padding:5px 14px;font-size:11px;}}QMenu::item:selected{{background:{HVR};}}")
        go = menu.addAction("Ir"); rm = menu.addAction("Remover")
        action = menu.exec_(self.aw.mapToGlobal(pos))
        if action == go:
            an = item.data(Qt.UserRole)
            if an: self.engine.seek(an.get('pos',0))
        elif action == rm:
            i = self.aw.row(item)
            if self.mgr.del_an(self.video_path, i): self.aw.takeItem(i)

    # ── Playlist ──
    def _pl_add(self, path):
        p = Path(path)
        if str(p) not in self._playlist:
            self._playlist.append(str(p))
            item = QListWidgetItem()
            # Shell icon for the file type
            try:
                fi = QFileInfo(str(p))
                icon = QFileIconProvider().icon(fi)
                item.setIcon(icon)
            except:
                pass
            item.setText(p.name)
            item.setToolTip(str(p))
            self.plw.addItem(item)
            self.plcnt.setText(f"{len(self._playlist)}")
    def _pl_row(self, row):
        if 0 <= row < len(self._playlist): self._pl_idx = row; self._open_file(self._playlist[row])
    def _clr_pl(self):
        self._playlist.clear(); self.plw.clear(); self._pl_idx=-1; self.engine.stop(); self.video_path=None; self.plcnt.setText("")
    def _next(self):
        if self._pl_idx < len(self._playlist)-1: self.plw.setCurrentRow(self._pl_idx+1)
    def _prev(self):
        if self._pl_idx > 0: self.plw.setCurrentRow(self._pl_idx-1)
    def _load_recent(self):
        try:
            if RECENT_FILE.exists():
                for p in json.loads(RECENT_FILE.read_text()).get("recent",[]):
                    if Path(p).exists(): self._pl_add(p)
        except: pass
    def _add_recent(self, path):
        try:
            d = {"recent":[]}
            if RECENT_FILE.exists(): d = json.loads(RECENT_FILE.read_text())
            r = d.get("recent",[])
            if path in r: r.remove(path)
            r.insert(0,path); d["recent"] = r[:20]
            RECENT_FILE.write_text(json.dumps(d, indent=2))
        except: pass

    # ── Tools ──
    def _export(self):
        if not self.video_path: return
        p, _ = QFileDialog.getSaveFileName(self, "Exportar", f"{Path(self.video_path).stem}_estudo.json", "JSON (*.json)")
        if p: Path(p).write_text(self.mgr.export(self.video_path), encoding='utf-8')
    def _check_upd(self):
        try:
            r = urlopen(Request("https://github.com/amandioestevao/lexio-player/releases/latest/download/version.txt", headers={'User-Agent':APP_NAME}), timeout=5)
            v = r.read().decode().strip()
            if v and v != APP_VERSION:
                if QMessageBox.question(self, "Atualização", f"Nova: {v}\nDescarregar?", QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                    webbrowser.open("https://github.com/amandioestevao/lexio-player/releases/latest")
        except: pass
    def _about(self):
        QMessageBox.about(self, APP_NAME, f"<div style='text-align:center;'><h2 style='color:{ACC};'>{APP_NAME}</h2><p style='color:{TS2};'>v{APP_VERSION}</p><p style='color:{TMT};'>VLC + Chat IA</p></div>")

    # ── Keyboard ──
    _SHORTCUT_KEYS = frozenset({
        Qt.Key_Space, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
        Qt.Key_B, Qt.Key_N, Qt.Key_P, Qt.Key_R, Qt.Key_Comma, Qt.Key_Period,
        Qt.Key_Z, Qt.Key_L, Qt.Key_X, Qt.Key_H, Qt.Key_F, Qt.Key_C, Qt.Key_Escape,
    })

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QTextEdit)) and event.key() in self._SHORTCUT_KEYS:
                self.keyPressEvent(event)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, e):
        k = e.key()
        # Any key reveals the transport while in fullscreen study mode.
        # EXCEPT Space (pause) — showing the bars mid-pause shrinks the video
        # area, causing a visual "jump" as the engine and overlay resize.
        if k != Qt.Key_Space:
            self._fs_activity()
        # Space always pauses/plays - chat input uses Enter to send
        if k == Qt.Key_Space:
            self._toggle()
        elif k == Qt.Key_C:
            # Toggle the AI chat — also works in fullscreen, where the top-bar
            # button is hidden (the controls-bar chat button stays reachable).
            self._toggle_chat(not self.chat.isVisible())
        elif k == Qt.Key_Left: self.engine.seek_rel(-5)
        elif k == Qt.Key_Right: self.engine.seek_rel(5)
        elif k == Qt.Key_Up: self.vol.setValue(min(200, self.vol.value()+10))
        elif k == Qt.Key_Down: self.vol.setValue(max(0, self.vol.value()-10))
        elif k == Qt.Key_B: self._add_bm()
        elif k == Qt.Key_N: self._next()
        elif k == Qt.Key_P: self._prev()
        elif k == Qt.Key_R: self._cycle_spd()
        # ── Subtitle practice (language learning) ──
        elif k == Qt.Key_Comma: self.engine.prev_sub()           # ,  frase anterior
        elif k == Qt.Key_Period: self.engine.next_sub()          # .  frase seguinte
        elif k == Qt.Key_Z: self.engine.replay_sub()             # Z  repetir frase
        elif k == Qt.Key_L: self._toggle_loop()                  # L  loop A-B da frase
        elif k == Qt.Key_X: self._toggle_autopause()             # X  auto-pausa (shadowing)
        elif k == Qt.Key_H: self._toggle_hide_subs()             # H  esconder legenda (recall)
        elif k == Qt.Key_O and (e.modifiers() & Qt.ControlModifier): self._open()
        elif k == Qt.Key_F: self._toggle_fs()
        elif k == Qt.Key_Escape:
            if self._study_mode: self._exit_study_mode()
            elif self.isFullScreen(): self.setWindowState(Qt.WindowNoState)
        else: super().keyPressEvent(e)

    def closeEvent(self, e):
        try: self._push_player_session()   # grava a sessão final p/ a IA da web saber
        except Exception: pass
        self.engine.cleanup(); super().closeEvent(e)

    # ── Sessões do player → player_sessions (atividade que a IA da web lê) ──
    def _roll_session(self, new_video):
        self._push_player_session()
        self._session_start = datetime.now()
        self._session_video = new_video or ""
        self._session_words = []

    def _push_player_session(self):
        if not self._session_start or not self._session_video:
            self._session_start = None
            return
        header = self.chat._get_token_header() if hasattr(self, "chat") else None
        start, video, words = self._session_start, self._session_video, list(self._session_words)
        self._session_start = None
        if not header:
            return
        threading.Thread(target=self._session_worker,
                         args=(header, start, video, words), daemon=True).start()

    def _session_worker(self, header, start, video, words):
        import base64
        try:
            tok = header.split(" ", 1)[1]; pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                return
            end = datetime.now()
            dur = max(0, int((end - start).total_seconds()))
            if dur < 5:                       # ignora aberturas triviais
                return
            row = {"user_id": uid, "started_at": start.isoformat(), "ended_at": end.isoformat(),
                   "duration_seconds": dur, "video_title": video, "words_encountered": words,
                   "chat_messages_count": 0,
                   "target_lang": (getattr(self.chat, "_user_target", "") or "en")[:5]}
            ih = {"Content-Type": "application/json", "apikey": SUPABASE_ANON,
                  "Authorization": header, "Prefer": "return=minimal"}
            urlopen(Request(f"{SUPABASE_URL}/rest/v1/player_sessions",
                            data=json.dumps(row).encode(), headers=ih), timeout=20)
            log(f"player_session pushed: {video} ({dur}s, {len(words)} words)")
        except Exception as e:
            log(f"push session: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY
# ═══════════════════════════════════════════════════════════════════════════

def main():
    log("main()")
    try:
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME); app.setStyle("Fusion")
        # App / taskbar icon. On Windows the taskbar groups by AppUserModelID, so
        # set an explicit id BEFORE creating windows or the taskbar shows the
        # generic python icon instead of ours.
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lexio.studyplayer")
        except Exception as _e:
            log(f"AppUserModelID failed: {_e}")
        try:
            _ico = os.path.join(_base_dir, "icon.ico")
            if not os.path.exists(_ico):
                _ico = os.path.join(_base_dir, "icon.png")
            if os.path.exists(_ico):
                app.setWindowIcon(QIcon(_ico))
        except Exception as _e:
            log(f"app icon failed: {_e}")
        # Dark, legible tooltips (the in-app guides). Without this the Fusion
        # default renders nearly invisible on the black theme.
        app.setStyleSheet(
            "QToolTip{background:#1c1c1c;color:#fafafa;border:1px solid #3a3a3a;"
            "padding:5px 9px;border-radius:6px;font-size:11px;font-family:'Inter';}")
        # Load the bundled Inter font (same as the web app) and use it everywhere
        try:
            from PyQt5.QtGui import QFontDatabase
            _font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Inter.ttf")
            if QFontDatabase.addApplicationFont(_font_path) == -1:
                log("Inter font: addApplicationFont returned -1")
        except Exception as _e:
            log(f"Inter font load failed: {_e}")
        _ui_font = QFont("Inter", 10)
        _ui_font.setHintingPreference(QFont.PreferFullHinting)
        app.setFont(_ui_font)
        w = MainWindow()
        try:
            _ico2 = os.path.join(_base_dir, "icon.ico")
            if os.path.exists(_ico2):
                w.setWindowIcon(QIcon(_ico2))
        except Exception:
            pass
        # Dark native title bar on Windows (DWMWA_USE_IMMERSIVE_DARK_MODE = 20,
        # or 19 on older Win10 builds) — turns the white caption bar black.
        try:
            import ctypes
            _hwnd = int(w.winId())
            for _attr in (20, 19):
                _val = ctypes.c_int(1)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(_hwnd, _attr, ctypes.byref(_val), ctypes.sizeof(_val)) == 0:
                    break
        except Exception as _e:
            log(f"dark titlebar failed: {_e}")
        w.show()
        log("window.show() OK")
        sys.exit(app.exec_())
    except Exception as e:
        err = f"FATAL: {e}\n{traceback.format_exc()}"
        log(err)
        # Also show a message box
        try:
            from PyQt5.QtWidgets import QMessageBox
            mb = QMessageBox()
            mb.setIcon(QMessageBox.Critical)
            mb.setWindowTitle("Lexio Player - Erro")
            mb.setText(f"Ocorreu um erro ao iniciar:\n{e}")
            mb.setDetailedText(traceback.format_exc())
            mb.exec_()
        except: pass
        raise

if __name__ == "__main__":
    main()
