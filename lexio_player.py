#!/usr/bin/env python3
"""
Lexio Study Player v3.8.0 — VLC embutido (standalone) + Voz neural natural (edge-tts) + Aba Pronúncia + Imagens em grande
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

log("=== LEXIO PLAYER a arrancar === (pyinstaller-friendly)")  # versão real logada após APP_VERSION

# ── VLC path ──
# A self-contained build ships libvlc.dll + libvlccore.dll + the plugins folder
# RIGHT NEXT TO the app (PyInstaller one-dir / _MEIPASS), so the user needs NOTHING
# else installed. We look there FIRST; only if it isn't bundled do we fall back to a
# system-wide VLC install (handy when running from source during development).
_VLC_PATH = None

def _bundled_vlc_dir():
    """Where VLC sits inside a frozen build (next to the exe, or _MEIPASS)."""
    if getattr(sys, "frozen", False):
        for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable)):
            if base and os.path.exists(os.path.join(base, "libvlc.dll")):
                return base
    return None

_search = []
_b = _bundled_vlc_dir()
if _b:
    _search.append(_b)
_search += [
    r"C:\Program Files\VideoLAN\VLC",
    r"C:\Program Files (x86)\VideoLAN\VLC",
    str(Path.home() / "AppData" / "Local" / "Programs" / "VLC"),
    str(Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"),
]
for _p in _search:
    dll = os.path.join(_p, "libvlc.dll")
    if os.path.exists(dll):
        _VLC_PATH = _p
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
        # Point python-vlc straight at our DLL + plugins so it never picks up some
        # other VLC on PATH (avoids version/bitness mismatches).
        os.environ["PYTHON_VLC_LIB_PATH"] = dll
        _plug = os.path.join(_p, "plugins")
        if os.path.isdir(_plug):
            os.environ["VLC_PLUGIN_PATH"] = _plug
        # Register the DLL directory by every available method.
        try: os.add_dll_directory(_p)
        except Exception: pass
        try:
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(_p)
        except Exception: pass
        log(f"VLC found{' (bundled)' if _p == _b else ''}: {_p}")
        break
if not _VLC_PATH:
    log("VLC NOT FOUND")
    log(f"PATH={os.environ.get('PATH','')[:200]}")

# ── Imports with early error display ──
try:
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve, QRect, QRectF, QPoint, QSize, QUrl, QEvent, QFileInfo
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QIcon, QCursor, QRadialGradient, QLinearGradient, QFontMetrics, QFontInfo
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QFileDialog, QListWidget, QListWidgetItem,
        QMenu, QMessageBox, QTextEdit, QLineEdit,
        QTabWidget, QTabBar, QStatusBar, QScrollArea, QSizePolicy, QDialog,
        QGraphicsOpacityEffect, QStyle, QStyleOptionSlider, QStyleOptionTab,
        QProxyStyle, QFileIconProvider, QComboBox,
        QLayout, QWidgetItem, QSplitter, QSystemTrayIcon, QCheckBox, QSpinBox
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
APP_VERSION = "3.21.0"
log(f"=== LEXIO PLAYER v{APP_VERSION} ===")  # versão REAL (o banner de cima já não tem versão hardcoded)
DATA_DIR = Path.home() / '.lexio-player'; DATA_DIR.mkdir(exist_ok=True)
RECENT_FILE = DATA_DIR / 'recent.json'
STUDY_FILE = DATA_DIR / 'study-data.json'
TOKEN_FILE = DATA_DIR / 'auth-token.json'
REMINDER_FILE = DATA_DIR / 'reminder.json'

SUPPORTED_VID = {'.mp4','.avi','.mkv','.mov','.wmv','.flv','.webm','.m4v','.mpg','.mpeg','.3gp','.ogv','.ts','.mts'}
SUPPORTED_AUD = {'.mp3','.wav','.flac','.ogg','.m4a','.aac','.wma'}
SUPPORTED = SUPPORTED_VID | SUPPORTED_AUD

# Backend principal (Vercel) e RÉPLICA CHINA (Cloudflare Pages). A Vercel é
# frequentemente lenta ou inacessível atrás do Great Firewall, o que mata TODAS as
# chamadas de IA (chat/tts/visão/exercícios). A réplica Cloudflare é um espelho
# completo do mesmo /api e é alcançável na China. No arranque sondamos o primário e,
# se não responder, comutamos LEXIO_API para a réplica — como quase todas as chamadas
# usam o global em f-strings (avaliado no momento) e o ExpressionMiner só é construído
# depois, basta trocar este global cedo em main().
LEXIO_API_PRIMARY = "https://lexio-app-five.vercel.app"
LEXIO_API_CHINA = "https://lexio-app-46s.pages.dev"
LEXIO_API = LEXIO_API_PRIMARY
SUPABASE_URL = "https://lobwdstwpcbuljferyyo.supabase.co"


def _host_reachable(base, timeout=3.0):
    """True se o host devolve QUALQUER resposta HTTP (DNS/TCP/TLS OK), mesmo 4xx/5xx.
    Só timeout/erro de ligação (típico do Great Firewall) conta como inacessível."""
    try:
        urlopen(Request(f"{base}/api/auth", headers={"User-Agent": APP_NAME}), timeout=timeout)
        return True
    except HTTPError:
        return True   # respondeu (ex.: 405/500) → host alcançável
    except Exception:
        return False  # timeout / connection refused / DNS → bloqueado/offline


def _select_backend():
    """Escolhe o backend acessível. Mantém o primário (Vercel) se responder; caso
    contrário, e se a réplica China (Cloudflare) responder, comuta para ela. Tem de
    correr ANTES de construir a MainWindow (o ExpressionMiner fixa o valor)."""
    global LEXIO_API
    try:
        if _host_reachable(LEXIO_API_PRIMARY, timeout=3.0):
            LEXIO_API = LEXIO_API_PRIMARY
            log(f"backend: primário OK ({LEXIO_API_PRIMARY})")
            return
        if _host_reachable(LEXIO_API_CHINA, timeout=4.0):
            LEXIO_API = LEXIO_API_CHINA
            log(f"backend: primário inacessível -> réplica China ({LEXIO_API_CHINA})")
            return
        log("backend: nenhum acessível; mantém primário")
    except Exception as e:
        log(f"_select_backend falhou ({e}); mantém primário")

# Vozes neurais Microsoft (as MESMAS da web, api/tts.js) — naturais, multilíngue.
# Geradas localmente via `edge-tts` (Python), que calcula o token Sec-MS-GEC que o
# servidor (npm edge-tts) já não envia → daí o 403. Aqui sai natural e fiável.
EDGE_VOICES = {
    "pt": "pt-PT-RaquelNeural", "en": "en-US-AriaNeural", "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural", "it": "it-IT-ElsaNeural",
    "ja": "ja-JP-NanamiNeural", "zh": "zh-CN-XiaoxiaoNeural", "ko": "ko-KR-SunHiNeural",
    "ru": "ru-RU-SvetlanaNeural", "ar": "ar-SA-ZariyahNeural", "nl": "nl-NL-FennaNeural",
}


def _backend_tts(text, lang="en", rate=0):
    """Pede a voz NEURAL ao backend (/api/tts, edge-tts do lado do servidor) e
    grava o mp3. É a fonte PRIMÁRIA: o edge-tts LOCAL apanhava 403 da Microsoft
    em muitas redes (daí a 'voz robótica' do fallback SAPI). O servidor não apanha
    esse 403, por isso a voz natural passa a sair sempre que há internet."""
    if not text or not text.strip():
        return None
    try:
        import tempfile, urllib.request
        mult = 1.0 + (max(-50, min(50, int(rate))) / 100.0) if rate else 1.0
        body = json.dumps({"text": text.strip(), "languageCode": (lang or "en")[:2],
                           "rate": mult}).encode()
        req = urllib.request.Request(f"{LEXIO_API}/api/tts", data=body,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": APP_NAME})
        r = urllib.request.urlopen(req, timeout=20)
        d = json.loads(r.read().decode())
        b64 = d.get("audioBase64")
        if not b64:
            log(f"backend tts: sem áudio ({d.get('error')})")
            return None
        import base64
        out = os.path.join(tempfile.gettempdir(), f"lexio_tts_be_{int(time.time()*1000)}.mp3")
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64))
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception as e:
        log(f"backend tts: {e}")
    return None


def speak_edge_tts(text, lang="en", rate=0):
    """Gera um mp3 com voz NEURAL Microsoft e devolve o caminho. Tenta PRIMEIRO o
    backend (servidor, sem 403) e só depois o edge-tts local. rate: percentagem de
    velocidade -50..+50 (negativo = mais devagar). 0/None = normal. None se falhar."""
    if not text or not text.strip():
        return None
    be = _backend_tts(text, lang, rate)   # voz natural fiável (servidor)
    if be:
        return be
    import asyncio, tempfile
    try:
        import edge_tts
    except Exception as e:
        log(f"edge-tts import: {e}")
        return None
    voice = EDGE_VOICES.get(lang, "en-US-AriaNeural")
    kwargs = {}
    if rate:
        rr = max(-50, min(50, int(rate)))
        kwargs["rate"] = f"+{rr}%" if rr >= 0 else f"{rr}%"
    # Retry: a 1ª ligação ao serviço da Microsoft falha às vezes (rede/token) — uma
    # 2ª tentativa resolve a maioria das "vozes robóticas" (que eram o fallback SAPI).
    for attempt in (1, 2):
        out = os.path.join(tempfile.gettempdir(), f"lexio_tts_{int(time.time() * 1000)}_{attempt}.mp3")
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(edge_tts.Communicate(text.strip(), voice, **kwargs).save(out))
            finally:
                loop.close()
            if os.path.exists(out) and os.path.getsize(out) > 0:
                return out
        except Exception as e:
            log(f"edge-tts (tentativa {attempt}): {e}")
    return None


def speak_local_sapi(text, lang="en"):
    """Fallback offline: voz nativa do Windows (SAPI). Não tão boa, mas nunca silêncio
    quando o edge-tts neural falha (rede). Usado pela aba Pronúncia e detalhes."""
    if sys.platform != "win32" or not text or not text.strip():
        return False
    culture = {
        "en": "en-US", "pt": "pt-PT", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
        "it": "it-IT", "ja": "ja-JP", "zh": "zh-CN", "ko": "ko-KR", "ru": "ru-RU",
        "ar": "ar-SA", "nl": "nl-NL",
    }.get((lang or "en")[:2], "en-US")
    safe = text.replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "try{$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,"
          "[System.Speech.Synthesis.VoiceAge]::NotSet,0,"
          f"[System.Globalization.CultureInfo]'{culture}')}}catch{{}};$s.Speak('{safe}')")
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         startupinfo=si, creationflags=0x08000000)
        return True
    except Exception as e:
        log(f"sapi: {e}")
        return False


class _SlowSpeaker:
    """Diz uma frase/legenda com voz NEURAL natural (edge-tts) a uma velocidade mais
    lenta, mantendo a naturalidade (não estica o áudio — re-sintetiza mais devagar),
    com fallback para a voz do Windows (SAPI). Um único player VLC partilhado por
    todos os pontos que pedem áudio (cartões Twitch, chat, aba Pronúncia)."""
    def __init__(self):
        self._player = None
        self._inst = None

    def speak(self, text, lang="en", rate=-25):
        text = (text or "").strip()
        if not text:
            return
        threading.Thread(target=self._work, args=(text, (lang or "en")[:2], rate),
                         daemon=True).start()

    def stop(self):
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass

    def _work(self, text, lang, rate):
        try:
            tmp = speak_edge_tts(text, lang, rate)
            if not tmp:
                speak_local_sapi(text, lang)   # nunca silêncio
                return
            import vlc
            if self._player is None:
                self._inst = vlc.Instance("--quiet", "--no-video",
                    "--audio-resampler=soxr", "--aout=wasapi")
                self._player = self._inst.media_player_new()
            self._player.stop()
            self._player.set_media(self._inst.media_new(tmp))
            self._player.audio_set_volume(100)
            self._player.play()
        except Exception as e:
            log(f"slow speak: {e}")
            try: speak_local_sapi(text, lang)
            except Exception: pass


SLOW_TTS = _SlowSpeaker()

SUPABASE_ANON ="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxvYndkc3R3cGNidWxqZmVyeXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3NDI5MTIsImV4cCI6MjA5NTMxODkxMn0.GvJRLDE6yLhgDQUq-ckjgRZWbpvS4eKsUZglNyBsjSA"

# ── i18n: UI traduzida; a língua é ESCOLHIDA pelo utilizador no player e fica
# guardada localmente. Conteúdo (dicionário/chat) herda a língua nativa da conta.
import i18n
from i18n import T, set_lang, set_native, native_language_name
try:
    import scene_agent   # cérebro do Scene Agent (deteção de missões + avaliação IA)
except Exception as _e:
    scene_agent = None
    log(f"scene_agent import falhou: {_e}")

# Tipos de missão que o player trata com os seus próprios diálogos (UI + avaliação
# dedicada), em vez do SceneMissionDialog genérico. Mantido aqui para não depender
# de scene_agent ter importado.
_PLAYER_EXERCISE_KINDS = frozenset((
    "fluency_translate", "paraphrase_line", "describe_scene", "describe_take",
    "dialogue_roleplay",
))

i18n.set_cache_dir(str(DATA_DIR / 'i18n-cache'))   # traduções IA on-demand ficam aqui
# Traduções pré-geradas que vêm NO instalador (read-only) — fazem TODAS as línguas
# oferecidas funcionar offline, sem depender da IA em runtime. Mesma base das fontes.
i18n.set_bundled_dir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n-bundled'))
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

# ── Línguas DA CONTA (web) — nativa + foco. NÃO se escolhem no desktop: vêm do
# perfil da app web (Supabase) e mandam no CONTEÚDO (explicações/exercícios na
# nativa, legendas/alvo no foco). A escolha do desktop é só a APRESENTAÇÃO (ui-lang).
# Guardamos a última conhecida para funcionar offline/antes do login.
_ACCOUNT_LANGS_FILE = DATA_DIR / 'account-langs.json'

def load_account_langs():
    """{'native': 'pt', 'target': 'en'} vindas do perfil web, em cache local."""
    try:
        return json.loads(_ACCOUNT_LANGS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}

def save_account_langs(native=None, target=None):
    d = load_account_langs()
    if native:
        d['native'] = i18n._norm(native)
    if target:
        d['target'] = i18n._norm(target)
    try:
        _ACCOUNT_LANGS_FILE.write_text(json.dumps(d), encoding='utf-8')
    except Exception as e:
        log(f"save account langs: {e}")

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

def topup_ui_via_ai(code):
    """Traduz APENAS as chaves de UI que faltam numa língua já em cache (ex.: novas
    strings adicionadas depois de a língua ter sido traduzida) e junta-as à cache.
    Garante que QUALQUER língua suportada — não só as 12 embutidas — recebe as
    strings novas, sem reescrever as traduções já existentes. Devolve True se
    preencheu alguma coisa."""
    try:
        missing = i18n.missing_ui_keys(code)
        if not missing:
            return False
        base = i18n.base_strings()
        subset = {k: base[k] for k in missing if k in base}
        if not subset:
            return False
        lang_en = i18n.language_en_name(code)
        sys_p = (
            "You are a professional software UI translator. You receive a JSON object "
            f"of UI strings. Translate every VALUE into {lang_en}. Keep every KEY exactly "
            "as-is. Preserve placeholders such as {score}, {lang}, {where} verbatim. Keep "
            "translations short (these are buttons, labels, tooltips). Reply with ONLY the "
            "translated JSON object — no markdown, no prose.")
        body = json.dumps({"model": "deepseek-chat", "max_tokens": 2000, "temperature": 0.1,
            "messages": [{"role": "system", "content": sys_p},
                         {"role": "user", "content": json.dumps(subset, ensure_ascii=False)}]}).encode()
        r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                            headers={"Content-Type": "application/json"}), timeout=90)
        d = json.loads(r.read().decode())
        raw = (d.get("text") or "").strip()
        if not raw and d.get("choices"):
            raw = d["choices"][0].get("message", {}).get("content", "")
        raw = raw.strip().strip("`")
        mapping = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        mapping = {k: str(v) for k, v in mapping.items() if k in subset and v}
        if mapping:
            i18n.register_translations(code, mapping, merge=True)
            log(f"ui topup {code}: +{len(mapping)} strings")
            return True
    except Exception as e:
        log(f"ui topup {code}: {e}")
    return False

def _openrouter_key():
    """Chave OpenRouter para o fallback de visão direto. Lida do ambiente ou de um
    ficheiro LOCAL em DATA_DIR — NUNCA hardcoded no código (não vai para o git nem
    para o .exe distribuído)."""
    try:
        k = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if k:
            return k
        f = DATA_DIR / "openrouter-key.txt"
        if f.exists():
            return f.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

# Modelos de VISÃO GRATUITOS no OpenRouter (custo $0). Tenta-se vários por ordem
# porque a disponibilidade dos ":free" varia ao longo do tempo — o 1º que responder
# ganha. Assim as avaliações com imagem funcionam sem custos.
FREE_VISION_MODELS = [
    # IDs verificados em 2026-06 (os antigos llama-3.2-vision/qwen2.5-vl/gemini-2.0
    # foram removidos do OpenRouter → davam 404). O nemotron-vl responde de imediato;
    # os gemma-4 servem de reforço quando o 1º estiver rate-limited (429).
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]

def _vision_image_content(prompt, images):
    """Monta o array `content` (texto + imagens) no formato OpenAI/multimodal."""
    content = [{"type": "text", "text": prompt}]
    for img in (images or []):
        data = img.get("data") if isinstance(img, dict) else None
        if data:
            mime = (img.get("mimeType") or "image/jpeg")
            url = data if str(data).startswith("data:") else f"data:{mime};base64,{data}"
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def _pollinations_vision(prompt, system, images, max_tokens, temperature, timeout):
    """Visão GRÁTIS e SEM CHAVE via Pollinations (endpoint OpenAI-compatible, modelo
    multimodal). É a via que faz a análise da imagem funcionar sem o utilizador
    configurar absolutamente nada."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": _vision_image_content(prompt, images)})
    payload = {"model": "openai", "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature, "referrer": "lexio-player"}
    r = urlopen(Request("https://text.pollinations.ai/openai",
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"}), timeout=timeout)
    raw = r.read().decode()
    try:
        d = json.loads(raw)
        txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return txt or raw.strip()
    except Exception:
        # Alguns endpoints devolvem texto puro em vez de JSON OpenAI.
        return raw.strip()


def call_vision(prompt, system="", images=None, model=None,
                max_tokens=700, temperature=0.3, json_mode=True, timeout=75):
    """Análise de imagem GRATUITA e sem configuração. Ordem:
      1) Pollinations (grátis, SEM chave) — funciona logo, zero setup;
      2) backend partilhado /api/vision (chave no servidor);
      3) OpenRouter direto, SE o utilizador tiver posto uma chave local (modelos :free).
    Devolve o texto da resposta ou levanta exceção com o resumo dos erros."""
    images = images or []
    models = ([model] if model else []) + [m for m in FREE_VISION_MODELS if m != model]
    errors = []
    # 1) Pollinations — keyless, a via principal (o utilizador não configura nada).
    try:
        txt = _pollinations_vision(prompt, system, images, max_tokens, temperature, min(timeout, 60))
        if txt:
            return txt
        errors.append("pollinations: empty")
    except Exception as e:
        errors.append(f"pollinations: {e}"); log(f"vision pollinations falhou: {e}")
    # 2) Backend partilhado (chave no servidor; envia a lista p/ fallbacks gratuitos).
    try:
        body = json.dumps({
            "prompt": prompt, "system": system, "json": json_mode,
            "model": models[0], "models": models,
            "maxTokens": max_tokens, "temperature": temperature,
            "images": images,
        }).encode()
        r = urlopen(Request(f"{LEXIO_API}/api/vision", data=body,
                            headers={"Content-Type": "application/json"}), timeout=min(timeout, 60))
        d = json.loads(r.read().decode())
        txt = (d.get("text") or "").strip()
        if txt:
            return txt
        errors.append("backend: empty")
    except Exception as e:
        errors.append(f"backend: {e}"); log(f"vision via backend falhou: {e}")
    # 3) OpenRouter direto (só se houver chave local) — modelos :free, sem
    #    response_format (alguns :free rejeitam-no; o prompt já pede JSON).
    key = _openrouter_key()
    if key:
        content = _vision_image_content(prompt, images)
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": content}]
        for m in models:
            try:
                payload = {"model": m, "messages": messages, "max_tokens": max_tokens,
                           "temperature": temperature}
                r = urlopen(Request("https://openrouter.ai/api/v1/chat/completions",
                                    data=json.dumps(payload).encode(),
                                    headers={"Content-Type": "application/json",
                                             "Authorization": f"Bearer {key}",
                                             "HTTP-Referer": "https://lexio.app",
                                             "X-Title": "Lexio Player"}), timeout=timeout)
                d = json.loads(r.read().decode())
                txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                if txt:
                    return txt
                errors.append(f"{m}: empty")
            except Exception as e:
                errors.append(f"{m}: {e}"); log(f"vision {m} falhou: {e}")
    raise RuntimeError("vision failed — " + "; ".join(errors[:4]))

set_lang(load_ui_lang())   # APRESENTAÇÃO da UI (escolha do desktop) — antes de construir a UI
# CONTEÚDO (explicações/exercícios) = língua NATIVA da conta web, NÃO a apresentação.
# Usa a última nativa conhecida (cache do perfil); só na 1ª vez, sem nada em cache,
# cai para a apresentação como palpite. O login sobrepõe com o valor real do perfil.
set_native(load_account_langs().get('native') or load_ui_lang())

def FMT(sec):
    s = max(0, int(sec)); h,s = divmod(s,3600); m,s = divmod(s,60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class _GuiInvoker(QObject):
    """Corre um callable na thread da GUI. NECESSÁRIO porque gui_call(fn)
    NÃO dispara a partir de threads worker (sem event loop) — bug que fazia os
    resultados dos exercícios/segmentação/STT nunca aparecerem. A conexão é Queued,
    por isso adia sempre para o event loop (igual ao singleShot(0)), venha de onde vier."""
    _run = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._run.connect(self._on_run, Qt.QueuedConnection)

    def _on_run(self, fn):
        try:
            fn()
        except Exception as e:
            log(f"gui_call: {e}")

    def call(self, fn):
        self._run.emit(fn)


_GUI_INVOKER = None

def ensure_gui_invoker():
    """Cria o invocador NA THREAD ATUAL (deve ser a main/GUI). Chamado cedo no arranque."""
    global _GUI_INVOKER
    if _GUI_INVOKER is None:
        _GUI_INVOKER = _GuiInvoker()
    return _GUI_INVOKER

def gui_call(fn):
    """Agenda `fn` para correr na thread da GUI. Substitui gui_call(fn)."""
    ensure_gui_invoker().call(fn)

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
# FLOW LAYOUT — quebra os widgets para a linha seguinte quando não cabem
# (usado na barra de Prática, p/ os botões NUNCA cortarem o texto)
# ═══════════════════════════════════════════════════════════════════════════

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6, center=False):
        super().__init__(parent)
        self._items = []
        self._hsp = hspacing
        self._vsp = vspacing
        self._center = center   # centrar cada linha horizontalmente (estilo media player)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        s += QSize(m.left() + m.right(), m.top() + m.bottom())
        return s

    def _do(self, rect, test):
        m = self.contentsMargins()
        left = rect.x() + m.left()
        right = rect.right() - m.right()
        avail = right - left
        y = rect.y() + m.top()
        # 1ª passagem: agrupar os itens em linhas (respeitando a quebra) para,
        # quando _center, sabermos a largura de cada linha e a podermos centrar.
        rows = []        # [[(item, w, h), ...], ...]
        cur = []; cur_w = 0
        for it in self._items:
            w = it.sizeHint().width(); h = it.sizeHint().height()
            need = w if not cur else cur_w + self._hsp + w
            if cur and need > avail:
                rows.append(cur); cur = []; cur_w = 0
                need = w
            cur.append((it, w, h)); cur_w = need
        if cur:
            rows.append(cur)
        # 2ª passagem: posicionar.
        for row in rows:
            row_w = sum(w for _it, w, _h in row) + self._hsp * (len(row) - 1)
            x = left + max(0, (avail - row_w) // 2) if self._center else left
            line_h = 0
            for it, w, h in row:
                if not test:
                    it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
                x += w + self._hsp
                line_h = max(line_h, h)
            y += line_h + self._vsp
        if rows:
            y -= self._vsp
        return y - rect.y() + m.bottom()


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
        self._track_segs = []  # [(start_frac, end_frac, done_bool)] — aulas/tracks
        # Preview da legenda ao passar o rato sobre o groove (só o seek bar; o
        # slider de volume NUNCA recebe isto, por isso a sua aparência fica intacta —
        # resolve o conflito #5 "nome da legenda no groove vs css do volume").
        self._preview = None
        self.setMouseTracking(True)

    def set_preview(self, fn):
        """fn(value)->str: texto a mostrar num tooltip flutuante para a posição
        apontada (ex.: a legenda nesse instante). Só faz sentido no seek bar."""
        self._preview = fn

    def set_track_segs(self, segs):
        """Marca as fronteiras dos tracks (aulas) no groove; segmentos concluídos
        ganham um sublinhado verde."""
        self._track_segs = segs or []
        self.update()

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
        if self.maximum() <= self.minimum():
            return
        from PyQt5.QtGui import QPainter, QColor, QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        # ── Fronteiras dos tracks/aulas: tracinho em cada início; segmento concluído
        # ganha uma barra verde por baixo do groove. ──
        if self._track_segs:
            mx = self.maximum()
            for sf, ef, done in self._track_segs:
                xs = int(self._x_for(sf * mx))
                xe = int(self._x_for(ef * mx))
                p.fillRect(QRect(xs, 2, 1, h - 4), QColor(255, 255, 255, 60))
                if done:
                    p.fillRect(QRect(xs, h // 2 + 3, max(2, xe - xs), 3),
                               QColor(94, 230, 160, 210))
        if not self._marks:
            p.end()
            return
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

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        # Tooltip flutuante com a legenda na posição apontada (preview de scrub).
        if self._preview is not None and self.maximum() > self.minimum():
            try:
                from PyQt5.QtWidgets import QToolTip
                v = self._value_at(e.pos())
                txt = self._preview(v)
                if txt:
                    QToolTip.showText(e.globalPos(), txt, self)
                else:
                    QToolTip.hideText()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# SRT PARSER
# ═══════════════════════════════════════════════════════════════════════════

class SubEntry:
    __slots__ = ('start', 'end', 'text')
    def __init__(self, start, end, text):
        self.start = start; self.end = end; self.text = text


class DialogueTurn:
    """Um TURNO de fala (uma personagem a falar de seguida), já agrupado a partir de
    várias legendas. O problema que isto resolve: uma personagem que fala muito aparece
    repartida por 2-3 legendas, e o role-play tratava cada legenda como uma personagem
    diferente. Aqui juntamos as legendas da mesma fala num só turno."""
    __slots__ = ('start', 'end', 'text', 'speaker')
    def __init__(self, start, end, text, speaker):
        self.start = start; self.end = end; self.text = text; self.speaker = speaker


# Marca de mudança de falante dentro de uma legenda: traço inicial ou " - " no meio.
# (parse_srt junta as linhas da legenda com espaço, por isso os traços sobrevivem.)
_SPK_DASH_RE = re.compile(r'(?:^|\s)[-–—]\s+')
# Prefixo de nome de personagem no início de uma fala: "JOHN:", "Maria:" etc.
_SPK_NAME_RE = re.compile(r'^([^\W\d_][\w\'’.\- ]{0,18}):\s+(.+)$', re.UNICODE)
# Início que indica continuação da MESMA fala (minúscula ou conjunção).
_CONT_START_RE = re.compile(
    r'^(?:and|but|so|or|because|cause|’cause|that|which|who|when|while|though|'
    r'although|e|mas|porque|que|para|então|ou|y|pero|porque)\b', re.I)
# A fala anterior NÃO terminou (sem pontuação final) → mesma personagem continua.
_SENTENCE_END_RE = re.compile(r'[.!?…"”’\)]\s*$')


def _split_speaker_segments(text):
    """Reparte UMA legenda em segmentos de falante. Devolve lista de
    (nome|None, texto, fronteira_explicita_bool). Traço inicial / nome são fronteiras."""
    text = (text or "").strip()
    if not text:
        return []
    # Traços a marcar dois falantes na mesma legenda → segmentos separados (fronteira).
    if _SPK_DASH_RE.search(text):
        parts = [p.strip() for p in _SPK_DASH_RE.split(text) if p and p.strip()]
        if len(parts) > 1:
            segs = []
            for p in parts:
                m = _SPK_NAME_RE.match(p)
                if m:
                    segs.append((m.group(1).strip(), m.group(2).strip(), True))
                else:
                    segs.append((None, p, True))
            return segs
    # Sem traços: legenda inteira é um segmento; pode ter prefixo de nome.
    m = _SPK_NAME_RE.match(text)
    if m:
        return [(m.group(1).strip(), m.group(2).strip(), True)]
    return [(None, text, False)]

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
    subtitle_changed = pyqtSignal(str)  # current subtitle text (original)
    subtitles_changed = pyqtSignal(str, str, str)  # original, 2ª linha, 3ª linha
    subtitle_exited = pyqtSignal(int)   # index of subtitle that just finished
    subtitle_entered = pyqtSignal(int)  # index of subtitle we JUST entered (lesson narration)
    ai_loop_changed = pyqtSignal(int)   # remaining loops for current sub, 0 = off

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};border:none;")
        # Minimum SMALL enough that the layout can genuinely shrink the video in
        # reduced windows. A 360px minimum made the layout overflow on small
        # windows: the bars below moved up but the video HWND stayed 360 tall,
        # so the subtitle overlay (glued to the engine) landed over the controls
        # bar / screen corner instead of on the visible video.
        self.setMinimumHeight(120)
        self.setFocusPolicy(Qt.StrongFocus)

        self._inst = None; self._player = None; self._media = None
        self._path = None; self._duration = 0
        self._subs = []        # SubEntry list
        self._played_ids = set()  # track which subs already shown
        # ── Legendas duplas/triplas ──
        self._subs2 = []        # 2ª legenda (outra língua / tradução manual)
        self._subs3 = []        # 3ª legenda (opcional)
        self._auto_tr = False   # auto-traduzir a 2ª linha via IA quando não há _subs2
        self._tr_lang = ""      # nome em inglês do idioma alvo (p/ o prompt da IA)
        self._tr_lang_code = "" # código do idioma alvo
        self._tr_cache = {}     # texto original -> tradução (preenchido em background)
        self._tr_inflight = set()  # textos já enviados p/ traduzir (não repetir)
        # ── Language-learning practice state ──
        self._loop = None       # (start, end) seconds, or None — A-B loop
        self._loop_a = None     # manual A point (seconds) waiting for B
        self._autopause = False # pause at the end of each subtitle (shadowing)
        self._ap_armed = False  # armed while inside a subtitle
        self._ap_last = -1      # last subtitle index we were inside
        self._last_sub = ""     # last non-empty subtitle text (stays on pause)
        self._last_sub_idx = -1 # index of last subtitle
        self._last_entered_idx = -1  # last index emitted via subtitle_entered (lesson)
        # ── AI Auto-Loop: each sentence repeats n times ──
        self._ai_loop = False       # toggle
        self._ai_loop_count = 2     # default repetitions per subtitle
        self._ai_loop_idx = -1      # which subtitle index we're counting loops for
        self._ai_loop_played = 0    # how many times played so far

        self.ph = QLabel("", self)
        self.ph.setAlignment(Qt.AlignCenter)
        self.ph.setStyleSheet(f"color:{TMT};font-size:15px;background:transparent;")
        self._show_ph()

        # Poll often so subtitles flip the instant the cue starts (≈1 video
        # frame), not up to 200ms late — that lag read as "out of sync".
        self._poll_ms = 40
        self._timer = QTimer(); self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._poll)
        self._init_vlc()

    def _show_ph(self):
        self.ph.setText(T("ph_hint"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.ph.setGeometry((self.width()-250)//2, (self.height()-60)//2, 250, 60)
        # Re-snap the subtitle/Twitch overlay to the video the INSTANT the video
        # widget changes size for ANY reason — window resize, bottom-bar collapse,
        # chat panel toggle. MainWindow.resizeEvent only fires for the WINDOW, so
        # internal layout changes used to leave the legendas lagging behind the
        # video by up to 300ms (the poll timer). This closes that gap.
        win = self.window()
        if win is not None and hasattr(win, "_reposition_overlay"):
            try:
                win._reposition_overlay()
            except Exception:
                pass

    def _init_vlc(self):
        try:
            if not _VLC_PATH:
                self.ph.setText("VLC nao encontrado\nhttps://videolan.org"); return
            # scaletempo2: estica o áudio no tempo MANTENDO o tom ao abrandar/acelerar,
            # com MUITO menos "cacos"/robótica que o scaletempo antigo (é o mesmo
            # algoritmo que os navegadores usam). É transparente a 1x — só atua quando a
            # velocidade ≠ 1, por isso não afeta a reprodução normal. Garante também que
            # o time-stretch está ligado para o shadowing devagar soar limpo.
            # soxr: resampler de altíssima qualidade (SoX Resampler) — áudio mais natural
            # e limpo, especialmente em taxas de amostragem não nativas.
            self._inst = vlc.Instance(["--no-xlib","--quiet","--no-video-title-show",
                "--intf","dummy","--no-osd","--no-stats","--avcodec-hw=none",
                "--network-caching=300","--file-caching=300",
                "--audio-time-stretch","--audio-filter=scaletempo2",
                "--audio-resampler=soxr",
                "--text-renderer=freetype",
                "--aout=wasapi"])
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
            current_idx = -1
            for i, sub in enumerate(self._subs):
                if sub.start <= p <= sub.end:
                    current_sub = sub.text
                    current_idx = i
                    break
            if current_sub:
                self._last_sub = current_sub
                self._last_sub_idx = current_idx
            elif not is_playing and self._last_sub:
                current_sub = self._last_sub
            self.subtitle_changed.emit(current_sub)
            # 2ª/3ª linha (legendas duplas/triplas): alinhadas pelo TEMPO (robusto a
            # ficheiros .srt com fronteiras diferentes), com fallback à auto-tradução IA.
            l2, l3 = self._secondary_lines(p, current_idx, current_sub)
            self.subtitles_changed.emit(current_sub, l2, l3)
            # Entrámos numa NOVA legenda? (usado pela narração ao vivo das aulas)
            if is_playing and current_idx >= 0 and current_idx != self._last_entered_idx:
                self._last_entered_idx = current_idx
                self.subtitle_entered.emit(current_idx)
            # Detect subtitle exit for listening mode
            if is_playing and self._last_sub_idx >= 0:
                inside = False
                for s in self._subs:
                    if s.start <= p <= s.end:
                        inside = True; break
                if not inside and p < self._duration - 1:
                    idx = self._last_sub_idx
                    self._last_sub_idx = -1
                    self.subtitle_exited.emit(idx)
            # ── A-B loop of the current line ──
            if self._loop and is_playing and p > self._loop[1] + 0.05:
                log(f"loop back {p:.1f}s -> {self._loop[0]:.1f}s")
                self.seek(self._loop[0])
            # ── Auto-pause SEMPRE no FIM de cada fala (shadowing) ──
            # Regra coerente: enquanto estamos DENTRO de uma legenda, ficamos "armados".
            # A pausa só dispara DEPOIS de a fala terminar — no silêncio a seguir (fim +
            # margem) ou, em falas seguidas sem silêncio, no instante em que começa a
            # próxima (= fim da anterior). Nunca pausa no meio/início de uma fala.
            elif self._autopause and is_playing:
                AP_PAD = 0.35   # margem: .srt mal sincronizado não corta a última palavra
                cur = -1
                for i, s in enumerate(self._subs):
                    if s.start <= p <= s.end:
                        cur = i; break
                if cur >= 0:
                    if (self._ap_armed and self._ap_last >= 0 and cur != self._ap_last
                            and p >= self._subs[self._ap_last].end - 0.05):
                        # Falas seguidas: a anterior acabou agora mesmo → pausa no fim dela.
                        self._ap_armed = False
                        self._player.pause()
                    else:
                        self._ap_last = cur; self._ap_armed = True   # dentro da fala → arma
                elif self._ap_armed and self._ap_last >= 0:
                    # Silêncio depois da fala: pausa quando passámos o fim + margem.
                    if p >= self._subs[self._ap_last].end + AP_PAD:
                        self._ap_armed = False
                        self._player.pause()
            # ── AI Auto-Loop: repeat each sentence N times ──
            if self._ai_loop and is_playing:
                inside = -1
                for i, s in enumerate(self._subs):
                    if s.start <= p <= s.end:
                        inside = i; break
                if inside >= 0:
                    if inside != self._ai_loop_idx:
                        self._ai_loop_idx = inside
                        self._ai_loop_played = 1
                    elif p >= self._subs[inside].end - 0.1:
                        # About to exit — loop back if not played enough
                        if self._ai_loop_played < self._ai_loop_count:
                            self._ai_loop_played += 1
                            log(f"AI loop {inside} play {self._ai_loop_played}/{self._ai_loop_count}")
                            self.ai_loop_changed.emit(self._ai_loop_count - self._ai_loop_played)
                            self.seek(self._subs[inside].start)
                elif self._ai_loop_idx >= 0 and p > self._subs[self._ai_loop_idx].end + 0.5:
                    # Past the current subtitle, into gap or next
                    self._ai_loop_idx = -1; self._ai_loop_played = 0
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
        # Legendas secundárias e cache de tradução são do filme anterior — limpar.
        self._subs2 = []; self._subs3 = []
        self._tr_cache = {}; self._tr_inflight = set()
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
            # Subtitles are rendered EXCLUSIVELY by our Qt VideoOverlay (positioned
            # safely above the controls bar, persists on pause, words clickable).
            # We deliberately do NOT feed the .srt to VLC's native renderer: VLC
            # burns subs at the bottom of the video frame, which in a windowed
            # (non-fullscreen) player lands over the controls groove and double-
            # draws under our overlay. self._subs (parsed above) drives the overlay.
            self._player.set_media(self._media)
            self._player.play()
            self.ph.hide()
            QTimer.singleShot(300, lambda: self._player and self._player.set_hwnd(int(self.winId())))
            # Disable any native subtitle track (external or embedded auto-pick) so
            # the Qt overlay is the single source of truth. The user can still turn
            # embedded tracks on via the CC cycle button.
            QTimer.singleShot(500, self._disable_native_subs)
            log(f"Playing: {path}")
        except Exception as e: log(f"open: {e}")

    def show_subtitle_reset(self):
        """Esquece a última legenda mostrada e emite uma legenda vazia. Chamado ao
        trocar de filme para que a legenda do filme anterior não reapareça no intervalo
        entre stop() e o novo open() (o _poll mostra _last_sub quando está em pausa)."""
        self._last_sub = ""
        self._last_sub_idx = -1
        self.subtitle_changed.emit("")

    def _disable_native_subs(self):
        """Turn off VLC's own subtitle rendering — the Qt overlay handles subs."""
        if not self._player: return
        try:
            self._player.video_set_spu(-1)
        except Exception as e:
            log(f"disable native subs: {e}")

    def load_srt(self, srt_path):
        """Load subtitle file manually — rendered by the Qt overlay, not VLC."""
        if not self._player: return False
        try:
            self._subs = parse_srt(Path(srt_path).read_text(encoding='utf-8', errors='replace'))
            self._played_ids = set()
            log(f"Loaded {len(self._subs)} subs from {srt_path}")
            # Keep VLC's native renderer OFF so the overlay stays the single source
            # of truth (no double subtitles, no controls-bar overlap).
            self._disable_native_subs()
            return True
        except Exception as e:
            log(f"load_srt fail: {e}")
            return False

    # ── Legendas duplas/triplas ───────────────────────────────────────────────
    @staticmethod
    def _text_at(subs, p):
        """Texto da legenda (numa lista) que cobre o instante p, ou "". Alinhamento
        por tempo: funciona mesmo quando os ficheiros .srt têm fronteiras diferentes."""
        for s in subs:
            if s.start <= p <= s.end:
                return s.text
        return ""

    def _secondary_lines(self, p, idx, orig):
        """Devolve (2ª linha, 3ª linha) para o instante p. A 2ª vem da 2ª legenda
        carregada; se não houver e a auto-tradução estiver ON, vem da cache de IA."""
        l2 = self._text_at(self._subs2, p)
        l3 = self._text_at(self._subs3, p)
        if not l2 and self._auto_tr and orig:
            key = orig.strip()
            l2 = self._tr_cache.get(key, "")
            if idx >= 0:
                self._prefetch_tr(idx)   # adianta a tradução das próximas falas
        return l2, l3

    def _prefetch_tr(self, idx):
        """Traduz em background a fala atual + as próximas (lote pequeno), guardando
        em _tr_cache. Evita repetir o que já está em cache/voo."""
        if not self._tr_lang:
            return
        batch = []
        for j in range(idx, min(idx + 6, len(self._subs))):
            t = (self._subs[j].text or "").strip()
            if t and t not in self._tr_cache and t not in self._tr_inflight:
                self._tr_inflight.add(t); batch.append(t)
        if batch:
            threading.Thread(target=self._tr_worker, args=(batch, self._tr_lang),
                             daemon=True).start()

    def _tr_worker(self, batch, lang):
        try:
            sys_p = ("You are a subtitle translator. Translate each line into "
                     f"{lang}. Keep it natural and concise (it must fit one subtitle "
                     "line). Reply with ONLY a JSON array of the translations, in the "
                     "same order and same length — no prose, no markdown.")
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 1200,
                "temperature": 0.2,
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}]}).encode()
            r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                headers={"Content-Type": "application/json"}), timeout=60)
            d = json.loads(r.read().decode())
            raw = (d.get("text") or "").strip()
            if not raw and d.get("choices"):
                raw = d["choices"][0].get("message", {}).get("content", "")
            raw = raw.strip().strip("`")
            arr = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
            for src, tr in zip(batch, arr):
                if tr:
                    self._tr_cache[src] = str(tr).strip()
        except Exception as e:
            log(f"tr worker: {e}")
        finally:
            for t in batch:
                self._tr_inflight.discard(t)

    def load_srt2(self, path):
        try:
            self._subs2 = parse_srt(Path(path).read_text(encoding='utf-8', errors='replace'))
            log(f"2ª legenda: {len(self._subs2)} de {Path(path).name}")
            return len(self._subs2) > 0
        except Exception as e:
            log(f"load_srt2: {e}"); return False

    def load_srt3(self, path):
        try:
            self._subs3 = parse_srt(Path(path).read_text(encoding='utf-8', errors='replace'))
            log(f"3ª legenda: {len(self._subs3)} de {Path(path).name}")
            return len(self._subs3) > 0
        except Exception as e:
            log(f"load_srt3: {e}"); return False

    def set_auto_translate(self, on, lang_en="", lang_code=""):
        self._auto_tr = bool(on)
        if lang_en:
            self._tr_lang = lang_en
        if lang_code:
            self._tr_lang_code = lang_code

    def sub_text_at(self, p):
        """Texto da legenda principal no instante p (para o preview do seek bar)."""
        return self._text_at(self._subs, p)

    def secondary_for_index(self, idx):
        """(2ª, 3ª) linha para a fala de índice idx (para o feed da aba Legendas).
        Usa o ponto médio da fala para alinhar por tempo; recorre à cache de
        auto-tradução quando não há 2ª legenda em ficheiro."""
        if not (0 <= idx < len(self._subs)):
            return "", ""
        s = self._subs[idx]
        mid = (s.start + s.end) / 2.0
        l2 = self._text_at(self._subs2, mid)
        l3 = self._text_at(self._subs3, mid)
        if not l2 and self._auto_tr:
            l2 = self._tr_cache.get((s.text or "").strip(), "")
        return l2, l3

    def clear_sub2(self):
        self._subs2 = []

    def clear_sub3(self):
        self._subs3 = []

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

    def video_size(self):
        """(width, height) of the actual decoded video, or (0,0) if unknown.
        Used to keep the subtitle/cards INSIDE the real video image (not over the
        black letterbox bars). Cached — VLC only knows it once decoding starts."""
        vw = vh = 0
        if self._player:
            try:
                sz = self._player.video_get_size(0)   # (w, h)
                if sz and len(sz) == 2:
                    vw, vh = int(sz[0]), int(sz[1])
            except Exception:
                vw = vh = 0
        if vw and vh:
            self._vid_size = (vw, vh)
        return getattr(self, "_vid_size", (0, 0))

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

    def play(self):
        if self._player and not self._player.is_playing():
            try: self._player.play()
            except: pass

    def pause(self):
        if self._player and self._player.is_playing():
            try: self._player.pause()
            except: pass

    def loop_range(self, start, end):
        """Loop an explicit time span — used by the Describe-scene exercise to keep
        the whole scene repeating while the user watches and describes it."""
        if start is None or end is None or end <= start:
            return
        self._loop = (float(start), float(end)); self._loop_a = None
        self.seek(start); self.play()

    def clear_loop(self):
        self._loop = None; self._loop_a = None

    def snapshot_b64(self, max_w=768):
        """Grab the current video frame as base64 (JPEG/PNG) for the vision model.
        Returns (data_b64, mime) or None. Used by Describe-scene/take so the AI can
        actually SEE the frame and compare it with what's being said."""
        if not self._player:
            return None
        try:
            import base64, tempfile
            vw, vh = self.video_size()
            w = 0
            if vw and vh and vw > max_w:
                w = max_w   # let VLC scale down; height 0 keeps aspect ratio
            fd, path = tempfile.mkstemp(suffix=".png", prefix="lexio_snap_")
            os.close(fd)
            ok = self._player.video_take_snapshot(0, path, w, 0)
            # video_take_snapshot returns 0 on success; the file is written async-ish,
            # but VLC writes it before returning for the current frame.
            data = None
            if os.path.exists(path):
                with open(path, "rb") as f:
                    raw = f.read()
                if raw:
                    data = base64.b64encode(raw).decode("ascii")
                try: os.remove(path)
                except Exception: pass
            if ok == 0 and data:
                return data, "image/png"
            return (data, "image/png") if data else None
        except Exception as e:
            log(f"snapshot: {e}")
            return None

    def stop(self):
        self._timer.stop()
        if self._player:
            self._player.stop(); self._media = None
        self._path = None; self._duration = 0; self._subs = []; self._played_ids = set()
        self._last_sub = ""
        self._ai_loop_idx = -1; self._ai_loop_played = 0
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

    def _sub_cluster(self, min_n=3, max_n=5, gap=2.5):
        """The 'strategic' cluster of consecutive subtitle lines around the current
        moment — the same group that's feeding the Twitch cards on screen. Returns
        (indices, current_index): a list of indices into self._subs, plus the index
        of the line that's actually playing now (the focus). Lines that belong to
        one scene are kept together — the cluster stops at a long silence between
        lines — and is sized 3-5 (fewer only if the scene genuinely has fewer)."""
        if not self._subs:
            return [], -1
        i = self._sub_idx_at(self.get_pos())
        if i < 0:
            i = self._last_sub_idx if self._last_sub_idx >= 0 else 0
        i = max(0, min(i, len(self._subs) - 1))
        idxs = [i]
        # Grow forward while consecutive lines stay close (same scene beat).
        j = i
        while len(idxs) < max_n and j + 1 < len(self._subs):
            if self._subs[j + 1].start - self._subs[j].end <= gap:
                j += 1; idxs.append(j)
            else:
                break
        # Too short for a meaningful passage → pull in lines before it (scene gap
        # allowed a touch wider going back), then, if still short, ignore gaps.
        k = i
        while len(idxs) < min_n and k - 1 >= 0:
            if self._subs[k].start - self._subs[k - 1].end <= gap * 1.6:
                k -= 1; idxs.insert(0, k)
            else:
                break
        while len(idxs) < min_n and j + 1 < len(self._subs):
            j += 1; idxs.append(j)
        while len(idxs) < min_n and idxs[0] - 1 >= 0:
            idxs.insert(0, idxs[0] - 1)
        return idxs, i

    def fluency_group(self, min_n=3, max_n=5, gap=2.5):
        """The cluster of subtitle lines for the Fluency exercise (translate the
        whole passage fluently to your own language)."""
        idxs, _ = self._sub_cluster(min_n, max_n, gap)
        return [self._subs[g] for g in idxs]

    def paraphrase_group(self, min_n=3, max_n=5, gap=2.5):
        """Same cluster, but for Paraphrase: returns (lines, focus_pos) where
        focus_pos is the index INSIDE `lines` of the line that's playing now — the
        one the user rewrites. The rest are passed to the AI as scene context so
        the paraphrase stays coherent with the surrounding dialogue."""
        idxs, cur = self._sub_cluster(min_n, max_n, gap)
        lines = [self._subs[g] for g in idxs]
        focus = idxs.index(cur) if cur in idxs else (0 if lines else -1)
        return lines, focus

    def dialogue_turns(self, max_turns=8, gap=2.2):
        """Reúne a conversa atual (legendas consecutivas a partir da posição) e AGRUPA-as
        em TURNOS de fala por heurística (marcadores de traço/nome + pontuação +
        continuação de frase), em vez de tratar cada legenda como uma personagem
        diferente. Devolve lista de DialogueTurn com falante
        atribuído (nome real se existir, senão A/B/C... alternados nas fronteiras)."""
        if not self._subs:
            return []
        i = self._sub_idx_at(self.get_pos())
        if i < 0:
            i = self._last_sub_idx if self._last_sub_idx >= 0 else 0
        i = max(0, min(i, len(self._subs) - 1))
        # Reúne a corrida de legendas da conversa atual (até quebrar por silêncio longo).
        # Reúne mais legendas do que turnos, porque o agrupamento reduz a contagem.
        cues = [self._subs[i]]; j = i
        while len(cues) < max_turns * 2 + 2 and j + 1 < len(self._subs):
            if self._subs[j + 1].start - self._subs[j].end <= gap:
                j += 1; cues.append(self._subs[j])
            else:
                break
        return self._group_turns(cues, max_turns)

    @staticmethod
    def _group_turns(cues, max_turns=8):
        """Agrupa SubEntry consecutivos em DialogueTurn. Junta a mesma personagem
        (frase que continua, mesmo nome) e abre turno novo nas fronteiras (traço,
        nome diferente, ou frase anterior terminada + nova começa em maiúscula)."""
        turns = []   # cada: {name, segs:[(text,start,end)], start, end}
        cur = None

        def text_of(t):
            return " ".join(s[0] for s in t["segs"]).strip()

        for cue in cues:
            segs = _split_speaker_segments(cue.text)
            n = len(segs)
            for k, (name, seg_text, explicit) in enumerate(segs):
                # Tempo do segmento: reparte a duração da legenda pelos seus segmentos.
                if n > 1:
                    span = (cue.end - cue.start) / float(n)
                    s_start = cue.start + span * k
                    s_end = cue.start + span * (k + 1)
                else:
                    s_start, s_end = cue.start, cue.end

                if cur is None:
                    cur = {"name": name, "segs": [(seg_text, s_start, s_end)],
                           "start": s_start, "end": s_end}
                    continue

                # Decidir: mesmo falante (continua) ou turno novo?
                if name is not None and cur["name"] is not None:
                    new_turn = (name.lower() != cur["name"].lower())
                elif explicit:
                    new_turn = True            # traço/nome → mudou de falante
                else:
                    prev = text_of(cur)
                    cont = (not _SENTENCE_END_RE.search(prev)        # frase aberta
                            or (seg_text[:1].islower())               # começa minúscula
                            or _CONT_START_RE.match(seg_text))        # conjunção
                    new_turn = not cont

                if new_turn:
                    turns.append(cur)
                    cur = {"name": name, "segs": [(seg_text, s_start, s_end)],
                           "start": s_start, "end": s_end}
                else:
                    if name and not cur["name"]:
                        cur["name"] = name
                    cur["segs"].append((seg_text, s_start, s_end))
                    cur["end"] = s_end
        if cur is not None:
            turns.append(cur)

        turns = turns[:max_turns]
        # Atribuir etiqueta de falante: nome real se houver; senão A/B/C alternados.
        named = any(t["name"] for t in turns)
        result = []
        if named:
            order = []
            for t in turns:
                nm = t["name"] or "?"
                if nm not in order:
                    order.append(nm)
            for t in turns:
                result.append(DialogueTurn(t["start"], t["end"], text_of(t),
                                           t["name"] or (order[0] if order else "A")))
        else:
            # Sem nomes: assume diálogo a dois e alterna A/B a cada turno (o caso comum).
            # Os turnos da mesma personagem já foram juntos antes, por isso cada fronteira
            # restante é, quase sempre, uma troca de falante.
            for li, t in enumerate(turns):
                spk = "A" if li % 2 == 0 else "B"
                result.append(DialogueTurn(t["start"], t["end"], text_of(t), spk))
        return result

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

    def set_ai_loop(self, count):
        """Enable/disable AI auto-loop with given repetitions per subtitle."""
        self._ai_loop = count > 0
        self._ai_loop_count = count if count > 0 else 2
        if not self._ai_loop:
            self._ai_loop_idx = -1; self._ai_loop_played = 0
        return self._ai_loop

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

    def set_audio_muted(self, m):
        """Muta/desmuta o áudio do VLC sem mexer no volume (restaura limpo). Usado
        no modo lento, em que a voz neural (edge-tts) toca por cima e o áudio
        original esticado do VLC só faria 'cacos'."""
        try:
            if self._player: self._player.audio_set_mute(bool(m))
        except Exception as e:
            log(f"set_audio_muted: {e}")

    def duck_volume(self, level=22):
        """Baixa o volume (sem mutar) guardando o anterior. Usado no exercício de
        diálogo/shadowing: o filme continua a ouvir-se baixinho enquanto o aluno fala
        por cima — em vez de pausar/mutar de repente."""
        if not self._player: return
        try:
            if getattr(self, "_vol_before_duck", None) is None:
                cur = self._player.audio_get_volume()
                self._vol_before_duck = cur if cur is not None and cur >= 0 else 100
            self._player.audio_set_volume(max(0, min(200, level)))
        except Exception as e:
            log(f"duck_volume: {e}")

    def restore_volume(self):
        """Repõe o volume guardado por duck_volume (se houver)."""
        if not self._player: return
        try:
            v = getattr(self, "_vol_before_duck", None)
            if v is not None and v >= 0:
                self._player.audio_set_volume(v)
        except Exception as e:
            log(f"restore_volume: {e}")
        self._vol_before_duck = None

    def nearest_sub_text(self):
        """Texto da legenda 'atual' para os exercícios: a última mostrada, senão a que
        está no tempo atual, senão a 1ª. Evita que o exercício falhe só porque o filme
        não está exatamente em cima de uma legenda."""
        if self._last_sub:
            return self._last_sub
        if not self._subs:
            return ""
        i = self._sub_idx_at(self.get_pos())
        if i < 0:
            i = 0
        return (self._subs[i].text or "").strip()

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
    "#ff0000", "#1e90ff", "#00ff00", "#ff00ff", "#ffd700",
    "#ff69b4", "#00ffff", "#ff4500", "#7b68ee", "#32cd32",
    "#ff1493", "#00bfff", "#ffd700", "#00fa9a", "#ff6347",
]

# "Utilizadores" do chat Twitch — nomes gerados e cores associadas
# Rotating accent colors for the left bar of each Twitch-style vocab card
# (no fake usernames — just a visual pop to distinguish adjacent cards)
CARD_COLORS = ["#ff0000", "#1e90ff", "#00ff00", "#ff00ff", "#ffd700",
               "#ff69b4", "#00ffff", "#ff4500", "#7b68ee", "#32cd32",
               "#ff1493", "#00bfff", "#00fa9a", "#ff6347"]
_CARD_COLOR_IDX = 0

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

# Grupos multi-palavra que a IA deteta a partir do guião REAL das legendas (em
# runtime, via ExpressionMiner, à medida que o filme avança). O mark_tokens
# consulta este conjunto ALÉM da lista offline EXPRESSIONS — assim sublinha como
# UMA UNIDADE expressões que perdem o sentido se separadas, mesmo que não estejam
# na lista fixa. Lê-se por membership (thread-safe sob o GIL); só cresce.
_AI_EXPRESSIONS = set()
_GROUP_MAXLEN = 6   # nº máx. de palavras de um grupo a tentar casar (cobre AI+offline)

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
        # Longest-first expression match starting at i. Consulta a lista offline
        # E os grupos detetados pela IA no guião atual (_AI_EXPRESSIONS).
        matched = 0
        for L in range(min(_GROUP_MAXLEN, n - i), 1, -1):
            seg = cores[i:i + L]
            if all(seg):
                phrase = " ".join(seg)
                if phrase in EXPRESSIONS or phrase in _AI_EXPRESSIONS:
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


class ExpressionMiner(QObject):
    """Lê o GUIÃO REAL das legendas (não palavras soltas) e pede à IA os GRUPOS de
    palavras que perdem o sentido se separados — phrasal verbs, idioms, colocações,
    expressões fixas. Corre em background, em blocos, PROGRESSIVAMENTE à medida que
    o filme avança (relê o que vem a seguir), e alimenta o conjunto global
    _AI_EXPRESSIONS que o mark_tokens consulta. Uma chamada por bloco, com cache.

    Assim o sublinhador deixa de ser "burro": além das palavras isoladas (heurística
    offline), passa a sublinhar como UMA unidade as expressões que a IA reconhece na
    legenda em contexto."""
    updated = pyqtSignal()
    CHUNK = 35   # nº de legendas enviadas à IA por bloco

    _SYS = (
        "You help a language learner study film subtitles. From the subtitle lines "
        "given, extract ONLY multi-word expressions that must be understood as a single "
        "unit — phrasal verbs, idioms, fixed collocations and set phrases — where the "
        "meaning is lost if the words are read separately. Use the surrounding context. "
        "Return STRICTLY a JSON array of lowercase strings, each the exact contiguous "
        "words as they appear in the text (2 to 6 words). NO single words, NO duplicates, "
        "NO explanations, NO extra keys. Example: [\"give up\",\"out of the blue\"]."
    )

    def __init__(self, api_base, auth_cb=None, parent=None):
        super().__init__(parent)
        self._api = api_base
        self._auth_cb = auth_cb      # callable → header de auth (ou None)
        self._cues = []
        self._key = None             # impressão digital da lista de legendas atual
        self._scheduled = set()      # índices de bloco já agendados
        self._lock = threading.Lock()

    def set_cues(self, cues):
        """(Re)inicia para um novo conjunto de legendas; processa logo a abertura."""
        cues = [c or "" for c in cues]
        key = (len(cues), cues[0][:40] if cues else "")
        if key == self._key:
            return
        self._key = key
        self._cues = cues
        with self._lock:
            self._scheduled = set()
        _AI_EXPRESSIONS.clear()
        self.updated.emit()
        if cues:
            self.ensure_for_index(0)

    def ensure_for_index(self, idx):
        """Garante que o bloco da legenda atual e o SEGUINTE estão a ser processados —
        é o que faz a IA 'reler à medida que o filme avança'."""
        if not self._cues or idx < 0:
            return
        base = idx // self.CHUNK
        for ci in (base, base + 1):
            start = ci * self.CHUNK
            if start >= len(self._cues):
                continue
            with self._lock:
                if ci in self._scheduled:
                    continue
                self._scheduled.add(ci)
            seg = self._cues[start:start + self.CHUNK]
            threading.Thread(target=self._work, args=(seg,), daemon=True).start()

    def _work(self, seg):
        try:
            phrases = self._ask_ai(seg)
            added = False
            for ph in phrases:
                ph = " ".join(''.join(c for c in w if c.isalpha() or c == "'")
                              for w in ph.lower().split()).strip()
                if ph and " " in ph and len(ph.split()) <= _GROUP_MAXLEN and ph not in _AI_EXPRESSIONS:
                    _AI_EXPRESSIONS.add(ph); added = True
            if added:
                self.updated.emit()
        except Exception as e:
            log(f"expr miner: {e}")

    def _ask_ai(self, seg):
        text = "\n".join(s for s in seg if s.strip())
        if not text.strip():
            return []
        hdrs = {"Content-Type": "application/json", "User-Agent": APP_NAME}
        h = self._auth_cb() if self._auth_cb else None
        if h:
            hdrs["Authorization"] = h
        body = json.dumps({
            "model": "deepseek-chat", "max_tokens": 500, "temperature": 0.1,
            "messages": [{"role": "system", "content": self._SYS},
                         {"role": "user", "content": text}],
        }).encode()
        r = urlopen(Request(f"{self._api}/api/deepseek-chat", data=body, headers=hdrs), timeout=45)
        data = json.loads(r.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", content, re.S)
        if not m:
            return []
        arr = json.loads(m.group(0))
        return [x for x in arr if isinstance(x, str)]


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
    speak_card = pyqtSignal(str)       # speaker button on a card → hear it slowly
    video_clicked = pyqtSignal()
    toggle_fullscreen = pyqtSignal()
    word_clicked = pyqtSignal(str)     # underlined key word clicked → details panel
    mouse_moved = pyqtSignal()         # any movement over the video (wakes fs controls)
    load_sub_requested = pyqtSignal()  # user clicked the "no subtitle — load one" banner

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
        self._current_sub2 = ""   # 2ª linha (legenda dupla / tradução)
        self._current_sub3 = ""   # 3ª linha (legenda tripla)
        self._sub_word_rects = []  # [(x, y, w, h, word)] for bottom subtitle
        self._hide_subs = False   # active-recall: hide subtitle until mouse peeks at bottom
        self._no_sub_hint = False # show a clickable "load a subtitle" banner over the video
        self._no_sub_rect = None  # QRect of that banner (for click hit-testing)
        self._mouse_y = 0
        self._transport_h = 0      # altura do transport flutuante (study mode); legenda+cartões sobem acima dele
        self._loop_active = False  # show a LOOP badge while the A-B loop is on
        self._ai_loop_active = False  # show AI loop badge
        self._ai_loop_remaining = 0   # loops left for current subtitle
        self._flash_msg = ""       # transient banner (e.g. "Guardado em Vídeos") for fullscreen
        self._flash_until = 0.0
        self._is_playing = True    # while paused we FREEZE card aging (the user may be
                                   # chatting with the AI / reading details — subs stay)

        # Animation timer: alta cadência e ESTÁVEL para o movimento dos cartões.
        # Qt.PreciseTimer é essencial no Windows — o timer "coarse" por omissão só
        # tem resolução de ~15ms, por isso os 4ms pedidos caíam para ~64fps e
        # tremiam ("a baixar"). Com PreciseTimer o ritmo mantém-se fixo e fluido.
        self._anim_timer = QTimer()
        self._anim_timer.setTimerType(Qt.PreciseTimer)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(8)   # ~120fps reais e constantes

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
                self._engine = eng     # cached for _video_rect() in paint/hit-tests
                # NEVER eng.mapToGlobal() here — the engine is a NATIVE child
                # (VLC set_hwnd) and Qt double-counts the window position for
                # native children, sending the overlay to the screen corner.
                gx, gy, gw, gh = w._engine_global_rect()
                # Only move if size/position changed (avoid flicker)
                cur = self.geometry()
                new_rect = QRect(gx, gy, gw, gh)
                if cur != new_rect:
                    self.setGeometry(new_rect)
                self.raise_()
                # Keep the floating transport (study mode) ABOVE this overlay so
                # its buttons stay clickable and visible over the subtitles.
                tov = getattr(w, "_transport_overlay", None)
                # Reserve the transport's height for the WHOLE time we're in study
                # mode — even while it's auto-hidden — so the subtitle and Twitch
                # cards keep a FIXED lowest point and don't jump up/down every time
                # the controls fade in or out. (Outside study mode the controls are
                # docked below the video, so nothing needs reserving here.)
                if getattr(w, "_study_mode", False) and tov is not None:
                    self._transport_h = (tov.height() or 90) + 10
                    if tov.isVisible():
                        tov.raise_()
                else:
                    self._transport_h = 0
                break

    def _video_rect(self):
        """Rect (x, y, w, h) of the ACTUAL video image inside the overlay — VLC
        letterboxes/pillarboxes the picture inside the widget, so we keep subtitles
        and cards within this rect instead of over the black bars / random spots."""
        W, H = self.width(), self.height()
        eng = getattr(self, "_engine", None)
        vw = vh = 0
        if eng is not None:
            try:
                vw, vh = eng.video_size()
            except Exception:
                vw = vh = 0
        if not vw or not vh or W <= 0 or H <= 0:
            return 0, 0, W, H
        scale = min(W / vw, H / vh)
        dw, dh = int(vw * scale), int(vh * scale)
        dx, dy = (W - dw) // 2, (H - dh) // 2
        return dx, dy, dw, dh

    def _active_rect(self):
        """(x0, y0, x1, y1) — the part of the video the user can actually SEE:
        the overlay clipped to the screen's work area (the window may be dragged
        partly off-screen) and, horizontally, to the video image (no pillarbox
        side bars). Subtitles and vocab cards are laid out inside this rect, so
        they always sit on the visible video — never at a screen corner."""
        W, H = self.width(), self.height()
        x0, y0, x1, y1 = 0, 0, W, H
        try:
            g = self.mapToGlobal(QPoint(0, 0))
            scr = QApplication.screenAt(QPoint(g.x() + W // 2, g.y() + H // 2)) \
                or QApplication.primaryScreen()
            if scr is not None:
                av = scr.availableGeometry()
                x0 = max(x0, av.left() - g.x());      y0 = max(y0, av.top() - g.y())
                x1 = min(x1, av.right() + 1 - g.x()); y1 = min(y1, av.bottom() + 1 - g.y())
        except Exception:
            pass
        # Horizontal clip to the video image. Vertically we keep the full band —
        # subtitles may sit on the bottom letterbox bar, like every player does.
        vx, vy, vw, vh = self._video_rect()
        x0 = max(x0, vx); x1 = min(x1, vx + vw)
        # Degenerate (window fully off-screen / sizes unknown) → whole overlay.
        if x1 - x0 < 160 or y1 - y0 < 90:
            return 0, 0, W, H
        return x0, y0, x1, y1

    def _sub_zone_top(self, ay0, ay1):
        """Y of the TOP of a one-line subtitle box for this active rect. The Twitch
        cards stack above this line, and it's used as the default even when no main
        subtitle is on screen — so the cards keep a FIXED lowest point and don't
        jump up/down each time the subtitle appears and disappears."""
        ah = ay1 - ay0
        fs = max(9, min(24, ah // 26))
        fm = QFontMetrics(QFont("Inter", fs, QFont.Bold))
        line_h = fm.height() + 2
        box_h = line_h + 14                 # one line, same formula as the drawn box
        margin_b = max(12, ah // 14)
        return ay1 - box_h - margin_b

    def flash(self, msg, secs=2.6):
        """Show a brief banner centred at the top of the video — the only place
        feedback is visible in fullscreen (the status-bar toast is hidden there)."""
        self._flash_msg = msg
        self._flash_until = time.time() + secs
        self.update()

    def show_subtitle(self, text):
        # Compat: legenda simples (sem 2ª/3ª linha). Delega no caminho duplo/triplo
        # para limpar quaisquer linhas de tradução penduradas.
        self.show_subtitles(text, "", "")

    def show_subtitles(self, orig, l2="", l3=""):
        """Legenda principal + 2ª/3ª linhas (legendas duplas/triplas). Repinta só
        quando algo muda."""
        if (orig, l2, l3) != (self._current_sub, self._current_sub2, self._current_sub3):
            self._current_sub = orig
            self._current_sub2 = l2
            self._current_sub3 = l3
            self.update()

    def reset_for_new_video(self):
        """Limpa todo o estado visual ao trocar de filme: legenda, cartões Twitch e
        banners. Evita que legendas/cartões do filme anterior fiquem congelados sobre
        o novo vídeo enquanto este ainda não emitiu nada."""
        self._current_sub = ""
        self._current_sub2 = ""
        self._current_sub3 = ""
        self._cards = []
        self._hover_idx = -1
        self._flash_msg = ""
        self._flash_until = 0.0
        self._no_sub_hint = False
        self._no_sub_rect = None
        self.update()

    def set_no_sub_hint(self, on):
        """Show/hide the clickable 'this video has no subtitle — load one' banner."""
        on = bool(on)
        if on != self._no_sub_hint:
            self._no_sub_hint = on
            self.update()

    MAX_CARDS = 6   # how many Twitch-style cards stay on screen at once

    def show_vocab(self, text):
        """Called when a subtitle triggers a new phrase. Cards are kept by COUNT,
        not by time: we keep the newest MAX_CARDS and never expire them on a clock.
        New cards only arrive WHILE PLAYING, so during a pause nothing is removed —
        the cards (and subtitle) stay put for as long as the user studies.
        Each card gets a rotating accent color (no fake usernames)."""
        global _CARD_COLOR_IDX
        now = time.time()
        color = CARD_COLORS[_CARD_COLOR_IDX % len(CARD_COLORS)]
        _CARD_COLOR_IDX += 1
        self._cards.append(VocabCard(text, now, color, now))
        if len(self._cards) > self.MAX_CARDS:
            self._cards = self._cards[-self.MAX_CARDS:]

    def _tick(self):
        # No time-based expiry: cards persist until pushed out by newer ones (see
        # show_vocab). This guarantees they never vanish on pause. We just keep the
        # animation repainting and the hover index sane.
        if self._cards and self._hover_idx >= len(self._cards):
            self._hover_idx = -1
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

    def leaveEvent(self, e):
        # Quando o rato sai do vídeo, esquece a posição: senão, se a última posição era
        # em baixo, a legenda escondida ficava revelada para sempre (queixa "esconder
        # legenda não funciona bem").
        self._mouse_y = 0
        if self._hide_subs and self._current_sub:
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        # "Load a subtitle" banner takes priority — it sits at the top, clear of cards.
        if self._no_sub_rect is not None and self._no_sub_rect.contains(e.pos()):
            self.load_sub_requested.emit()
            return
        idx = self._hit_test_vocab(e.pos())
        if idx >= 0 and idx < len(self._cards):
            card = self._cards[idx]
            mx, my = e.pos().x(), e.pos().y()
            # 1) Clicked an underlined key word → open details panel (NOT chat IA)
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
        """Yield (i, card, col_w, y, h, now) for visible cards, bottom→top.
        Cards live inside the VISIBLE part of the video (active rect): anchored
        to its right edge, stacked ABOVE the subtitle (no overlap), so they never
        land on black bars, screen corners or off-screen window areas."""
        ax0, ay0, ax1, ay1 = self._active_rect()
        col_w = min(350, int((ax1 - ax0) * 0.4))
        # Cards stack ABOVE a STABLE reserved band sized for a 2-line subtitle. This
        # mirrors the subtitle geometry in paintEvent (fs = ah//26, etc.) but for a
        # FIXED 2 lines — so the cards (a) never cover the subtitle, and (b) never jump
        # when the subtitle appears/disappears or switches between 1 and 2 lines.
        ah = ay1 - ay0
        fs = max(9, min(24, ah // 26))
        line_h = QFontMetrics(QFont("Inter", fs, QFont.Bold)).height() + 2
        margin_b = max(12, ah // 14) + self._transport_h
        sub_reserve = 2 * line_h + 14 + margin_b   # 2-line subtitle box + gap (+ transport)
        y = ay1 - sub_reserve - 8
        now = time.time()
        for i, card in enumerate(self._cards):
            nlines = max(len(card.text.split('\n')), 1)
            h = nlines * 18 + 20  # card height (text + padding, no username header)
            y -= h + 4
            if y < ay0:
                break
            yield (i, card, col_w, y, h, now)

    def _hit_test_vocab(self, pos):
        ax0, ay0, ax1, ay1 = self._active_rect()
        for i, card, cw, y, h, now in self._card_rects():
            x = ax1 - cw - 20  # match margin=20 in paintEvent
            if x <= pos.x() <= x + cw and y <= pos.y() <= y + h:
                return i
        return -1

    def _handle_vocab_click(self, mx, card, idx):
        ax0, ay0, ax1, ay1 = self._active_rect()
        col_w = min(350, int((ax1 - ax0) * 0.4))
        x = ax1 - col_w - 20
        btn_x = x + col_w - 52
        chat_x = btn_x + 24
        spk_x = btn_x - 24
        if spk_x <= mx <= spk_x + 22:
            self.speak_card.emit(card.text)   # ouvir a frase devagar
        elif btn_x <= mx <= btn_x + 22:
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
        # Everything is laid out inside the VISIBLE part of the video (the window
        # may hang off-screen; the video may be letterboxed). ax/ay = that rect.
        ax0, ay0, ax1, ay1 = self._active_rect()
        acx = (ax0 + ax1) // 2          # horizontal centre of the visible video
        # Top of the subtitle box this frame (updated below). The Twitch cards stack
        # ABOVE this so the two never overlap. Defaults to the FIXED one-line subtitle
        # line (not the visible bottom) so the cards keep the same lowest point whether
        # or not a main subtitle is currently showing — no more up/down jump.
        self._sub_top = self._sub_zone_top(ay0, ay1)

        # ── LOOP badge (clear feedback that the A-B loop is active) ──
        if self._loop_active:
            bf = QFont("Inter", 11, QFont.Bold); p.setFont(bf)
            bw = QFontMetrics(bf).horizontalAdvance("LOOP") + 24
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 230))
            p.drawRoundedRect(ax0 + 16, ay0 + 16, bw, 26, 13, 13)
            p.setPen(QColor(0, 0, 0)); p.drawText(QRect(ax0 + 16, ay0 + 16, bw, 26), Qt.AlignCenter, "LOOP")

        # ── AI LOOP badge ──
        if self._ai_loop_active:
            ai_label = f"AI LOOP {self._ai_loop_remaining}×" if self._ai_loop_remaining > 0 else "AI LOOP"
            bf = QFont("Inter", 11, QFont.Bold); p.setFont(bf)
            bw = QFontMetrics(bf).horizontalAdvance(ai_label) + 24
            bx = ax0 + 26 + (bw if self._loop_active else 16)
            p.setPen(Qt.NoPen); p.setBrush(QColor(75, 170, 230, 230))
            p.drawRoundedRect(bx, ay0 + 16, bw, 26, 13, 13)
            p.setPen(QColor(0, 0, 0)); p.drawText(QRect(bx, ay0 + 16, bw, 26), Qt.AlignCenter, ai_label)

        # ── Transient flash banner
        if self._flash_msg and time.time() < self._flash_until:
            ff = QFont("Inter", 12, QFont.DemiBold); p.setFont(ff)
            fm2 = QFontMetrics(ff)
            fbw = fm2.horizontalAdvance(self._flash_msg) + 36
            fbx = acx - fbw // 2
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 235))
            p.drawRoundedRect(fbx, ay0 + 18, fbw, 34, 17, 17)
            p.setPen(QColor(10, 10, 10))
            p.drawText(QRect(fbx, ay0 + 18, fbw, 34), Qt.AlignCenter, self._flash_msg)

        # ── "No subtitle — click to load" banner (top-centre, clickable) ──
        # Only when the flash isn't busy, so the two never fight for the spot.
        self._no_sub_rect = None
        if self._no_sub_hint and not (self._flash_msg and time.time() < self._flash_until):
            nf = QFont("Inter", 12, QFont.DemiBold); p.setFont(nf)
            nfm = QFontMetrics(nf)
            label = "  " + T("no_sub_banner")
            nbw = nfm.horizontalAdvance(label) + 44
            nbx = acx - nbw // 2
            nby = ay0 + 16
            rect = QRect(nbx, nby, nbw, 36)
            self._no_sub_rect = rect
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 205))
            p.drawRoundedRect(rect, 18, 18)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignCenter, label)

        # ── 1. Subtitle at the bottom of the VISIBLE video. The active rect already
        # accounts for the window hanging partly off-screen and for pillarbox bars,
        # so the subtitle always sits on video the user can actually see. VLC's own
        # subtitle renderer is disabled (single source, nothing over the controls). ──
        if self._current_sub:
            aw = ax1 - ax0; ah = ay1 - ay0
            # Banda de "espreitar" proporcional à altura do vídeo: 170px fixos eram
            # maiores que o vídeo em janela pequena → a legenda revelava SEMPRE, por
            # isso o "esconder legenda" só parecia funcionar no modo expandido.
            peek = min(150, max(44, int(ah * 0.28)))
            reveal = (not self._hide_subs) or (self._mouse_y > ay1 - peek)
            if reveal:
                # Responsive size: the font scales with the VISIBLE video height, so
                # a small (windowed) player gets smaller subtitles that fit, and a
                # big/full one gets larger. WRAPs to two lines instead of truncating.
                fs = max(9, min(24, ah // 26))
                sub_font = QFont("Inter", fs, QFont.Bold)
                fm = QFontMetrics(sub_font)
                ul_sub = QFont(sub_font); ul_sub.setUnderline(True)
                space_w = fm.horizontalAdvance(" ")
                line_h = fm.height() + 2
                pad = 16
                maxw = int(aw * 0.86)
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

                # ── 2ª/3ª linha (legendas duplas/triplas): por BAIXO da original,
                # mais pequenas e a cinzento (tema monocromático — distinguem-se pelo
                # tamanho/tom, não por cor) e quebradas em no máx. 2 linhas cada. ──
                tr_fs = max(8, fs - 3)
                tr_font = QFont("Inter", tr_fs)
                tr_fm = QFontMetrics(tr_font)
                tr_line_h = tr_fm.height() + 2
                tr_sp = tr_fm.horizontalAdvance(" ")

                def _wrap_plain(txt):
                    out, c, cw = [], [], 0
                    for wd in [x for x in txt.split(" ") if x]:
                        ww2 = tr_fm.horizontalAdvance(wd)
                        add = ww2 + (tr_sp if c else 0)
                        if c and cw + add > avail:
                            out.append(" ".join(c)); c, cw = [], 0; add = ww2
                        c.append(wd); cw += add
                    if c:
                        out.append(" ".join(c))
                    if len(out) > 2:
                        out = out[:2]; out[1] = out[1] + " …"
                    return out

                l2_lines = _wrap_plain(self._current_sub2) if self._current_sub2 else []
                l3_lines = _wrap_plain(self._current_sub3) if self._current_sub3 else []

                gap = 5 if (l2_lines or l3_lines) else 0
                inner_h = len(lines) * line_h
                if l2_lines:
                    inner_h += gap + len(l2_lines) * tr_line_h
                if l3_lines:
                    inner_h += (gap if not l2_lines else 3) + len(l3_lines) * tr_line_h
                box_h = inner_h + 14
                widths = [line_width(ln) for ln in lines]
                widths += [tr_fm.horizontalAdvance(s) for s in l2_lines]
                widths += [tr_fm.horizontalAdvance(s) for s in l3_lines]
                sw = min(maxw, max(widths, default=0) + 2 * pad)
                # Sobe a legenda acima do transport flutuante (study mode) para os
                # controlos NUNCA a taparem.
                margin_b = max(12, ah // 14) + self._transport_h
                sy = ay1 - box_h - margin_b         # bottom of the VISIBLE video
                sx = acx - sw // 2                  # centred on the visible video
                self._sub_top = sy                  # cards stack above this (no overlap)
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 200))
                p.drawRoundedRect(sx, sy, sw, box_h, 8, 8)

                # Original (branco) — palavra a palavra; tinge palavras-chave (sem
                # sublinhar). Só os cartões Twitch têm palavras clicáveis para detalhes.
                self._sub_word_rects = []
                for li, ln in enumerate(lines):
                    lx = acx - line_width(ln) // 2
                    ly = sy + 7 + li * line_h
                    for word, mk in ln:
                        ww = fm.horizontalAdvance(word)
                        if mk and mk["color"]:
                            p.setPen(QColor(mk["color"]))
                            p.setFont(sub_font)  # no underline
                        else:
                            p.setPen(QColor(255, 255, 255)); p.setFont(sub_font)
                        p.drawText(QRect(lx, ly, ww + 4, line_h), Qt.AlignLeft | Qt.AlignVCenter, word)
                        lx += ww + space_w

                # 2ª linha (tradução / legenda dupla) — cinzento claro.
                ty = sy + 7 + len(lines) * line_h
                if l2_lines:
                    ty += gap
                    p.setFont(tr_font); p.setPen(QColor(200, 200, 200))
                    for s in l2_lines:
                        sw2 = tr_fm.horizontalAdvance(s)
                        p.drawText(QRect(acx - sw2 // 2, ty, sw2 + 4, tr_line_h),
                                   Qt.AlignLeft | Qt.AlignVCenter, s)
                        ty += tr_line_h
                # 3ª linha (legenda tripla) — cinzento mais ténue.
                if l3_lines:
                    ty += (gap if not l2_lines else 3)
                    p.setFont(tr_font); p.setPen(QColor(150, 150, 150))
                    for s in l3_lines:
                        sw3 = tr_fm.horizontalAdvance(s)
                        p.drawText(QRect(acx - sw3 // 2, ty, sw3 + 4, tr_line_h),
                                   Qt.AlignLeft | Qt.AlignVCenter, s)
                        ty += tr_line_h
                p.setFont(sub_font)
            else:
                # Active-recall: subtitle hidden — discreet placeholder, peek by
                # moving the mouse to the bottom of the video.
                ph = "•  •  •   (passa o rato em baixo para ver)"
                pf = QFont("Inter", 11); pfm = QFontMetrics(pf)
                pw = pfm.horizontalAdvance(ph) + 40
                px = acx - pw // 2
                py = ay1 - 52
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 130))
                p.drawRoundedRect(px, py, pw, 26, 13, 13)
                p.setPen(QColor(200, 200, 200, 180)); p.setFont(pf)
                p.drawText(QRect(px, py, pw, 26), Qt.AlignCenter, ph)

        # ── 2. Twitch-style vocab cards — right column, slide from right ──
        if not self._cards:
            p.end()
            return

        # Esconder os cartões Twitch JUNTO com a legenda: em recall ativo (esconder
        # legenda ON) os cartões revelariam o vocabulário da fala. Só aparecem quando a
        # legenda também está revelada (rato no fundo do vídeo).
        if self._hide_subs:
            peek = min(150, max(44, int((ay1 - ay0) * 0.28)))
            if not (self._mouse_y > ay1 - peek):
                p.end()
                return

        fm = QFontMetrics(QFont("Inter", 11))
        now = time.time()
        # Fixed-width right column: max 350px or 40% of the visible video
        col_w = min(350, int((ax1 - ax0) * 0.4))
        margin = 20  # right margin from the visible video's right edge

        for i, card, cw, y, h, _ in self._card_rects():
            # Full opacity — no fade-out. Cards persist until newer cards push them
            # out (count-based), so they never vanish on pause.
            alpha = 230
            hovering = (i == self._hover_idx)

            # Right-aligned within the VISIBLE video (never black bars / off-screen)
            target_x = ax1 - col_w - margin
            start_x = ax1  # slides in from the visible right edge

            # Slide animation: 150ms ease-out (rapido)
            slide_t = min(1.0, (now - card.slide_start) / 0.15)
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
            # Reserva uma faixa à direita para os botões (♪ / + / AI / ✓) — sem isto o
            # texto comprido passava POR BAIXO dos botões ("botões em cima das letras").
            text_right = cur_x + col_w - 82
            # Text starts close to the top of the card (no username header)
            text_y_offset = 6
            for li, line in enumerate(lines[:2]):
                wx = cur_x + 14
                wy = y + text_y_offset + li * 18
                words = line[:70].split(" ")
                marks = mark_tokens(words)
                for word, mk in zip(words, marks):
                    if not word:
                        wx += sp_w; continue
                    ww = fmc.horizontalAdvance(word)
                    if wx + ww > text_right:
                        # Não há espaço sem invadir os botões → reticências e corta.
                        p.setPen(QColor(255, 255, 255, alpha)); p.setFont(base_font)
                        p.drawText(QRect(wx, wy, 16, 18), Qt.AlignLeft | Qt.AlignVCenter, "…")
                        break
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

            # Buttons on hover — fundos opacos para não deixarem ver o texto por trás
            if hovering:
                bx = cur_x + col_w - 52
                # ♪ ouvir devagar — à esquerda do +. Ícone do Segoe (sem emojis).
                spk_bx = bx - 24
                p.setBrush(QColor(45, 45, 45, 245))
                p.drawRoundedRect(spk_bx, y + (h - 22) // 2, 20, 18, 4, 4)
                p.setPen(QColor(210, 210, 210, alpha))
                p.setFont(QFont("Segoe Fluent Icons", 9))
                p.drawText(QRect(spk_bx, y + (h - 22) // 2, 20, 18), Qt.AlignCenter, chr(0xE767))

                add_bg = QColor(34, 120, 60, 245) if card.saved else QColor(45, 45, 45, 245)
                p.setBrush(add_bg)
                p.drawRoundedRect(bx, y + (h - 22) // 2, 20, 18, 4, 4)
                p.setPen(QColor(255, 255, 255, alpha))
                p.setFont(QFont("Inter", 9, QFont.Bold))
                p.drawText(QRect(bx, y + (h - 22) // 2, 20, 18), Qt.AlignCenter, "✓" if card.saved else "+")

                chat_bg = QColor(45, 45, 45, 245)
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


# ═══════════════════════════════════════════════════════════════════════════
# AVALIAÇÃO DE IMAGENS — 👍/👎 em cada imagem. Guardado localmente E sincronizado
# para o Supabase (tabela image_ratings). As avaliações ENVIESAM a ordem das
# candidatas na próxima vez (gostadas primeiro, rejeitadas no fim) → a escolha de
# imagem fica cada vez mais precisa. Mesma ideia replicada na web.
# ═══════════════════════════════════════════════════════════════════════════
IMG_RATINGS_FILE = DATA_DIR / 'image-ratings.json'

def _load_img_ratings():
    try:
        if IMG_RATINGS_FILE.exists():
            return json.loads(IMG_RATINGS_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}

_IMG_RATINGS = _load_img_ratings()   # { "word\turl": score }  +1 gostei / -1 não

def _img_rating_key(word, url):
    return f"{(word or '').strip().lower()}\t{url}"

def get_image_rating(word, url):
    try:
        return int(_IMG_RATINGS.get(_img_rating_key(word, url), 0))
    except Exception:
        return 0

def set_image_rating_local(word, url, score):
    k = _img_rating_key(word, url)
    if score == 0:
        _IMG_RATINGS.pop(k, None)
    else:
        _IMG_RATINGS[k] = int(score)
    try:
        IMG_RATINGS_FILE.write_text(json.dumps(_IMG_RATINGS, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        log(f"save image ratings: {e}")

def sync_image_rating(word, url, score, auth_header=None):
    """Fire-and-forget upsert para o Supabase (image_ratings). Só sincroniza com
    sessão iniciada; offline/deslogado fica só local."""
    if not auth_header or not url:
        return
    def _worker():
        try:
            import base64
            tok = auth_header.split(" ", 1)[1]
            pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                return
            row = {"user_id": uid, "word": (word or "").strip().lower(),
                   "image_url": url, "score": int(score)}
            headers = {"Content-Type": "application/json", "apikey": SUPABASE_ANON,
                       "Authorization": auth_header,
                       "Prefer": "resolution=merge-duplicates,return=minimal"}
            urlopen(Request(f"{SUPABASE_URL}/rest/v1/image_ratings?on_conflict=user_id,word,image_url",
                            data=json.dumps(row).encode(), headers=headers), timeout=15)
            log(f"image rating synced: {word} {score:+d}")
        except Exception as e:
            log(f"image rating sync: {e}")
    threading.Thread(target=_worker, daemon=True).start()

def apply_rating_bias(word, candidates):
    """Reordena candidatas pelas avaliações guardadas: gostadas primeiro,
    rejeitadas no fim (mas nunca remove todas — há SEMPRE imagem)."""
    liked, neutral, disliked = [], [], []
    for u in candidates:
        s = get_image_rating(word, u)
        (liked if s > 0 else disliked if s < 0 else neutral).append(u)
    return liked + neutral + disliked

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


# ── Online subtitle search (OpenSubtitles legacy REST — keyless) ──────────────
# ISO 639-1 (UI codes) → ISO 639-2/B (what OpenSubtitles' sublanguageid expects).
_OS_LANG3 = {
    "en": "eng", "pt": "por", "es": "spa", "fr": "fre", "de": "ger", "it": "ita",
    "nl": "dut", "ru": "rus", "ar": "ara", "zh": "chi", "ja": "jpn", "ko": "kor",
    "hi": "hin", "tr": "tur", "pl": "pol", "sv": "swe", "vi": "vie", "th": "tha",
    "id": "ind", "uk": "ukr", "ro": "rum", "el": "ell", "cs": "cze", "da": "dan",
    "fi": "fin", "no": "nor", "hu": "hun", "he": "heb", "fa": "per", "bg": "bul",
    "hr": "hrv", "sr": "srp", "sk": "slo", "sl": "slv", "et": "est", "lt": "lit",
    "lv": "lav", "ca": "cat", "gl": "glg", "eu": "eus", "is": "ice", "sq": "alb",
}
# A sensible default order for the language picker (covers most learners).
_OS_LANG_ORDER = ["en", "es", "pt", "fr", "de", "it", "nl", "ru", "ar", "zh",
                  "ja", "ko", "hi", "tr", "pl", "sv", "vi", "th", "id", "uk",
                  "ro", "el", "cs", "da", "fi", "no", "hu", "he", "fa"]
_OS_UA = "TemporaryUserAgent"   # OpenSubtitles' documented keyless test UA
# A API legacy (rest.opensubtitles.org) bloqueia/limita por User-Agent e anda muitas
# vezes em baixo. Sem chave, a única forma de falhar menos é tentar vários User-Agents
# conhecidos (todos públicos/de teste) até um responder. Ordem = do mais fiável p/ menos.
_OS_UAS = ["TemporaryUserAgent", "VLSub 0.10.2", "trailers.to-UA", "SubDownloader/1.0"]
_OS_HOSTS = ["https://rest.opensubtitles.org", "https://api.opensubtitles.org"]

def _clean_sub_query(stem):
    """Turn a video filename into a clean search query: drop release tags
    (1080p, x264, BluRay…), years and separators, keep the title words."""
    s = re.sub(r"[._]+", " ", stem or "")
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)        # bracketed groups
    s = re.split(r"\b(19|20)\d{2}\b", s)[0] or s        # cut at a year
    s = re.sub(r"\b(1080p|720p|480p|2160p|4k|x264|x265|h264|h265|hevc|bluray|"
               r"blu-ray|brrip|bdrip|webrip|web-dl|webdl|hdrip|dvdrip|xvid|aac|"
               r"ac3|dts|hdtv|proper|repack|remux|yify|yts|rarbg)\b.*$", "",
               s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s or (stem or "")


class SubSearchDialog(QDialog):
    """Search OpenSubtitles (keyless legacy API) for a subtitle and load it.
    All network work runs off the UI thread; results come back via signals.
    On accept, ``self.result_path`` holds the saved .srt path."""
    _search_done = pyqtSignal(object, object)   # (results | None, error | None)
    _dl_done = pyqtSignal(object, object)        # (saved_path | None, error | None)

    def __init__(self, parent, query, video_path, default_lang):
        super().__init__(parent)
        self.setWindowTitle(T("subsearch_title"))
        self.setMinimumSize(560, 460)
        self.setStyleSheet(f"background:{BG};color:{TXT};")
        self.result_path = None
        self._video_path = video_path
        self._busy = False

        lo = QVBoxLayout(self); lo.setContentsMargins(16, 14, 16, 14); lo.setSpacing(10)
        title = QLabel(T("subsearch_title"))
        title.setStyleSheet(f"color:{TXT};font-size:15px;font-weight:bold;background:transparent;")
        lo.addWidget(title)

        # Query + language + search button
        row = QHBoxLayout(); row.setSpacing(8)
        self.q = QLineEdit(query)
        self.q.setPlaceholderText(T("subsearch_query"))
        self.q.setStyleSheet(f"QLineEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};"
                             f"border-radius:6px;padding:7px 10px;font-size:12px;}}QLineEdit:focus{{border-color:{ACC};}}")
        row.addWidget(self.q, 1)
        self.lang = QComboBox()
        self.lang.setStyleSheet(
            f"QComboBox{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:6px;padding:6px 8px;font-size:12px;}}"
            f"QComboBox QAbstractItemView{{background:{ELV};color:{TXT};selection-background-color:{HVR};}}")
        for code in _OS_LANG_ORDER:
            self.lang.addItem(i18n.language_display_name(code), code)
        di = self.lang.findData(default_lang)
        if di >= 0:
            self.lang.setCurrentIndex(di)
        row.addWidget(self.lang)
        self.btn = QPushButton(T("subsearch_btn"))
        self.btn.setStyleSheet(f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:6px;"
                               f"padding:7px 16px;font-size:12px;font-weight:600;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.btn.clicked.connect(self._do_search)
        row.addWidget(self.btn)
        lo.addLayout(row)

        self.results = QListWidget()
        self.results.setStyleSheet(
            f"QListWidget{{background:{SRF};color:{TXT};border:1px solid {BRD};border-radius:6px;font-size:12px;}}"
            f"QListWidget::item{{padding:7px 9px;border-bottom:1px solid {BRD};}}"
            f"QListWidget::item:selected{{background:{HVR};color:{TXT};}}")
        self.results.itemDoubleClicked.connect(self._download_selected)
        lo.addWidget(self.results, 1)

        self.status = QLabel(T("subsearch_hint"))
        self.status.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        lo.addWidget(self.status)

        self._search_done.connect(self._on_search_done)
        self._dl_done.connect(self._on_dl_done)
        self.q.returnPressed.connect(self._do_search)
        QTimer.singleShot(250, self._do_search)   # auto-search with the prefilled title

    # — search —
    def _do_search(self):
        if self._busy:
            return
        q = self.q.text().strip()
        if not q:
            return
        lang3 = _OS_LANG3.get(self.lang.currentData(), "eng")
        self._busy = True; self.btn.setEnabled(False)
        self.results.clear(); self.status.setText(T("subsearch_searching"))
        threading.Thread(target=self._search_worker, args=(q, lang3), daemon=True).start()

    def _search_worker(self, q, lang3):
        from urllib.parse import quote
        path = f"/search/query-{quote(q)}/sublanguageid-{lang3}"
        last_err = None
        # Sem chave: tenta cada host x cada User-Agent até um devolver uma lista válida.
        for host in _OS_HOSTS:
            for ua in _OS_UAS:
                try:
                    req = Request(host + path, headers={
                        "X-User-Agent": ua, "User-Agent": ua, "Accept": "application/json"})
                    raw = urlopen(req, timeout=20).read().decode("utf-8", "replace")
                    data = json.loads(raw)
                    if not isinstance(data, list):
                        data = []
                    if not data:
                        last_err = "empty"
                        continue
                    data.sort(key=lambda d: int(d.get("SubDownloadsCnt") or 0), reverse=True)
                    self._search_done.emit(data[:40], None)
                    return
                except Exception as e:
                    last_err = str(e)
                    log(f"subsearch {host} [{ua}]: {e}")
        # Nada respondeu com resultados.
        if last_err == "empty":
            self._search_done.emit([], None)        # serviço respondeu, mas sem matches
        else:
            self._search_done.emit(None, last_err or "fail")

    def _on_search_done(self, data, err):
        self._busy = False; self.btn.setEnabled(True)
        if err is not None:
            self.status.setText(T("subsearch_fail")); return
        if not data:
            self.status.setText(T("subsearch_none")); return
        for d in data:
            name = d.get("MovieReleaseName") or d.get("SubFileName") or "—"
            dls = d.get("SubDownloadsCnt") or "0"
            lang = d.get("LanguageName") or ""
            it = QListWidgetItem(f"{name}\n   {lang} · ⬇ {dls}")
            it.setData(Qt.UserRole, d.get("SubDownloadLink") or "")
            self.results.addItem(it)
        self.status.setText(T("subsearch_hint"))

    # — download —
    def _download_selected(self, item):
        if self._busy or item is None:
            return
        link = item.data(Qt.UserRole)
        if not link:
            return
        self._busy = True; self.status.setText(T("subsearch_downloading"))
        threading.Thread(target=self._dl_worker, args=(link,), daemon=True).start()

    def _dl_worker(self, link):
        import gzip
        blob = None; last_err = None
        for ua in _OS_UAS:
            try:
                req = Request(link, headers={"X-User-Agent": ua, "User-Agent": ua})
                blob = urlopen(req, timeout=30).read()
                break
            except Exception as e:
                last_err = str(e); log(f"subdl [{ua}]: {e}")
        if blob is None:
            self._dl_done.emit(None, last_err or "fail"); return
        try:
            try:
                srt_bytes = gzip.decompress(blob)
            except Exception:
                srt_bytes = blob   # some mirrors return the raw .srt
            # utf-8-sig strips a leading BOM (OpenSubtitles files often carry one),
            # which would otherwise corrupt the first cue index for the parser.
            text = srt_bytes.decode("utf-8-sig", "replace")
            # Save next to the video (so it's auto-found next time); fall back to the data dir.
            try:
                dest = Path(self._video_path).with_suffix(".srt")
                dest.write_text(text, encoding="utf-8")
            except Exception:
                dest = DATA_DIR / (Path(self._video_path).stem + ".srt")
                dest.write_text(text, encoding="utf-8")
            self._dl_done.emit(str(dest), None)
        except Exception as e:
            log(f"subdl: {e}")
            self._dl_done.emit(None, str(e))

    def _on_dl_done(self, path, err):
        self._busy = False
        if err is not None or not path:
            self.status.setText(T("subsearch_dl_fail")); return
        self.result_path = path
        self.accept()


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
body{background:#121212;color:#fff;font-family:'Inter','Segoe UI',sans-serif;
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
    speak_requested = pyqtSignal(str)                  # ♪ ouvir a legenda devagar (texto do input ou legenda atual)
    user_sent = pyqtSignal(str)                        # o utilizador enviou uma mensagem (texto) — usado pelo modo Listening
    eval_result = pyqtSignal(object, object)           # (response_text | None, error | None) — usado pelos diálogos de avaliação
    lesson_result = pyqtSignal(object, object, object) # (text | None, loader, done_cb) — narração ao vivo das aulas

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages = []
        self._token = self._load_token()
        self._user_name = ""           # nome do utilizador (perfil da web)
        self._user_target = load_account_langs().get("target", "") or ""  # foco (perfil web), em cache p/ offline
        self._activity_summary = ""    # resumo da atividade (player+web) p/ a IA "conhecer" o user
        self._setup_ui()
        self._ai_thread = None
        self.login_result.connect(self._on_login_done)
        self.chat_result.connect(self._on_chat_result)
        self.lesson_result.connect(self._on_lesson_result)
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
        title.setStyleSheet(f"color:{TXT};font-size:14px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        hl.addWidget(title)
        hl.addStretch()
        self.login_btn = QPushButton(T("login") if not self._token else T("account"))
        # Altura fixa mas largura ajusta-se ao texto (Login/Conta/Account não cortam).
        # Chip preenchido (não um contorno solto) — assenta melhor no cabeçalho do chat.
        self.login_btn.setFixedHeight(26); self.login_btn.setMinimumWidth(60)
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.login_btn.setStyleSheet(
            f"QPushButton{{background:{ELV};border:1px solid {BRD};border-radius:13px;"
            f"color:{TXT};font-size:11px;font-weight:600;padding:0 14px;"
            f"font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{HVR};border-color:{ACC};color:{TXT};}}")
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

        # Boas-vindas com tipografia cuidada: 1ª linha vira título, o resto fica
        # como exemplos discretos (chips), em vez de um bloco de texto achatado.
        self.welcome = QLabel()
        self.welcome.setTextFormat(Qt.RichText)
        _wl = [l.strip() for l in T("chat_welcome").split("\n") if l.strip()]
        _wtitle = _wl[0] if _wl else T("chat_welcome")
        _wex = "".join(
            f"<div style='margin-top:9px;padding:7px 12px;background:{ELV};"
            f"border:1px solid {BRD};border-radius:12px;color:{TMT};font-size:12px;'>{l}</div>"
            for l in _wl[1:] if not l.lower().startswith(("e.g", "ex.", "ex:", "por exemplo", "p. ex")))
        self.welcome.setText(
            f"<div style='font-size:15px;font-weight:700;color:{TXT};margin-bottom:4px;'>{_wtitle}</div>"
            f"{_wex}")
        self.welcome.setStyleSheet(
            f"color:{TMT};font-family:'Inter','Segoe UI',sans-serif;"
            f"background:transparent;padding:30px 22px;")
        self.welcome.setWordWrap(True); self.welcome.setAlignment(Qt.AlignCenter)
        self.ml.insertWidget(0, self.welcome)

        inp = QWidget(); inp.setStyleSheet(f"background:{ELV};border-top:1px solid {BRD};")
        il = QHBoxLayout(inp); il.setContentsMargins(6,6,6,6)
        # ♪ ouvir devagar — diz a legenda (ou o texto escrito) com voz neural lenta.
        speak = QPushButton(chr(0xE767)); speak.setFixedSize(36, 36)
        speak.setToolTip(T("chat_speak_tip"))
        speak.setCursor(Qt.PointingHandCursor)
        speak.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {BRD};border-radius:15px;"
            f"color:{TS2};font-family:'Segoe Fluent Icons','Segoe MDL2 Assets';font-size:14px;}}"
            f"QPushButton:hover{{border-color:{ACC};color:{TXT};background:{HVR};}}")
        speak.clicked.connect(lambda: self.speak_requested.emit(self.input.text().strip()))
        il.addWidget(speak)
        self.input = QLineEdit()
        self.input.setPlaceholderText(T("chat_placeholder"))
        self.input.setStyleSheet(f"QLineEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:19px;padding:9px 15px;font-size:12.5px;font-family:'Inter','Segoe UI',sans-serif;}}QLineEdit:focus{{border-color:{ACC};background:{HVR};}}")
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
            info = {"name": "", "target": "", "native": "", "videos": []}
            try:
                u = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{uid}&select=display_name,target_lang,native_lang"
                d = json.loads(urlopen(Request(u, headers=ih), timeout=15).read().decode())
                if d:
                    info["name"] = d[0].get("display_name") or ""
                    info["target"] = d[0].get("target_lang") or ""
                    info["native"] = d[0].get("native_lang") or ""
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
        # Língua NATIVA e de FOCO vêm do perfil web (não do desktop). A nativa manda no
        # conteúdo (explicações/exercícios); guardamos ambas para o próximo arranque.
        native = (info.get("native", "") or "").strip()
        if native:
            set_native(native)        # conteúdo passa a sair na nativa real da conta
        save_account_langs(native=native or None, target=self._user_target or None)
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
        self.user_sent.emit(t)   # modo Listening usa isto para retomar o filme com "continuar"
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
        # Resposta da IA: sublinha o vocabulário-chave (MESMO sistema das legendas),
        # clicável → abre a aba Detalhes. user/system ficam em texto simples.
        if role == "assistant":
            msg.setOpenExternalLinks(False)
            msg.setTextFormat(Qt.RichText)
            msg.setText(mark_html(text, subtle=True))
            try: msg.linkActivated.connect(self._on_marked_word)
            except Exception: pass
        else:
            msg.setOpenExternalLinks(True)
            msg.setTextFormat(Qt.PlainText)
            msg.setText(text)
        msg.setStyleSheet(f"QLabel{{background:transparent;color:{fg};font-size:12.5px;}}"
                          f"QLabel a{{color:{ACC};}}")
        msg.setMaximumWidth(252)
        bl.addWidget(msg)

        c = QWidget(); c.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(c); cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(bubble, 0, align)
        self.ml.insertWidget(self.ml.count() - 1, c)

    def _on_marked_word(self, href):
        """Clique numa palavra/expressão sublinhada numa mensagem da IA → abre a aba
        Detalhes (mesmo destino que clicar numa palavra das legendas). Links http
        normais abrem no navegador."""
        if not href:
            return
        if href.startswith("lexioword:"):
            from urllib.parse import unquote
            word = unquote(href.split(":", 1)[1])
            mw = self.parent()
            try:
                if mw and hasattr(mw, "word_details"):
                    mw.word_details.show_for(word)
                    if hasattr(mw, "_balance_left_dock"):
                        mw._balance_left_dock()
            except Exception as e:
                log(f"marked word: {e}")
        else:
            try:
                from PyQt5.QtGui import QDesktopServices
                from PyQt5.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(href))
            except Exception:
                pass

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
                parts = ["You are Lexio's in-player AI language TUTOR for a learner watching a video — act like a real, thorough teacher, not a chatbot.",
                         f"Always reply in the user's native language ({native_language_name()}), warm and encouraging.",
                         "Teach in depth: when a word, phrase or expression comes up, give (1) a clear meaning, "
                         "(2) 1–2 natural EXAMPLE sentences, (3) common COLLOCATIONS / how it's really used, "
                         "(4) close SYNONYMS and any useful antonyms, and (5) register or nuance (formal/informal, "
                         "tone) when relevant. Point out related expressions and frequent mistakes.",
                         "Keep it well organised and skimmable: short paragraphs or simple bullet lines, never a wall of text. "
                         "Don't over-explain trivial words; go deep only where it helps. Always end by inviting a follow-up question."]
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

    def request_evaluation(self, system_extra, user_text):
        """Envia um pedido de avaliação (Fluência/Paráfrase) através do chat IA,
        herdando todo o contexto do utilizador (nome, nível, vídeo atual, palavras
        guardadas). O resultado vem pelo sinal eval_result.
        A resposta NÃO é adicionada ao histórico do chat visível."""
        import ssl
        def work():
            try:
                parts = ["You are Lexio's in-player AI tutor for a language learner watching a video.",
                         f"Always reply in the user's native language ({native_language_name()}), "
                         f"warm and concise. Respond ONLY with valid JSON."]
                if self._user_name:
                    parts.append(f"The user's name is {self._user_name}.")
                if self._activity_summary:
                    parts.append("User activity: " + self._activity_summary)
                if self.parent() and hasattr(self.parent(), 'engine') and self.parent().engine.path():
                    vn = Path(self.parent().engine.path()).name
                    parts.append(f"Currently watching: {vn}")
                try:
                    _vf = DATA_DIR / 'saved-vocab.json'
                    if _vf.exists():
                        _saved = json.loads(_vf.read_text(encoding='utf-8'))
                        _words = [s.get('text', '') for s in _saved[-30:] if s.get('text')]
                        if _words:
                            parts.append("Saved vocab: " + "; ".join(_words))
                except: pass
                parts.append(system_extra)
                ctx = "\n".join(parts)
                hdrs = {"Content-Type": "application/json"}
                auth_header = self._get_token_header()
                if auth_header:
                    hdrs["Authorization"] = auth_header
                msgs = [{"role": "system", "content": ctx},
                        {"role": "user", "content": user_text}]
                payload = {"model": "deepseek-chat", "max_tokens": 800, "temperature": 0.3,
                           "feature": "evaluation", "messages": msgs}
                body = json.dumps(payload).encode()
                ctx_ssl = ssl._create_unverified_context()
                r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body, headers=hdrs),
                            timeout=15, context=ctx_ssl)
                d = json.loads(r.read().decode())
                c = d.get("text") or d.get("content") or ""
                self.eval_result.emit(c.strip(), None)
            except Exception as e:
                log(f"eval err: {e}")
                self.eval_result.emit(None, str(e))
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

    # ── Narração ao vivo das aulas (tracks) ──
    def post_lesson_note(self, system_extra, user_text, done_cb=None):
        """Pede à IA uma explicação curta da cena/legenda atual e larga-a no chat
        como mensagem do tutor. Uma chamada por legenda (modo 'ao vivo'). Reaproveita
        o caminho de entrega na GUI via lesson_result. done_cb corre na GUI no fim."""
        self.welcome.hide()
        load = QLabel(T("lesson_narrating"))
        load.setStyleSheet(f"color:{ACC};font-size:11px;padding:4px;background:transparent;font-weight:bold;")
        lc = QWidget(); lc.setStyleSheet("background:transparent;")
        lcl = QVBoxLayout(lc); lcl.setContentsMargins(0,0,0,0); lcl.addWidget(load, 0, Qt.AlignLeft)
        self.ml.insertWidget(self.ml.count()-1, lc)
        scroll = self.findChild(QScrollArea)
        if scroll:
            QTimer.singleShot(50, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))
        def work():
            try:
                target = (getattr(self, "_user_target", "") or "").strip()
                tgt_clause = (f"the language the learner is studying ({target})" if target
                              else "the language being learned (the language of the film's subtitles)")
                parts = [
                    "You are Lexio's in-player AI tutor giving a LIVE, guided lesson over a video "
                    "for a language learner. Explain what is happening in the scene, the context, "
                    "tone, cultural references and any tricky vocabulary or expressions.",
                    f"Give the lesson IN {tgt_clause}: write your explanation in that target language so "
                    "the learner stays immersed — this is a real lesson, not a translation into their "
                    "own language. Keep it natural but GRADED to their level: short, clear sentences, "
                    "and briefly gloss any hard word/expression. Only when something is genuinely "
                    f"confusing, add a tiny clarification in {native_language_name()} in parentheses. "
                    "Be warm and SHORT (2-4 sentences). Plain prose, no headings, no lists."]
                if self._user_name:
                    parts.append(f"The user's name is {self._user_name}.")
                if self.parent() and hasattr(self.parent(), 'engine') and self.parent().engine.path():
                    parts.append("They are watching: " + Path(self.parent().engine.path()).name)
                parts.append(system_extra)
                ctx = "\n".join(parts)
                hdrs = {"Content-Type": "application/json"}
                auth = self._get_token_header()
                if auth: hdrs["Authorization"] = auth
                msgs = [{"role": "system", "content": ctx},
                        {"role": "user", "content": user_text}]
                payload = {"model": "deepseek-chat", "max_tokens": 320, "temperature": 0.4,
                           "feature": "chat", "messages": msgs}
                r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat",
                                    data=json.dumps(payload).encode(), headers=hdrs), timeout=30)
                d = json.loads(r.read().decode())
                c = d.get("text") or d.get("content") or ""
                if not c and "choices" in d: c = d["choices"][0]["message"]["content"]
                self.lesson_result.emit((c or "").strip() or None, lc, done_cb)
            except Exception as e:
                log(f"lesson note err: {e}")
                self.lesson_result.emit(None, lc, done_cb)
        threading.Thread(target=work, daemon=True).start()

    def _on_lesson_result(self, text, lc, done_cb):
        """GUI thread: remove o loader, mostra a nota (se houver) e chama o callback.
        As notas de aula NÃO entram no histórico do chat (_messages) para não roubar
        a memória da conversa normal."""
        try: lc.deleteLater()
        except Exception: pass
        if text:
            self._add_msg(text, "assistant")
            scroll = self.findChild(QScrollArea)
            if scroll:
                QTimer.singleShot(50, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))
        if done_cb:
            try: done_cb()
            except Exception as e: log(f"lesson done_cb err: {e}")

    # ── Promote a video-vocab word to the user's MAIN account vocabulary ──
    def promote_word(self, text, note="", translation=""):
        """Adiciona a palavra ao vocabulário PRINCIPAL na conta web (tabela words).
        note/translation = personalização opcional do utilizador (cai na conta web)."""
        if not text:
            return
        header = self._get_token_header()
        if not header:
            self._add_msg(T("need_login_vocab"), "system")
            return
        self._add_msg(f"A adicionar “{text[:40]}” ao teu vocabulário…", "system")
        threading.Thread(target=self._promote_worker,
                         args=(text, header, note, translation), daemon=True).start()

    def _promote_worker(self, text, header, note="", translation=""):
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

            # Personalização do utilizador (vai junto p/ a conta web):
            # tradução manual sobrepõe-se à da IA; a nota fica visível na definição.
            definition = pack.get("definition", "")
            tags = ["video"]
            if note and note.strip():
                definition = (definition + ("\n" if definition else "") + f"Nota: {note.strip()}").strip()
                tags = ["video", "nota"]
            row = {
                "user_id": uid, "word": pack.get("word") or text,
                "lang": (pack.get("lang") or "en")[:5],
                "translation": (translation.strip() if translation and translation.strip() else pack.get("translation", "")),
                "type": "word", "definition": definition,
                "examples": pack.get("examples") or [], "tags": tags,
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


class ReminderManager(QObject):
    """Lembrete de revisão espaçada: a cada N minutos mostra uma notificação do
    sistema com uma palavra GUARDADA que está 'a vencer' (tabela `words` da
    conta), com a tradução e uma frase de exemplo. As palavras vêm da conta, por
    isso precisa de login; sem sessão fica em silêncio. Liga/desliga e intervalo
    são configuráveis na aba Ferramentas e ficam guardados em reminder.json."""
    show_note = pyqtSignal(str, str)   # (título, corpo) — emitido p/ a GUI

    def __init__(self, get_header, parent=None):
        super().__init__(parent)
        self._get_header = get_header          # callable → "Bearer ..." (ou None)
        self._recent = []                      # palavras já mostradas (evita repetir)
        cfg = self._load()
        self.enabled = bool(cfg.get("enabled", False))
        self.interval_min = max(5, int(cfg.get("interval_min", 30)))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if self.enabled:
            self._timer.start(self.interval_min * 60_000)

    def _load(self):
        try:
            if REMINDER_FILE.exists():
                return json.loads(REMINDER_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def _save(self):
        try:
            REMINDER_FILE.write_text(json.dumps(
                {"enabled": self.enabled, "interval_min": self.interval_min},
                indent=2), encoding='utf-8')
        except Exception:
            pass

    def set_enabled(self, on):
        self.enabled = bool(on)
        self._save()
        self._timer.stop()
        if self.enabled:
            self._timer.start(self.interval_min * 60_000)

    def set_interval(self, minutes):
        self.interval_min = max(5, int(minutes))
        self._save()
        if self.enabled:
            self._timer.stop()
            self._timer.start(self.interval_min * 60_000)

    def _tick(self):
        if not self.enabled:
            return
        header = self._get_header() if self._get_header else None
        if not header:
            return   # sem login → sem lembrete (silencioso)
        threading.Thread(target=self._fetch_and_emit, args=(header,), daemon=True).start()

    def _fetch_and_emit(self, header):
        import base64
        try:
            tok = header.split(" ", 1)[1]
            pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            uid = json.loads(base64.urlsafe_b64decode(pl).decode()).get("sub")
            if not uid:
                return
            now_iso = datetime.now().isoformat()
            q = (f"{SUPABASE_URL}/rest/v1/words?user_id=eq.{uid}"
                 f"&select=word,translation,definition,examples,due_date"
                 f"&order=due_date.asc&limit=40")
            hdrs = {"apikey": SUPABASE_ANON, "Authorization": header}
            r = urlopen(Request(q, headers=hdrs), timeout=20)
            rows = json.loads(r.read().decode())
            if not rows:
                return
            # Prefere as vencidas (due_date <= agora); se nenhuma, usa as mais próximas.
            due = [w for w in rows if (w.get("due_date") or "") <= now_iso] or rows
            pick = next((w for w in due if w.get("word") not in self._recent), None)
            if pick is None:
                self._recent.clear()
                pick = due[0]
            self._recent.append(pick.get("word"))
            if len(self._recent) > 20:
                self._recent.pop(0)
            word = (pick.get("word") or "").strip()
            tr = (pick.get("translation") or "").strip()
            exs = pick.get("examples") or []
            ex = (exs[0] if exs else "").strip()
            body = tr
            if ex:
                body = (body + "\n" + ex).strip() if body else ex
            if not body:
                body = (pick.get("definition") or "").strip()[:140]
            self.show_note.emit(word or T("reminder_title"), body or word)
        except Exception as e:
            log(f"reminder fetch: {e}")


def _thumb_icon(up, color, size=16):
    """Draw a clean, monochrome thumbs-up / thumbs-down ICON (no emoji) — sleeve +
    fist + raised thumb, rotated 180° for 'down'. Matches the player's flat theme."""
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2.0, size / 2.0)
    p.scale(size / 24.0, size / 24.0)
    if not up:
        p.rotate(180)
    p.translate(-12, -12)
    p.setPen(Qt.NoPen); p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(2.0, 13.0, 4.0, 9.0), 1.2, 1.2)    # sleeve / wrist
    p.drawRoundedRect(QRectF(7.0, 11.0, 13.0, 11.0), 2.5, 2.5)  # fist
    p.drawRoundedRect(QRectF(8.0, 2.0, 5.0, 11.0), 2.5, 2.5)    # raised thumb
    p.end()
    return QIcon(pm)


# Cores das avaliações (monocromático + um verde/vermelho discretos no estado ativo)
_RATE_ON_UP = QColor(64, 196, 128)     # gostei (verde suave)
_RATE_ON_DOWN = QColor(224, 96, 96)    # não gostei (vermelho suave)


class ImageLightbox(QWidget):
    """Mostra uma imagem em GRANDE sobre a janela (como o lightbox da web).
    Clique em qualquer sítio — ou Esc — fecha."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self._pix = pixmap
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet("background:rgba(0,0,0,0.9);")
        self.lbl = QLabel(self); self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setStyleSheet("background:transparent;")
        hint = QLabel(self); hint.setText("×")
        hint.setStyleSheet("background:transparent;color:rgba(255,255,255,0.7);font-size:26px;")
        self._hint = hint
        win = parent.window() if parent else None
        if win:
            g = win.geometry()
            self.setGeometry(g.x(), g.y(), g.width(), g.height())
        self._relayout()
        self.show(); self.raise_(); self.activateWindow()

    def _relayout(self):
        self.lbl.setGeometry(0, 0, self.width(), self.height())
        self._hint.setGeometry(self.width() - 44, 12, 32, 32)
        if self._pix and not self._pix.isNull():
            m = 48
            self.lbl.setPixmap(self._pix.scaled(
                max(1, self.width() - m), max(1, self.height() - m),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        self._relayout()

    def mousePressEvent(self, e):
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


class RatedThumb(QWidget):
    """Small image thumbnail (web AI-sidebar style) with like/dislike ICON buttons.
    Ratings are stored locally + synced to Supabase and bias future image picks.
    Clicar na miniatura abre a imagem em grande (ImageLightbox)."""
    TW, TH = 92, 64

    def __init__(self, parent, get_auth=None):
        super().__init__(parent)
        self._get_auth = get_auth      # callable → Authorization header (or None)
        self._word = ""; self._url = ""; self._score = 0; self._full_pix = None
        self._lightbox = None
        self.setFixedWidth(self.TW)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
        self.img = QLabel(""); self.img.setFixedSize(self.TW, self.TH)
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setStyleSheet(
            f"background:{ELV};border:1px solid {BRD};border-radius:8px;color:{TMT};font-size:9px;")
        self.img.setToolTip(T("img_zoom_tip"))
        self.img.mousePressEvent = self._open_zoom   # clicar → ver em grande
        v.addWidget(self.img)
        rr = QHBoxLayout(); rr.setContentsMargins(0, 0, 0, 0); rr.setSpacing(4)
        rr.addStretch()
        self.up = self._rbtn("Boa imagem")
        self.up.clicked.connect(lambda: self._rate(1))
        self.down = self._rbtn("Imagem fraca")
        self.down.clicked.connect(lambda: self._rate(-1))
        rr.addWidget(self.up); rr.addWidget(self.down); rr.addStretch()
        v.addLayout(rr)
        self.clear()

    def img_size(self):
        return (self.TW, self.TH)

    def _rbtn(self, tip):
        b = QPushButton(); b.setFixedSize(26, 20); b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip); b.setIconSize(QSize(15, 15))
        b.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:5px;}"
            f"QPushButton:hover{{background:{HVR};}}")
        return b

    def _refresh_icons(self):
        self.up.setIcon(_thumb_icon(True, _RATE_ON_UP if self._score > 0 else TMT))
        self.down.setIcon(_thumb_icon(False, _RATE_ON_DOWN if self._score < 0 else TMT))

    def clear(self):
        self._url = ""; self._score = 0; self._full_pix = None
        self.img.setPixmap(QPixmap()); self.img.setText("")
        self.img.setCursor(Qt.ArrowCursor)
        self.up.setEnabled(False); self.down.setEnabled(False)
        self._refresh_icons()
        self.hide()

    def _open_zoom(self, _e=None):
        if self._full_pix and not self._full_pix.isNull():
            self._lightbox = ImageLightbox(self.window(), self._full_pix)

    def set_image(self, pixmap, word, url):
        self._word = word; self._url = url; self._full_pix = pixmap
        self.img.setPixmap(pixmap.scaled(self.TW, self.TH, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.img.setText("")
        self.img.setCursor(Qt.PointingHandCursor)
        has_url = bool(url)
        self.up.setEnabled(has_url); self.down.setEnabled(has_url)
        self._score = get_image_rating(word, url) if has_url else 0
        self._refresh_icons()
        self.show()

    def _rate(self, score):
        if not self._url:
            return
        self._score = 0 if self._score == score else score   # click active again → clear
        set_image_rating_local(self._word, self._url, self._score)
        self._refresh_icons()
        auth = self._get_auth() if self._get_auth else None
        sync_image_rating(self._word, self._url, self._score, auth)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════

class WordDetailsPanel(QWidget):
    """Rich word-details panel like the web VocabSidebar: word + audio, phonetic,
    type, meaning, one example at a time (prev/next) with an image that
    illustrates THAT example, synonyms, collocations, note."""
    _ready = pyqtSignal(object, object)
    _img_ready = pyqtSignal(object)    # (example_index, image_bytes)
    _tts_done = pyqtSignal()           # áudio pronto/falhou → parar o spinner do botão

    def __init__(self, parent, chat):
        super().__init__(parent)
        self._chat = chat
        self._word = ""; self._lang = "en"; self._meaning = ""
        self._examples = []; self._ex_idx = 0
        self._tts_player = None; self._tts_inst = None
        # ── Spinner de "a processar" para os botões ouvir/youglish ──
        self._spin_frames = ["◜", "◝", "◟", "◞"]  # arco a rodar
        self._spin_i = 0
        self._spin_btn = None
        self._spin_orig = ""
        self._spin_css = ""
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(110)
        self._spin_timer.timeout.connect(self._spin_tick)
        self._tts_done.connect(self._stop_spin)
        self.setStyleSheet(f"background:{SRF};border-right:1px solid {BRD};")
        self.setMinimumWidth(330); self.setMaximumWidth(440)
        lo = QVBoxLayout(self); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)

        hdr = QWidget(); hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 10, 10, 10)
        ht = QLabel(T("details")); ht.setStyleSheet(
            f"color:{TXT};font-size:13px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
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
            f"color:{TXT};font-size:22px;font-weight:800;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        wr.addWidget(self.word_lbl)
        # Pronunciation button — fone/headphone icon (ouvir a pronúncia da palavra)
        # Ícone Segoe MDL2 (altifalante) — sem emojis.
        self.listen_btn = QPushButton(chr(0xE767)); self.listen_btn.setCursor(Qt.PointingHandCursor); self.listen_btn.setFixedSize(28, 28)
        self.listen_btn.setToolTip(T("listen"))
        self.listen_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:14px;"
            f"font-size:13px;font-family:'Segoe Fluent Icons','Segoe MDL2 Assets';}}QPushButton:hover{{border-color:{ACC};color:{TXT};}}")
        self.listen_btn.clicked.connect(self._play_tts)
        wr.addWidget(self.listen_btn)
        # YouGlish — ícone de vídeo (Segoe MDL2), sem emojis.
        self.yg_btn = QPushButton(chr(0xE714)); self.yg_btn.setCursor(Qt.PointingHandCursor); self.yg_btn.setFixedSize(28, 28)
        self.yg_btn.setToolTip(T("yg_tip"))
        self.yg_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:14px;"
            f"font-size:13px;font-family:'Segoe Fluent Icons','Segoe MDL2 Assets';}}"
            f"QPushButton:hover{{border-color:{ACC};color:{TXT};}}")
        self.yg_btn.clicked.connect(self._open_youglish)
        wr.addWidget(self.yg_btn); wr.addStretch()
        il.addLayout(wr)

        self.meta_lbl = QLabel(""); self.meta_lbl.setWordWrap(True)
        self.meta_lbl.setStyleSheet(f"color:{TMT};font-size:12px;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        il.addWidget(self.meta_lbl)

        self.meaning_lbl = QLabel(""); self.meaning_lbl.setWordWrap(True)
        self.meaning_lbl.setStyleSheet(f"color:{TXT};font-size:13.5px;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
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
        self.ex_text.setStyleSheet(f"color:{TXT};font-size:13px;font-style:italic;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        exl.addWidget(self.ex_text)
        # Image thumbnails (web AI-sidebar style): a few small, friendly-sized
        # pictures of THIS example — each with 👍/👎 rating that biases future picks.
        self.img_status = QLabel("")
        self.img_status.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        exl.addWidget(self.img_status)
        self.thumb_row = QWidget(); self.thumb_row.setStyleSheet("background:transparent;")
        trl = QHBoxLayout(self.thumb_row); trl.setContentsMargins(0, 2, 0, 0); trl.setSpacing(8)
        _auth = (lambda: self._chat._get_token_header()) if self._chat else None
        self._thumbs = [RatedThumb(self.thumb_row, _auth) for _ in range(3)]
        for _t in self._thumbs:
            trl.addWidget(_t)
        trl.addStretch()
        exl.addWidget(self.thumb_row)
        self.ex_box.hide()
        il.addWidget(self.ex_box)

        self.extra_lbl = QLabel(""); self.extra_lbl.setWordWrap(True); self.extra_lbl.setTextFormat(Qt.RichText)
        self.extra_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse); self.extra_lbl.setAlignment(Qt.AlignTop)
        self.extra_lbl.setStyleSheet(f"color:{TXT};font-size:12.5px;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        il.addWidget(self.extra_lbl); il.addStretch()
        scroll.setWidget(inner); lo.addWidget(scroll, 1)

        ftr = QWidget(); ftr.setStyleSheet(f"background:{ELV};border-top:1px solid {BRD};")
        fl = QHBoxLayout(ftr); fl.setContentsMargins(12, 10, 12, 10); fl.setSpacing(8)
        self.add_btn = QPushButton(T("add_vocab")); self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;padding:9px 14px;"
            f"font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.add_btn.clicked.connect(self._add)
        fl.addWidget(self.add_btn, 1)
        # "Personalizar": abre o diálogo (tradução + nota tua) antes de cair na conta web.
        self.custom_btn = QPushButton(T("add_word_personalise")); self.custom_btn.setCursor(Qt.PointingHandCursor)
        self.custom_btn.setToolTip(T("add_word_personalise_tip"))
        self.custom_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:14px;padding:9px 14px;"
            f"font-size:12px;font-family:'Inter','Segoe UI',sans-serif;}}QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        self.custom_btn.clicked.connect(self._personalise)
        fl.addWidget(self.custom_btn)
        lo.addWidget(ftr)

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
        for t in self._thumbs:
            t.clear()
        self.img_status.setText(T("gen_image"))
        threading.Thread(target=self._img_worker, args=(idx, ex), daemon=True).start()

    def _img_worker(self, idx, example):
        """Same image config as the web: ask /api/media-search for REAL photos
        (Unsplash→Tavily→SerpApi→Pollinations), then fall through Pollinations and
        LoremFlickr. Fetches up to 3 DISTINCT images (a thumbnail strip, like the
        web AI sidebar). Candidates are biased by past 👍/👎 ratings."""
        image_prompt = _img_extract_context(example, self._word)
        candidates = build_image_candidates(self._word, example, self._meaning, image_prompt)
        candidates = apply_rating_bias(self._word, candidates)
        slot = 0
        for u in candidates:
            if idx != self._ex_idx:      # user navigated away — stop wasting data
                return
            if slot >= len(self._thumbs):
                break
            try:
                req = Request(u, headers={"User-Agent": CHROME_UA, "Accept": "image/*"})
                raw = urlopen(req, timeout=30).read()
                if raw and len(raw) > 800 and idx == self._ex_idx:
                    self._img_ready.emit((idx, slot, raw, u))
                    slot += 1
            except Exception as e:
                log(f"example image: {e}")
        if slot == 0 and idx == self._ex_idx:   # everything failed → guaranteed card
            self._img_ready.emit((idx, 0, b"", ""))

    def _on_img(self, payload):
        idx, slot, raw, url = payload
        if idx != self._ex_idx:      # user already navigated away
            return
        self.img_status.setText("")
        if not (0 <= slot < len(self._thumbs)):
            return
        thumb = self._thumbs[slot]
        if raw:
            pm = QPixmap()
            if pm.loadFromData(raw):
                thumb.set_image(pm, self._word, url)
                return
        # Guarantee an image (never just a blank), exactly like the web's local card.
        ex = self._examples[idx] if 0 <= idx < len(self._examples) else ""
        thumb.set_image(local_card_pixmap(self._word, ex), self._word, "")

    # ── Spinner "a processar" (ouvir / youglish) ──
    def _start_spin(self, btn):
        if self._spin_btn is btn:
            return
        self._spin_btn = btn
        self._spin_orig = btn.text()
        self._spin_css = btn.styleSheet()
        self._spin_i = 0
        btn.setEnabled(False)
        # Segoe UI Symbol tem os glifos do arco (Inter não tem) → render garantido.
        btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACC};border:1px solid {ACC};"
            f"border-radius:14px;font-size:13px;font-family:'Segoe UI Symbol';}}")
        self._spin_timer.start()

    def _spin_tick(self):
        if not self._spin_btn:
            self._spin_timer.stop(); return
        self._spin_btn.setText(self._spin_frames[self._spin_i % len(self._spin_frames)])
        self._spin_i += 1

    def _stop_spin(self):
        self._spin_timer.stop()
        if self._spin_btn:
            self._spin_btn.setText(self._spin_orig)
            self._spin_btn.setStyleSheet(self._spin_css)
            self._spin_btn.setEnabled(True)
            self._spin_btn = None

    def _play_tts(self, rate=0):
        if not self._word:
            return
        self._start_spin(self.listen_btn)   # mostra "a processar" enquanto gera o áudio
        threading.Thread(target=self._tts_worker,
                         args=(self._word, self._lang or "en", rate), daemon=True).start()

    def _tts_worker(self, word, lang, rate=0):
        """Pronúncia com voz NATURAL (Microsoft Neural via edge-tts), igual à web.
        `rate` é uma percentagem de velocidade (-50..+50) p/ ouvir devagar/rápido."""
        try:
            tmp = speak_edge_tts(word, lang, rate)
            if not tmp:
                # Sem internet / edge falhou → último recurso: voz local do Windows
                # (não tão boa, mas melhor que silêncio quando offline).
                self._speak_local(word, lang)
                return
            import vlc
            # Instância VLC dedicada + media_new + set_media (padrão fiável do motor).
            if self._tts_player is None:
                self._tts_inst = vlc.Instance("--quiet", "--no-video",
                    "--audio-resampler=soxr", "--aout=wasapi")
                self._tts_player = self._tts_inst.media_player_new()
            self._tts_player.stop()
            self._tts_player.set_media(self._tts_inst.media_new(tmp))
            self._tts_player.audio_set_volume(100)
            self._tts_player.play()
        except Exception as e:
            log(f"tts: {e}")
            try:
                self._speak_local(word, lang)
            except Exception:
                pass
        finally:
            # Para o spinner na GUI thread (sinal é thread-safe).
            self._tts_done.emit()

    def _speak_local(self, text, lang):
        """Fallback offline: voz nativa do Windows (SAPI via System.Speech).
        Usado quando a API TTS falha (Edge devolve 403). Sem dependências extra."""
        if sys.platform != "win32" or not text:
            return False
        culture = {
            "en": "en-US", "pt": "pt-PT", "es": "es-ES", "fr": "fr-FR",
            "de": "de-DE", "it": "it-IT", "ja": "ja-JP", "zh": "zh-CN",
            "ko": "ko-KR", "ru": "ru-RU", "ar": "ar-SA", "nl": "nl-NL",
        }.get(lang, "en-US")
        safe = text.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "try{$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,"
            "[System.Speech.Synthesis.VoiceAge]::NotSet,0,"
            f"[System.Globalization.CultureInfo]'{culture}')}}catch{{}};"
            f"$s.Speak('{safe}')"
        )
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                startupinfo=si, creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            return True
        except Exception as e:
            log(f"tts local: {e}")
            return False

    def _add(self):
        if self._chat and self._word:
            self._chat.promote_word(self._word)

    def _personalise(self):
        """Abre o diálogo de personalização (tradução + nota) já com esta palavra,
        para o utilizador ajustar antes de cair na conta web."""
        if not (self._chat and self._word):
            return
        try:
            dlg = AddWordDialog(self, self._chat, prefill=self._word)
            dlg.exec_()
        except Exception as e:
            log(f"personalise: {e}")

    def _open_youglish(self):
        """Open the word on YouGlish for pronunciation in context."""
        if self._word:
            import urllib.parse
            self._start_spin(self.yg_btn)   # feedback "a abrir..." enquanto o browser arranca
            query = urllib.parse.quote(self._word)
            webbrowser.open(f"https://youglish.com/pronounce/{query}/english/us")
            QTimer.singleShot(1100, self._stop_spin)


class PronunciationPanel(QWidget):
    """Aba Pronúncia: ouvir a legenda ATUAL em várias velocidades, com a MESMA
    voz neural natural da web (edge-tts). Painel lateral, como o de detalhes."""

    prep_changed = pyqtSignal(bool)   # True = a preparar áudio nos bastidores

    def __init__(self, parent):
        super().__init__(parent)
        self._line = ""; self._lang = "en"
        self._tts_player = None; self._tts_inst = None
        self._spd_btns = []
        self.setStyleSheet(f"background:{SRF};border-right:1px solid {BRD};")
        self.setMinimumWidth(300); self.setMaximumWidth(420)
        lo = QVBoxLayout(self); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)

        hdr = QWidget(); hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 10, 10, 10)
        ht = QLabel(T("pron_title")); ht.setStyleSheet(
            f"color:{TXT};font-size:13px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        hl.addWidget(ht); hl.addStretch()
        close = QPushButton("×"); close.setFixedSize(24, 24); close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TMT};font-size:17px;}}"
                            f"QPushButton:hover{{color:{TXT};}}")
        close.clicked.connect(self.hide); hl.addWidget(close)
        lo.addWidget(hdr)

        inner = QWidget(); inner.setStyleSheet(f"background:{SRF};")
        il = QVBoxLayout(inner); il.setContentsMargins(16, 16, 16, 16); il.setSpacing(14)
        self.line_lbl = QLabel(T("pron_empty")); self.line_lbl.setWordWrap(True)
        self.line_lbl.setStyleSheet(
            f"color:{TXT};font-size:17px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;background:transparent;")
        il.addWidget(self.line_lbl)
        hint = QLabel(T("pron_hint")); hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        il.addWidget(hint)

        # Botões de velocidade — cada um (re)toca a linha a essa velocidade.
        for label, rate in ((T("pron_normal"), 0), (T("pron_slow"), -25), (T("pron_slower"), -45)):
            b = QPushButton(label); b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(42)
            b.setStyleSheet(
                f"QPushButton{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:10px;"
                f"font-size:13px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;text-align:left;padding:0 16px;}}"
                f"QPushButton:hover{{border-color:{ACC};background:{HVR};}}"
                f"QPushButton:disabled{{color:{TMT};border-color:{BRD};background:{SRF};}}")
            b.clicked.connect(lambda _checked=False, r=rate: self._play(r))
            il.addWidget(b)
            self._spd_btns.append(b)
        # Indicador de "a preparar" — o áudio neural é gerado nos bastidores (rede),
        # por isso há um pequeno atraso; aqui mostra-se que está a ser preparado.
        self.prep_lbl = QLabel(""); self.prep_lbl.setVisible(False)
        self.prep_lbl.setStyleSheet(
            f"color:{ACC};font-size:11px;font-weight:600;background:transparent;padding:2px 0;")
        il.addWidget(self.prep_lbl)
        il.addStretch()
        lo.addWidget(inner, 1)
        self.prep_changed.connect(self._set_preparing)
        self.hide()

    def _set_preparing(self, busy):
        """Estado de carregamento dos botões de velocidade (corre no GUI thread)."""
        self.prep_lbl.setText(T("pron_preparing") if busy else "")
        self.prep_lbl.setVisible(bool(busy))
        for b in self._spd_btns:
            b.setEnabled(not busy)

    def show_for(self, line, lang="en"):
        line = (line or "").strip()
        if not line:
            self.line_lbl.setText(T("pron_empty"))
        else:
            self._line = line; self._lang = (lang or "en")[:2]
            self.line_lbl.setText(line)
        self.show()

    def _play(self, rate):
        if not self._line:
            return
        self.prep_changed.emit(True)   # mostra o loading enquanto prepara
        threading.Thread(target=self._worker, args=(self._line, self._lang, rate), daemon=True).start()

    def _worker(self, line, lang, rate):
        try:
            tmp = speak_edge_tts(line, lang, rate)
            if not tmp:
                # Nunca silêncio: voz do Windows como último recurso (a aba
                # "não funcionava" porque aqui retornava sem tocar nada).
                speak_local_sapi(line, lang)
                return
            import vlc
            if self._tts_player is None:
                self._tts_inst = vlc.Instance("--quiet", "--no-video",
                    "--audio-resampler=soxr", "--aout=wasapi")
                self._tts_player = self._tts_inst.media_player_new()
            self._tts_player.stop()
            self._tts_player.set_media(self._tts_inst.media_new(tmp))
            self._tts_player.audio_set_volume(100)
            self._tts_player.play()
        except Exception as e:
            log(f"pron: {e}")
            try:
                speak_local_sapi(line, lang)
            except Exception:
                pass
        finally:
            self.prep_changed.emit(False)   # esconde o loading (preparação terminada)


class AddWordDialog(QDialog):
    """O sítio onde o utilizador PERSONALIZA o que quer adicionar ao vocabulário e
    isso cai TUDO na conta web (tabela words). Pode escrever uma palavra/expressão à
    mão, dar a sua própria tradução e uma nota pessoal. A IA preenche o resto
    (definição, exemplos) e o cartão é sincronizado com a app web ao guardar."""

    def __init__(self, parent, chat_panel, prefill=""):
        super().__init__(parent)
        self._chat = chat_panel
        self.setWindowTitle(T("add_word_title"))
        self.setMinimumWidth(340)
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20, 18, 20, 18); lo.setSpacing(10)

        hdr = QLabel(T("add_word_title"))
        hdr.setStyleSheet(f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)
        hint = QLabel(T("add_word_hint")); hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        lo.addWidget(hint)

        def field(label, ph, multiline=False):
            lab = QLabel(label); lab.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;margin-top:4px;")
            lo.addWidget(lab)
            w = QTextEdit() if multiline else QLineEdit()
            w.setStyleSheet(
                f"background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:8px;"
                f"padding:7px 9px;font-size:12px;")
            w.setPlaceholderText(ph)   # QLineEdit e QTextEdit suportam ambos
            if multiline:
                w.setFixedHeight(56)
            lo.addWidget(w)
            return w

        self.word_in = field(T("add_word_word"), T("add_word_word_ph"))
        self.word_in.setText(prefill or "")
        self.tr_in = field(T("add_word_translation"), T("add_word_translation_ph"))
        self.note_in = field(T("add_word_note"), T("add_word_note_ph"), multiline=True)

        # Estado de login — deixa claro que vai (ou não) para a conta web.
        self.status_lbl = QLabel(""); self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;padding-top:4px;")
        lo.addWidget(self.status_lbl)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.save_btn = QPushButton(T("add_word_save")); self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:9px 20px;font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}")
        self.save_btn.clicked.connect(self._save)
        bb.addWidget(self.save_btn); bb.addStretch()
        cl = QPushButton(T("exercise_close")); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                         f"border-radius:14px;padding:9px 16px;font-size:11px;}}"
                         f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        cl.clicked.connect(self.reject)
        bb.addWidget(cl)
        lo.addLayout(bb)
        self._refresh_login()

    def _refresh_login(self):
        logged = bool(self._chat and self._chat._get_token_header())
        self.status_lbl.setText(T("add_word_synced") if logged else T("add_word_local_only"))
        self.status_lbl.setStyleSheet(
            f"color:{'#9EE6A0' if logged else '#FFB27A'};font-size:11px;background:transparent;padding-top:4px;")

    def _save(self):
        word = self.word_in.text().strip()
        if not word:
            self.word_in.setFocus(); return
        if not (self._chat and self._chat._get_token_header()):
            # Sem login → não há conta web onde cair. Avisa e tenta abrir o login.
            self.status_lbl.setText(T("need_login_vocab"))
            self.status_lbl.setStyleSheet("color:#FFB27A;font-size:11px;background:transparent;padding-top:4px;")
            try: self._chat._handle_login()
            except Exception: pass
            return
        note = self.note_in.toPlainText().strip()
        tr = self.tr_in.text().strip()
        self._chat.promote_word(word, note=note, translation=tr)
        self.accept()


class ExerciseDialog(QDialog):
    """AI-generated comprehension exercise from the current subtitle.
    Multiple-choice question with 4 options. Uses DeepSeek."""

    def __init__(self, parent, engine):
        super().__init__(parent)
        self._engine = engine
        self._answer = ""; self._answered = False
        self.setWindowTitle(T("exercise_btn"))
        self.setMinimumSize(300, 300)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20,18,20,18); lo.setSpacing(10)

        hdr = QLabel(T("exercise_btn")); hdr.setStyleSheet(
            f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)

        self.sub_lbl = QLabel(""); self.sub_lbl.setWordWrap(True)
        self.sub_lbl.setStyleSheet(f"color:{TMT};font-size:12px;font-style:italic;background:transparent;padding:6px 0;")
        lo.addWidget(self.sub_lbl)

        self.q_lbl = QLabel(""); self.q_lbl.setWordWrap(True)
        self.q_lbl.setStyleSheet(f"color:{TXT};font-size:13px;font-weight:600;background:transparent;")
        lo.addWidget(self.q_lbl)

        self.opts = []
        self.opt_btns = []
        for i in range(4):
            b = QPushButton(""); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:10px;"
                f"padding:10px 14px;text-align:left;font-size:12px;font-family:'Inter','Segoe UI',sans-serif;}}"
                f"QPushButton:hover{{background:{HVR};border-color:{ACC};}}"
                f"QPushButton:disabled{{color:{TMT};border-color:{BRD};}}")
            b.clicked.connect(lambda _, i=i: self._check(i))
            lo.addWidget(b)
            self.opt_btns.append(b)
            self.opts.append("")

        self.fb_lbl = QLabel(""); self.fb_lbl.setWordWrap(True)
        self.fb_lbl.setStyleSheet(f"color:{TXT};font-size:12px;background:transparent;padding:4px 0;")
        lo.addWidget(self.fb_lbl)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.next_btn = QPushButton(T("exercise_next")); self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:8px 20px;font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}")
        self.next_btn.clicked.connect(self._gen)
        bb.addWidget(self.next_btn)
        bb.addStretch()
        cl = QPushButton(T("exercise_close")); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                         f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                         f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        cl.clicked.connect(self.close)
        bb.addWidget(cl)
        lo.addLayout(bb)
        lo.addStretch()

        QTimer.singleShot(100, self._gen)

    def _gen(self):
        sub = self._engine.nearest_sub_text()
        if not sub:
            self.q_lbl.setText(T("exercise_failed")); return
        self.sub_lbl.setText(f"\u201c{sub}\u201d")
        self.q_lbl.setText(T("exercise_loading"))
        self.fb_lbl.setText("")
        self._answered = False
        self._answer = ""
        for b in self.opt_btns:
            b.setText(""); b.setEnabled(False)
            b.setStyleSheet(
                f"QPushButton{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:10px;"
                f"padding:10px 14px;text-align:left;font-size:12px;font-family:'Inter','Segoe UI',sans-serif;}}"
                f"QPushButton:hover{{background:{HVR};border-color:{ACC};}}"
                f"QPushButton:disabled{{color:{TMT};border-color:{BRD};}}")
        threading.Thread(target=self._work, args=(sub,), daemon=True).start()

    def _work(self, sub):
        try:
            from urllib.request import urlopen, Request
            import ssl
            log(f"exercise: a gerar (sub={sub[:40]!r})")
            nat = native_language_name()
            sys_p = (
                f"Generate ONE multiple-choice comprehension question about this sentence in the target language.\n"
                f"Respond ONLY with JSON:\n"
                '{"question":"<question in target language>",'
                '"options":["<option A>","<option B>","<option C>","<option D>"],'
                '"correct":0}\n'
                f"correct is the 0-based index of the right answer. "
                f"The question tests understanding, not vocabulary. Include context. "
                f"Include a brief explanation in {nat} as the 4th option (index 3) that says why the answer is right.")
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 700, "temperature": 0.3,
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": sub}]}).encode()
            ctx = ssl._create_unverified_context()
            r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                headers={"Content-Type": "application/json"}),
                        timeout=15, context=ctx)
            d = json.loads(r.read().decode())
            raw = (d.get("text") or "").strip().strip("`")
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            log("exercise: gerado OK")
            gui_call(lambda: self._show(parsed))
        except Exception as e:
            log(f"exercise FALHOU: {type(e).__name__}: {e}")
            gui_call(lambda: self.q_lbl.setText(T("exercise_failed")))

    def _show(self, data):
        self.q_lbl.setText(data.get("question", "?"))
        opts = data.get("options", ["","","",""])
        self._answer = opts[data.get("correct", 0)] if len(opts) > 0 else ""
        for i in range(min(4, len(opts))):
            self.opts[i] = opts[i]
            b = self.opt_btns[i]; b.setText(opts[i]); b.setEnabled(True)
        self.next_btn.setText(T("exercise_next"))

    def _check(self, idx):
        if self._answered:
            return
        self._answered = True
        chosen = self.opts[idx] if 0 <= idx < len(self.opts) else ""
        correct = chosen == self._answer
        for i, b in enumerate(self.opt_btns):
            b.setEnabled(False)
            bg = "#1a4a2a" if 0 <= i < len(self.opts) and self.opts[i] == self._answer else ELV
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{TXT};border:1px solid {BRD};border-radius:10px;"
                f"padding:10px 14px;text-align:left;font-size:12px;font-family:'Inter','Segoe UI',sans-serif;}}"
                f"QPushButton:disabled{{color:{TXT};}}")
        if correct:
            self.fb_lbl.setText(T("exercise_correct"))
            self.fb_lbl.setStyleSheet(f"color:#5ae05a;font-size:12px;background:transparent;padding:4px 0;")
        else:
            self.fb_lbl.setText(T("exercise_wrong", answer=self._answer))
            self.fb_lbl.setStyleSheet(f"color:#e05a5a;font-size:12px;background:transparent;padding:4px 0;")


def _esc_html(s):
    """Escape text going into a rich-text QLabel so user/AI content can't break markup."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def mark_html(text, subtle=False):
    """Texto simples → HTML (RichText) com as palavras e expressões-chave SUBLINHADAS
    e CLICÁVEIS (href 'lexioword:<frase>'), usando a MESMA classificação do
    sublinhador das legendas (mark_tokens): expressões em violeta, nível em verde,
    avançadas em âmbar. Escapa o texto e preserva quebras de linha. O clique abre a
    aba Detalhes (quem usa liga `linkActivated` a um handler que faz word_details.show_for).

    subtle=True (usado no CHAT): NÃO pinta tudo de cores — só as expressões multi-palavra
    ficam coloridas (quando faz mesmo falta); as restantes ficam apenas SUBLINHADAS na
    cor do texto, para a resposta da IA não parecer um arco-íris."""
    from urllib.parse import quote
    import re
    # Limpa marcadores Markdown (a IA por vezes usa-os) p/ não saírem literais no RichText.
    txt = str(text or "")
    txt = re.sub(r'\*\*(.+?)\*\*', r'\1', txt)
    txt = re.sub(r'__(.+?)__', r'\1', txt)
    txt = re.sub(r'`(.+?)`', r'\1', txt)
    txt = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', txt)
    txt = re.sub(r'(?m)^\s*[-*]\s+', '• ', txt)
    out_lines = []
    for line in txt.split("\n"):
        words = line.split(" ")
        marks = mark_tokens(words)
        parts = []; i = 0; n = len(words)
        while i < n:
            w = words[i]
            m = marks[i] if i < len(marks) else None
            if m and m.get("key") and m.get("color"):
                color = m["color"]; click = (m.get("click") or _clean_core(w))
                # No chat: só as expressões (grupos violeta) mantêm cor; o resto
                # fica sublinhado na cor normal do texto (sem "todas coloridas").
                if subtle and color != MARK_GROUP:
                    color = TXT
                # Junta as palavras seguidas que formam a MESMA expressão (grupo violeta).
                j = i
                if color == MARK_GROUP:
                    while (j + 1 < n and marks[j + 1] and marks[j + 1].get("color") == MARK_GROUP
                           and marks[j + 1].get("click") == click):
                        j += 1
                phrase_disp = " ".join(words[i:j + 1])
                href = "lexioword:" + quote(click)
                parts.append(f'<a href="{href}" style="color:{color};text-decoration:underline;">'
                             f'{_esc_html(phrase_disp)}</a>')
                i = j + 1
            else:
                parts.append(_esc_html(w)); i += 1
        out_lines.append(" ".join(parts))
    return "<br>".join(out_lines)


def _list_show_full(lst):
    """Faz uma QListWidget mostrar o texto dos itens POR INTEIRO: quebra de linha em
    vez de reticências, e barra horizontal quando precisa. (Queixa do user: nas abas
    Vídeos/Tracks/Playlist os dizeres não cabiam / não dava p/ ver tudo.)"""
    try:
        lst.setWordWrap(True)
        lst.setTextElideMode(Qt.ElideNone)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    except Exception:
        pass


class FluencyDialog(QDialog):
    """Exercício de Fluência (versão player do 'Fluency' da web). O filme já está na
    língua que o utilizador está a APRENDER, por isso aqui o exercício inverte-se:
    mostra um GRUPO de legendas (o cluster da cena atual, o mesmo que alimenta os
    cartões Twitch) e pede uma tradução FLUENTE para a língua nativa. A IA (DeepSeek)
    avalia fluência+precisão e mostra uma tradução-modelo."""

    def __init__(self, parent, engine, chat_panel=None):
        super().__init__(parent)
        self._engine = engine
        self._chat_panel = chat_panel or (parent.chat if hasattr(parent, 'chat') else None)
        self._group = []
        self._checking = False
        self.setWindowTitle(T("fluency_btn"))
        self.setMinimumSize(300, 360)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20, 18, 20, 18); lo.setSpacing(10)

        hdr = QLabel(T("fluency_btn")); hdr.setStyleSheet(
            f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)

        self.instr = QLabel(T("fluency_instruction"))
        self.instr.setWordWrap(True)
        self.instr.setStyleSheet(f"color:{TMT};font-size:12px;background:transparent;")
        lo.addWidget(self.instr)

        # Grupo de legendas na língua-alvo (o que o utilizador tem de traduzir).
        self.group_lbl = QLabel(""); self.group_lbl.setWordWrap(True)
        self.group_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.group_lbl.setStyleSheet(
            f"color:{TS2};font-size:14px;background:{ELV};"
            f"border:1px solid {BRD};border-radius:10px;padding:12px 14px;")
        lo.addWidget(self.group_lbl)

        self.answer = QTextEdit(); self.answer.setPlaceholderText(T("fluency_placeholder"))
        self.answer.setStyleSheet(f"QTextEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};"
                                  f"border-radius:8px;padding:10px;font-size:13px;font-family:'Inter','Segoe UI',sans-serif;}}")
        self.answer.setMinimumHeight(80)
        lo.addWidget(self.answer)

        self.fb = QLabel(""); self.fb.setWordWrap(True); self.fb.setVisible(False)
        self.fb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fb.setStyleSheet(f"color:{TXT};font-size:12px;background:{ELV};"
                              f"border:1px solid {BRD};border-radius:8px;padding:10px 12px;")
        lo.addWidget(self.fb)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.check_btn = QPushButton(T("fluency_check")); self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:8px 20px;font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}"
            f"QPushButton:disabled{{background:{ELV};color:{TMT};}}")
        self.check_btn.clicked.connect(self._check)
        bb.addWidget(self.check_btn)

        self.next_btn = QPushButton(T("fluency_next")); self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                                    f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                                    f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        self.next_btn.setToolTip(T("fluency_next_tip"))
        self.next_btn.clicked.connect(self._load_group)
        bb.addWidget(self.next_btn)

        bb.addStretch()
        cl = QPushButton(T("exercise_close")); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                         f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                         f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        cl.clicked.connect(self.close)
        bb.addWidget(cl)
        lo.addLayout(bb)

        QTimer.singleShot(80, self._load_group)

    def _load_group(self):
        self.fb.setVisible(False); self.fb.setText("")
        self.answer.clear(); self.answer.setFocus()
        self._group = self._engine.fluency_group()
        if not self._group:
            log(f"fluency: grupo vazio (subs_loaded={self._engine.subs_loaded()})")
            self.group_lbl.setText(T("fluency_no_subs"))
            self.check_btn.setEnabled(False)
            return
        self.check_btn.setEnabled(True)
        self.group_lbl.setText("\n".join(s.text.replace("\n", " ").strip() for s in self._group))

    def _passage(self):
        return "\n".join(s.text.replace("\n", " ").strip() for s in self._group)

    def _check(self):
        if self._checking:
            return
        ans = self.answer.toPlainText().strip()
        if not ans or not self._group:
            return
        self._checking = True
        self.check_btn.setEnabled(False)
        self.fb.setVisible(True)
        self.fb.setText(T("fluency_checking"))
        threading.Thread(target=self._work, args=(self._passage(), ans), daemon=True).start()

    def _work(self, passage, ans):
        try:
            import ssl
            log("fluency: a avaliar...")
            nat = native_language_name()
            sys_p = (
                "You are a fluency coach. The user is learning a language by watching a film. "
                "Below is a short passage of consecutive subtitle lines in the language they are "
                f"LEARNING, plus the user's translation of that whole passage into their native "
                f"language ({nat}). Judge how FLUENT and ACCURATE the user's {nat} translation is — "
                "reward natural, native-sounding phrasing over word-for-word literalness, but penalise "
                "real meaning errors. Respond ONLY with JSON:\n"
                '{"score": <integer 0-100>, '
                f'"feedback": "<2-3 sentences in {nat}: what was good and what to improve>", '
                f'"model": "<the most fluent, natural {nat} translation of the whole passage>"}}')
            user_p = f"PASSAGE (language being learned):\n{passage}\n\nUSER TRANSLATION ({nat}):\n{ans}"
            # Usa o Chat IA em vez de chamada direta — herda contexto do utilizador
            cp = self._chat_panel
            if cp:
                cp.eval_result.connect(self._on_eval)
                cp.request_evaluation(sys_p, user_p)
            else:
                raise Exception("ChatPanel nao disponivel")
        except Exception as e:
            log(f"fluency FALHOU: {type(e).__name__}: {e}")
            gui_call(self._fail)

    def _on_eval(self, resp, err):
        # Desliga o sinal para nao acumular chamadas
        cp = self._chat_panel
        if cp:
            try: cp.eval_result.disconnect(self._on_eval)
            except: pass
        if err or not resp:
            log(f"fluency eval error: {err or 'resposta vazia'}")
            gui_call(self._fail)
            return
        try:
            raw = resp.strip().strip("`")
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            gui_call(lambda: self._show(parsed))
        except Exception as e:
            log(f"fluency parse FALHOU: {type(e).__name__}: {e}")
            gui_call(self._fail)

    def _fail(self):
        self._checking = False
        self.check_btn.setEnabled(True)
        self.fb.setText(T("exercise_failed"))

    def _show(self, data):
        self._checking = False
        self.check_btn.setEnabled(True)
        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except Exception:
            score = 0
        color = "#5ae05a" if score >= 75 else ("#e0c05a" if score >= 50 else "#e07a5a")
        fb = _esc_html(data.get("feedback", "")).replace("\n", "<br>")
        model = _esc_html(data.get("model", "")).replace("\n", "<br>")
        self.fb.setText(
            f"<span style='color:{color};font-weight:700;'>{T('fluency_score', score=score)}</span><br>"
            f"<span style='color:{TXT};'>{fb}</span><br><br>"
            f"<span style='color:{TMT};font-weight:600;'>{T('fluency_model')}</span><br>"
            f"<span style='color:{TS2};'>{model}</span>")


class ParaphraseDialog(QDialog):
    """Exercício de Paráfrase (versão player do 'Paraphrase' da web). Mostra o grupo
    de legendas da cena atual (o mesmo que alimenta os cartões Twitch), com a linha
    que está a tocar EM DESTAQUE, e pede ao utilizador para a reescrever de outra
    forma — na MESMA língua (a que está a aprender), mantendo o sentido. A IA recebe
    TODAS as legendas do grupo como contexto, para a paráfrase ficar coerente com a
    cena, e avalia (mantém o sentido? palavras diferentes? natural?) + mostra modelo."""

    def __init__(self, parent, engine, chat_panel=None):
        super().__init__(parent)
        self._engine = engine
        self._chat_panel = chat_panel or (parent.chat if hasattr(parent, 'chat') else None)
        self._lines = []
        self._focus = -1
        self._checking = False
        self.setWindowTitle(T("paraphrase_btn"))
        self.setMinimumSize(300, 360)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20, 18, 20, 18); lo.setSpacing(10)

        hdr = QLabel(T("paraphrase_btn")); hdr.setStyleSheet(
            f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)

        self.instr = QLabel(T("paraphrase_instruction")); self.instr.setWordWrap(True)
        self.instr.setStyleSheet(f"color:{TMT};font-size:12px;background:transparent;")
        lo.addWidget(self.instr)

        # Grupo de legendas (contexto da cena) com a linha-foco destacada.
        self.group_lbl = QLabel(""); self.group_lbl.setWordWrap(True)
        self.group_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.group_lbl.setStyleSheet(
            f"color:{TS2};font-size:14px;background:{ELV};"
            f"border:1px solid {BRD};border-radius:10px;padding:12px 14px;")
        lo.addWidget(self.group_lbl)

        self.answer = QTextEdit(); self.answer.setPlaceholderText(T("paraphrase_placeholder"))
        self.answer.setStyleSheet(f"QTextEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};"
                                  f"border-radius:8px;padding:10px;font-size:13px;font-family:'Inter','Segoe UI',sans-serif;}}")
        self.answer.setMinimumHeight(80)
        lo.addWidget(self.answer)

        self.fb = QLabel(""); self.fb.setWordWrap(True); self.fb.setVisible(False)
        self.fb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fb.setStyleSheet(f"color:{TXT};font-size:12px;background:{ELV};"
                              f"border:1px solid {BRD};border-radius:8px;padding:10px 12px;")
        lo.addWidget(self.fb)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.check_btn = QPushButton(T("paraphrase_check")); self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:8px 20px;font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}"
            f"QPushButton:disabled{{background:{ELV};color:{TMT};}}")
        self.check_btn.clicked.connect(self._check)
        bb.addWidget(self.check_btn)

        self.next_btn = QPushButton(T("fluency_next")); self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                                    f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                                    f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        self.next_btn.setToolTip(T("fluency_next_tip"))
        self.next_btn.clicked.connect(self._load_group)
        bb.addWidget(self.next_btn)

        bb.addStretch()
        cl = QPushButton(T("exercise_close")); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                         f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                         f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        cl.clicked.connect(self.close)
        bb.addWidget(cl)
        lo.addLayout(bb)

        QTimer.singleShot(80, self._load_group)

    def _load_group(self):
        self.fb.setVisible(False); self.fb.setText("")
        self.answer.clear(); self.answer.setFocus()
        self._lines, self._focus = self._engine.paraphrase_group()
        if not self._lines or self._focus < 0:
            log(f"paraphrase: grupo vazio/sem foco (subs_loaded={self._engine.subs_loaded()})")
            self.group_lbl.setText(T("fluency_no_subs"))
            self.check_btn.setEnabled(False)
            return
        self.check_btn.setEnabled(True)
        parts = []
        for n, s in enumerate(self._lines):
            txt = _esc_html(s.text.replace("\n", " ").strip())
            if n == self._focus:
                parts.append(f"<span style='color:{ACC};font-weight:700;'>▸ {txt}</span>")
            else:
                parts.append(f"<span style='color:{TMT};'>{txt}</span>")
        self.group_lbl.setText("<br>".join(parts))

    def _check(self):
        if self._checking:
            return
        ans = self.answer.toPlainText().strip()
        if not ans or not self._lines or self._focus < 0:
            return
        self._checking = True
        self.check_btn.setEnabled(False)
        self.fb.setVisible(True)
        self.fb.setText(T("fluency_checking"))
        scene = "\n".join(
            (("[FOCUS] " if n == self._focus else "") + s.text.replace("\n", " ").strip())
            for n, s in enumerate(self._lines))
        focus = self._lines[self._focus].text.replace("\n", " ").strip()
        threading.Thread(target=self._work, args=(scene, focus, ans), daemon=True).start()

    def _work(self, scene, focus, ans):
        try:
            import ssl
            log("paraphrase: a avaliar...")
            nat = native_language_name()
            sys_p = (
                "You are a paraphrasing coach. The user is learning a language by watching a film. "
                "Below is a short scene of consecutive subtitle lines in the language they are LEARNING. "
                "One line is marked [FOCUS]. The user rewrote ONLY that focus line, in the SAME language, "
                "trying to keep the same meaning while using different words, and it must still fit the "
                "surrounding lines. Judge the user's paraphrase: does it preserve the meaning of the focus "
                "line, use genuinely different wording (not a trivial copy), sound natural, and stay coherent "
                "with the rest of the scene? Respond ONLY with JSON:\n"
                '{"score": <integer 0-100>, '
                f'"feedback": "<2-3 sentences in {nat}: what was good and what to improve>", '
                '"model": "<one strong, natural paraphrase of the FOCUS line, in the language being learned>"}')
            user_p = f"SCENE (language being learned):\n{scene}\n\nFOCUS LINE:\n{focus}\n\nUSER PARAPHRASE:\n{ans}"
            # Usa o Chat IA em vez de chamada direta — herda contexto do utilizador
            cp = self._chat_panel
            if cp:
                cp.eval_result.connect(self._on_eval)
                cp.request_evaluation(sys_p, user_p)
            else:
                raise Exception("ChatPanel nao disponivel")
        except Exception as e:
            log(f"paraphrase FALHOU: {type(e).__name__}: {e}")
            gui_call(self._fail)

    def _on_eval(self, resp, err):
        cp = self._chat_panel
        if cp:
            try: cp.eval_result.disconnect(self._on_eval)
            except: pass
        if err or not resp:
            log(f"paraphrase eval error: {err or 'resposta vazia'}")
            gui_call(self._fail)
            return
        try:
            raw = resp.strip().strip("`")
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            gui_call(lambda: self._show(parsed))
        except Exception as e:
            log(f"paraphrase parse FALHOU: {type(e).__name__}: {e}")
            gui_call(self._fail)

    def _fail(self):
        self._checking = False
        self.check_btn.setEnabled(True)
        self.fb.setText(T("exercise_failed"))

    def _show(self, data):
        self._checking = False
        self.check_btn.setEnabled(True)
        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except Exception:
            score = 0
        color = "#5ae05a" if score >= 75 else ("#e0c05a" if score >= 50 else "#e07a5a")
        fb = _esc_html(data.get("feedback", "")).replace("\n", "<br>")
        model = _esc_html(data.get("model", "")).replace("\n", "<br>")
        self.fb.setText(
            f"<span style='color:{color};font-weight:700;'>{T('fluency_score', score=score)}</span><br>"
            f"<span style='color:{TXT};'>{fb}</span><br><br>"
            f"<span style='color:{TMT};font-weight:600;'>{T('paraphrase_model')}</span><br>"
            f"<span style='color:{TS2};'>{model}</span>")


class DescribeDialog(QDialog):
    """Exercício de descrição na língua-alvo. Dois modos:
      • 'scene' — descrever a CENA. Ao abrir, o filme entra em LOOP sobre o grupo de
        legendas (a cena repete enquanto o utilizador a observa e descreve).
      • 'take'  — descrever um TAKE/plano. Ao abrir, o filme PAUSA no fotograma atual.
    A IA recebe as legendas do grupo como contexto e avalia a descrição (riqueza,
    correção, coerência com a cena) + mostra uma descrição-modelo. Ao fechar, o
    estado anterior do filme (loop / reprodução) é reposto."""

    def __init__(self, parent, engine, mode="scene"):
        super().__init__(parent)
        self._engine = engine
        self._mode = "take" if mode == "take" else "scene"
        self._lines = []
        self._checking = False
        # Guardar estado para repor ao fechar.
        self._prev_loop = engine._loop
        self._was_playing = engine.is_playing()
        self._prev_autopause = getattr(engine, "_autopause", False)
        self._prev_ai_loop = getattr(engine, "_ai_loop", False)

        self._lines = engine.fluency_group()
        # Aplicar o comportamento pedido: cena → loop; take → pause.
        if self._mode == "scene" and self._lines:
            # Auto-pausa/AI-loop dariam cabo do loop da cena (pausava/repetia linha a
            # linha). Desligam-se enquanto a cena anda em loop; repostos ao fechar.
            engine._autopause = False
            engine._ai_loop = False
            engine.loop_range(self._lines[0].start, self._lines[-1].end)
        elif self._mode == "take":
            engine.pause()

        title = T("describe_take_btn") if self._mode == "take" else T("describe_scene_btn")
        self.setWindowTitle(title)
        self.setMinimumSize(300, 360)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20, 18, 20, 18); lo.setSpacing(10)

        hdr = QLabel(title); hdr.setStyleSheet(
            f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)

        mode_note = T("describe_take_mode") if self._mode == "take" else T("describe_scene_mode")
        badge = QLabel(mode_note); badge.setStyleSheet(
            f"color:{ACC};font-size:10px;font-weight:700;letter-spacing:.06em;background:transparent;")
        lo.addWidget(badge)

        instr_key = "describe_take_instruction" if self._mode == "take" else "describe_scene_instruction"
        self.instr = QLabel(T(instr_key)); self.instr.setWordWrap(True)
        self.instr.setStyleSheet(f"color:{TMT};font-size:12px;background:transparent;")
        lo.addWidget(self.instr)

        # Legendas da cena como contexto (o que está a ser dito).
        self.ctx_lbl = QLabel(""); self.ctx_lbl.setWordWrap(True)
        self.ctx_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ctx_lbl.setStyleSheet(
            f"color:{TMT};font-size:12px;font-style:italic;background:{ELV};"
            f"border:1px solid {BRD};border-radius:10px;padding:10px 12px;")
        if self._lines:
            self.ctx_lbl.setText(T("describe_context") + "\n" +
                                 "\n".join(s.text.replace("\n", " ").strip() for s in self._lines))
        else:
            self.ctx_lbl.setVisible(False)
        lo.addWidget(self.ctx_lbl)

        self.answer = QTextEdit(); self.answer.setPlaceholderText(T("describe_placeholder"))
        self.answer.setStyleSheet(f"QTextEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};"
                                  f"border-radius:8px;padding:10px;font-size:13px;font-family:'Inter','Segoe UI',sans-serif;}}")
        self.answer.setMinimumHeight(90)
        lo.addWidget(self.answer)

        self.fb = QLabel(""); self.fb.setWordWrap(True); self.fb.setVisible(False)
        self.fb.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.fb.setOpenExternalLinks(False)
        self.fb.linkActivated.connect(self._on_marked_word)   # palavra sublinhada → Detalhes
        self.fb.setStyleSheet(f"color:{TXT};font-size:12px;background:{ELV};"
                              f"border:1px solid {BRD};border-radius:8px;padding:10px 12px;")
        lo.addWidget(self.fb)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.check_btn = QPushButton(T("describe_check")); self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:8px 20px;font-size:12px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}"
            f"QPushButton:disabled{{background:{ELV};color:{TMT};}}")
        self.check_btn.clicked.connect(self._check)
        if not self._lines:
            self.check_btn.setEnabled(False)
        bb.addWidget(self.check_btn)
        bb.addStretch()
        cl = QPushButton(T("exercise_close")); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                         f"border-radius:14px;padding:8px 16px;font-size:11px;}}"
                         f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
        cl.clicked.connect(self.close)
        bb.addWidget(cl)
        lo.addLayout(bb)
        QTimer.singleShot(60, self.answer.setFocus)

    def _scene_text(self):
        return "\n".join(s.text.replace("\n", " ").strip() for s in self._lines)

    def _check(self):
        if self._checking:
            return
        ans = self.answer.toPlainText().strip()
        if not ans:
            return
        self._checking = True
        self.check_btn.setEnabled(False)
        self.fb.setVisible(True)
        self.fb.setText(T("describe_seeing") if self._vision_ok() else T("fluency_checking"))
        # Captura o fotograma atual NA THREAD da UI (VLC) e passa-o à avaliação.
        frame = None
        try:
            frame = self._engine.snapshot_b64()
        except Exception:
            frame = None
        threading.Thread(target=self._work, args=(self._scene_text(), ans, frame), daemon=True).start()

    def _vision_ok(self):
        # Só tentamos visão se há imagem possível (player ativo). A própria captura
        # confirma; aqui é só para a mensagem "a ver…".
        return self._engine is not None and getattr(self._engine, "_player", None) is not None

    def _work(self, scene, ans, frame=None):
        # Fluxo em 2 PASSOS (robusto):
        #   PASSO 1 — uma IA de VISÃO gratuita olha para o fotograma e descreve, em
        #             texto simples, o que se vê. (Modelos pedem só prosa, não JSON →
        #             muito mais fiável do que pedir scoring à IA de visão.)
        #   PASSO 2 — a IA de TEXTO (DeepSeek, fiável) recebe essa descrição da imagem
        #             + as legendas + a descrição do aluno e AVALIA se bate certo.
        # Se a visão falhar (sem chave / rate-limit), o passo 2 corre só com as
        # legendas — o exercício nunca rebenta.
        nat = native_language_name()
        # Nome da língua-ALVO (a que o utilizador está a aprender) p/ a IA escrever a
        # descrição-modelo NELA (e não na nativa). Vem da conta via _content_lang().
        try:
            mw = self.parent()
            tgt_name = i18n.language_en_name(mw._content_lang()) if mw and hasattr(mw, "_content_lang") else ""
        except Exception:
            tgt_name = ""
        tgt_name = tgt_name or "the language being learned"
        unit = "single shot (a take)" if self._mode == "take" else "scene"
        seen_desc = ""
        if frame:
            try:
                data, mime = frame
                seen_desc = call_vision(
                    "Describe, in 2-4 plain sentences, what is visibly happening in this "
                    "film frame: the people, their actions and expressions, the setting and "
                    "the mood. Describe ONLY what is actually visible — no preamble, no guesses.",
                    system="You are a precise visual describer for a film. Describe only what is "
                           "actually visible in the image.",
                    images=[{"data": data, "mimeType": mime}],
                    max_tokens=300, temperature=0.2, json_mode=False).strip().strip("`")
            except Exception as e:
                log(f"describe visão (passo 1) indisponível: {e}")
                seen_desc = ""
        try:
            if seen_desc:
                sys_p = (
                    "You are a language coach. The user is learning a language and is describing "
                    f"a {unit} from a film in the language they are LEARNING. You are given: "
                    "(A) an objective description of what the frame actually SHOWS (from an image "
                    "model), (B) the subtitle lines (what is being SAID), and (C) the user's "
                    "description. Judge whether the user's description MATCHES what is genuinely "
                    "shown and said, and how rich, natural and grammatical it is in the target "
                    "language. Gently flag anything the user claims that the image does NOT support. "
                    "Be specific and encouraging. Respond ONLY with JSON:\n"
                    '{"score": <integer 0-100>, '
                    f'"feedback": "<2-3 sentences in {nat}: accuracy vs the image, language quality, what to improve>", '
                    f'"seen": "<1 sentence in {nat}: what the image actually shows>", '
                    f'"model": "<a RICH, DETAILED model description written entirely in {tgt_name} (the '
                    'target language), 3-5 sentences covering who is present, their actions and '
                    'expressions, the setting, the mood, and how it ties to the dialogue>"}')
                user_p = (f"(A) WHAT THE IMAGE SHOWS:\n{seen_desc}\n\n"
                          f"(B) SUBTITLES (language being learned):\n{scene or '(no dialogue here)'}\n\n"
                          f"(C) USER DESCRIPTION:\n{ans}")
            else:
                sys_p = (
                    "You are a language coach. The user is learning a language by watching a film and is "
                    f"describing a {unit} in the language they are LEARNING. Below are the subtitle lines of "
                    "that part of the film, as context for what is happening. Evaluate the user's description: "
                    "is it in the target language, rich and varied in vocabulary, grammatically natural, and "
                    "coherent with what the dialogue suggests is happening? Be encouraging but specific. "
                    "Respond ONLY with JSON:\n"
                    '{"score": <integer 0-100>, '
                    f'"feedback": "<2-3 sentences in {nat}: what was good and what to improve>", '
                    f'"model": "<a RICH, DETAILED model description written entirely in {tgt_name} (the '
                    'target language), 3-5 sentences covering who is present, their actions, the setting, '
                    'the mood, and how it ties to the dialogue>"}')
                user_p = f"SCENE SUBTITLES (language being learned):\n{scene or '(no dialogue in this moment)'}\n\nUSER DESCRIPTION:\n{ans}"
            body = json.dumps({"model": "deepseek-chat", "max_tokens": 1100, "temperature": 0.3,
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": user_p}]}).encode()
            r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                headers={"Content-Type": "application/json"}), timeout=60)
            d = json.loads(r.read().decode())
            raw = (d.get("text") or "").strip().strip("`")
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            gui_call(lambda: self._show(parsed))
        except Exception as e:
            log(f"describe: {e}")
            gui_call(self._fail)

    def _fail(self):
        self._checking = False
        self.check_btn.setEnabled(True)
        self.fb.setText(T("exercise_failed"))

    def _show(self, data):
        self._checking = False
        self.check_btn.setEnabled(True)
        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except Exception:
            score = 0
        color = "#5ae05a" if score >= 75 else ("#e0c05a" if score >= 50 else "#e07a5a")
        fb = _esc_html(data.get("feedback", "")).replace("\n", "<br>")
        # Descrição-modelo na língua-alvo → vocabulário sublinhado e clicável (→ Detalhes).
        model = mark_html(data.get("model", ""))
        seen = _esc_html(data.get("seen", "")).replace("\n", "<br>")
        seen_html = (f"<span style='color:{TMT};font-weight:600;'>{T('describe_seen')}</span><br>"
                     f"<span style='color:{TS2};'>{seen}</span><br><br>") if seen else ""
        self.fb.setText(
            f"<span style='color:{color};font-weight:700;'>{T('fluency_score', score=score)}</span><br>"
            f"<span style='color:{TXT};'>{fb}</span><br><br>"
            f"{seen_html}"
            f"<span style='color:{TMT};font-weight:600;'>{T('describe_model')}</span><br>"
            f"<span style='color:{TS2};'>{model}</span>")

    def _on_marked_word(self, href):
        """Clique numa palavra/expressão sublinhada na descrição-modelo → abre Detalhes."""
        if href and href.startswith("lexioword:"):
            from urllib.parse import unquote
            mw = self.parent()
            try:
                if mw and hasattr(mw, "word_details"):
                    mw.word_details.show_for(unquote(href.split(":", 1)[1]))
                    if hasattr(mw, "_balance_left_dock"): mw._balance_left_dock()
            except Exception as e:
                log(f"describe marked word: {e}")

    def closeEvent(self, e):
        # Repor o estado do filme: tirar o loop da cena (a menos que já existisse) e
        # retomar a reprodução se o take a tinha pausado.
        try:
            if self._mode == "scene":
                self._engine._loop = self._prev_loop
                self._engine._loop_a = None
                self._engine._autopause = self._prev_autopause
                self._engine._ai_loop = self._prev_ai_loop
            elif self._mode == "take" and self._was_playing:
                self._engine.play()
        except Exception:
            pass
        super().closeEvent(e)


class DialogueDialog(QDialog):
    """Diálogo + Shadowing (linha-a-linha). Sem adivinhar quem fala: o filme toca uma
    fala (legenda) a volume normal; no fim, em vez de pausar/mutar, BAIXA o volume e
    repete a fala em loop suave para o aluno a dizer por cima (shadowing). 'Continuar'
    repõe o volume e avança. Funciona com qualquer legenda (não precisa de marcas de
    personagem, que a maioria dos .srt não tem)."""

    def __init__(self, parent, engine):
        super().__init__(parent)
        self._engine = engine
        # O Loop IA / auto-pausa / loop A-B do MOTOR fazem o seu próprio seek a cada
        # fala e lutavam contra a condução deste exercício (que também faz seek por
        # fala) — com o "Loop IA" ligado o diálogo não avançava/parecia não abrir.
        # Suspende-os enquanto o exercício está aberto; repõe no closeEvent.
        self._prev_ai_loop = getattr(engine, "_ai_loop", False)
        self._prev_autopause = getattr(engine, "_autopause", False)
        self._prev_loop = getattr(engine, "_loop", None)
        try:
            engine._ai_loop = False
            engine._autopause = False
            engine._loop = None
        except Exception:
            pass
        self._lines = self._collect_lines(engine)   # corrida de legendas a partir da posição
        self._idx = -1
        self._done = False
        self._phase = "listen"   # "listen" (volume normal) | "shadow" (loop a volume baixo)

        self.setWindowTitle(T("dialogue_btn"))
        self.setMinimumWidth(300)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        lo = QVBoxLayout(self); lo.setContentsMargins(20, 18, 20, 18); lo.setSpacing(10)

        hdr = QLabel(T("dialogue_btn")); hdr.setStyleSheet(
            f"color:{TXT};font-size:15px;font-weight:700;background:transparent;")
        lo.addWidget(hdr)

        self.role_lbl = QLabel(T("dialogue_echo_hint")); self.role_lbl.setWordWrap(True)
        self.role_lbl.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        lo.addWidget(self.role_lbl)

        self.turn_lbl = QLabel(""); self.turn_lbl.setStyleSheet(
            f"color:{ACC};font-size:12px;font-weight:800;letter-spacing:.08em;background:transparent;")
        lo.addWidget(self.turn_lbl)

        self.line_lbl = QLabel(""); self.line_lbl.setWordWrap(True)
        self.line_lbl.setMinimumHeight(64)
        self.line_lbl.setStyleSheet(
            f"color:{TS2};font-size:16px;background:{ELV};border:1px solid {BRD};"
            f"border-radius:10px;padding:14px 16px;")
        lo.addWidget(self.line_lbl)

        bb = QHBoxLayout(); bb.setSpacing(8)
        self.cont_btn = QPushButton(T("dialogue_continue")); self.cont_btn.setCursor(Qt.PointingHandCursor)
        self.cont_btn.setStyleSheet(
            f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:14px;"
            f"padding:8px 20px;font-size:12px;font-weight:700;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{ACC_HOVER};}}"
            f"QPushButton:disabled{{background:{ELV};color:{TMT};}}")
        self.cont_btn.clicked.connect(self._on_continue)
        bb.addWidget(self.cont_btn)

        def ghost(txt, fn):
            b = QPushButton(txt); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                            f"border-radius:14px;padding:8px 14px;font-size:11px;}}"
                            f"QPushButton:hover{{color:{TXT};border-color:{ACC};}}")
            b.clicked.connect(fn); return b
        self.replay_btn = ghost(T("dialogue_replay"), self._replay)
        bb.addWidget(self.replay_btn)
        bb.addWidget(ghost(T("dialogue_restart"), self._start))
        bb.addStretch()
        bb.addWidget(ghost(T("exercise_close"), self.close))
        lo.addLayout(bb)

        self._timer = QTimer(self); self._timer.setInterval(90)
        self._timer.timeout.connect(self._drive)

        if len(self._lines) < 1:
            self.line_lbl.setText(T("dialogue_no_dialogue"))
            self.cont_btn.setEnabled(False); self.replay_btn.setEnabled(False)
        else:
            QTimer.singleShot(60, self._start)

    @staticmethod
    def _collect_lines(engine, max_lines=12, gap=2.6):
        """Reúne as legendas consecutivas a partir da posição atual, partindo só quando
        há um silêncio longo. Cada legenda é uma 'fala' a repetir (sem agrupar por
        personagem)."""
        subs = getattr(engine, "_subs", [])
        if not subs:
            return []
        i = engine._sub_idx_at(engine.get_pos())
        if i < 0:
            i = getattr(engine, "_last_sub_idx", 0)
        i = max(0, min(i, len(subs) - 1))
        run = [subs[i]]; j = i
        while len(run) < max_lines and j + 1 < len(subs):
            if subs[j + 1].start - subs[j].end <= gap:
                j += 1; run.append(subs[j])
            else:
                break
        return run

    # ── condução ──
    # Fases: "listen" (a fala toca a volume normal) → "shadow" (a MESMA fala fica em
    # loop a volume BAIXO para o aluno falar por cima; o filme não pausa nem muta).
    def _start(self):
        if not self._lines:
            return
        self._done = False
        self._idx = -1
        self._phase = "listen"
        self._timer.start()
        self._enter(0)

    def _enter(self, idx):
        """Toca a fala idx desde o início a volume normal (fase 'listen')."""
        self._idx = idx
        if idx >= len(self._lines):
            return self._finish()
        line = self._lines[idx]
        self._phase = "listen"
        self.turn_lbl.setText(T("dialogue_listen"))
        self.line_lbl.setText(line.text.replace(chr(10), " ").strip())
        self.cont_btn.setEnabled(False)
        try:
            self._engine.restore_volume()   # volume normal para ouvir bem
            self._engine.seek(line.start)
            self._engine.play()
        except Exception:
            pass

    def _drive(self):
        if self._done or not self._lines or not (0 <= self._idx < len(self._lines)):
            return
        line = self._lines[self._idx]
        pos = self._engine.get_pos()
        if self._phase == "listen":
            if pos >= line.end - 0.04:
                # Acabou de ouvir → passa a shadowing: baixa o volume (NÃO pausa) e
                # repete a fala em loop para o aluno falar por cima.
                self._phase = "shadow"
                try:
                    self._engine.duck_volume()
                    self._engine.seek(line.start)
                    if not self._engine.is_playing():
                        self._engine.play()
                except Exception:
                    pass
                self.turn_lbl.setText(T("dialogue_your_turn"))
                self.cont_btn.setEnabled(True)
        elif self._phase == "shadow":
            # Mantém a fala em loop suave (volume baixo) até o aluno clicar Continuar.
            if pos >= line.end - 0.04 or pos < line.start - 0.5:
                try: self._engine.seek(line.start)
                except Exception: pass

    def _replay(self):
        # Voltar a ouvir a fala atual a volume normal.
        if self._done or not (0 <= self._idx < len(self._lines)):
            return
        self._enter(self._idx)

    def _on_continue(self):
        if self._done:
            return
        self.cont_btn.setEnabled(False)
        try: self._engine.restore_volume()
        except Exception: pass
        self._enter(self._idx + 1)

    def _finish(self):
        self._done = True
        self._timer.stop()
        try:
            self._engine.restore_volume()
            self._engine.pause()
        except Exception: pass
        self.turn_lbl.setText("")
        self.line_lbl.setText(T("dialogue_done"))
        self.cont_btn.setEnabled(False)

    def closeEvent(self, e):
        try: self._timer.stop()
        except Exception: pass
        try: self._engine.restore_volume()   # nunca deixar o filme com volume baixo
        except Exception: pass
        # Repor os modos do motor que tínhamos suspendido (Loop IA / auto-pausa / A-B).
        try:
            self._engine._ai_loop = self._prev_ai_loop
            self._engine._autopause = self._prev_autopause
            self._engine._loop = self._prev_loop
        except Exception:
            pass
        super().closeEvent(e)


class SceneMissionDialog(QDialog):
    """Missão interativa do Scene Agent: o filme pausa numa cena e pede ao utilizador
    para agir (assumir personagem, shadowing, resumir, etc.). Avalia a resposta com
    IA (DeepSeek, via scene_agent) e mostra feedback real. É o 'Deus' a agir."""
    _eval_ready = pyqtSignal(dict)

    def __init__(self, parent, mission, ctx, auth_header):
        super().__init__(parent)
        self._mission = mission
        self._ctx = ctx
        self._auth = auth_header
        self.setWindowTitle(mission.title)
        self.setMinimumSize(300, 360)   # estreito: encaixa na sidebar
        self.setStyleSheet(f"background:{BG};")
        self._eval_ready.connect(self._on_eval)

        lo = QVBoxLayout(self); lo.setContentsMargins(22, 20, 22, 20); lo.setSpacing(10)
        kicker = QLabel(mission.label.upper() + "  ·  " + FMT(mission.timestamp))
        kicker.setStyleSheet(f"color:{ACC};font-size:10px;font-weight:700;letter-spacing:.08em;background:transparent;")
        lo.addWidget(kicker)
        ttl = QLabel(mission.title); ttl.setWordWrap(True)
        ttl.setStyleSheet(f"color:{TXT};font-size:18px;font-weight:800;background:transparent;")
        lo.addWidget(ttl)
        prompt = QLabel(mission.prompt); prompt.setWordWrap(True)
        prompt.setStyleSheet(f"color:{TMT};font-size:13px;line-height:1.5;background:transparent;")
        lo.addWidget(prompt)

        if mission.target_line:
            tl = QLabel(mission.target_line); tl.setWordWrap(True)
            tl.setStyleSheet(f"color:{TS2};font-size:14px;background:{ELV};border:1px solid {BRD};"
                             f"border-radius:8px;padding:10px 12px;")
            lo.addWidget(tl)

        self.answer = QTextEdit(); self.answer.setPlaceholderText("Escreve (ou dita) a tua resposta...")
        self.answer.setStyleSheet(f"QTextEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};"
                                  f"border-radius:8px;padding:10px;font-size:13px;font-family:'Inter','Segoe UI',sans-serif;}}")
        self.answer.setMinimumHeight(90)
        lo.addWidget(self.answer)

        self.fb = QLabel(""); self.fb.setWordWrap(True); self.fb.setStyleSheet("background:transparent;")
        self.fb.hide()
        lo.addWidget(self.fb)
        lo.addStretch()

        row = QHBoxLayout(); row.setSpacing(8)
        self.skip_btn = QPushButton("Saltar")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{TMT};border:1px solid {BRD};"
                                    f"border-radius:8px;padding:9px 16px;font-size:12px;}}QPushButton:hover{{color:{TXT};}}")
        self.skip_btn.clicked.connect(self.reject)
        self.go_btn = QPushButton("Avaliar"); self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.setStyleSheet(f"QPushButton{{background:{ACC};color:{ON_ACC};border:none;border-radius:8px;"
                                  f"padding:9px 20px;font-size:13px;font-weight:700;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.go_btn.clicked.connect(self._evaluate)
        row.addWidget(self.skip_btn); row.addStretch(); row.addWidget(self.go_btn)
        self._row = row
        lo.addLayout(row)

    def _evaluate(self):
        ans = self.answer.toPlainText().strip()
        if not ans:
            self.reject(); return
        self.go_btn.setEnabled(False); self.go_btn.setText("A avaliar...")
        def work():
            try:
                res = scene_agent.evaluate_scene_mission(
                    self._mission, ans,
                    native_lang=self._ctx.get("native", "pt"),
                    target_lang=self._ctx.get("target", "en"),
                    level=self._ctx.get("level", "B1"),
                    api_base=LEXIO_API, auth_header=self._auth)
            except Exception as e:
                log(f"scene mission eval: {type(e).__name__}: {e}")
                res = {"score": 0, "feedback": f"Erro: {e}", "ai_graded": False}
            self._eval_ready.emit(res or {"score": 0, "feedback": "Sem resposta da IA.", "ai_graded": False})
        threading.Thread(target=work, daemon=True).start()

    def _on_eval(self, res):
        score = res.get("score", 0)
        col = "#5ae05a" if score >= 80 else ("#7dd3fc" if score >= 60 else "#f8b478")
        parts = [f"<b style='color:{col};font-size:20px'>{score}%</b>"]
        if res.get("feedback"):
            parts.append(f"<span style='color:{TMT}'>{res['feedback']}</span>")
        if res.get("corrected"):
            parts.append(f"<span style='color:{TS2}'>Versão melhor: <i>{res['corrected']}</i></span>")
        self.fb.setText("<br><br>".join(parts)); self.fb.show()
        self.go_btn.setText("Continuar filme"); self.go_btn.setEnabled(True)
        self.go_btn.clicked.disconnect(); self.go_btn.clicked.connect(self.accept)


class MainWindow(QMainWindow):
    # Entrega segura de resultados de threads worker para a GUI (queued).
    tracks_ready = pyqtSignal(object)   # (lista de segmentos)
    tracks_failed = pyqtSignal(str)     # (mensagem de erro)

    def __init__(self):
        super().__init__()
        self._study_mode = False
        self._sub_names = ["", "", ""]  # nomes dos ficheiros das 3 legendas (principal/2ª/3ª)
        self._transport_overlay = None     # floating seek+controls window (study mode)
        self._transport_floating = False
        self._transport_opacity = 0.90   # opacidade do transport flutuante (ajustável: clique-direito)
        self._controls_state = {}  # save/restore visibility
        # Sessão do player → enviada p/ player_sessions (a IA da web fica a saber).
        self._session_start = None
        self._session_video = ""
        self._session_words = []
        try: self._setup()
        except Exception as e: log(f"FATAL: {e}\n{traceback.format_exc()}"); raise

    def _setup(self):
        self.video_path = None; self.mgr = StudyMgr()
        # ── Lembrete de revisão espaçada (notificação do sistema) ──
        # Criado cedo porque a aba Ferramentas (construída mais abaixo) já liga o
        # checkbox a ele. O token resolve-se preguiçosamente (self.chat ainda não
        # existe aqui; já existe quando o timer dispara).
        self._tray = None
        self.reminder = ReminderManager(
            lambda: self.chat._get_token_header() if getattr(self, "chat", None) else None,
            self)
        self.reminder.show_note.connect(self._show_reminder_note)
        self._autopause_on = False
        # ── Coach AI (responsibility calls) ──
        self.coach_mgr = CoachManager(self)
        self.coach_mgr.coach_call.connect(self._on_coach_call)
        # ── Tipo de estudo: desligado | leve | focado. A IA (Scene Agent) está SEMPRE
        # em modo "Deus" (máxima qualidade); o que muda é QUANTO intervém:
        #   desligado = sem agente, só ver; leve = poucas missões; focado = muitas + autopause/loop.
        self._study_kind = "desligado"  # Scene Agent removido — fica sempre desligado
        self._scene_mode = "off"        # sem missões automáticas (só exercícios manuais)
        self._scene_missions = []
        self._scene_done = set()        # ids de missões já feitas/saltadas
        self._scene_subs_key = None     # rebuild só quando as legendas mudam
        self._in_mission = False        # evita re-disparar enquanto o diálogo está aberto
        # ── Exercícios automáticos ao longo do filme (toggle do user) ──
        # Quando ligado, a cada ~N falas (numa pausa natural) abre, encaixado no
        # sidebar, o próximo exercício em rotação — o filme tece exercícios sozinho.
        self._auto_ex = False
        self._auto_ex_count = 0
        self._auto_ex_every = 8         # uma atividade a cada ~8 falas ouvidas
        self._auto_ex_rotation = 0
        self._tracks = []          # [{"title": str, "start_idx": int, "end_idx": int}]
        # ── Aulas (tracks): narração ao vivo enquanto o segmento toca ──
        self._lesson_active = False
        self._lesson_row = None         # índice do track em curso
        self._lesson_range = None       # (start_idx, end_idx)
        self._lesson_seen = set()       # legendas já narradas neste track
        self._lesson_inflight = False   # uma nota da IA de cada vez
        self._lesson_pending = None     # legenda à espera enquanto há uma em curso
        self._lesson_done = set()       # rows de tracks concluídos (marca no groove)
        self._slow_voice = False        # modo lento: VLC mudo + voz neural por cima (<1x)
        self._listening_mode = False
        self._listening_interval = 2  # reouvir+perguntar a cada N falas
        self._listening_sub_count = 0
        self._listening_pending = False
        self._listening_replays = 2   # quantas vezes a fala se repete (loop) antes da pergunta — configurável
        self._playlist = []; self._pl_idx = -1
        self._cur_sub = ""        # última legenda visível (p/ a aba Pronúncia)
        self._rate = 1.0; self._vol = 50; self._seeking = False
        self._overlay_shown = False
        # Auto-hide for the fullscreen transport (seek + controls).
        self._fs_hide_timer = QTimer(self); self._fs_hide_timer.setSingleShot(True)
        self._fs_hide_timer.setInterval(2800)
        self._fs_hide_timer.timeout.connect(self._fs_hide_controls)
        # Sonda a posição do cursor no modo estudo: mostra o groove quando o cursor
        # está na zona de baixo, mesmo durante exercícios (um diálogo modal rouba os
        # eventos de movimento do rato, por isso o mousemove sozinho não chegava).
        self._fs_cursor_timer = QTimer(self); self._fs_cursor_timer.setInterval(250)
        self._fs_cursor_timer.timeout.connect(self._fs_cursor_poll)
        self._setup_ui()
        self.engine.position_changed.connect(self._on_pos)
        self.engine.media_ended.connect(self._on_end)
        self.engine.playing_changed.connect(self._on_play)
        self.engine.duration_changed.connect(self._on_dur)
        # Wire overlay signals
        self.engine.subtitles_changed.connect(self.overlay.show_subtitles)
        self.engine.subtitle_changed.connect(self._remember_last_sub)
        self.engine.subtitle_exited.connect(self._on_sub_exited)
        self.engine.subtitle_entered.connect(self._lesson_on_sub)
        self.engine.subtitle_entered.connect(self._slow_voice_on_sub)
        self.engine.subtitle_entered.connect(self._auto_ex_on_sub)
        self.tracks_ready.connect(self._on_tracks_ready)
        self.tracks_failed.connect(self._track_fail)
        self.engine.ai_loop_changed.connect(self._on_ai_loop)
        # Cartões "twitch": uma legenda → um cartão. Antes vinham de vocab_triggered,
        # que usa _played_ids e por isso SALTAVA para sempre qualquer fala já tocada
        # (loops, seek p/ trás, listening) → "nem todas as legendas apareciam no feed".
        # subtitle_entered dispara em CADA entrada de fala, em paridade exata com a
        # legenda de baixo, por isso o feed nunca mais perde linhas.
        self.engine.subtitle_entered.connect(self._card_on_sub)
        self.engine.subtitle_entered.connect(self._subs_feed_on_sub)   # destaca/scroll no feed
        # Sublinhador inteligente: lê o guião em contexto e deteta GRUPOS de palavras.
        self._expr_miner = ExpressionMiner(LEXIO_API)
        self._expr_miner.updated.connect(self.overlay.update)   # repinta com novos grupos
        self.engine.vocab_triggered.connect(self._feed_expr_miner)
        self.overlay.add_word.connect(self._on_overlay_add)
        self.overlay.ask_ai.connect(self._on_overlay_ask)
        self.overlay.speak_card.connect(self._speak_slow)
        self.overlay.video_clicked.connect(self._toggle)
        self.overlay.toggle_fullscreen.connect(self._toggle_fs)
        self.overlay.mouse_moved.connect(self._fs_activity)
        self.overlay.load_sub_requested.connect(self._load_sub_file)
        self.setAcceptDrops(True)   # drag a .srt (or video) straight onto the window
        self._load_recent()
        # Route shortcut keys app-wide (so they work even when the VLC video has
        # focus) — but never when typing in the chat / notes.
        QApplication.instance().installEventFilter(self)
        log("MainWindow ready")

    def _setup_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        # Fit the window to the user's screen. A fixed 1200x780 default does NOT
        # fit a 1366x768 display (taller than the screen!), so the window opened
        # hanging off-screen and subtitles landed at the screen corner. Clamp the
        # clamp the default to the available work area and open centred; keep the
        # minimum large enough for all nav/exercise buttons to fit comfortably.
        # Mínimo modesto: com as barras a quebrarem (FlowLayout) e as listas/abas a
        # mostrarem tudo, a app continua usável e SEM cortar nada em janelas pequenas.
        self.setMinimumSize(680, 520)
        try:
            av = QApplication.primaryScreen().availableGeometry()
            w0 = min(1200, av.width() - 24); h0 = min(780, av.height() - 24)
            self.resize(w0, h0)
            self.move(av.left() + (av.width() - w0) // 2,
                      av.top() + (av.height() - h0) // 2)
        except Exception:
            self.resize(1200, 780)
        self.setStyleSheet(f"QMainWindow{{background:{BG};color:{TXT};}}")

        c = QWidget(); self.setCentralWidget(c)
        outer = QVBoxLayout(c); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        # ═══ (sem barra de topo) ═══
        # A antiga TOP BAR (logo + "Chat IA" + "Abrir") foi removida: repetia o
        # cabeçalho "Chat IA" do painel de chat. Os seus botões vivem agora na
        # barra de controlos do vídeo (chat = self.chat_btn; abrir = self.open_btn)
        # e o nome do vídeo atual passa para o título da janela (mais limpo).

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
        self._seek_bar_w = sb   # used by _engine_global_rect to find the video's true bottom
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
        # Preview da legenda ao passar o rato sobre o seek (mostra o que se diz nesse
        # instante). Só no seek bar — o volume não tem preview, logo não há conflito (#5).
        self.seek.set_preview(lambda v: (FMT(v) + "  ·  " + self.engine.sub_text_at(v))
                              if self.engine.sub_text_at(v) else FMT(v))
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
        cb = QWidget(); cb.setObjectName("controls_bar")
        cb.setStyleSheet("#controls_bar{background:#1c1c1c;}")
        cb.setMinimumHeight(56)
        # FlowLayout: em janelas estreitas os controlos QUEBRAM p/ a linha seguinte em
        # vez de serem cortados — garante que TODOS os botões ficam sempre visíveis,
        # qualquer que seja o tamanho da janela (igual às barras nav/exercícios).
        # center=True: os controlos de transporte ficam CENTRADOS (estilo Windows
        # Media Player), tanto em janela como em ecrã inteiro — antes encostavam à
        # esquerda porque o FlowLayout alinhava sempre a partir da margem esquerda.
        cl = FlowLayout(cb, margin=0, hspacing=6, vspacing=4, center=True)
        cl.setContentsMargins(14,6,14,6)
        _spc = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum); _spc.setHeightForWidth(True)
        cb.setSizePolicy(_spc)

        self.pb = _icn(chr(0xE892), 38, 14, T("prev_p")); self.pb.clicked.connect(self._prev)
        self.play_btn = QPushButton(chr(0xE768)); self.play_btn.setFixedSize(46,46); self.play_btn.setToolTip(T("play_tip"))
        self.play_btn.setStyleSheet(f"QPushButton{{background:{ACC};border:none;border-radius:23px;color:{ON_ACC};font-family:{ICON_F};font-size:18px;}}QPushButton:hover{{background:{ACC_HOVER};}}")
        self.play_btn.clicked.connect(self._toggle)
        self.nb = _icn(chr(0xE893), 38, 14, T("next_n")); self.nb.clicked.connect(self._next)

        # 0xE7F0 = ClosedCaption (o CC tradicional). 0xE720 era o Microfone — errado.
        self.sub_btn = _icn(chr(0xE7F0), 36, 16, T("sub_mgr_btn_tip"))
        self.sub_btn.clicked.connect(self._open_sub_manager)
        self.sub_icon = QPushButton(chr(0xE7F0)); self.sub_icon.setFixedSize(30,24)
        self.sub_icon.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{TMT};font-family:{ICON_F};font-size:13px;}}QPushButton:hover{{color:{ACC};}}")
        self.sub_icon.setToolTip(T("sub_toggle_tip") + " · " + T("sub_menu_tip"))
        self.sub_icon.clicked.connect(self._cycle_subs)
        # Clique-direito no CC → legendas duplas/triplas + auto-tradução.
        self.sub_icon.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sub_icon.customContextMenuRequested.connect(self._sub_menu)

        self.vol_icon = QLabel(chr(0xE767)); self.vol_icon.setStyleSheet(f"color:{TS2};font-family:{ICON_F};font-size:15px;background:transparent;")
        # SeekSlider (not plain QSlider): clicking anywhere on the bar jumps the
        # volume to that point instead of nudging one step toward it.
        self.vol = SeekSlider(Qt.Horizontal); self.vol.setRange(0,200); self.vol.setValue(50); self.vol.setFixedWidth(84)
        self.vol.setStyleSheet(f"QSlider::groove:horizontal{{background:{HVR};height:3px;border-radius:1.5px;}}QSlider::sub-page:horizontal{{background:{TS2};border-radius:1.5px;}}QSlider::handle:horizontal{{background:{TS2};width:11px;height:11px;margin:-4px 0;border-radius:5.5px;}}")
        self.vol.valueChanged.connect(lambda v: (self.engine.set_vol(v), setattr(self,'_vol',v)))

        self.spd = QPushButton("1.0x"); self.spd.setFixedSize(50,30); self.spd.setToolTip(T("spd_tip"))
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

        # Abrir vídeo — antes vivia na barra de topo (removida); agora é um ícone
        # discreto na barra de controlos, ao lado dos restantes.
        self.open_btn = QPushButton(chr(0xE8E5)); self.open_btn.setFixedSize(38, 38)   # OpenFile
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setToolTip(T("open_video_tip"))
        self.open_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{TS2};font-family:{ICON_F};font-size:15px;border-radius:19px;}}"
            f"QPushButton:hover{{background:{HVR};color:{TXT};}}")
        self.open_btn.clicked.connect(self._open)

        self.fs_btn = _icn(chr(0xE740), 38, 15, T("fullscreen_f")); self.fs_btn.clicked.connect(self._toggle_study_mode)

        # Ordem: abrir · velocidade · anterior · play · seguinte · CC · alternar CC ·
        # volume · chat · ecrã inteiro. (Sem stretches: o FlowLayout quebra sozinho.)
        for w in (self.open_btn, self.spd, self.pb, self.play_btn, self.nb,
                  self.sub_btn, self.sub_icon, self.vol_icon, self.vol, self.chat_btn, self.fs_btn):
            cl.addWidget(w)
        left_lo.addWidget(cb)

        # ── Barra de navegação de legendas (rótulos de texto legíveis + tooltips) ──
        # Texto em vez de glyphs de ícone: nunca renderiza como quadradinho e é
        # inequívoco — estes não são controlos universais (segmentar, auto-legenda,
        # esconder legenda…), por isso a palavra é mais intuitiva que um símbolo.
        def nav_icn(label, tip, checkable=False):
            b = QPushButton(label); b.setToolTip(tip); b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                f"border-radius:13px;font-size:11px;padding:4px 11px;font-family:'Inter','Segoe UI',sans-serif;}}"
                f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
                f"QPushButton:checked{{background:{HVR};color:{TXT};border-color:{ACC};}}")
            return b
        # Controlos de reprodução/prática (Repetir/Anterior/Seguinte/Loop/Auto-pausa):
        # ícones COMPACTOS — são ações convencionais de vídeo, por isso o símbolo
        # poupa espaço e lê-se logo. Fonte Segoe MDL2 Assets (presente em todo o
        # Windows 10), codepoints DISTINTOS (nada de duplicados); o tooltip mantém
        # a palavra para quem tiver dúvida.
        def nav_sym(glyph, tip, checkable=False):
            b = QPushButton(glyph); b.setToolTip(tip); b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor); b.setFixedSize(30, 26)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};"
                f"border-radius:13px;font-size:13px;padding:0;font-family:'Segoe MDL2 Assets','Segoe Fluent Icons';}}"
                f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
                f"QPushButton:checked{{background:rgba(80,150,255,0.15);color:{TXT};border-color:{ACC};}}")
            return b
        self.nav_bar = QWidget(); self.nav_bar.setObjectName("nav_bar")
        self.nav_bar.setStyleSheet("#nav_bar{background:#181818;}")
        # FlowLayout: quando a janela estreita, os botões QUEBRAM para a linha
        # seguinte em vez de serem cortados (os ícones deixavam de aparecer). A
        # política de tamanho com heightForWidth deixa a barra crescer em altura.
        nav_lo = FlowLayout(self.nav_bar, margin=0, hspacing=6, vspacing=6)
        nav_lo.setContentsMargins(12,3,12,3)
        _sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum); _sp.setHeightForWidth(True)
        self.nav_bar.setSizePolicy(_sp)
        self.btn_sub = nav_icn(T("sub_mgr_btn"), T("sub_mgr_btn_tip"), True)
        self.btn_sub.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};border:1px solid {ACC};"
            f"border-radius:13px;font-size:11px;padding:4px 13px;font-family:'Inter','Segoe UI',sans-serif;font-weight:600;}}"
            f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
            f"QPushButton:checked{{background:rgba(60,180,90,0.18);color:#9EE6A0;border-color:#3CB45A;}}")
        self.btn_sub.clicked.connect(self._open_sub_manager)
        nav_lo.addWidget(self.btn_sub)
        self.btn_sub_online = nav_icn(T("sub_online"), T("sub_online_tip"))
        self.btn_sub_online.clicked.connect(self._search_subs_online)
        nav_lo.addWidget(self.btn_sub_online)
        self.btn_segment = nav_icn(T("track_segment"), T("track_segment_tip"))
        self.btn_segment.clicked.connect(self._segment_subs)
        nav_lo.addWidget(self.btn_segment)
        # (Auto-legenda removida por agora: o DeepSeek não transcreve áudio e o
        # Whisper local não vinha no build — o botão só dava erro. Volta quando
        # houver um STT na nuvem decidido. _generate_auto_captions fica inerte.)
        sep1 = QLabel("|"); sep1.setStyleSheet(f"color:{BRD};font-size:11px;padding:0 2px;background:transparent;")
        nav_lo.addWidget(sep1)
        b_rep = nav_sym(chr(0xE8ED), T("prac_repeat_tip")); b_rep.clicked.connect(self.engine.replay_sub); b_rep.clicked.connect(lambda: self._flash_btn(b_rep))   # RepeatOne
        b_prev = nav_sym(chr(0xE892), T("prac_prev_tip")); b_prev.clicked.connect(self.engine.prev_sub); b_prev.clicked.connect(lambda: self._flash_btn(b_prev))    # Previous
        b_next = nav_sym(chr(0xE893), T("prac_next_tip")); b_next.clicked.connect(self.engine.next_sub); b_next.clicked.connect(lambda: self._flash_btn(b_next))     # Next
        for b in (b_rep, b_prev, b_next): nav_lo.addWidget(b)
        sep2 = QLabel("|"); sep2.setStyleSheet(f"color:{BRD};font-size:11px;padding:0 2px;background:transparent;")
        nav_lo.addWidget(sep2)
        b_a = QPushButton("A"); b_a.setFixedSize(22,22); b_a.setToolTip(T("prac_loop_a_tip"))
        b_a.setCursor(Qt.PointingHandCursor)
        b_a.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:11px;font-size:10px;font-weight:bold;padding:0;}}QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}")
        b_a.clicked.connect(self._set_loop_a)
        b_b = QPushButton("B"); b_b.setFixedSize(22,22); b_b.setToolTip(T("prac_loop_b_tip"))
        b_b.setCursor(Qt.PointingHandCursor)
        b_b.setStyleSheet(f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:11px;font-size:10px;font-weight:bold;padding:0;}}QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}")
        b_b.clicked.connect(self._set_loop_b)
        nav_lo.addWidget(b_a); nav_lo.addWidget(b_b)
        self.btn_loop = nav_sym(chr(0xE8EE), T("prac_loop_tip"), True); self.btn_loop.clicked.connect(self._toggle_loop)   # RepeatAll (loop A-B)
        self.btn_ap = nav_sym(chr(0xE769), T("prac_autopause_tip"), True); self.btn_ap.clicked.connect(self._toggle_autopause)   # Pause (auto-pausa)
        self.btn_ai_loop = nav_icn(T("ai_loop_label"), T("ai_loop_tip"), True); self.btn_ai_loop.clicked.connect(self._toggle_ai_loop)
        self.btn_hide = nav_icn(T("hide_sub"), T("prac_hide_tip"), True); self.btn_hide.clicked.connect(self._toggle_hide_subs)
        for b in (self.btn_loop, self.btn_ap, self.btn_hide, self.btn_ai_loop): nav_lo.addWidget(b)
        b_pron = nav_icn(T("pron_title"), T("pron_open_tip")); b_pron.clicked.connect(self._open_pronunciation)
        nav_lo.addWidget(b_pron)
        left_lo.addWidget(self.nav_bar)

        # ── Barra de exercícios (rótulos de texto — ações não-convencionais que
        # ganham muito em clareza com a palavra em vez de um ícone ambíguo) ──
        def ex_icn(label, tip, checkable=False):
            b = QPushButton(label); b.setToolTip(tip); b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};"
                f"border:1px solid {BRD};border-radius:13px;font-size:11px;padding:4px 11px;font-family:'Inter','Segoe UI',sans-serif;}}"
                f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
                f"QPushButton:checked{{background:{HVR};color:{TXT};border-color:{ACC};}}")
            return b
        self.ex_bar = QWidget(); self.ex_bar.setObjectName("ex_bar")
        self.ex_bar.setStyleSheet("#ex_bar{background:#141414;border-top:1px solid #222;}")
        ex_lo = FlowLayout(self.ex_bar, margin=0, hspacing=6, vspacing=6)
        ex_lo.setContentsMargins(12,3,12,3)
        _spx = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum); _spx.setHeightForWidth(True)
        self.ex_bar.setSizePolicy(_spx)
        ex_lab = QLabel(T("practice")); ex_lab.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;")
        ex_lo.addWidget(ex_lab)
        # Toggle: exercícios automáticos ao longo do filme (o user liga/desliga).
        # Vem ANTES do Listening e tem uma cor de "ligado" BEM distinta (verde
        # preenchido) — antes o estado ativo era subtil e não se percebia que
        # estava ligado.
        self.btn_auto_ex = ex_icn(T("auto_ex_label"), T("auto_ex_tip"), True)
        self.btn_auto_ex.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TS2};"
            f"border:1px solid {BRD};border-radius:13px;font-size:11px;padding:4px 11px;font-family:'Inter','Segoe UI',sans-serif;}}"
            f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}"
            f"QPushButton:checked{{background:rgba(60,180,90,0.22);color:#9EE6A0;border-color:#3CB45A;font-weight:700;}}")
        self.btn_auto_ex.clicked.connect(self._toggle_auto_ex)
        ex_lo.addWidget(self.btn_auto_ex)
        self.btn_listening = ex_icn(T("listening_btn"), T("listening_tip"), True)
        self.btn_listening.clicked.connect(self._toggle_listening)
        # Clique-direito no Listening → escolher quantas vezes cada fala se repete.
        self.btn_listening.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_listening.customContextMenuRequested.connect(self._listening_reps_menu)
        ex_lo.addWidget(self.btn_listening)
        b_ex = ex_icn(T("exercise_btn"), T("exercise_tip")); b_ex.clicked.connect(self._open_exercise)
        b_flu = ex_icn(T("fluency_btn"), T("fluency_tip")); b_flu.clicked.connect(self._open_fluency)
        b_par = ex_icn(T("paraphrase_btn"), T("paraphrase_tip")); b_par.clicked.connect(self._open_paraphrase)
        b_dsc = ex_icn(T("describe_scene_btn"), T("describe_scene_tip")); b_dsc.clicked.connect(self._open_describe_scene)
        b_dtk = ex_icn(T("describe_take_btn"), T("describe_take_tip")); b_dtk.clicked.connect(self._open_describe_take)
        b_dlg = ex_icn(T("dialogue_btn"), T("dialogue_tip")); b_dlg.clicked.connect(self._open_dialogue)
        for b in (b_ex, b_flu, b_par, b_dsc, b_dtk, b_dlg): ex_lo.addWidget(b)
        left_lo.addWidget(self.ex_bar)

        # ── Collapsible tools section ──
        self.tools_wrap = QWidget()
        self.tools_wrap.setStyleSheet(f"background:{SRF};border-top:1px solid {BRD};")
        twl = QVBoxLayout(self.tools_wrap); twl.setContentsMargins(0,0,0,0); twl.setSpacing(0)

        # Header bar with collapse toggle — entire bar is clickable
        tools_hdr = QWidget(); tools_hdr.setFixedHeight(32)
        tools_hdr.setStyleSheet(f"background:{ELV};border-bottom:1px solid {BRD};"
                                f"QWidget:hover{{background:{HVR};}}")
        tools_hdr.setCursor(Qt.PointingHandCursor)
        thl = QHBoxLayout(tools_hdr); thl.setContentsMargins(10,0,8,0)
        self._tools_collapsed = False
        self._tools_hdr_lbl = QLabel(T("tools_collapse"))  # will be toggled
        self._tools_hdr_lbl.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;")
        self.tools_toggle = QPushButton("\u25be")
        self.tools_toggle.setFixedSize(28,26)
        self.tools_toggle.setToolTip("Recolher ou expandir a barra inferior (navegacao, controles, ferramentas)")
        self.tools_toggle.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{TS2};font-size:13px;"
            f"border-radius:13px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{HVR};color:{TXT};}}")
        self.tools_toggle.clicked.connect(self._toggle_bottom)
        # Make clicking the header text also toggle
        self._tools_hdr_lbl.mousePressEvent = lambda e: self._toggle_bottom()
        thl.addWidget(self.tools_toggle)
        thl.addWidget(self._tools_hdr_lbl)
        thl.addStretch()
        twl.addWidget(tools_hdr)

        self._tools_content = QWidget()
        self._tools_content.setStyleSheet(f"background:transparent;")
        tcl = QVBoxLayout(self._tools_content); tcl.setContentsMargins(0,0,0,0); tcl.setSpacing(0)
        # Mais altura útil para caber mais informação numa só janela (listas de
        # vocábulo/tracks/playlist mostram mais linhas sem rolar).
        self._tools_content.setMinimumHeight(120)
        self._tools_content.setMaximumHeight(300)

        tabs = QTabWidget()
        self.tabs = tabs   # referenced so saving a word can jump to the Vídeos tab
        # Abas HORIZONTAIS (a pedido do user). Mais visíveis: separador com fundo
        # próprio, aba selecionada com chip + sublinhado, pílula de hover.
        tabs.setStyleSheet(
            f"QTabWidget::pane{{background:{SRF};border:none;border-top:1px solid {BRD};}}"
            f"QTabBar{{background:{ELV};qproperty-drawBase:0;}}"
            f"QTabBar::tab{{background:transparent;color:{TMT};padding:7px 14px;border:none;"
            f"font-size:11px;font-weight:600;font-family:'Inter','Segoe UI',sans-serif;margin-right:1px;}}"
            f"QTabBar::tab:hover{{color:{TXT};background:{HVR};}}"
            f"QTabBar::tab:selected{{color:{TXT};background:{SRF};border-bottom:2px solid {ACC};}}")
        # Os rótulos das abas (Vídeos/Tracks/Playlist/Ferramentas) mostram-se SEMPRE por
        # inteiro — NUNCA cortados/com reticências (queixa do user: "não dá p/ ver tudo").
        # Não esticam (largura natural ao texto) e, se faltar largura, surgem setas de
        # scroll em vez de truncar.
        tb = tabs.tabBar()
        tb.setExpanding(False)
        tb.setElideMode(Qt.ElideNone)
        tabs.setUsesScrollButtons(True)

        # (Aba "Marcos"/Bookmarks removida — marcadores manuais saíram do fluxo;
        # o foco do painel é vocabulário e cenas geridos pela IA.)

        # ── Vídeos: vocabulary captured from subtitles, SEPARATE from the main
        # study vocabulary. The user opts in (right-click → add) to promote a word
        # to their real account vocabulary. ──
        vvt = QWidget(); vvl = QVBoxLayout(vvt); vvl.setContentsMargins(6,6,6,6); vvl.setSpacing(4)
        vhl = QHBoxLayout()
        self.vv_title = QLabel(T("videos_vocab_title"))
        self.vv_title.setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        vhl.addWidget(self.vv_title); vhl.addStretch()
        # "+ Adicionar palavra": abre o sítio de personalização (AddWordDialog) que
        # cai na conta web. É o ponto de entrada manual pedido pelo user.
        vv_add = yt_btn(T("add_word_manual"), small=True, accent=True)
        vv_add.clicked.connect(self._open_add_word)
        vhl.addWidget(vv_add)
        vvl.addLayout(vhl)
        vhint = QLabel(T("videos_hint"))
        vhint.setWordWrap(True); vhint.setStyleSheet(f"color:{TMT};font-size:10px;background:transparent;")
        vvl.addWidget(vhint)
        # Caixa de pesquisa — filtra a lista por palavra ou nome do filme (a lista
        # crescia muito e não dava p/ encontrar nada).
        self._vv_filter = ""
        self.vv_search = QLineEdit(); self.vv_search.setPlaceholderText(T("videos_search_ph"))
        self.vv_search.setClearButtonEnabled(True)
        self.vv_search.setStyleSheet(
            f"QLineEdit{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:8px;"
            f"padding:5px 9px;font-size:11px;}}QLineEdit:focus{{border-color:{ACC};}}")
        self.vv_search.textChanged.connect(self._vv_search_changed)
        vvl.addWidget(self.vv_search)
        self.vv_list = QListWidget()
        self.vv_list.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:5px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}")
        self.vv_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vv_list.customContextMenuRequested.connect(self._vv_menu)
        # Clique numa palavra → ABRE o filme de onde veio e repete a fala. O botão de
        # balão em cada linha "coloca no chat". (Detalhes/personalizar/remover ficam no
        # menu de clique-direito.)
        self.vv_list.itemClicked.connect(self._vv_clicked)
        _list_show_full(self.vv_list)   # texto completo (quebra de linha, sem cortar)
        vvl.addWidget(self.vv_list)
        tabs.addTab(vvt, T("tab_videos"))
        gui_call(self._load_video_vocab)   # populate once UI is ready

        # ── Smart Tracks: segmentação IA ──
        twt = QWidget(); twl2 = QVBoxLayout(twt); twl2.setContentsMargins(6,6,6,6)
        twl2.setSpacing(4)
        twhl = QHBoxLayout()
        self.tw_title = QLabel(T("tab_tracks"))
        self.tw_title.setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        twhl.addWidget(self.tw_title); twhl.addStretch()
        twl2.addLayout(twhl)
        self.tw_list = QListWidget()
        self.tw_list.setStyleSheet(
            f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}"
            f"QListWidget::item{{padding:8px 8px;border-radius:4px;border-bottom:1px solid {BRD};}}"
            f"QListWidget::item:hover{{background:{HVR};}}"
            f"QListWidget::item:selected{{background:rgba(139,92,246,0.3);}}")
        self.tw_list.currentRowChanged.connect(self._track_clicked)
        _list_show_full(self.tw_list)   # título+tempos+nº falas inteiros (sem cortar)
        twl2.addWidget(self.tw_list)
        self.tw_empty = QLabel(T("track_no_sub"))
        self.tw_empty.setAlignment(Qt.AlignCenter)
        self.tw_empty.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;padding:16px;")
        twl2.addWidget(self.tw_empty)
        twl2.addStretch()
        tabs.addTab(twt, T("tab_tracks"))

        # ── Legendas: FEED das falas (original + 2ª/3ª linha), com palavras-chave
        # SUBLINHADAS e clicáveis (abre Detalhes) — o estudo das legendas secundárias
        # vive aqui, onde há espaço, em vez de no overlay apertado do vídeo. Acompanha
        # o vídeo (a fala atual fica destacada e faz auto-scroll). ──
        sft = QWidget(); sfl = QVBoxLayout(sft); sfl.setContentsMargins(6, 6, 6, 6); sfl.setSpacing(4)
        sf_hint = QLabel(T("subs_feed_hint")); sf_hint.setWordWrap(True)
        sf_hint.setStyleSheet(f"color:{TMT};font-size:10px;background:transparent;")
        sfl.addWidget(sf_hint)
        self.sf_scroll = QScrollArea(); self.sf_scroll.setWidgetResizable(True)
        self.sf_scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollBar:vertical{{background:transparent;width:8px;}}"
            f"QScrollBar::handle:vertical{{background:{BRD};border-radius:4px;min-height:24px;}}")
        self.sf_inner = QWidget(); self.sf_inner.setStyleSheet("background:transparent;")
        self.sf_lo = QVBoxLayout(self.sf_inner); self.sf_lo.setContentsMargins(0, 0, 0, 0); self.sf_lo.setSpacing(4)
        self.sf_empty = QLabel(T("subs_feed_empty")); self.sf_empty.setWordWrap(True)
        self.sf_empty.setAlignment(Qt.AlignTop)
        self.sf_empty.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;padding:14px 6px;")
        self.sf_lo.addWidget(self.sf_empty)
        self.sf_lo.addStretch(1)
        self.sf_scroll.setWidget(self.sf_inner)
        sfl.addWidget(self.sf_scroll, 1)
        self._sf_rows = {}   # idx -> QLabel da fala (para destacar/atualizar)
        tabs.addTab(sft, T("tab_subs"))

        # (Aba "Notas" removida — bloco de notas manual fora do espírito "a IA trata".)

        # Playlist
        pwt = QWidget(); pwl = QVBoxLayout(pwt); pwl.setContentsMargins(6,6,6,6)
        phl2 = QHBoxLayout()
        phl2.addWidget(QLabel(T("tab_playlist"))); phl2.itemAt(0).widget().setStyleSheet(f"color:{TXT};font-size:11px;font-weight:bold;background:transparent;")
        phl2.addStretch()
        pcl = yt_btn(T("pl_clear"), small=True); pcl.clicked.connect(self._clr_pl); phl2.addWidget(pcl)
        pwl.addLayout(phl2)
        self.plw = QListWidget()
        self.plw.setDragDropMode(QListWidget.InternalMove)
        self.plw.setStyleSheet(f"QListWidget{{background:transparent;border:none;color:{TXT};font-size:11px;}}QListWidget::item{{padding:4px 6px;border-radius:3px;border-bottom:1px solid {BRD};}}QListWidget::item:hover{{background:{HVR};}}QListWidget::item:selected{{background:rgba(139,92,246,0.3);}}")
        self.plw.currentRowChanged.connect(self._pl_row)
        _list_show_full(self.plw)   # nome do ficheiro inteiro (sem cortar)
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
        # ── Lembretes de revisão ──
        rem_lbl = QLabel(T("reminders_label")); rem_lbl.setStyleSheet(f"color:{TMT};font-size:10px;font-weight:600;background:transparent;margin-top:8px;")
        tl.addWidget(rem_lbl)
        self.rem_check = QCheckBox(T("reminders_label"))
        self.rem_check.setChecked(self.reminder.enabled)
        self.rem_check.setCursor(Qt.PointingHandCursor)
        self.rem_check.setStyleSheet(
            f"QCheckBox{{color:{TXT};font-size:11px;background:transparent;spacing:6px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;border:1px solid {BRD};border-radius:4px;background:{ELV};}}"
            f"QCheckBox::indicator:checked{{background:{ACC};border-color:{ACC};}}")
        self.rem_check.toggled.connect(self._toggle_reminders)
        tl.addWidget(self.rem_check)
        rem_row = QHBoxLayout(); rem_row.setContentsMargins(0,0,0,0); rem_row.setSpacing(6)
        rem_every = QLabel(T("reminder_every")); rem_every.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        rem_row.addWidget(rem_every)
        self.rem_spin = QSpinBox(); self.rem_spin.setRange(5, 240); self.rem_spin.setSingleStep(5)
        self.rem_spin.setValue(self.reminder.interval_min)
        self.rem_spin.setSuffix(" " + T("reminder_min"))
        self.rem_spin.setStyleSheet(
            f"QSpinBox{{background:{ELV};color:{TXT};border:1px solid {BRD};border-radius:6px;padding:3px 6px;font-size:11px;}}"
            f"QSpinBox:hover{{border-color:{ACC};}}")
        self.rem_spin.valueChanged.connect(self.reminder.set_interval)
        rem_row.addWidget(self.rem_spin); rem_row.addStretch()
        tl.addLayout(rem_row)
        rem_hint = QLabel(T("reminder_hint")); rem_hint.setWordWrap(True)
        rem_hint.setStyleSheet(f"color:{TMT};font-size:9px;background:transparent;margin-bottom:4px;")
        tl.addWidget(rem_hint)
        # Só o essencial para um utilizador normal: exportar o que estudou, procurar
        # atualizações e "Sobre". (A chave de visão e a pasta de dados eram opções
        # técnicas/de programador que confundiam — saíram daqui.)
        for txt, cb in [(T("tools_export"), self._export), (T("tools_updates"), self._check_upd), (T("tools_about"), self._about)]:
            b = yt_btn(txt, small=True); b.clicked.connect(cb); tl.addWidget(b)
        tl.addStretch()
        tabs.addTab(tw, T("tab_tools"))

        tcl.addWidget(tabs)
        twl.addWidget(self._tools_content)
        left_lo.addWidget(self.tools_wrap)
        
        # ── Right: Chat ──
        self.chat = ChatPanel(self)
        self.chat.speak_requested.connect(self._speak_sub_slow)
        self.chat.user_sent.connect(self._on_chat_user_sent)
        self.chat.setMinimumWidth(300)
        # Floating word-details panel (click an underlined subtitle word)
        self.word_details = WordDetailsPanel(self, self.chat)
        self.overlay.word_clicked.connect(self.word_details.show_for)
        # Ao mostrar os detalhes com um exercício já aberto, repartir a coluna em 2.
        self.overlay.word_clicked.connect(lambda *_: self._balance_left_dock())
        self.chat.setMaximumWidth(420)
        # Aba Pronúncia — ouvir a legenda atual em várias velocidades (voz natural)
        self.pron_panel = PronunciationPanel(self)

        # ── Sidebar ESQUERDA (encaixada): exercícios + detalhes da palavra + pronúncia.
        # Antes os exercícios eram popups modais por cima das legendas; agora encaixam
        # aqui. Quando há mais do que um painel aberto (ex.: exercício + detalhes), o
        # QSplitter vertical DIVIDE a coluna em 2 (em cima/baixo). Cada painel esconde-se
        # sozinho; o splitter ignora os escondidos, por isso colapsa quando está vazio.
        self.ex_host = QWidget()
        self.ex_host.setStyleSheet(f"background:{BG};border-right:1px solid {BRD};")
        self.ex_host.setMinimumWidth(300)
        self.ex_host_lo = QVBoxLayout(self.ex_host)
        self.ex_host_lo.setContentsMargins(0, 0, 0, 0); self.ex_host_lo.setSpacing(0)
        self.ex_host.hide()
        self._ex_current = None

        self.left_dock = QSplitter(Qt.Vertical)
        self.left_dock.setChildrenCollapsible(False)
        self.left_dock.setHandleWidth(4)
        self.left_dock.setStyleSheet(
            f"QSplitter::handle{{background:{BRD};}}QSplitter::handle:hover{{background:{ACC};}}")
        self.left_dock.setMaximumWidth(340)   # sidebar estreita, não rouba o vídeo
        self.left_dock.addWidget(self.ex_host)
        self.left_dock.addWidget(self.word_details)
        self.left_dock.addWidget(self.pron_panel)

        body_lo.addWidget(self.left_dock)
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
    def _tree_global_rect(self, widget):
        """Global rect of a widget by WALKING THE WIDGET TREE (pure parent-
        relative arithmetic). NEVER use mapToGlobal() on the engine or anything
        near it: VLC's set_hwnd() makes the engine a NATIVE child widget, and
        Qt's native-child mapToGlobal DOUBLE-COUNTS the window position — that
        glued the subtitle overlay to the screen's bottom-right corner whenever
        the window wasn't at (0,0) (i.e. any mode other than fullscreen)."""
        off_x = off_y = 0
        wdg = widget
        while wdg is not None and wdg is not self:
            off_x += wdg.x(); off_y += wdg.y()
            wdg = wdg.parentWidget()
        g = self.geometry()   # top-level client geometry — global coords, reliable
        return (g.x() + off_x, g.y() + off_y, widget.width(), widget.height())

    def _engine_global_rect(self):
        """TRUE global rect of the video area. The engine widget itself can keep
        a STALE size after window resizes (Qt sometimes fails to re-apply layout
        geometry to the VLC-owned native HWND), overlapping the bars below it.
        The seek bar is a normal (alien) widget with reliable geometry and sits
        immediately under the video — so its top edge is the video's true bottom.
        When they disagree we also FORCE the engine back into its real slot, so
        VLC renders the picture at the right size too.

        When the transport is floating (fullscreen), the seek_bar is reparented
        to the overlay (it floats OVER the video, not below it), so we skip
        the seek-bar correction and rely on the engine widget's own rect."""
        ex, ey, ew, eh = self._tree_global_rect(self.engine)
        # Skip seek-bar correction when floating — the bar is no longer under
        # the video, so sy - ey would be meaningless or negative.
        if not getattr(self, '_transport_floating', False):
            sb = getattr(self, "_seek_bar_w", None)
            if sb is not None and sb.isVisible() and sb.window() is self:
                sx, sy, sw, sh = self._tree_global_rect(sb)
                true_h = sy - ey
                true_w = sw                       # same column as the video
                if true_h >= 60:
                    # Heal the stale native HWND if the OS-level rect disagrees with
                    # the layout slot. Qt's resize() does not reach the VLC-owned
                    # window (its cached geometry stays stale too), so compare with
                    # GetWindowRect and apply via MoveWindow in the native parent's
                    # client coordinates.
                    try:
                        import ctypes
                        from ctypes import wintypes
                        hwnd = int(self.engine.winId())
                        cur = wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(cur))
                        cw_, ch_ = cur.right - cur.left, cur.bottom - cur.top
                        if (abs(cur.left - ex) > 2 or abs(cur.top - ey) > 2
                                or abs(cw_ - true_w) > 2 or abs(ch_ - true_h) > 2):
                            parent = ctypes.windll.user32.GetParent(hwnd)
                            pt = wintypes.POINT(ex, ey)
                            if parent:
                                ctypes.windll.user32.ScreenToClient(parent, ctypes.byref(pt))
                            ctypes.windll.user32.MoveWindow(hwnd, pt.x, pt.y,
                                                    true_w, true_h, True)
                            log(f"ENGINE HEAL: ({cur.left},{cur.top}) {cw_}x{ch_} -> ({ex},{ey}) {true_w}x{true_h}")
                    except Exception as e:
                        log(f"engine heal: {e}")
                    eh, ew = true_h, true_w
        return (ex, ey, ew, eh)

    def _reposition_overlay(self):
        if hasattr(self, 'engine') and hasattr(self, 'overlay') and self._overlay_shown:
            self.overlay._engine = self.engine   # keep _video_rect() in sync
            new = self._engine_global_rect()
            self.overlay.setGeometry(*new)
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
                gui_call(self._reposition_overlay)

    # ── Toggles ──
    def _toggle_chat(self, visible):
        self.chat.setVisible(visible)
        if visible:
            fade_in(self.chat, 200)
        # Keep the controls-bar chat toggle in sync (top-bar toggle foi removido).
        if hasattr(self, 'chat_btn'): self.chat_btn.setChecked(visible)

    def _toggle_bottom(self):
        """Collapse/expand the bottom section: nav_bar, ex_bar, tools, seek and controls.
        The tools header (with toggle button and label) stays visible as a handle."""
        self._tools_collapsed = not self._tools_collapsed
        for name in ('nav_bar', 'ex_bar'):
            w = self.findChild(QWidget, name)
            if w: w.setVisible(not self._tools_collapsed)
        if hasattr(self, '_tools_content'):
            self._tools_content.setVisible(not self._tools_collapsed)
        if hasattr(self, 'tools_toggle'):
            self.tools_toggle.setText("\u25b8" if self._tools_collapsed else "\u25be")
        if hasattr(self, '_tools_hdr_lbl'):
            self._tools_hdr_lbl.setText(T("tools_expand") if self._tools_collapsed else T("tools_collapse"))
        # Also collapse seek bar and controls bar — the "groove de controle"
        # should appear/disappear together with the buttons.
        for name in ('seek_bar', 'controls_bar'):
            w = self.findChild(QWidget, name)
            if w: w.setVisible(not self._tools_collapsed)

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
            # Hide the chrome that has no place in fullscreen. As barras de
            # navegação/exercícios também SAEM aqui: ficavam encaixadas na coluna
            # do vídeo, por isso mostrá-las/escondê-las ao mexer o cursor encolhia
            # e voltava a esticar o vídeo (o "salto" de que o user se queixava). Em
            # ecrã inteiro o transporte flutuante chega; o vídeo fica ESTÁTICO.
            for name in ["top_bar", "practice_bar", "nav_bar", "ex_bar"]:
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
            self._fs_cursor_timer.start()   # passa a seguir a posição do cursor
            # Re-anchor once fullscreen geometry settles (it applies asynchronously).
            QTimer.singleShot(80, self._reposition_transport)
        else:
            self._exit_study_mode()

    def _exit_study_mode(self):
        """Restore normal UI"""
        self._study_mode = False
        self._fs_hide_timer.stop()
        self._fs_cursor_timer.stop()
        self.setWindowState(Qt.WindowNoState)
        self._float_transport(False)   # dock seek + controls back into the layout
        for name in ["top_bar", "practice_bar"]:
            w = self.findChild(QWidget, name)
            if w: w.show()
        self.tools_wrap.show()
        # Restore nav_bar and ex_bar respecting the collapse state
        collapsed = getattr(self, '_tools_collapsed', False)
        for name in ('nav_bar', 'ex_bar'):
            w = self.findChild(QWidget, name)
            if w: w.setVisible(not collapsed)
        self.statusBar().show()
        self.fs_btn.setText("\u26F6")
        self.fs_btn.setToolTip(T("fullscreen_f"))
        self.sbl.setText(T("ready"))

    # \u2500\u2500 Floating transport (fullscreen) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    def _ensure_transport_overlay(self):
        """Lazily build the frameless window that hosts the seek + controls bars
        over the bottom of the video in study mode. The groove is draggable:
        double-click and drag anywhere on the background to reposition it.
        The position persists until the user moves it again or closes the app."""
        if getattr(self, "_transport_overlay", None) is None:
            ov = QWidget(self)
            ov.setObjectName("transport_overlay")
            ov.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
            ov.setAttribute(Qt.WA_ShowWithoutActivating)
            ov.setStyleSheet("#transport_overlay{background:#0c0c0c;border-radius:14px;}")
            ov.setWindowOpacity(self._transport_opacity)
            ov.setMouseTracking(True)
            self._transport_custom_pos = None  # persists across fullscreen toggles
            # Drag support: double-click to grab, drag to move, release to drop
            ov._drag_pos = None
            def _mdc(e):
                """Double-click starts drag mode — cursor changes to grabbing hand."""
                if e.button() == Qt.LeftButton:
                    ov._drag_pos = e.globalPos() - ov.frameGeometry().topLeft()
                    ov.setCursor(Qt.ClosedHandCursor)
                    e.accept()
            def _mm(e):
                # Any mouse movement over the groove keeps it alive (restarts hide timer)
                self._fs_activity()
                if ov._drag_pos is not None:
                    ov.move(e.globalPos() - ov._drag_pos)
                    e.accept()
            def _mr(e):
                if ov._drag_pos is not None:
                    ov._drag_pos = None
                    ov.setCursor(Qt.ArrowCursor)
                    # Save the position so it persists across fullscreen toggles
                    self._transport_custom_pos = (ov.x(), ov.y())
                    e.accept()
            ov.mouseDoubleClickEvent = _mdc
            ov.mouseMoveEvent = _mm
            ov.mouseReleaseEvent = _mr
            # Clique-direito no transport → mudar opacidade.
            ov.setContextMenuPolicy(Qt.CustomContextMenu)
            ov.customContextMenuRequested.connect(self._transport_menu)
            lo = QVBoxLayout(ov); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)
            self._transport_overlay = ov
            self._transport_lo = lo
        return self._transport_overlay

    def _transport_menu(self, _pos):
        """Menu de opacidade do transport flutuante (clique-direito)."""
        from PyQt5.QtWidgets import QMenu
        ov = getattr(self, "_transport_overlay", None)
        if not ov:
            return
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};}}"
                        f"QMenu::item:selected{{background:{ACC};color:{ON_ACC};}}")
        for label, val in [("Opaco (100%)", 1.0), ("90%", 0.9), ("75%", 0.75),
                           ("60%", 0.6), ("Discreto (45%)", 0.45)]:
            act = m.addAction(("● " if abs(val - self._transport_opacity) < 0.02 else "   ") + label)
            act.triggered.connect(lambda _=False, v=val: self._set_transport_opacity(v))
        m.exec_(ov.mapToGlobal(_pos))

    def _set_transport_opacity(self, val):
        self._transport_opacity = val
        ov = getattr(self, "_transport_overlay", None)
        if ov:
            ov.setWindowOpacity(val)

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
        """Anchor the floating transport. If the user has dragged it to a custom
        position (via double-click + drag), use that instead of the auto-anchor.
        The custom position persists across fullscreen toggles."""
        ov = getattr(self, "_transport_overlay", None)
        if not ov or not ov.isVisible() or not hasattr(self, "engine"):
            return
        # If user placed the groove manually, keep it there
        cp = getattr(self, '_transport_custom_pos', None)
        if cp is not None:
            ov.move(cp[0], cp[1])
            return
        h = 90  # seek (34) + controls (56)
        gx, gy, gw, gh = self._engine_global_rect()   # never engine.mapToGlobal (native child)
        # Pill centrado em vez de ocupar a largura toda — "não tão comprido" e deixa
        # ver mais do vídeo nos lados. Margem inferior pequena para flutuar.
        pw = max(420, min(gw - 24, int(gw * 0.62)))
        px = gx + (gw - pw) // 2
        py = gy + gh - h - 10
        ov.setGeometry(px, py, pw, h)
        ov.setWindowOpacity(self._transport_opacity)
        ov.raise_()

    def _fs_cursor_poll(self):
        """Poll do cursor (250ms) em modo estudo. SÓ se comporta como atividade
        (revela o transport + reinicia o contador) quando o cursor está na zona de
        baixo do vídeo. Se o cursor estiver longe, NÃO faz nada — deixa o contador
        de auto-ocultar expirar. Antes, este poll chamava _fs_activity sempre que o
        transport estava visível e reiniciava o contador a cada 250ms, por isso o
        groove NUNCA desaparecia."""
        if not self._study_mode:
            return
        ov = getattr(self, "_transport_overlay", None)
        if not ov:
            return
        overlay = getattr(self, 'overlay', None)
        if overlay and overlay.isVisible():
            orect = overlay.geometry()
            orect_g = QRect(overlay.mapToGlobal(orect.topLeft()), orect.size())
            if QCursor.pos().y() >= orect_g.bottom() - 160:
                self._fs_activity()   # cursor na zona de baixo → revela/mantém o groove

    def _fs_activity(self):
        """Mouse/keyboard activity in fullscreen: reveal the transport when
        the cursor approaches the bottom ~80px of the video, and restart
        the inactivity countdown. If the transport is already visible it
        stays up regardless of cursor position."""
        if not self._study_mode:
            return
        ov = getattr(self, "_transport_overlay", None)
        if not ov:
            return
        # If the transport is not visible yet, only show when cursor is
        # near the bottom of the video (the groove zone). Use global
        # cursor position so it works even when the mouse is over the
        # letterbox area outside the video overlay.
        if not ov.isVisible():
            overlay = getattr(self, 'overlay', None)
            if overlay and overlay.isVisible():
                orect = overlay.geometry()
                orect_g = QRect(overlay.mapToGlobal(orect.topLeft()), orect.size())
                cursor_y = QCursor.pos().y()
                # Zona de revelação generosa (~160px) para o groove aparecer logo que
                # o cursor desce para onde os botões estão — antes (80px) era preciso
                # ir mesmo ao fundo e "não aparecia claro".
                if cursor_y < orect_g.bottom() - 160:
                    return  # cursor too high — keep the groove hidden
            ov.show()
            self._reposition_transport()
        else:
            ov.raise_()
        # NÃO tocar em nav_bar/ex_bar aqui: estão escondidas em ecrã inteiro e
        # mostrá-las reflui a coluna do vídeo (fazia o vídeo saltar). O transporte
        # flutuante (seek + controlos) é o único que aparece, POR CIMA do vídeo.
        self._fs_hide_timer.start()

    def _fs_hide_controls(self):
        if not self._study_mode:
            return
        ov = getattr(self, "_transport_overlay", None)
        # Keep it up while the pointer is over the controls themselves.
        if ov:
            if ov.underMouse():
                self._fs_hide_timer.start()
                return
            # Also check by geometry: if cursor is within or near the groove
            # bounds, keep it visible (underMouse can be unreliable for
            # Qt.Tool windows).
            og = ov.geometry()
            og_g = QRect(ov.mapToGlobal(og.topLeft()), og.size())
            cp = QCursor.pos()
            margin = 20  # px tolerance around the groove
            if (og_g.left() - margin <= cp.x() <= og_g.right() + margin and
                    og_g.top() - margin <= cp.y() <= og_g.bottom() + margin):
                self._fs_hide_timer.start()
                return
            ov.hide()
        # nav_bar/ex_bar ficam escondidas em ecrã inteiro — não há nada a esconder
        # aqui (e mexer-lhes faria o vídeo saltar).

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
            gui_call(lambda: self._on_lang_translated(code, ok))
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

    def _feed_expr_miner(self, text):
        """Mantém o minerador de expressões alinhado com o filme: garante que o guião
        atual está carregado e processa o bloco da legenda atual + o seguinte (a IA
        'relê à medida que o filme avança')."""
        try:
            subs = getattr(self.engine, "_subs", None)
            if not subs:
                return
            self._expr_miner.set_cues([s.text for s in subs])
            self._expr_miner.ensure_for_index(getattr(self.engine, "_last_sub_idx", 0))
        except Exception as e:
            log(f"feed expr miner: {e}")

    # ── Vocab overlay ──
    def _on_overlay_add(self, text):
        """+ on a subtitle card → save to the SEPARATE video-vocab list (Vídeos tab)
        AND push to the cloud as PENDING (saved_words) so it shows on the web, where
        the user opts in (Add to vocabulary) or discards. NOT the main vocabulary.

        UX estilo web: feedback OTIMISTA imediato — uma pílula animada "A adicionar
        “palavra”…" aparece já, e o trabalho real corre deferido (60ms) para a pílula
        pintar primeiro; depois a pílula vira "Adicionado · <onde>"."""
        text = (text or "").strip()
        if not text:
            return
        pill = self._show_pill(T("adding_word", text=text[:24]), "accent")
        QTimer.singleShot(60, lambda: self._do_save_vocab(text, pill))

    def _do_save_vocab(self, text, pill=None):
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
            where = T("saved_videos_web") if synced else T("saved_videos")
            # Pílula → estado final "Adicionado"; em fullscreen a status-bar está
            # escondida, por isso também faz flash do banner sobre o vídeo.
            self._update_pill(pill, T("added_word", where=where), "ok")
            if self._study_mode:
                self.overlay.flash(T("saved_flash", where=where))
            if not self._study_mode and self.tools_wrap.isVisible():
                idx = self._vv_tab_index()
                if idx is not None:
                    self.tabs.setCurrentIndex(idx)
        except Exception as e:
            log(f"save vocab: {e}")
            self._update_pill(pill, T("saved_videos"), "ok")

    # ── Pílula de feedback animada (estilo web: aparece, sobe e desvanece) ──
    def _show_pill(self, text, kind="accent"):
        """Cria uma pílula flutuante no topo-centro da janela, com fade+subida."""
        try:
            color = "#3CB45A" if kind == "ok" else ACC
            pill = QLabel(text, self)
            pill.setStyleSheet(
                f"background:{ELV};color:{TXT};border:1px solid {color};border-radius:16px;"
                f"padding:8px 16px;font-size:12px;font-weight:600;"
                f"font-family:'Inter','Segoe UI',sans-serif;")
            pill.adjustSize()
            self._position_pill(pill)
            pill.show(); pill.raise_()
            eff = QGraphicsOpacityEffect(pill); pill.setGraphicsEffect(eff)
            a = QPropertyAnimation(eff, b"opacity", pill)
            a.setDuration(180); a.setStartValue(0.0); a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.OutCubic); a.start()
            pill._anim = a            # manter referência viva
            return pill
        except Exception as e:
            log(f"pill: {e}"); return None

    def _position_pill(self, pill):
        try:
            pill.adjustSize()
            x = max(8, (self.width() - pill.width()) // 2)
            pill.move(x, 18)
        except RuntimeError:
            pass

    def _update_pill(self, pill, text, kind="ok", hold=1700):
        """Atualiza a pílula para o estado final e agenda o desvanecimento."""
        if pill is None:
            self._show_pill(text, kind); return
        try:
            color = "#3CB45A" if kind == "ok" else ACC
            pill.setText(text)
            pill.setStyleSheet(
                f"background:{ELV};color:{TXT};border:1px solid {color};border-radius:16px;"
                f"padding:8px 16px;font-size:12px;font-weight:600;"
                f"font-family:'Inter','Segoe UI',sans-serif;")
            self._position_pill(pill)
            QTimer.singleShot(hold, lambda: self._fade_out_pill(pill))
        except RuntimeError:
            pass

    def _fade_out_pill(self, pill):
        try:
            eff = QGraphicsOpacityEffect(pill); pill.setGraphicsEffect(eff)
            a = QPropertyAnimation(eff, b"opacity", pill)
            a.setDuration(300); a.setStartValue(1.0); a.setEndValue(0.0)
            a.setEasingCurve(QEasingCurve.InCubic)
            a.finished.connect(pill.deleteLater); a.start()
            pill._anim = a
        except RuntimeError:
            pass

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
        flt = (getattr(self, "_vv_filter", "") or "").strip().lower()
        # Pares (índice_original, entrada), do mais recente para o mais antigo, já
        # filtrados pela pesquisa (palavra OU nome do filme).
        shown = []
        for i in range(len(self._vv_entries) - 1, -1, -1):
            e = self._vv_entries[i]
            if flt:
                hay = (str(e.get("text", "")) + " " + str(e.get("video", ""))).lower()
                if flt not in hay:
                    continue
            shown.append((i, e))
        if not shown:
            empty = QListWidgetItem(T("videos_no_match") if flt else T("videos_empty"))
            empty.setFlags(Qt.NoItemFlags)   # not selectable — it's a hint
            empty.setForeground(QColor(TMT))
            self.vv_list.addItem(empty)
        for orig_idx, e in shown:
            vid = e.get("video", ""); txt = e.get("text", "")
            it = QListWidgetItem()
            it.setData(Qt.UserRole, orig_idx)   # mapeia a linha → entrada real (robusto com filtro)
            self.vv_list.addItem(it)
            # Linha = texto (clicar na linha abre o filme de origem) + botão Chat.
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row); rl.setContentsMargins(2, 1, 2, 1); rl.setSpacing(6)
            lbl = QLabel(self._vocab_html(txt, vid))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)  # deixa a LISTA tratar clique/right-click
            lbl.setStyleSheet("background:transparent;font-size:11px;padding:1px 2px;")
            rl.addWidget(lbl, 1)
            # Botão "colocar no chat" (ícone de balão Segoe MDL2, sem emojis).
            chat_b = QPushButton(chr(0xE8BD)); chat_b.setFixedSize(26, 26)
            chat_b.setCursor(Qt.PointingHandCursor); chat_b.setToolTip(T("videos_to_chat"))
            chat_b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};border:1px solid {BRD};border-radius:13px;"
                f"font-family:'Segoe Fluent Icons','Segoe MDL2 Assets';font-size:12px;}}"
                f"QPushButton:hover{{border-color:{ACC};color:{TXT};background:{HVR};}}")
            chat_b.clicked.connect(lambda _=False, t=txt: self._on_overlay_ask(t))
            rl.addWidget(chat_b, 0, Qt.AlignTop)
            self.vv_list.setItemWidget(it, row)
            it.setSizeHint(row.sizeHint())
        n = len(self._vv_entries)
        self.vv_title.setText(f"{T('videos_vocab_title')} ({n})" if n else T("videos_vocab_title"))

    def _vv_search_changed(self, txt):
        self._vv_filter = txt or ""
        self._load_video_vocab()

    def _open_add_word(self, prefill=""):
        """Abre o diálogo de personalização (palavra + tradução + nota) que cai na
        conta web. Ponto de entrada manual a partir da aba Vídeos e dos Detalhes."""
        if not hasattr(self, "chat"):
            return
        dlg = AddWordDialog(self, self.chat, prefill=prefill if isinstance(prefill, str) else "")
        dlg.exec_()

    def _vv_entry_at(self, it):
        """Entrada (dict) por trás de um item da lista Vídeos, via UserRole."""
        if not it:
            return None
        idx = it.data(Qt.UserRole)
        if idx is None or not (0 <= int(idx) < len(self._vv_entries)):
            return None
        return self._vv_entries[int(idx)]

    def _vv_clicked(self, it):
        """Clique simples numa palavra guardada → abre o FILME de onde veio e repete
        a fala (pedido do user). Se não houver filme guardado, mostra os Detalhes."""
        entry = self._vv_entry_at(it)
        if not entry:
            return
        if entry.get("video"):
            self._vv_open_source(entry)
        else:
            word = (entry.get("text", "") or "").strip()
            if word and hasattr(self, "word_details"):
                self.word_details.show_for(word)
                self._balance_left_dock()

    def _vv_open_source(self, entry):
        """Abre o filme de onde a palavra foi tirada (se o ficheiro for encontrado)
        e procura a primeira fala que a contém para repetir aí."""
        name = (entry or {}).get("video", "")
        if not name:
            self._notify(T("videos_no_source")); return
        # Já está aberto? então é só procurar a fala.
        cur = Path(self.video_path).name if self.video_path else ""
        path = None
        if cur == name:
            path = self.video_path
        else:
            # Procura o ficheiro: na playlist e na pasta do vídeo atual.
            cands = list(self._playlist)
            if self.video_path:
                cands += [str(p) for p in Path(self.video_path).parent.glob(name)]
            for c in cands:
                if Path(c).name == name and Path(c).exists():
                    path = c; break
        if not path:
            self._notify(T("videos_source_missing", name=name)); return
        word = (entry.get("text", "") or "").strip()
        def _seek_to_word():
            try:
                subs = self.engine._subs or []
                wl = word.lower()
                for s in subs:
                    if wl and wl in s.text.lower():
                        self.engine.seek(max(0, s.start - 0.3)); self.engine.play()
                        self._notify(T("videos_replaying", word=word[:24])); return
            except Exception as e:
                log(f"vv open source seek: {e}")
        if path == self.video_path:
            _seek_to_word()
        else:
            self._open_file(path)
            QTimer.singleShot(1500, _seek_to_word)   # dá tempo a carregar o vídeo+legenda

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
        idx = it.data(Qt.UserRole)   # índice real (robusto mesmo com pesquisa a filtrar)
        if idx is None or not (0 <= int(idx) < len(self._vv_entries)):
            return
        idx = int(idx)
        entry = self._vv_entries[idx]
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};padding:4px;}}"
                        f"QMenu::item{{padding:6px 14px;border-radius:4px;}}QMenu::item:selected{{background:{HVR};}}")
        a_det = m.addAction(T("details"))
        a_ask = m.addAction(T("ask_ai"))
        a_src = m.addAction(T("videos_open_source")) if entry.get("video") else None
        a_add = m.addAction(T("menu_add_vocab"))
        m.addSeparator()
        a_del = m.addAction(T("menu_remove"))
        chosen = m.exec_(self.vv_list.mapToGlobal(pos))
        if chosen == a_det:
            word = (entry.get("text", "") or "").strip()
            if word and hasattr(self, "word_details"):
                self.word_details.show_for(word); self._balance_left_dock()
        elif chosen == a_del:
            try:
                del self._vv_entries[idx]
                (DATA_DIR / 'saved-vocab.json').write_text(
                    json.dumps(self._vv_entries, indent=2, ensure_ascii=False), encoding='utf-8')
            except Exception as e:
                log(f"remove vocab: {e}")
            self._load_video_vocab()
        elif chosen == a_ask:
            self._on_overlay_ask(entry.get("text", ""))
        elif a_src is not None and chosen == a_src:
            self._vv_open_source(entry)
        elif chosen == a_add and hasattr(self, 'chat'):
            self._toggle_chat(True)
            self.chat.promote_word(entry.get("text", ""))

    def _on_overlay_ask(self, text):
        """Called when user clicks the chat icon on a vocab overlay, or clicks
        an underlined word in a subtitle/Twitch card. Sends the text DIRECTLY
        to Chat IA as a query, not just fills the input box."""
        if hasattr(self, 'chat') and text:
            # Send directly as a chat message, not just filling the input
            self.chat._add_msg(text, "user")
            self.chat._messages.append({"role": "user", "content": text})
            if len(self.chat._messages) > 20:
                self.chat._messages = self.chat._messages[-20:]
            self.chat._call_ai(text)
            self.chat.welcome.hide()
            # Make sure chat is visible
            self._toggle_chat(True)

    def _remember_last_sub(self, text):
        """Guarda a última legenda NÃO vazia — fonte da aba Pronúncia.
        (Renomeado de _remember_sub: havia DOIS métodos com esse nome e o de 2 args
        sobrepunha este, causando TypeError no sinal subtitle_changed → crash sob
        pythonw, que não tem stderr para 'engolir' a exceção.)"""
        if text and text.strip():
            self._cur_sub = text.strip()

    def _content_lang(self):
        """Língua do filme/legenda = língua-alvo da conta, senão inglês."""
        tgt = getattr(getattr(self, "chat", None), "_user_target", "") or ""
        return (tgt[:2] or "en")

    def _open_pronunciation(self):
        """Abre a aba Pronúncia para a legenda atual (não pausa o filme)."""
        self.word_details.hide()
        self.pron_panel.show_for(self._cur_sub, self._content_lang())
        self._balance_left_dock()

    def _speak_slow(self, text):
        """Diz um texto (frase de cartão Twitch ou legenda) devagar, com voz neural
        natural, na língua do filme. Usado pelo botão ♪ dos cartões e pelo chat."""
        SLOW_TTS.speak(text, self._content_lang(), rate=-10)

    def _speak_sub_slow(self, text=""):
        """Pedido vindo do chat: ouvir uma legenda devagar. Usa o texto enviado; se
        vazio, recorre à legenda atual do filme."""
        line = (text or "").strip() or (self._cur_sub or self.engine._last_sub or "")
        if line:
            SLOW_TTS.speak(line, self._content_lang(), rate=-10)
        else:
            self._notify(T("need_sub_for_tool"))

    # ── Language-learning practice toggles (buttons + keyboard share these) ──
    def _toggle_loop(self):
        was_on = self.engine._loop is not None
        on = self.engine.toggle_loop()
        self.overlay._loop_active = on; self.overlay.update()
        if not on: self.seek.clear_marks()
        if hasattr(self, 'btn_loop'): self.btn_loop.setChecked(on)
        if on:
            self._notify(T("loop_on"))
        elif was_on:
            self._notify(T("loop_off"))
        elif not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool"))
        else:
            self._notify(T("loop_no_line"))

    def _set_loop_a(self):
        if not self.video_path:
            showToast(T("open_first"), "accent"); return
        a = self.engine.set_loop_a()
        self.seek.set_mark('A', a); self.seek.set_mark('B', None)
        showToast(T("loop_a_marked", t=FMT(a)), "accent")

    def _set_loop_b(self):
        lp = self.engine.set_loop_b()
        if lp:
            self.overlay._loop_active = True; self.overlay.update()
            self.seek.set_mark('A', lp[0]); self.seek.set_mark('B', lp[1])
            if hasattr(self, 'btn_loop'): self.btn_loop.setChecked(True)
            showToast(T("loop_ab_active", a=FMT(lp[0]), b=FMT(lp[1])), "accent")
        else:
            showToast(T("loop_mark_a"), "accent")

    def _toggle_autopause(self):
        # These tools only do something with a subtitle loaded — otherwise the button
        # looks dead. Guide the user to load one instead of silently doing nothing.
        if not self.engine.subs_loaded():
            if hasattr(self, 'btn_ap'): self.btn_ap.setChecked(False)
            self._notify(T("need_sub_for_tool")); return
        self._autopause_on = not getattr(self, '_autopause_on', False)
        self.engine.set_autopause(self._autopause_on)
        if hasattr(self, 'btn_ap'): self.btn_ap.setChecked(self._autopause_on)
        self._notify(T("autopause_on") if self._autopause_on else T("autopause_off"))

    def _toggle_ai_loop(self):
        if not self.engine.subs_loaded():
            if hasattr(self, 'btn_ai_loop'): self.btn_ai_loop.setChecked(False)
            self._notify(T("need_sub_for_tool")); return
        on = not self.engine._ai_loop
        self.engine.set_ai_loop(2 if on else 0)
        if hasattr(self, 'btn_ai_loop'): self.btn_ai_loop.setChecked(on)
        self.overlay._ai_loop_active = on
        self.overlay._ai_loop_remaining = 2 if on else 0
        self.overlay.update()
        if on:
            self._notify(T("ai_loop_on", n=self.engine._ai_loop_count))
        else:
            self._notify(T("ai_loop_off"))

    def _on_ai_loop(self, remaining):
        """Update overlay badge with remaining loops for current subtitle."""
        self.overlay._ai_loop_remaining = remaining
        self.overlay.update()

    def _toggle_hide_subs(self):
        if not self.engine.subs_loaded():
            if hasattr(self, 'btn_hide'): self.btn_hide.setChecked(False)
            self._notify(T("need_sub_for_tool")); return
        self.overlay._hide_subs = not self.overlay._hide_subs
        self.overlay.update()
        if hasattr(self, 'btn_hide'): self.btn_hide.setChecked(self.overlay._hide_subs)
        self._notify(T("subs_hidden") if self.overlay._hide_subs else T("subs_visible"))

    # ── Exercícios encaixados na sidebar esquerda (já não são popups por cima do vídeo) ──
    def _dock_exercise(self, w, on_close=None):
        """Encaixa um exercício (antes era um QDialog modal) na sidebar esquerda, em vez
        de o abrir por cima das legendas. Fecha qualquer exercício anterior. on_close (se
        dado) corre quando o painel fecha — usado pelas missões da IA para retomar o filme."""
        # TUDO no sidebar — nada de pop-ups por cima do vídeo (decisão do user). Se
        # estávamos em modo estudo/ecrã inteiro (sem sidebar à vista), sai dele primeiro
        # para o painel do exercício ficar visível na coluna esquerda.
        if getattr(self, "_study_mode", False) or self.isFullScreen():
            try: self._exit_study_mode()
            except Exception as e: log(f"ex exit study: {e}")
        self._close_dock_exercise()
        self._ex_current = w
        self._ex_on_close = on_close
        self.ex_host_lo.addWidget(w)
        try: w.finished.connect(self._on_ex_finished)
        except Exception: pass
        self.ex_host.show()
        w.show()
        self._balance_left_dock()

    def _on_ex_finished(self, *_a):
        self._close_dock_exercise()

    def _close_dock_exercise(self):
        w = getattr(self, "_ex_current", None)
        cb = getattr(self, "_ex_on_close", None)
        self._ex_current = None
        self._ex_on_close = None
        if w is not None:
            try: w.finished.disconnect(self._on_ex_finished)
            except Exception: pass
            try: self.ex_host_lo.removeWidget(w)
            except Exception: pass
            try: w.close()           # dispara closeEvent → cada exercício repõe o filme
            except Exception: pass
            try: w.setParent(None); w.deleteLater()
            except Exception: pass
        if hasattr(self, "ex_host"): self.ex_host.hide()
        self._balance_left_dock()
        if cb:
            try: cb()
            except Exception as e: log(f"ex on_close: {e}")

    def _balance_left_dock(self):
        """Reparte a altura da coluna esquerda pelos painéis visíveis. O exercício leva a
        maior parte; detalhes/pronúncia ficam por baixo. Os escondidos são ignorados pelo
        QSplitter, por isso quando só há um, ele ocupa a coluna toda."""
        if hasattr(self, "left_dock"):
            # ex_host, word_details, pron_panel — pesos (exercício maior).
            self.left_dock.setSizes([1400, 900, 900])

    def _open_exercise(self):
        if not self.engine.subs_loaded() or not self.engine._last_sub:
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(ExerciseDialog(self, self.engine))

    def _open_fluency(self):
        if not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(FluencyDialog(self, self.engine))

    def _open_paraphrase(self):
        if not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(ParaphraseDialog(self, self.engine))

    def _open_describe_scene(self):
        if not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(DescribeDialog(self, self.engine, mode="scene"))

    def _open_describe_take(self):
        if not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(DescribeDialog(self, self.engine, mode="take"))

    def _open_dialogue(self):
        if not self.engine.subs_loaded():
            self._notify(T("need_sub_for_tool")); return
        self._dock_exercise(DialogueDialog(self, self.engine))

    # ── Exercícios automáticos ao longo do filme (toggle) ──
    def _toggle_auto_ex(self):
        """Liga/desliga a inserção automática de exercícios à medida que o filme corre."""
        if not self.engine.subs_loaded() and not self._auto_ex:
            if hasattr(self, 'btn_auto_ex'): self.btn_auto_ex.setChecked(False)
            self._notify(T("need_sub_for_tool")); return
        self._auto_ex = not self._auto_ex
        self._auto_ex_count = 0
        if hasattr(self, 'btn_auto_ex'): self.btn_auto_ex.setChecked(self._auto_ex)
        self._notify(T("auto_ex_on") if self._auto_ex else T("auto_ex_off"))

    def _card_on_sub(self, idx):
        """Empurra a fala recém-entrada para o feed de cartões 'twitch'. Garante
        paridade total com a legenda de baixo (uma linha → um cartão)."""
        try:
            subs = self.engine._subs
            if 0 <= idx < len(subs):
                self.overlay.show_vocab(subs[idx].text)
        except Exception as e:
            log(f"card on sub: {e}")

    # ── Feed da aba "Legendas" (original + 2ª/3ª linha, sublinhadas e clicáveis) ──
    def _sf_entry_html(self, idx):
        """HTML de uma fala para o feed: tempo (salto) + original + traduções, com as
        palavras-chave sublinhadas/clicáveis (mark_html). A 2ª/3ª linha a cinzento."""
        subs = self.engine._subs
        if not (0 <= idx < len(subs)):
            return ""
        s = subs[idx]
        ts = FMT(int(s.start))
        l2, l3 = self.engine.secondary_for_index(idx)
        html = (f'<a href="lexioseek:{s.start:.2f}" style="color:{TMT};'
                f'text-decoration:none;font-size:10px;">[{ts}]</a> ')
        html += f'<span style="color:{TS2};font-size:12px;">{mark_html(s.text, subtle=True)}</span>'
        if l2:
            html += (f'<div style="color:#c8c8c8;font-size:11px;margin-top:2px;">'
                     f'{mark_html(l2, subtle=True)}</div>')
        if l3:
            html += (f'<div style="color:#9a9a9a;font-size:11px;">'
                     f'{mark_html(l3, subtle=True)}</div>')
        return html

    def _rebuild_subs_feed(self):
        """Reconstrói o feed da aba Legendas a partir das falas carregadas."""
        if not hasattr(self, 'sf_lo'):
            return
        # Evita reconstruir quando nada mudou (o _update_sub_icon é chamado várias
        # vezes): assinatura = tamanhos das 3 listas + estado da auto-tradução.
        sig = (len(self.engine._subs), len(self.engine._subs2),
               len(self.engine._subs3), bool(self.engine._auto_tr),
               tuple(self._sub_names))
        if sig == getattr(self, '_sf_sig', None):
            return
        self._sf_sig = sig
        # Limpa as linhas anteriores (mantém o stretch final).
        for lbl in self._sf_rows.values():
            lbl.setParent(None); lbl.deleteLater()
        self._sf_rows = {}
        subs = self.engine._subs
        has = len(subs) > 0
        self.sf_empty.setVisible(not has)
        if not has:
            return
        for idx in range(len(subs)):
            lbl = QLabel(self._sf_entry_html(idx))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(False)
            lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
            lbl.linkActivated.connect(self._subs_feed_link)
            lbl.setStyleSheet(
                f"QLabel{{background:{SRF};border:1px solid transparent;border-radius:8px;"
                f"padding:6px 8px;}}QLabel:hover{{background:{HVR};}}")
            # Inserir antes do stretch (último item do layout).
            self.sf_lo.insertWidget(self.sf_lo.count() - 1, lbl)
            self._sf_rows[idx] = lbl

    def _subs_feed_on_sub(self, idx):
        """Destaca a fala atual no feed e faz auto-scroll até ela. Atualiza a tradução
        da linha (caso a auto-tradução IA já tenha chegado entretanto)."""
        try:
            lbl = self._sf_rows.get(idx)
            if lbl is None:
                # Feed ainda não construído para estas legendas → constrói agora.
                if self.engine.sub_count() > 0 and not self._sf_rows:
                    self._rebuild_subs_feed()
                    lbl = self._sf_rows.get(idx)
                if lbl is None:
                    return
            # Refresca o HTML (preenche tradução que possa ter chegado da IA).
            lbl.setText(self._sf_entry_html(idx))
            # Realça a fala atual; tira o realce das outras.
            for i, w in self._sf_rows.items():
                cur = (i == idx)
                w.setStyleSheet(
                    f"QLabel{{background:{HVR if cur else SRF};"
                    f"border:1px solid {ACC if cur else 'transparent'};border-radius:8px;"
                    f"padding:6px 8px;}}QLabel:hover{{background:{HVR};}}")
            # Auto-scroll suave até à fala atual.
            self.sf_scroll.ensureWidgetVisible(lbl, 0, 40)
        except Exception as e:
            log(f"subs feed: {e}")

    def _subs_feed_link(self, href):
        """Clique no feed: tempo → salta o vídeo; palavra → abre Detalhes."""
        try:
            if href.startswith("lexioseek:"):
                self.engine.seek(float(href.split(":", 1)[1])); self.engine.play()
            elif href.startswith("lexioword:"):
                from urllib.parse import unquote
                self.word_details.show_for(unquote(href.split(":", 1)[1]))
                if hasattr(self, "_balance_left_dock"):
                    self._balance_left_dock()
        except Exception as e:
            log(f"subs feed link: {e}")

    def _auto_ex_on_sub(self, idx):
        """A cada fala ouvida (com auto-exercícios ligado), conta; ao fim de N abre o
        próximo exercício — mas nunca empilha sobre um exercício/aula/missão já aberto."""
        if not self._auto_ex:
            return
        if getattr(self, "_ex_current", None) is not None or self._in_mission or self._lesson_active:
            return
        if not self.engine.subs_loaded():
            return
        self._auto_ex_count += 1
        if self._auto_ex_count < self._auto_ex_every:
            return
        self._auto_ex_count = 0
        self._open_auto_exercise()

    def _open_auto_exercise(self):
        """Abre o próximo exercício da rotação, encaixado no sidebar. Cada exercício
        trata sozinho do pause/loop e repõe o filme ao fechar."""
        openers = [self._open_fluency, self._open_paraphrase, self._open_describe_scene,
                   self._open_dialogue, self._open_exercise, self._open_describe_take]
        fn = openers[self._auto_ex_rotation % len(openers)]
        self._auto_ex_rotation += 1
        try:
            self._notify(T("auto_ex_starting"))
            fn()
        except Exception as e:
            log(f"auto ex: {e}")

    def _toggle_listening(self):
        """Toggle listening mode: hide subs + AI asks comprehension questions."""
        if not self.engine.subs_loaded():
            if hasattr(self, 'btn_listening'): self.btn_listening.setChecked(False)
            self._notify(T("need_sub_for_tool")); return
        self._listening_mode = not self._listening_mode
        on = self._listening_mode
        if hasattr(self, 'btn_listening'): self.btn_listening.setChecked(on)
        if on:
            # Hide subs automatically, reset counters
            self.overlay._hide_subs = True
            if hasattr(self, 'btn_hide'): self.btn_hide.setChecked(True)
            self._listening_sub_count = 0
            self._listening_pending = False
            self._notify(T("listening_on"))
        else:
            self.overlay._hide_subs = False
            if hasattr(self, 'btn_hide'): self.btn_hide.setChecked(False)
            self._listening_pending = False
            self._notify(T("listening_off"))
        self.overlay.update()

    def _on_sub_exited(self, idx):
        """Called when a subtitle finishes playing. In listening mode, ask a question."""
        if not self._listening_mode or self._listening_pending:
            return
        self._listening_sub_count += 1
        if self._listening_sub_count < self._listening_interval:
            return
        self._listening_sub_count = 0
        self._listening_pending = True
        # Reouvir a fala (o áudio) em LOOP N vezes antes de perguntar — em listening
        # as legendas estão escondidas, por isso ouvir de novo ajuda a recordar o que
        # foi dito. O nº de repetições é configurável (clique-direito no botão
        # Listening). No fim do loop, pausa e faz a pergunta.
        subs = self.engine._subs
        if 0 <= idx < len(subs):
            line_text = subs[idx].text
            reps = max(1, int(getattr(self, "_listening_replays", 2)))
            self._listening_replay_loop(idx, line_text, reps)
        else:
            self._listening_pause_and_ask(self.engine._last_sub or "")

    def _listening_replay_loop(self, idx, line_text, reps_left):
        """Repete a fala `reps_left` vezes (loop) e só então pausa e pergunta."""
        if not self._listening_mode:
            self._listening_pending = False; return
        subs = self.engine._subs
        if not (0 <= idx < len(subs)):
            self._listening_pause_and_ask(line_text); return
        s = subs[idx]
        self.engine.seek(s.start)
        try: self.engine._player.play()
        except: pass
        self._notify(T("listening_replay"))
        rate = getattr(self, "_rate", 1.0) or 1.0
        dur = max(0.4, (s.end - s.start) / rate)
        if reps_left > 1:
            QTimer.singleShot(int(dur * 1000) + 200,
                              lambda: self._listening_replay_loop(idx, line_text, reps_left - 1))
        else:
            QTimer.singleShot(int(dur * 1000) + 250,
                              lambda: self._listening_pause_and_ask(line_text))

    def _listening_reps_menu(self, _pos):
        """Menu (clique-direito no Listening) para escolher quantas vezes cada fala
        se repete em loop antes da pergunta de compreensão."""
        from PyQt5.QtWidgets import QMenu
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};}}"
                        f"QMenu::item:selected{{background:{ACC};color:{ON_ACC};}}")
        cur = int(getattr(self, "_listening_replays", 2))
        for n in (1, 2, 3, 5):
            act = m.addAction(("● " if n == cur else "   ") + f"{n}×")
            act.triggered.connect(lambda _=False, v=n: self._set_listening_reps(v))
        m.exec_(self.btn_listening.mapToGlobal(_pos))

    def _set_listening_reps(self, n):
        self._listening_replays = max(1, int(n))
        self._notify(T("listening_reps_set", n=self._listening_replays))

    def _listening_pause_and_ask(self, sub):
        if not self._listening_mode:
            self._listening_pending = False; return
        try: self.engine._player.pause()
        except: pass
        self._notify(T("listening_paused"))
        if not sub:
            self._listening_pending = False; return
        self.chat._add_msg(T("listening_question"), "system")
        self._ask_listening_question(sub)

    def _ask_listening_question(self, sub):
        """Generate a listening comprehension question in the chat."""
        def work():
            try:
                from urllib.request import urlopen, Request
                nat = native_language_name()
                sys_p = (
                    f"You are a listening comprehension tutor. "
                    f"The user just heard this sentence (it was hidden): \"{sub}\".\n"
                    f"Ask ONE short question in {nat} about what was said, to test if they "
                    f"understood. Ask ONLY the question now (do not reveal the answer). "
                    f"Tell them, in {nat}, to answer in the chat and then type 'continuar' "
                    f"to resume the film. Keep it short and supportive.")
                body = json.dumps({"model": "deepseek-chat", "max_tokens": 500, "temperature": 0.4,
                    "messages": [{"role": "system", "content": sys_p}]}).encode()
                r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                    headers={"Content-Type": "application/json"}), timeout=45)
                d = json.loads(r.read().decode())
                resp = (d.get("text") or "").strip()
                gui_call(lambda: self._show_listening_q(resp))
            except Exception as e:
                log(f"listening: {e}")
                gui_call(lambda: setattr(self, '_listening_pending', False))
        threading.Thread(target=work, daemon=True).start()

    def _show_listening_q(self, text):
        q = text or T("listening_fallback_q")
        self.chat._add_msg(q, "assistant")
        # CRÍTICO: meter a pergunta no histórico do chat. Sem isto, a resposta do aluno
        # era enviada à IA SEM a pergunta → a IA não tinha contexto e "a avaliação não
        # funcionava". Agora o chat avalia a resposta com a pergunta no histórico.
        try:
            self.chat._messages.append({"role": "assistant", "content": q})
        except Exception:
            pass
        # Mantém _listening_pending=True (vídeo pausado) até o aluno escrever "continuar"
        # no chat — assim não se empilham perguntas enquanto ele responde.

    def _on_chat_user_sent(self, text):
        """Enquanto o modo Listening tem uma pergunta no ar (vídeo pausado), escrever
        'continuar'/'continue' no chat retoma o filme. Qualquer outra coisa é a resposta
        do aluno (avaliada pela IA do chat, que agora tem a pergunta no histórico)."""
        if not self._listening_mode or not self._listening_pending:
            return
        norm = (text or "").strip().lower().strip(".!? ")
        if norm in ("continuar", "continua", "continue", "próxima", "proxima", "next",
                    "seguir", "segue", "avançar", "avancar"):
            self._listening_pending = False
            self._listening_sub_count = 0
            try: self.engine.play()
            except Exception: pass
            self._notify(T("listening_resumed"))

    def _toggle_focus_mode(self):
        """Scene Agent removido — esta ação (e a tecla M) já não faz nada. Mantida só
        para não partir ligações antigas (keybinding). Os exercícios passaram a ser
        todos manuais (botões da barra de prática)."""
        return

    def _generate_auto_captions(self):
        """Generate speech-to-text captions from the video's audio track using
        faster-whisper. Creates SubEntry objects with timestamps and loads them
        into the engine, where the existing overlay colours/synchronizes them."""
        vid = self.video_path
        if not vid:
            self._notify(T("stt_no_video")); return
        self.btn_stt.setEnabled(False)
        self.btn_stt.setText(T("stt_loading"))

        def _work():
            tmp_path = None
            # Imports PESADOS (av + faster_whisper) feitos AQUI, no thread worker, e
            # protegidos: se o build não os incluir, antes a app CRASHAVA (o import
            # estava no GUI thread, fora do try). Agora avisa em vez de rebentar.
            try:
                import av, tempfile, os
                from faster_whisper import WhisperModel
            except Exception as e:
                log(f"stt indisponível: {type(e).__name__}: {e}")
                gui_call(lambda: self._stt_fail(T("stt_unavailable")))
                return
            try:
                log(f"stt: starting transcription for {vid}")
                # 1) Extract audio via PyAV → WAV temp file
                container = av.open(vid)
                audio_stream = next((s for s in container.streams if s.type == "audio"), None)
                if audio_stream is None:
                    raise RuntimeError("No audio stream in video")
                sr = audio_stream.codec_context.sample_rate or 16000
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp_path = tmp.name; tmp.close()
                # Decode audio to WAV with PyAV
                out_container = av.open(tmp_path, mode="w", format="wav")
                out_stream = out_container.add_stream("pcm_s16le", rate=16000)
                out_stream.channels = 1
                out_stream.layout = "mono"
                for frame in container.decode(audio=0):
                    frame.pts = None
                    for packet in out_stream.encode(frame):
                        out_container.mux(packet)
                for packet in out_stream.encode(None):
                    out_container.mux(packet)
                out_container.close()
                container.close()
                log(f"stt: audio extracted to {tmp_path}")

                # 2) Transcribe with faster-whisper
                model = WhisperModel("tiny", device="cpu", compute_type="int8")
                segments, info = model.transcribe(tmp_path, beam_size=5,
                    language=None, vad_filter=True)
                log(f"stt: detected lang={info.language} (p={info.language_probability:.2f})")

                # 3) Build SubEntry list from segments
                subs = []
                for seg in segments:
                    text = seg.text.strip()
                    if text:
                        subs.append(SubEntry(seg.start, seg.end, text))
                # Cleanup temp file
                try: os.unlink(tmp_path)
                except: pass
                log(f"stt: {len(subs)} subtitles generated")

                if not subs:
                    gui_call(lambda: self._stt_fail(T("stt_failed")))
                    return

                # 4) Load into engine (replaces existing subtitles)
                self.engine._subs = subs
                self.engine._played_ids = set()
                self.engine._last_sub = ""
                self.engine._last_sub_idx = -1
                self.engine.show_subtitle_reset()
                log(f"stt: loaded {len(subs)} subs into engine")

                gui_call(lambda: self._stt_done(len(subs)))
            except Exception as e:
                log(f"stt FALHOU: {type(e).__name__}: {e}")
                try: os.unlink(tmp_path)
                except: pass
                gui_call(lambda: self._stt_fail(str(e)))

        threading.Thread(target=_work, daemon=True).start()

    def _stt_done(self, count):
        """Called on STT success — restore button and notify."""
        if hasattr(self, 'btn_stt'):
            self.btn_stt.setEnabled(True)
            self.btn_stt.setText(T("stt_btn"))
        self._notify(T("stt_done", n=count))

    def _stt_fail(self, err):
        """Called on STT failure — restore button and notify."""
        if hasattr(self, 'btn_stt'):
            self.btn_stt.setEnabled(True)
            self.btn_stt.setText(T("stt_btn"))
        self._notify(str(err))

    def _segment_subs(self):
        """Call the AI to analyse subtitles and return thematic segments."""
        subs = self.engine._subs
        if not subs:
            self._notify(T("track_no_sub")); return
        if hasattr(self, 'btn_segment'):
            self.btn_segment.setEnabled(False)
            self.btn_segment.setText(T("track_loading"))
        if hasattr(self, 'tw_empty'):
            self.tw_empty.setText(T("track_loading"))
        # Build subtitle text with indices for the AI
        lines = []
        for i, s in enumerate(subs):
            ts = datetime.utcfromtimestamp(s.start).strftime('%H:%M:%S')
            te = datetime.utcfromtimestamp(s.end).strftime('%H:%M:%S')
            lines.append(f"[{i}] {ts}-{te} {s.text}")
        full = "\n".join(lines)
        # Truncate if too long (token limit)
        if len(full) > 12000:
            # Keep evenly spaced samples
            step = max(1, len(subs) // 200)
            sampled = "\n".join(full.split("\n")[::step])
            full = sampled
        n = len(subs)
        # Limite de segmentos proporcional ao tamanho (≈1 cada 4 falas), entre 6 e 30 —
        # evita JSON gigante que estoura o limite de tokens e fica truncado (= parse a
        # falhar = "não preparou nada").
        max_segs = max(6, min(30, n // 4 or 6))
        def work():
            try:
                from urllib.request import urlopen, Request
                nat = native_language_name()
                sys_p = (
                    f"You are a content analyst splitting a video into LESSON-sized scenes. "
                    f"Each segment becomes a mini-lesson, so cut wherever the scene, location, "
                    f"topic or beat naturally changes. Make as many as the content needs "
                    f"(typically 8-20), but NO MORE THAN {max_segs}. Respond ONLY with JSON, "
                    f"no prose, no markdown fences:\n"
                    '{"segments":[{"title":"<title in ' + nat + '>","start_idx":<int>,"end_idx":<int>}]}\n'
                    "Rules:\n"
                    "- start_idx and end_idx are the [i] index numbers shown.\n"
                    "- Segments cover ALL entries exactly (no gaps/overlap); first starts at 0, "
                    f"last ends at {n-1}.\n"
                    "- Each title (in " + nat + "): 2-5 words describing that scene.\n"
                    f"Subtitle data ({n} entries):\n{full[:10000]}")
                body = json.dumps({"model": "deepseek-chat", "max_tokens": 2400, "temperature": 0.1,
                    "messages": [{"role": "system", "content": sys_p},
                                 {"role": "user", "content": "Return the segments JSON now."}]}).encode()
                r = urlopen(Request(f"{LEXIO_API}/api/deepseek-chat", data=body,
                                    headers={"Content-Type": "application/json"}), timeout=60)
                d = json.loads(r.read().decode())
                raw = (d.get("text") or d.get("content") or "").strip().strip("`")
                segs = self._parse_segments(raw, n)
                if segs:
                    self.tracks_ready.emit(segs)
                else:
                    self.tracks_failed.emit("empty/parse")
            except Exception as e:
                log(f"segment err: {e}")
                self.tracks_failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _parse_segments(raw, n):
        """Extrai os segmentos do texto da IA de forma tolerante: tenta JSON inteiro e,
        se vier truncado, salva os objetos {..} individuais que estiverem completos."""
        import re
        out = []
        def _clamp(sg):
            try:
                s = max(0, min(int(sg["start_idx"]), n - 1))
                e = max(s, min(int(sg["end_idx"]), n - 1))
                t = str(sg.get("title", "") or "").strip() or T("scene_default")
                return {"title": t, "start_idx": s, "end_idx": e}
            except Exception:
                return None
        # 1) JSON completo.
        try:
            obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            for sg in obj.get("segments", []):
                c = _clamp(sg)
                if c: out.append(c)
        except Exception:
            pass
        # 2) Fallback: apanhar cada objeto de segmento individual (resiste a truncagem).
        if not out:
            for m in re.finditer(r'\{[^{}]*?"start_idx"\s*:\s*\d+[^{}]*?\}', raw):
                try:
                    c = _clamp(json.loads(m.group(0)))
                    if c: out.append(c)
                except Exception:
                    continue
        # Ordena e garante cobertura mínima coerente.
        out.sort(key=lambda x: x["start_idx"])
        return out

    def _on_tracks_ready(self, segs):
        self._tracks = segs or []
        self._populate_tracks()

    def _populate_tracks(self):
        if hasattr(self, 'btn_segment'):
            self.btn_segment.setEnabled(True)
            self.btn_segment.setText(T("track_segment"))
        # Nova segmentação → esquece o progresso de aulas anterior.
        self._lesson_active = False
        self._lesson_range = None
        self._lesson_row = None
        self._lesson_done = set()
        if hasattr(self, 'tw_list') and hasattr(self, 'tw_empty'):
            self.tw_list.clear()
            for i, t in enumerate(self._tracks):
                subs = self.engine._subs
                start_s = subs[t["start_idx"]].start if subs else 0
                end_s = subs[t["end_idx"]].end if subs and t["end_idx"] < len(subs) else subs[-1].end if subs else 0
                st = datetime.utcfromtimestamp(start_s).strftime('%M:%S')
                et = datetime.utcfromtimestamp(end_s).strftime('%M:%S')
                count = t["end_idx"] - t["start_idx"] + 1
                item = QListWidgetItem(f"{t['title']}  ({st}–{et})  · {T('track_lines', count=count)}")
                item.setData(Qt.UserRole, t["start_idx"])
                item.setToolTip(T("lesson_click_hint"))
                self.tw_list.addItem(item)
            self.tw_empty.setText(T("lesson_click_hint"))
            # Switch to Tracks tab
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == T("tab_tracks"):
                    self.tabs.setCurrentIndex(i)
                    break
            self._refresh_track_marks()
            self._notify(f'{len(self._tracks)} {T("tab_tracks")}')

    def _track_fail(self, err):
        if hasattr(self, 'btn_segment'):
            self.btn_segment.setEnabled(True)
            self.btn_segment.setText(T("track_segment"))
        if hasattr(self, 'tw_empty'):
            self.tw_empty.setText(T("track_failed"))
        self._notify(T("track_failed"))

    def _track_clicked(self, row):
        if row < 0 or row >= len(self._tracks):
            return
        self._start_lesson(row)

    # ── Aulas: cada track é uma aula guiada pela IA ──
    def _start_lesson(self, row):
        """Arranca a aula do track: salta para o início, garante o chat aberto, dá a
        introdução da cena e liga a narração ao vivo legenda a legenda."""
        t = self._tracks[row]
        subs = self.engine._subs
        if not subs:
            return
        si = t.get("start_idx", 0); ei = t.get("end_idx", si)
        self._lesson_active = True
        # A aula toca a cena seguida e narra linha-a-linha. O Loop IA / auto-pausa /
        # loop A-B fariam o filme repetir/parar a meio da aula ("o filme falha muito"
        # com o segmentar/aula ativos). Suspende-os durante a aula; repõe no fim.
        self._lesson_prev_ai_loop = getattr(self.engine, "_ai_loop", False)
        self._lesson_prev_autopause = getattr(self.engine, "_autopause", False)
        self._lesson_prev_loop = getattr(self.engine, "_loop", None)
        try:
            self.engine._ai_loop = False
            self.engine._autopause = False
            self.engine._loop = None
        except Exception:
            pass
        self._lesson_row = row
        self._lesson_range = (si, ei)
        self._lesson_seen = set()
        self._lesson_pending = None
        # O motor pode já estar dentro de uma legenda — não a saltes na narração.
        self.engine._last_entered_idx = -1
        # Garante o chat visível para ver a aula.
        if hasattr(self, 'chat') and not self.chat.isVisible():
            try:
                self.chat.setVisible(True)
                if hasattr(self, 'chat_btn'): self.chat_btn.setChecked(True)
            except Exception: pass
        if si < len(subs):
            self.engine.seek(subs[si].start)
            try:
                if not self.engine._player or not self.engine._player.is_playing():
                    self.engine._player.play()
            except Exception: pass
        self._notify(f'{T("lesson_started")}: {t.get("title","")}')
        # Introdução da cena (1 chamada). Bloqueia a primeira narração até chegar.
        self._lesson_inflight = True
        lines = []
        for i in range(si, min(ei + 1, len(subs))):
            lines.append(subs[i].text)
        scene = " ".join(lines)[:1500]
        sys_extra = (f"This is the START of a lesson on one scene/segment titled "
                     f"\"{t.get('title','')}\". Give a short, inviting introduction: what this "
                     f"scene is about and the context the learner should keep in mind. Do NOT "
                     f"translate line by line yet.")
        user_text = f"Scene transcript:\n{scene}"
        self.chat.post_lesson_note(sys_extra, user_text, done_cb=self._lesson_note_done)

    def _lesson_on_sub(self, idx):
        """Narração ao vivo: explica a legenda atual dentro do track em curso."""
        if not self._lesson_active or not self._lesson_range:
            return
        s, e = self._lesson_range
        if idx > e:
            self._finish_lesson()
            return
        if idx < s or idx in self._lesson_seen:
            return
        if self._lesson_inflight:
            self._lesson_pending = idx   # apanha-a assim que a anterior terminar
            return
        self._narrate_line(idx)

    def _narrate_line(self, idx):
        subs = self.engine._subs
        if idx >= len(subs):
            return
        self._lesson_seen.add(idx)
        self._lesson_inflight = True
        # Algum contexto à volta para a explicação não ficar solta.
        ctx_before = subs[idx-1].text if idx > 0 else ""
        line = subs[idx].text
        ts = datetime.utcfromtimestamp(subs[idx].start).strftime('%M:%S')
        title = self._tracks[self._lesson_row].get("title", "") if self._lesson_row is not None else ""
        sys_extra = (f"You are mid-lesson on the scene \"{title}\". Explain THIS line as it plays: "
                     f"meaning, tone, any idiom/expression or cultural nuance worth knowing. "
                     f"Start with the timestamp {ts} in bold.")
        user_text = (f"Previous line: {ctx_before}\nCurrent line ({ts}): {line}")
        self.chat.post_lesson_note(sys_extra, user_text, done_cb=self._lesson_note_done)

    def _lesson_note_done(self):
        """Uma nota da IA terminou — liberta a fila e trata a legenda pendente."""
        self._lesson_inflight = False
        if not self._lesson_active:
            return
        pend = self._lesson_pending
        self._lesson_pending = None
        if pend is not None and self._lesson_range:
            s, e = self._lesson_range
            if s <= pend <= e and pend not in self._lesson_seen:
                self._narrate_line(pend)

    def _finish_lesson(self):
        if self._lesson_row is not None:
            self._lesson_done.add(self._lesson_row)
            self._mark_track_done_ui(self._lesson_row)
        self._lesson_active = False
        self._lesson_range = None
        self._lesson_row = None
        self._lesson_pending = None
        # Repõe os modos do motor suspendidos durante a aula.
        try:
            self.engine._ai_loop = getattr(self, "_lesson_prev_ai_loop", self.engine._ai_loop)
            self.engine._autopause = getattr(self, "_lesson_prev_autopause", self.engine._autopause)
            self.engine._loop = getattr(self, "_lesson_prev_loop", self.engine._loop)
        except Exception:
            pass
        self._refresh_track_marks()

    def _mark_track_done_ui(self, row):
        """Marca o track concluído na lista (cor) — o groove é tratado à parte."""
        if hasattr(self, 'tw_list') and 0 <= row < self.tw_list.count():
            it = self.tw_list.item(row)
            if it:
                from PyQt5.QtGui import QColor
                it.setForeground(QColor("#9EE6A0"))

    def _refresh_track_marks(self):
        """Desenha as fronteiras dos tracks no groove e realça os concluídos."""
        if not hasattr(self, 'seek'):
            return
        dur = self.engine._duration or 0
        subs = self.engine._subs
        segs = []
        if dur > 0 and subs and self._tracks:
            for i, t in enumerate(self._tracks):
                si = t.get("start_idx", 0); ei = t.get("end_idx", si)
                if si < len(subs):
                    sf = subs[si].start / dur
                    ef = (subs[ei].end if ei < len(subs) else subs[-1].end) / dur
                    segs.append((max(0.0, min(1.0, sf)), max(0.0, min(1.0, ef)), i in self._lesson_done))
        self.seek.set_track_segs(segs)

    def _notify(self, msg):
        """Feedback the user can actually SEE: a flash on the video (works in
        fullscreen) plus the status-bar message. The status bar alone was too easy
        to miss, which made the practice buttons feel like they did nothing."""
        showToast(msg, "accent")
        if getattr(self, 'overlay', None) and self.video_path:
            self.overlay.flash(msg)

    # ── Button press animation ──
    def _flash_btn(self, btn):
        """Brief opacity pulse on button press — native Qt ease-out curve."""
        eff = QGraphicsOpacityEffect(btn)
        btn.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", btn)
        anim.setDuration(200)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        def cleanup():
            try:
                if btn.graphicsEffect() is eff:
                    btn.setGraphicsEffect(None)
            except RuntimeError:
                pass
        anim.finished.connect(cleanup)
        anim.start()

    # ── Playback ──
    def _toggle(self):
        if not self.video_path: self._open(); return
        self.engine.toggle()
        self._flash_btn(self.play_btn)

    def _on_play(self, p):
        self.play_btn.setText(chr(0xE769) if p else chr(0xE768))
        # Tell the overlay so it freezes vocab-card aging while paused (subs stay).
        self.overlay._is_playing = bool(p)
    def _on_pos(self, p):
        if self._seeking: return
        self.tlbl.setText(FMT(p))
        self.seek.blockSignals(True); self.seek.setValue(int(p)); self.seek.blockSignals(False)
        self._scene_check(p)

    # ── Scene Agent: a IA pausa o filme em cenas-chave e pede uma ação ──
    def _scene_intensity(self):
        return {"light": "light", "balanced": "balanced", "god": "god"}.get(self._scene_mode)

    def _scene_build_if_needed(self):
        if not scene_agent or self._scene_mode == "off":
            return
        subs = getattr(self.engine, "_subs", [])
        if not subs:
            return
        key = (len(subs), self._scene_mode, round(subs[0].start, 1) if subs else 0)
        if key == self._scene_subs_key:
            return
        try:
            self._scene_missions = scene_agent.build_scene_missions(subs, self._scene_intensity())
            self._scene_subs_key = key
            log(f"scene agent: {len(self._scene_missions)} missões ({self._scene_mode})")
        except Exception as e:
            log(f"scene build: {e}")
            self._scene_missions = []

    def _scene_check(self, p):
        if (not scene_agent or self._scene_mode == "off" or self._in_mission
                or not self.engine.is_playing()):
            return
        self._scene_build_if_needed()
        if not self._scene_missions:
            return
        for m in self._scene_missions:
            if m.id in self._scene_done:
                continue
            if m.timestamp <= p <= m.timestamp + 1.4:
                self._scene_done.add(m.id)
                self._start_mission(m)
                break

    def _start_mission(self, m):
        self._in_mission = True
        # Os exercícios próprios do player (Fluência, Paráfrase, Descrever cena/take)
        # têm UI e avaliação dedicadas — a IA tece-os no filme, mas abrem o seu
        # próprio painel (que trata sozinho do loop/pause/visão).
        if getattr(m, "kind", "") in _PLAYER_EXERCISE_KINDS:
            self._run_exercise_mission(m)   # gere o _in_mission no fecho do painel
            return
        try:
            if self.engine.is_playing():
                self.engine.toggle()   # pausa
        except Exception:
            pass
        try:
            native = native_language_name() or "pt"
        except Exception:
            native = "pt"
        try:
            target = self._content_lang() or "en"
        except Exception:
            target = "en"
        ctx = {"native": native, "target": target, "level": "B1"}
        auth = None
        try:
            auth = self.chat._get_token_header()
        except Exception:
            pass

        def _resume():
            self._in_mission = False
            try:
                if not self.engine.is_playing():
                    self.engine.toggle()   # retoma
            except Exception:
                pass
        # Encaixa na sidebar (não tapa as legendas); retoma o filme quando fechar.
        try:
            dlg = SceneMissionDialog(self, m, ctx, auth)
            self._dock_exercise(dlg, on_close=_resume)
        except Exception as e:
            log(f"mission dialog: {e}")
            _resume()

    def _run_exercise_mission(self, m):
        """Abre o exercício próprio do player correspondente ao tipo de missão, encaixado
        na sidebar (já não é popup). O painel lê a cena a partir da posição atual (o filme
        está na cena da missão) e trata sozinho do loop/pause/visão. Retomamos a
        reprodução quando o painel fecha, se estava a tocar."""
        was_playing = self.engine.is_playing()
        try:
            self.engine.pause()   # assenta na cena; os painéis gerem o resto
        except Exception:
            pass
        kind = getattr(m, "kind", "")

        def _resume():
            self._in_mission = False
            try:
                if was_playing and not self.engine.is_playing():
                    self.engine.play()
            except Exception:
                pass
        try:
            if kind == "fluency_translate":
                w = FluencyDialog(self, self.engine)
            elif kind == "paraphrase_line":
                w = ParaphraseDialog(self, self.engine)
            elif kind == "describe_take":
                w = DescribeDialog(self, self.engine, mode="take")
            elif kind == "dialogue_roleplay":
                w = DialogueDialog(self, self.engine)
            else:   # describe_scene
                w = DescribeDialog(self, self.engine, mode="scene")
            self._dock_exercise(w, on_close=_resume)
        except Exception as e:
            log(f"exercise mission ({kind}): {e}")
            _resume()

    def _on_dur(self, d):
        self.dlbl.setText(FMT(d)); self.seek.setRange(0, max(1, int(d)))
    def _on_end(self):
        self.play_btn.setText(chr(0xE768))
        if self._pl_idx < len(self._playlist)-1:
            QTimer.singleShot(1200, lambda: self.plw.setCurrentRow(self._pl_idx+1))
    def _seek_to(self):
        self.engine.seek(float(self.seek.value())); self._seeking = False

    def _open(self):
        paths, _ = QFileDialog.getOpenFileNames(self, T("dlg_open"), "",
            f"Multimédia (*{' *'.join(sorted(SUPPORTED_VID|SUPPORTED_AUD))})")
        if paths:
            for p in paths: self._pl_add(p)
            self._open_file(paths[0])

    def _open_file(self, path):
        if not path or not Path(path).exists(): return
        # Mudar de filme → fecha SÓ o exercício aberto (ficava com a cena do filme
        # antigo). O chat IA NÃO se mexe — mantém a conversa entre filmes.
        self._close_dock_exercise()
        self.engine.stop(); self.video_path = path
        # Limpa já a legenda/cartões do filme anterior, antes de o novo vídeo arrancar,
        # para não ficarem "colados" sobre o novo (bug das legendas congeladas).
        self.overlay.reset_for_new_video()
        self.engine.show_subtitle_reset()
        self._sub_names = ["", "", ""]        # filme novo → esquece nomes das legendas
        self._sf_sig = None                   # força rebuild do feed da aba Legendas
        self._roll_session(Path(path).name)   # envia a sessão anterior, começa nova
        self.seek.clear_marks()
        # Filme novo → esquece tracks/aulas e limpa as marcas do groove.
        self._tracks = []
        self._lesson_active = False; self._lesson_range = None; self._lesson_row = None
        self._lesson_done = set(); self._lesson_pending = None; self._lesson_inflight = False
        self.seek.set_track_segs([])
        if hasattr(self, 'tw_list'):
            self.tw_list.clear()
        if hasattr(self, 'tw_empty'):
            self.tw_empty.setText(T("track_no_sub"))
        self._add_recent(path)
        self.setWindowTitle(f"{Path(path).name} — {APP_NAME}")
        self.engine.open(path)
        self._update_sub_icon()
        self._apply_slow_voice_mode()   # re-muta o novo player se ainda estiver em <1x
        # Auto-load a subtitle the user picked for this video before (memory),
        # only if none was auto-detected next to the file.
        if self.engine.sub_count() == 0:
            srt = self._recall_sub(path)
            if srt and self.engine.load_srt(srt):
                self._update_sub_icon()
                self._sub_names[0] = Path(srt).name
                self.sbl.setText(T("sub_from_memory", name=Path(srt).name))
                return
        self.sbl.setText(Path(path).name)

    # ── Drag & drop: a .srt onto the video loads it; a video opens it ──
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        subs  = [p for p in paths if Path(p).suffix.lower() in ('.srt', '.vtt')]
        media = [p for p in paths if Path(p).suffix.lower() in (SUPPORTED_VID | SUPPORTED_AUD)]
        if media:
            for p in media:
                self._pl_add(p)
            self._open_file(media[0])
        if subs:
            if not self.engine.path():
                showToast(T("sub_need_first"), "accent")
            elif self.engine.load_srt(subs[0]):
                self._remember_sub(self.engine.path(), subs[0])
                self._update_sub_icon()
                name = Path(subs[0]).name
                self._sub_names[0] = name
                self.sbl.setText(f"CC {name}")
                self.overlay.flash(T("sub_dropped", name=name))
            else:
                showToast(T("sub_load_fail"), "accent")
        e.acceptProposedAction()

    def _open_sub_manager(self):
        """Gestor de legendas VISÍVEL: 3 slots (principal/2ª/3ª) + auto-tradução, para
        ser óbvio que se pode mostrar mais do que uma legenda ao mesmo tempo."""
        # O botão é checkable (indicador verde): repõe o estado correto ao fechar.
        if not self.engine.path():
            showToast(T("sub_need_first"), "accent")
            self._update_sub_icon(); return

        dlg = QDialog(self)
        dlg.setWindowTitle(T("sub_mgr_title"))
        dlg.setMinimumWidth(460)
        dlg.setStyleSheet(f"QDialog{{background:{ELV};}}QLabel{{color:{TXT};background:transparent;}}")
        lo = QVBoxLayout(dlg); lo.setContentsMargins(18, 16, 18, 16); lo.setSpacing(10)

        title = QLabel(T("sub_mgr_title"))
        title.setStyleSheet(f"color:{TXT};font-size:16px;font-weight:700;background:transparent;")
        lo.addWidget(title)
        intro = QLabel(T("sub_mgr_intro")); intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
        lo.addWidget(intro)

        def _btn(label, accent=False):
            b = QPushButton(label); b.setCursor(Qt.PointingHandCursor)
            brd = ACC if accent else BRD
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{TS2};border:1px solid {brd};"
                f"border-radius:13px;font-size:11px;padding:5px 13px;}}"
                f"QPushButton:hover{{background:{HVR};color:{TXT};border-color:{ACC};}}")
            return b

        rows = {}   # slot -> name QLabel (para refrescar)

        def _make_row(slot, title_txt, can_online):
            row = QWidget(); row.setStyleSheet(f"background:{SRF};border-radius:10px;")
            rl = QVBoxLayout(row); rl.setContentsMargins(12, 10, 12, 10); rl.setSpacing(6)
            cap = QLabel(title_txt)
            cap.setStyleSheet(f"color:{TXT};font-size:12px;font-weight:600;background:transparent;")
            rl.addWidget(cap)
            line = QHBoxLayout(); line.setSpacing(8)
            name_lbl = QLabel(""); name_lbl.setStyleSheet(f"color:{TMT};font-size:11px;background:transparent;")
            name_lbl.setWordWrap(True)
            line.addWidget(name_lbl, 1)
            rows[slot] = name_lbl
            if slot == 0:
                b_load = _btn(T("sub_mgr_change"), accent=True)
                b_load.clicked.connect(lambda: (self._load_sub_file(), _refresh()))
                line.addWidget(b_load)
                if can_online:
                    b_on = _btn(T("sub_mgr_online"))
                    b_on.clicked.connect(lambda: (self._search_subs_online(), _refresh()))
                    line.addWidget(b_on)
            else:
                b_add = _btn(T("sub_mgr_add"), accent=True)
                b_add.clicked.connect(lambda _=0, s=slot: (self._load_sub_n(s + 1), _refresh()))
                line.addWidget(b_add)
                b_rm = _btn(T("sub_mgr_remove"))
                def _rm(_=0, s=slot):
                    (self.engine.clear_sub2() if s == 1 else self.engine.clear_sub3())
                    self._sub_names[s] = ""
                    self._rebuild_subs_feed()
                    self.overlay.flash(T("sub2_off") if s == 1 else T("sub3_off"))
                    _refresh()
                b_rm.clicked.connect(_rm)
                line.addWidget(b_rm)
            rl.addLayout(line)
            return row

        r0 = _make_row(0, T("sub_mgr_main"), True)
        r1 = _make_row(1, T("sub_mgr_2nd"), False)
        r2 = _make_row(2, T("sub_mgr_3rd"), False)
        for r in (r0, r1, r2):
            lo.addWidget(r)

        # Auto-tradução da 2ª linha (alternativa a carregar ficheiro na 2ª).
        lang_en = i18n.language_en_name(i18n.current_lang())
        chk = QCheckBox(T("sub_mgr_autotr", lang=lang_en))
        chk.setChecked(bool(self.engine._auto_tr))
        chk.setStyleSheet(f"QCheckBox{{color:{TXT};font-size:11px;background:transparent;}}")
        chk.toggled.connect(lambda on: (self._toggle_auto_tr(on), _refresh()))
        lo.addWidget(chk)

        note = QLabel(T("sub_mgr_note")); note.setWordWrap(True)
        note.setStyleSheet(f"color:{TMT};font-size:10px;background:transparent;")
        lo.addWidget(note)

        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        b_close = _btn(T("sub_mgr_close"), accent=True)
        b_close.clicked.connect(dlg.accept)
        btn_row.addWidget(b_close)
        lo.addLayout(btn_row)

        def _refresh():
            # Slot 0: nome guardado, ou "carregada" se houver subs sem nome (auto-detetada).
            n0 = self._sub_names[0] or (("✓ " + T("sub_loaded")) if self.engine.sub_count() > 0 else T("sub_mgr_none"))
            rows[0].setText(n0)
            n1 = self._sub_names[1] or (("✓ " + T("sub_loaded")) if len(self.engine._subs2) > 0
                 else (("IA → " + lang_en) if self.engine._auto_tr else T("sub_mgr_none")))
            rows[1].setText(n1)
            n2 = self._sub_names[2] or (("✓ " + T("sub_loaded")) if len(self.engine._subs3) > 0 else T("sub_mgr_none"))
            rows[2].setText(n2)

        _refresh()
        dlg.exec_()
        self._update_sub_icon()   # repõe o estado verde do botão

    def _load_sub_file(self):
        """Open file dialog to load .srt subtitle manually"""
        if not self.engine.path():
            showToast(T("sub_need_first"), "accent")
            self.sbl.setText(T("sub_need_first")); return
        path, _ = QFileDialog.getOpenFileName(self, T("dlg_load_sub"), "",
            "Legendas (*.srt *.SRT *.vtt *.VTT);;Todos (*)")
        if path and self.engine.load_srt(path):
            self._remember_sub(self.engine.path(), path)   # remember for next time
            self._update_sub_icon()
            name = Path(path).name
            self._sub_names[0] = name
            self.sbl.setText(f"CC {name}")
            self.overlay.flash(T("sub_dropped", name=name))
        elif path:
            self.sbl.setText(T("sub_load_fail"))
            self.overlay.flash(T("sub_load_fail"))

    def _search_subs_online(self):
        """Open the OpenSubtitles search dialog, prefilled from the video name."""
        if not self.engine.path():
            showToast(T("sub_need_first"), "accent"); return
        query = _clean_sub_query(Path(self.video_path).stem)
        dlg = SubSearchDialog(self, query, self.video_path, i18n.current_lang())
        if dlg.exec_() == QDialog.Accepted and dlg.result_path:
            if self.engine.load_srt(dlg.result_path):
                self._remember_sub(self.engine.path(), dlg.result_path)
                self._update_sub_icon()
                name = Path(dlg.result_path).name
                self.sbl.setText(f"CC {name}")
                self.overlay.flash(T("sub_dropped", name=name))
            else:
                self._notify(T("sub_load_fail"))

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
            self.sbl.setText(T("sub_track_on"))
        else:
            self.sbl.setText(T("sub_track_off"))

    def _sub_menu(self, pos):
        """Menu de legendas duplas/triplas + auto-tradução (clique-direito no CC)."""
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{ELV};color:{TXT};border:1px solid {BRD};padding:4px;}}"
                        f"QMenu::item{{padding:6px 14px;border-radius:4px;}}QMenu::item:selected{{background:{HVR};}}")
        a2 = m.addAction(T("sub2_load"))
        a3 = m.addAction(T("sub3_load"))
        m.addSeparator()
        at = m.addAction(T("sub_auto_tr"))
        at.setCheckable(True); at.setChecked(self.engine._auto_tr)
        m.addSeparator()
        c2 = m.addAction(T("sub2_clear"))
        c3 = m.addAction(T("sub3_clear"))
        act = m.exec_(self.sub_icon.mapToGlobal(pos))
        if act is None:
            return
        if act == a2:
            self._load_sub_n(2)
        elif act == a3:
            self._load_sub_n(3)
        elif act == at:
            self._toggle_auto_tr(at.isChecked())
        elif act == c2:
            self.engine.clear_sub2(); self._sub_names[1] = ""; self._rebuild_subs_feed(); self.overlay.flash(T("sub2_off"))
        elif act == c3:
            self.engine.clear_sub3(); self._sub_names[2] = ""; self._rebuild_subs_feed(); self.overlay.flash(T("sub3_off"))

    def _load_sub_n(self, n):
        if not self.engine.path():
            showToast(T("sub_need_first"), "accent"); return
        path, _ = QFileDialog.getOpenFileName(self, T("dlg_load_sub"), "",
            "Legendas (*.srt *.SRT *.vtt *.VTT);;Todos (*)")
        if not path:
            return
        ok = self.engine.load_srt2(path) if n == 2 else self.engine.load_srt3(path)
        if ok:
            self._sub_names[n - 1] = Path(path).name
            self._rebuild_subs_feed()
            self.overlay.flash(T(f"sub{n}_loaded", name=Path(path).name))
        else:
            self.overlay.flash(T("sub_load_fail"))
        return ok

    def _toggle_auto_tr(self, on):
        code = i18n.current_lang()
        lang_en = i18n.language_en_name(code)
        self.engine.set_auto_translate(on, lang_en, code)
        self._rebuild_subs_feed()
        self.overlay.flash(T("sub_auto_tr_on", lang=lang_en) if on else T("sub_auto_tr_off"))

    def _update_sub_icon(self):
        """Update the subtitle indicator based on loaded subs, and the big subtitle
        button / on-video 'load a subtitle' banner so the state is obvious."""
        srt = self.engine.sub_count()
        vlc_tracks = self.engine.sub_track_count()
        has_subs = srt > 0 or vlc_tracks > 0
        if srt > 0:
            self.sub_icon.setText(f"CC {srt}")
            self.sub_icon.setToolTip(T("subs_loaded_count", n=srt))
        elif vlc_tracks > 0:
            self.sub_icon.setText(f"VLC {vlc_tracks}")
            self.sub_icon.setToolTip(f"{vlc_tracks} faixas VLC")
        else:
            self.sub_icon.setText("")
            self.sub_icon.setToolTip(T("subs_none"))
        # Botão "Legendas" (abre o gestor): mantém o rótulo e fica verde quando há sub.
        if hasattr(self, 'btn_sub'):
            self.btn_sub.setText(T("sub_mgr_btn"))
            self.btn_sub.setChecked(has_subs)
        # On-video banner: only when a video is open and there's still no subtitle.
        if hasattr(self, 'overlay'):
            self.overlay.set_no_sub_hint(bool(self.video_path) and not has_subs)
        # Reconstrói o feed da aba Legendas (falas + traduções) sempre que as legendas mudam.
        self._rebuild_subs_feed()

    def _cycle_spd(self):
        spds = [0.5,0.75,1.0,1.25,1.5,2.0]
        i = spds.index(self._rate) if self._rate in spds else 2
        self._rate = spds[(i+1)%len(spds)]; self.engine.set_rate(self._rate); self.spd.setText(f"{self._rate}x")
        self._apply_slow_voice_mode()

    # ── Modo lento com voz neural (edge-tts) por cima ──
    def _apply_slow_voice_mode(self):
        """Abaixo de 1x: muta o VLC (sem 'cacos') e a voz neural lê cada legenda.
        A 1x ou mais: restaura o áudio original e pára a voz."""
        want = self._rate < 1.0 and bool(self.video_path)
        changed = (want != self._slow_voice)
        self._slow_voice = want
        self.engine.set_audio_muted(want)
        if not want:
            SLOW_TTS.stop()
        if changed:
            self._notify(T("slow_voice_on") if want else T("slow_voice_off"))
        if want:
            # Começa logo pela legenda atual, sem esperar pela próxima.
            idx = self.engine._last_entered_idx
            if idx is not None and idx >= 0:
                self._speak_line_slow(idx)

    def _slow_voice_on_sub(self, idx):
        if self._slow_voice:
            self._speak_line_slow(idx)

    def _speak_line_slow(self, idx):
        subs = self.engine._subs
        if idx < 0 or idx >= len(subs):
            return
        line = subs[idx].text.strip()
        if not line:
            return
        # Voz mais lenta proporcional à velocidade do filme (0.5x→-50%, 0.75x→-25%).
        rate = max(-50, min(0, int(round((self._rate - 1.0) * 100))))
        SLOW_TTS.speak(line, self._content_lang(), rate=rate)

    # (Bookmarks/Annotations UI removida — abas "Marcos" e "Notas" saíram.
    # A camada de dados (DataMgr.get_bm/get_an) mantém-se para o export.)

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
        self._flash_btn(self.nb)
        if self._pl_idx < len(self._playlist)-1: self.plw.setCurrentRow(self._pl_idx+1)
    def _prev(self):
        self._flash_btn(self.pb)
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
    # ── Lembretes de revisão (notificação do sistema) ──
    def _ensure_tray(self):
        """Cria (uma vez) o ícone na bandeja do sistema — necessário no Windows
        para mostrar as notificações balão."""
        if self._tray is not None:
            return self._tray
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        ico = QApplication.instance().windowIcon()
        if ico is None or ico.isNull():
            _bd = os.path.dirname(os.path.abspath(__file__))
            for _n in ("icon.ico", "icon.png"):
                _p = os.path.join(_bd, _n)
                if os.path.exists(_p):
                    ico = QIcon(_p); break
        self._tray = QSystemTrayIcon(ico, self)
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(lambda _r: (self.showNormal(), self.raise_(), self.activateWindow()))
        return self._tray

    def _toggle_reminders(self, on):
        self.reminder.set_enabled(on)
        tray = self._ensure_tray()
        if tray is not None:
            tray.setVisible(bool(on))

    def _show_reminder_note(self, title, body):
        tray = self._ensure_tray()
        if tray is None:
            return
        if not tray.isVisible():
            tray.show()
        tray.showMessage(title or T("reminder_title"), body or "",
                         QSystemTrayIcon.Information, 12000)

    # ── Coach AI call handler ──
    def _on_coach_call(self, level, word):
        """Called when the CoachManager detects it's time for a responsibility call."""
        # Speak the opening line using edge-tts
        lines = {
            "calm": "Ola. Vamos fazer uma revisao curta e honesta.",
            "firm": "Lexio na linha. Chega de adiar. Tens uma missao curta agora.",
            "maximum": "Lexio na linha. Levanta-te. A tua sessao comeca agora.",
        }
        opening = lines.get(level, "Lexio na linha.")
        try:
            speak_edge_tts(opening, i18n.current_lang() or "pt", -20)
        except:
            speak_local_sapi(opening, "pt")

        # Show tray notification
        tray = self._ensure_tray()
        if tray:
            title = "Pressao maxima!" if level == "maximum" else "Lexio Coach"
            body = "A tua divida de estudo esta critica." if level == "maximum" else "Coach de responsabilidade — hora de provar o que aprendeste."
            tray.showMessage(title, body, QSystemTrayIcon.Information, 15000)

        # Only show dialog if window is visible (otherwise tray notification is enough)
        if self.isVisible():
            dialog = CoachDialog(level, word, self)
            result = dialog.result() if dialog.exec_() == QDialog.Accepted else "cancelled"

            # Update debt
            state = _load_coach_state()
            if result == "passed":
                state["debt"] = max(0, state["debt"] - 1)
            elif result in ("failed", "skipped"):
                state["debt"] = state["debt"] + 1
            elif result == "cancelled":
                state["debt"] = state["debt"] + (2 if level == "maximum" else 1)
            _save_coach_state(state)

    def _export(self):
        if not self.video_path: return
        p, _ = QFileDialog.getSaveFileName(self, T("dlg_export"), f"{Path(self.video_path).stem}_estudo.json", "JSON (*.json)")
        if p: Path(p).write_text(self.mgr.export(self.video_path), encoding='utf-8')
    def _check_upd(self):
        try:
            r = urlopen(Request("https://github.com/Tchycolomuenho/lexio-player/releases/latest/download/version.txt", headers={'User-Agent':APP_NAME}), timeout=5)
            v = r.read().decode().strip()
            if v and v != APP_VERSION:
                if QMessageBox.question(self, T("dlg_update"), f"Nova: {v}\nDescarregar?", QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                    webbrowser.open("https://github.com/Tchycolomuenho/lexio-player/releases/latest")
        except: pass
    def _about(self):
        QMessageBox.about(self, APP_NAME, f"<div style='text-align:center;'><h2 style='color:{ACC};'>{APP_NAME}</h2><p style='color:{TS2};'>v{APP_VERSION}</p><p style='color:{TMT};'>VLC + Chat IA</p></div>")

    def _set_vision_key(self):
        """Ativa a análise de imagem GRATUITA: o utilizador cola uma chave do
        OpenRouter (criar é grátis em openrouter.ai/keys); os modelos de visão
        :free passam a avaliar 'descrever cena/take' a ver mesmo o fotograma. A
        chave fica só LOCAL (DATA_DIR/openrouter-key.txt), nunca no código/.exe."""
        from PyQt5.QtWidgets import QInputDialog
        from PyQt5.QtGui import QDesktopServices
        cur = _openrouter_key()
        box = QMessageBox(self)
        box.setWindowTitle(T("tools_vision_key"))
        box.setStyleSheet(f"QMessageBox{{background:{ELV};}}QLabel{{color:{TXT};}}")
        status = T("vision_key_set") if cur else T("vision_key_unset")
        box.setText(status + "\n\n" + T("vision_key_help"))
        open_btn = box.addButton(T("vision_key_open"), QMessageBox.ActionRole)
        paste_btn = box.addButton(T("vision_key_paste"), QMessageBox.AcceptRole)
        box.addButton(T("exercise_close"), QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is open_btn:
            QDesktopServices.openUrl(QUrl("https://openrouter.ai/keys"))
            return
        if clicked is not paste_btn:
            return
        key, ok = QInputDialog.getText(self, T("tools_vision_key"),
                                       T("vision_key_prompt"), text=cur)
        if not ok:
            return
        key = (key or "").strip()
        try:
            f = DATA_DIR / "openrouter-key.txt"
            if key:
                f.write_text(key, encoding="utf-8")
                self._notify(T("vision_key_saved"))
            else:
                if f.exists(): f.unlink()
                self._notify(T("vision_key_cleared"))
        except Exception as e:
            log(f"vision key save: {e}")
            self._notify(T("vision_key_failed"))

    # ── Keyboard ──
    _SHORTCUT_KEYS = frozenset({
        Qt.Key_Space, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
        Qt.Key_B, Qt.Key_N, Qt.Key_P, Qt.Key_R, Qt.Key_Comma, Qt.Key_Period,
        Qt.Key_Z, Qt.Key_L, Qt.Key_X, Qt.Key_H, Qt.Key_F, Qt.Key_C, Qt.Key_Escape,
        Qt.Key_M, Qt.Key_K, Qt.Key_J, Qt.Key_G,
    })

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QTextEdit)) and event.key() in self._SHORTCUT_KEYS:
                self.keyPressEvent(event)
                return True
        elif event.type() == QEvent.MouseMove and self._study_mode:
            # In fullscreen, any mouse movement anywhere on screen should
            # reveal the groove if the cursor is near the bottom zone.
            self._fs_activity()
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
        elif k == Qt.Key_M: self._toggle_focus_mode()            # M  modo Focado/Leve
        elif k == Qt.Key_K: self._toggle_ai_loop()               # K  AI Loop (cada frase repete N vezes)
        elif k == Qt.Key_J: self._open_exercise()                # J  Exercício sobre a legenda atual
        elif k == Qt.Key_U: self._open_fluency()                 # U  Fluência (traduzir grupo de legendas)
        elif k == Qt.Key_Y: self._open_paraphrase()              # Y  Paráfrase (reescrever a linha atual)
        elif k == Qt.Key_D: self._open_describe_scene()          # D  Descrever cena (loop)
        elif k == Qt.Key_T: self._open_describe_take()           # T  Descrever take (pause)
        elif k == Qt.Key_I: self._open_dialogue()                # I  Diálogo (role-play falado)
        elif k == Qt.Key_G: self._toggle_listening()             # G  Modo Listening
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
# COACH AI — Background responsibility coach for desktop
# ═══════════════════════════════════════════════════════════════════════════

COACH_STATE_FILE = DATA_DIR / "coach-state.json"
COACH_DEFAULT_INTERVAL = 180  # minutes

def _coach_defaults():
    return {
        "enabled": False,
        "level": "firm",
        "intervalMinutes": COACH_DEFAULT_INTERVAL,
        "questionsPerCall": 3,
        "quietStart": "22:00",
        "quietEnd": "08:00",
        "nextCallAt": None,  # epoch ms
        "debt": 0,
    }

def _load_coach_state():
    try:
        if COACH_STATE_FILE.exists():
            data = json.loads(COACH_STATE_FILE.read_text(encoding="utf-8"))
            return {**_coach_defaults(), **data}
    except Exception as e:
        log(f"coach load: {e}")
    return _coach_defaults()

def _save_coach_state(state):
    try:
        COACH_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"coach save: {e}")

def _is_coach_quiet_hours(state, now=None):
    if now is None:
        now = datetime.now()
    current = now.hour * 60 + now.minute
    sh, sm = map(int, state["quietStart"].split(":"))
    eh, em = map(int, state["quietEnd"].split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start == end:
        return False
    return current >= start and current < end if start < end else current >= start or current < end


class CoachDialog(QDialog):
    """Full-screen challenge dialog for the desktop player coach."""

    def __init__(self, level, word, parent=None):
        super().__init__(parent)
        self.level = level
        self.word = word
        self._result = "skipped"
        self._timer_secs = 75 if level == "calm" else (30 if level == "maximum" else 50)
        self._timer_running = False
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Lexio Coach")
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG};
                color: {TXT};
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }}
            QLabel {{ color: {TXT}; font-size: 14px; }}
            QPushButton {{
                background-color: {ELV};
                color: {TXT};
                border: 1px solid {BRD};
                border-radius: 10px;
                padding: 14px 28px;
                font-size: 14px;
                font-weight: 600;
                min-width: 120px;
            }}
            QPushButton:hover {{ background-color: {HVR}; border-color: {ACC}; }}
            QPushButton#passBtn {{ background-color: #1a6b3c; border-color: #22c55e; color: #fff; }}
            QPushButton#passBtn:hover {{ background-color: #228b4a; }}
            QPushButton#failBtn {{ background-color: #6b1a1a; border-color: #ef4444; color: #fff; }}
            QPushButton#failBtn:hover {{ background-color: #8b2222; }}
        """)
        self.setMinimumSize(500, 300)
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 40, 40, 40)

        title_text = {
            "calm": "Revisão curta e honesta",
            "firm": "Lexio na linha — chega de adiar",
            "maximum": "PRESSÃO MÁXIMA — foco total!",
        }.get(self.level, "Lexio Coach")

        title = QLabel(f"<h2 style='color:{ACC};margin:0'>{title_text}</h2>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        timer_color = "#ef4444" if self.level == "maximum" else ACC
        self.timer_label = QLabel(f"<span style='font-size:32px;font-weight:700;color:{timer_color}'>{self._timer_secs}s</span>")
        self.timer_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.timer_label)

        prompt = QLabel(f"<p style='font-size:16px;color:{TMT};text-align:center;margin:0'>Traduz ou usa a palavra:</p>")
        prompt.setAlignment(Qt.AlignCenter)
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        word_label = QLabel(f"<p style='font-size:22px;font-weight:700;color:{TXT};text-align:center;margin:0'>{self.word}</p>")
        word_label.setAlignment(Qt.AlignCenter)
        word_label.setWordWrap(True)
        layout.addWidget(word_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        pass_btn = QPushButton("✓ Passei")
        pass_btn.setObjectName("passBtn")
        pass_btn.clicked.connect(lambda: self._done("passed"))
        btn_layout.addWidget(pass_btn)

        fail_btn = QPushButton("✗ Falhei")
        fail_btn.setObjectName("failBtn")
        fail_btn.clicked.connect(lambda: self._done("failed"))
        btn_layout.addWidget(fail_btn)

        skip_btn = QPushButton("Saltar")
        skip_btn.clicked.connect(lambda: self._done("skipped"))
        btn_layout.addWidget(skip_btn)

        cancel_btn = QPushButton("Cancelar (+ dívida)")
        cancel_btn.clicked.connect(lambda: self._done("cancelled"))
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self._start_timer()

    def _start_timer(self):
        self._timer_running = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self):
        self._timer_secs -= 1
        self.timer_label.setText(
            f"<span style='font-size:32px;font-weight:700;color:{'#ef4444' if self._timer_secs <= 10 else ACC}'>{self._timer_secs}s</span>"
        )
        if self._timer_secs <= 0:
            self._timer.stop()
            self._done("failed")

    def _done(self, result):
        self._timer_running = False
        if hasattr(self, "_timer"):
            self._timer.stop()
        self._result = result
        self.accept()

    def result(self):
        return self._result

    def closeEvent(self, event):
        if self._timer_running:
            self._timer.stop()
        super().closeEvent(event)


class CoachManager(QObject):
    """Background thread that checks coach schedule and triggers calls."""

    coach_call = pyqtSignal(str, str)  # level, word

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = _load_coach_state()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.setInterval(15_000)  # every 15s
        if self._state["enabled"]:
            self._timer.start()

    def save(self, state):
        self._state = state
        _save_coach_state(state)
        if state["enabled"] and not self._timer.isActive():
            self._timer.start()
        elif not state["enabled"] and self._timer.isActive():
            self._timer.stop()

    def _check(self):
        if not self._state["enabled"]:
            return
        if self._state.get("nextCallAt") is None:
            return
        if _is_coach_quiet_hours(self._state):
            return
        if self._state["level"] == "maximum" and not self._state.get("maximumConsent"):
            return

        now_ms = int(time.time() * 1000)
        if now_ms >= self._state["nextCallAt"]:
            # Trigger call
            words = self._state.get("words", [])
            word = words[0] if words else "example"
            self.coach_call.emit(self._state["level"], word)

            # Schedule next
            jitter = int(self._state["intervalMinutes"] * 60_000 * 0.08 * random.random())
            self._state["nextCallAt"] = now_ms + self._state["intervalMinutes"] * 60_000 + jitter
            _save_coach_state(self._state)

    def stop(self):
        self._timer.stop()


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY
# ═══════════════════════════════════════════════════════════════════════════

def main():
    log("main()")
    try:
        # High-DPI awareness — MUST be set before QApplication. Without it, on a
        # scaled display (125%/150%) the top-level subtitle overlay (Qt logical
        # coords) drifts off the VLC video (HWND in physical px) by the engine's
        # offset, so subtitles land in a corner when the window is not fullscreen.
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME); app.setStyle("Fusion")
        ensure_gui_invoker()   # cria o invocador GUI na main thread (entrega de workers)
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
            "padding:5px 9px;border-radius:6px;font-size:11px;font-family:'Inter','Segoe UI',sans-serif;}")
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
        # Direção do layout segue a língua de APRESENTAÇÃO: árabe/hebraico/farsi/urdu
        # invertem toda a UI (igual ao dir/data-rtl da app web). Antes de criar widgets.
        app.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl(i18n.current_lang()) else Qt.LeftToRight)
        # China-friendly: sonda o backend e comuta p/ réplica Cloudflare se a Vercel
        # estiver bloqueada (Great Firewall). TEM de ser antes de MainWindow (o
        # ExpressionMiner fixa LEXIO_API na construção).
        _select_backend()
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
        # Garante que a língua atual da UI — mesmo as não-embutidas (ex.: Farsi) —
        # tem TODAS as strings: preenche em background, na cache, só as chaves que
        # faltarem (ex.: exercícios novos) e avisa para reiniciar se preencheu algo.
        def _ui_topup():
            try:
                if topup_ui_via_ai(i18n.current_lang()):
                    gui_call(lambda: showToast(T("lang_topup_ready"), "accent", 5000))
            except Exception as _e:
                log(f"ui topup startup: {_e}")
        threading.Thread(target=_ui_topup, daemon=True).start()
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
