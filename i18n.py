# -*- coding: utf-8 -*-
"""
i18n do Lexio Study Player.

A UI do player era 100% em português fixo. Este módulo dá-lhe tradução para as
mesmas 12 línguas da app web (en, pt, es, fr, de, it, nl, zh, ja, ko, ru, ar).

Uso:
    from i18n import T, set_lang, native_language_name
    set_lang("en")            # define a língua da UI (herdada da conta web)
    btn.setText(T("add_vocab"))

Resolução de string: língua atual -> inglês -> a própria chave. Por isso uma
chave sem tradução numa língua cai para inglês (nunca fica partida).
"""

SUPPORTED = ["en", "pt", "es", "fr", "de", "it", "nl", "zh", "ja", "ko", "ru", "ar"]

# Nome de cada língua para usar nos prompts da IA (dicionário/chat) — "in <X>".
# A native do utilizador entra aqui para as traduções saírem na língua certa.
LANG_NAMES = {
    "en": "English", "pt": "European Portuguese", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "nl": "Dutch", "zh": "Mandarin Chinese",
    "ja": "Japanese", "ko": "Korean", "ru": "Russian", "ar": "Arabic",
}

import os, json

_current = "en"
_native = "pt"        # língua nativa do utilizador (para o conteúdo da IA)
_extra = {}           # code -> {key: str}  traduções da IA (línguas não embutidas)
_cache_dir = None     # onde guardar as traduções da IA


def _norm(code):
    return str(code or "").lower().replace("_", "-").split("-")[0]


def set_cache_dir(path):
    global _cache_dir
    _cache_dir = path
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _cache_file(code):
    return os.path.join(_cache_dir, "ui_%s.json" % code) if _cache_dir else None


def has_language(code):
    """True se a língua tem tradução disponível: embutida, em memória, ou em cache."""
    code = _norm(code)
    if code in SUPPORTED or code in _extra:
        return True
    f = _cache_file(code)
    if f and os.path.exists(f):
        try:
            _extra[code] = json.load(open(f, encoding="utf-8"))
            return True
        except Exception:
            pass
    return False


def register_translations(code, mapping, persist=True):
    """Regista (e guarda) traduções geradas pela IA para uma língua não embutida."""
    code = _norm(code)
    if not isinstance(mapping, dict):
        return
    _extra[code] = mapping
    if persist and _cache_dir:
        try:
            json.dump(mapping, open(_cache_file(code), "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass


def base_strings():
    """Strings EN base (chave -> texto) para enviar à IA traduzir."""
    return {k: v.get("en", k) for k, v in STRINGS.items()}


def set_lang(code):
    """Define a língua da UI. Aceita 'pt-PT' etc. Carrega cache se existir."""
    global _current
    code = _norm(code)
    if not code:
        return
    if code in SUPPORTED or has_language(code):
        _current = code
    # senão: mantém a atual (o player pede tradução IA e volta a chamar set_lang)


def set_native(code):
    global _native
    if code:
        _native = _norm(code)


def current_lang():
    return _current


def native_language_name():
    """Nome da língua nativa do utilizador para os prompts da IA."""
    return LANG_NAMES.get(_native, "English")


def T(key, **fmt):
    entry = STRINGS.get(key)
    # 1) embutida na língua atual  2) tradução IA (cache)  3) inglês  4) chave
    s = None
    if entry:
        s = entry.get(_current)
    if s is None:
        s = _extra.get(_current, {}).get(key)
    if s is None and entry:
        s = entry.get("en")
    if s is None:
        s = key
    if fmt:
        try:
            return s.format(**fmt)
        except Exception:
            return s
    return s


# ── Tabela de traduções ──────────────────────────────────────────────────────
# Uma chave por string visível. Ordem das línguas: en, pt, es, fr, de, it, nl,
# zh, ja, ko, ru, ar. Strings curtas de UI (alta frequência) — traduzidas com
# cuidado; placeholders {x} preservados em todas as línguas.
STRINGS = {
    # — Cabeçalho / janela —
    "player": {"en": "Player", "pt": "Player", "es": "Reproductor", "fr": "Lecteur",
               "de": "Player", "it": "Player", "nl": "Speler", "zh": "播放器",
               "ja": "プレーヤー", "ko": "플레이어", "ru": "Плеер", "ar": "المشغّل"},
    "open_video": {"en": "Open", "pt": "Abrir", "es": "Abrir", "fr": "Ouvrir",
                   "de": "Öffnen", "it": "Apri", "nl": "Openen", "zh": "打开",
                   "ja": "開く", "ko": "열기", "ru": "Открыть", "ar": "فتح"},
    "open_video_tip": {"en": "Open video (Ctrl+O)", "pt": "Abrir vídeo (Ctrl+O)",
                       "es": "Abrir vídeo (Ctrl+O)", "fr": "Ouvrir une vidéo (Ctrl+O)",
                       "de": "Video öffnen (Strg+O)", "it": "Apri video (Ctrl+O)",
                       "nl": "Video openen (Ctrl+O)", "zh": "打开视频 (Ctrl+O)",
                       "ja": "動画を開く (Ctrl+O)", "ko": "동영상 열기 (Ctrl+O)",
                       "ru": "Открыть видео (Ctrl+O)", "ar": "فتح فيديو (Ctrl+O)"},
    "ready": {"en": "Ready", "pt": "Pronto", "es": "Listo", "fr": "Prêt",
              "de": "Bereit", "it": "Pronto", "nl": "Gereed", "zh": "就绪",
              "ja": "準備完了", "ko": "준비됨", "ru": "Готово", "ar": "جاهز"},
    "open_first": {"en": "Open a video first", "pt": "Abre um vídeo primeiro",
                   "es": "Abre un vídeo primero", "fr": "Ouvre d'abord une vidéo",
                   "de": "Öffne zuerst ein Video", "it": "Apri prima un video",
                   "nl": "Open eerst een video", "zh": "请先打开视频",
                   "ja": "先に動画を開いてください", "ko": "먼저 동영상을 여세요",
                   "ru": "Сначала откройте видео", "ar": "افتح فيديو أولاً"},

    # — Chat —
    "chat_ai": {"en": "AI Chat", "pt": "Chat IA", "es": "Chat IA", "fr": "Chat IA",
                "de": "KI-Chat", "it": "Chat IA", "nl": "AI-chat", "zh": "AI 聊天",
                "ja": "AIチャット", "ko": "AI 채팅", "ru": "ИИ-чат", "ar": "دردشة الذكاء"},
    "chat_toggle_tip": {"en": "Show/hide AI Chat", "pt": "Mostrar/esconder Chat IA",
                        "es": "Mostrar/ocultar Chat IA", "fr": "Afficher/masquer le Chat IA",
                        "de": "KI-Chat ein-/ausblenden", "it": "Mostra/nascondi Chat IA",
                        "nl": "AI-chat tonen/verbergen", "zh": "显示/隐藏 AI 聊天",
                        "ja": "AIチャットの表示/非表示", "ko": "AI 채팅 표시/숨기기",
                        "ru": "Показать/скрыть ИИ-чат", "ar": "إظهار/إخفاء دردشة الذكاء"},
    "chat_toggle_tip_c": {"en": "Show/hide AI Chat (C)", "pt": "Mostrar/esconder Chat IA (C)",
                          "es": "Mostrar/ocultar Chat IA (C)", "fr": "Afficher/masquer le Chat IA (C)",
                          "de": "KI-Chat ein-/ausblenden (C)", "it": "Mostra/nascondi Chat IA (C)",
                          "nl": "AI-chat tonen/verbergen (C)", "zh": "显示/隐藏 AI 聊天 (C)",
                          "ja": "AIチャットの表示/非表示 (C)", "ko": "AI 채팅 표시/숨기기 (C)",
                          "ru": "Показать/скрыть ИИ-чат (C)", "ar": "إظهار/إخفاء دردشة الذكاء (C)"},
    "chat_placeholder": {"en": "Ask...", "pt": "Pergunta...", "es": "Pregunta...",
                         "fr": "Pose ta question...", "de": "Frage...", "it": "Chiedi...",
                         "nl": "Vraag...", "zh": "提问...", "ja": "質問...",
                         "ko": "질문...", "ru": "Спросите...", "ar": "اسأل..."},
    "thinking": {"en": "Thinking...", "pt": "A pensar...", "es": "Pensando...",
                 "fr": "Réflexion...", "de": "Denke nach...", "it": "Sto pensando...",
                 "nl": "Aan het denken...", "zh": "思考中...", "ja": "考え中...",
                 "ko": "생각 중...", "ru": "Думаю...", "ar": "جارٍ التفكير..."},
    "ask_ai": {"en": "Ask the AI", "pt": "Perguntar à IA", "es": "Preguntar a la IA",
               "fr": "Demander à l'IA", "de": "KI fragen", "it": "Chiedi all'IA",
               "nl": "Vraag de AI", "zh": "询问 AI", "ja": "AIに質問",
               "ko": "AI에게 묻기", "ru": "Спросить ИИ", "ar": "اسأل الذكاء"},

    # — Login / conta —
    "login": {"en": "Login", "pt": "Login", "es": "Entrar", "fr": "Connexion",
              "de": "Anmelden", "it": "Accedi", "nl": "Inloggen", "zh": "登录",
              "ja": "ログイン", "ko": "로그인", "ru": "Войти", "ar": "تسجيل الدخول"},
    "account": {"en": "Account", "pt": "Conta", "es": "Cuenta", "fr": "Compte",
                "de": "Konto", "it": "Account", "nl": "Account", "zh": "账户",
                "ja": "アカウント", "ko": "계정", "ru": "Аккаунт", "ar": "الحساب"},
    "login_google": {"en": "Sign in with Google", "pt": "Iniciar sessão com Google",
                     "es": "Iniciar sesión con Google", "fr": "Se connecter avec Google",
                     "de": "Mit Google anmelden", "it": "Accedi con Google",
                     "nl": "Inloggen met Google", "zh": "使用 Google 登录",
                     "ja": "Google でログイン", "ko": "Google로 로그인",
                     "ru": "Войти через Google", "ar": "تسجيل الدخول عبر Google"},
    "login_title": {"en": "Lexio — Sign In", "pt": "Lexio — Iniciar Sessão",
                    "es": "Lexio — Iniciar sesión", "fr": "Lexio — Connexion",
                    "de": "Lexio — Anmelden", "it": "Lexio — Accedi",
                    "nl": "Lexio — Inloggen", "zh": "Lexio — 登录",
                    "ja": "Lexio — ログイン", "ko": "Lexio — 로그인",
                    "ru": "Lexio — Вход", "ar": "Lexio — تسجيل الدخول"},
    "login_open_browser": {"en": "Opening the browser to sign in with Google...",
                           "pt": "A abrir o browser para iniciares sessão com o Google...",
                           "es": "Abriendo el navegador para iniciar sesión con Google...",
                           "fr": "Ouverture du navigateur pour se connecter avec Google...",
                           "de": "Browser wird zum Anmelden mit Google geöffnet...",
                           "it": "Apertura del browser per accedere con Google...",
                           "nl": "Browser wordt geopend om met Google in te loggen...",
                           "zh": "正在打开浏览器以使用 Google 登录...",
                           "ja": "Google でログインするためブラウザを開いています...",
                           "ko": "Google 로그인을 위해 브라우저를 여는 중...",
                           "ru": "Открываю браузер для входа через Google...",
                           "ar": "جارٍ فتح المتصفح لتسجيل الدخول عبر Google..."},
    "login_connected": {"en": "Account connected successfully!", "pt": "Conta conectada com sucesso!",
                        "es": "¡Cuenta conectada con éxito!", "fr": "Compte connecté avec succès !",
                        "de": "Konto erfolgreich verbunden!", "it": "Account collegato con successo!",
                        "nl": "Account succesvol verbonden!", "zh": "账户连接成功！",
                        "ja": "アカウントが正常に接続されました！", "ko": "계정이 성공적으로 연결되었습니다!",
                        "ru": "Аккаунт успешно подключён!", "ar": "تم ربط الحساب بنجاح!"},
    "login_failed": {"en": "Login failed: {err}", "pt": "Login falhou: {err}",
                     "es": "Error al iniciar sesión: {err}", "fr": "Échec de connexion : {err}",
                     "de": "Anmeldung fehlgeschlagen: {err}", "it": "Accesso non riuscito: {err}",
                     "nl": "Inloggen mislukt: {err}", "zh": "登录失败：{err}",
                     "ja": "ログインに失敗しました：{err}", "ko": "로그인 실패: {err}",
                     "ru": "Ошибка входа: {err}", "ar": "فشل تسجيل الدخول: {err}"},
    "login_cancelled": {"en": "Login cancelled or expired. Try again.",
                        "pt": "Login cancelado ou expirado. Tenta novamente.",
                        "es": "Inicio de sesión cancelado o caducado. Inténtalo de nuevo.",
                        "fr": "Connexion annulée ou expirée. Réessaie.",
                        "de": "Anmeldung abgebrochen oder abgelaufen. Versuche es erneut.",
                        "it": "Accesso annullato o scaduto. Riprova.",
                        "nl": "Inloggen geannuleerd of verlopen. Probeer opnieuw.",
                        "zh": "登录已取消或已过期。请重试。",
                        "ja": "ログインがキャンセルまたは期限切れです。もう一度お試しください。",
                        "ko": "로그인이 취소되었거나 만료되었습니다. 다시 시도하세요.",
                        "ru": "Вход отменён или истёк. Попробуйте снова.",
                        "ar": "تم إلغاء تسجيل الدخول أو انتهت صلاحيته. حاول مرة أخرى."},
    "session_ended": {"en": "Session ended.", "pt": "Sessão terminada.",
                      "es": "Sesión finalizada.", "fr": "Session terminée.",
                      "de": "Sitzung beendet.", "it": "Sessione terminata.",
                      "nl": "Sessie beëindigd.", "zh": "会话已结束。",
                      "ja": "セッションが終了しました。", "ko": "세션이 종료되었습니다.",
                      "ru": "Сеанс завершён.", "ar": "انتهت الجلسة."},

    # — Detalhes (sidebar) —
    "details": {"en": "Details", "pt": "Detalhes", "es": "Detalles", "fr": "Détails",
                "de": "Details", "it": "Dettagli", "nl": "Details", "zh": "详情",
                "ja": "詳細", "ko": "세부정보", "ru": "Подробности", "ar": "التفاصيل"},
    "loading_details": {"en": "Loading details…", "pt": "A carregar detalhes…",
                        "es": "Cargando detalles…", "fr": "Chargement des détails…",
                        "de": "Details werden geladen…", "it": "Caricamento dettagli…",
                        "nl": "Details laden…", "zh": "正在加载详情…",
                        "ja": "詳細を読み込み中…", "ko": "세부정보 불러오는 중…",
                        "ru": "Загрузка сведений…", "ar": "جارٍ تحميل التفاصيل…"},
    "details_failed": {"en": "Couldn't load the details.", "pt": "Não consegui carregar os detalhes.",
                       "es": "No se pudieron cargar los detalles.", "fr": "Impossible de charger les détails.",
                       "de": "Details konnten nicht geladen werden.", "it": "Impossibile caricare i dettagli.",
                       "nl": "Kon de details niet laden.", "zh": "无法加载详情。",
                       "ja": "詳細を読み込めませんでした。", "ko": "세부정보를 불러올 수 없습니다.",
                       "ru": "Не удалось загрузить сведения.", "ar": "تعذّر تحميل التفاصيل."},
    "example": {"en": "EXAMPLE", "pt": "EXEMPLO", "es": "EJEMPLO", "fr": "EXEMPLE",
                "de": "BEISPIEL", "it": "ESEMPIO", "nl": "VOORBEELD", "zh": "例句",
                "ja": "例文", "ko": "예문", "ru": "ПРИМЕР", "ar": "مثال"},
    "synonyms": {"en": "SYNONYMS", "pt": "SINÓNIMOS", "es": "SINÓNIMOS", "fr": "SYNONYMES",
                 "de": "SYNONYME", "it": "SINONIMI", "nl": "SYNONIEMEN", "zh": "同义词",
                 "ja": "類義語", "ko": "유의어", "ru": "СИНОНИМЫ", "ar": "مرادفات"},
    "collocations": {"en": "COLLOCATIONS", "pt": "COLOCAÇÕES", "es": "COLOCACIONES",
                     "fr": "COLLOCATIONS", "de": "KOLLOKATIONEN", "it": "COLLOCAZIONI",
                     "nl": "COLLOCATIES", "zh": "搭配", "ja": "コロケーション",
                     "ko": "연어", "ru": "СОЧЕТАНИЯ", "ar": "المتلازمات"},
    "note": {"en": "NOTE", "pt": "NOTA", "es": "NOTA", "fr": "NOTE", "de": "HINWEIS",
             "it": "NOTA", "nl": "NOTITIE", "zh": "注释", "ja": "メモ", "ko": "메모",
             "ru": "ЗАМЕТКА", "ar": "ملاحظة"},
    "listen": {"en": "Listen", "pt": "Ouvir", "es": "Escuchar", "fr": "Écouter",
               "de": "Anhören", "it": "Ascolta", "nl": "Luister", "zh": "朗读",
               "ja": "聞く", "ko": "듣기", "ru": "Слушать", "ar": "استماع"},
    "yg_tip": {"en": "Hear it pronounced in context on YouGlish",
               "pt": "Ouvir pronúncia em contexto no YouGlish",
               "es": "Oír la pronunciación en contexto en YouGlish",
               "fr": "Écouter la prononciation en contexte sur YouGlish",
               "de": "Aussprache im Kontext auf YouGlish hören",
               "it": "Ascolta la pronuncia in contesto su YouGlish",
               "nl": "Hoor de uitspraak in context op YouGlish",
               "zh": "在 YouGlish 上听语境发音",
               "ja": "YouGlish で文脈の発音を聞く",
               "ko": "YouGlish에서 문맥 속 발음 듣기",
               "ru": "Услышать произношение в контексте на YouGlish",
               "ar": "استمع إلى النطق في سياقه على YouGlish"},
    "gen_image": {"en": "Generating example image…", "pt": "A gerar imagem do exemplo…",
                  "es": "Generando imagen del ejemplo…", "fr": "Génération de l'image…",
                  "de": "Beispielbild wird erstellt…", "it": "Generazione immagine…",
                  "nl": "Voorbeeldafbeelding genereren…", "zh": "正在生成示例图片…",
                  "ja": "例の画像を生成中…", "ko": "예시 이미지 생성 중…",
                  "ru": "Создаю изображение…", "ar": "جارٍ إنشاء صورة المثال…"},
    "no_image": {"en": "(no image)", "pt": "(sem imagem)", "es": "(sin imagen)",
                 "fr": "(pas d'image)", "de": "(kein Bild)", "it": "(nessuna immagine)",
                 "nl": "(geen afbeelding)", "zh": "（无图片）", "ja": "（画像なし）",
                 "ko": "(이미지 없음)", "ru": "(нет изображения)", "ar": "(لا توجد صورة)"},
    "add_vocab": {"en": "Add to my vocabulary", "pt": "Adicionar ao meu vocabulário",
                  "es": "Añadir a mi vocabulario", "fr": "Ajouter à mon vocabulaire",
                  "de": "Zu meinem Wortschatz hinzufügen", "it": "Aggiungi al mio vocabolario",
                  "nl": "Aan mijn woordenschat toevoegen", "zh": "添加到我的词汇",
                  "ja": "自分の語彙に追加", "ko": "내 어휘에 추가",
                  "ru": "Добавить в мой словарь", "ar": "أضف إلى مفرداتي"},

    # — Controlos / transporte —
    "prev_p": {"en": "Previous (P)", "pt": "Anterior (P)", "es": "Anterior (P)",
               "fr": "Précédent (P)", "de": "Zurück (P)", "it": "Precedente (P)",
               "nl": "Vorige (P)", "zh": "上一个 (P)", "ja": "前へ (P)",
               "ko": "이전 (P)", "ru": "Назад (P)", "ar": "السابق (P)"},
    "next_n": {"en": "Next (N)", "pt": "Seguinte (N)", "es": "Siguiente (N)",
               "fr": "Suivant (N)", "de": "Weiter (N)", "it": "Successivo (N)",
               "nl": "Volgende (N)", "zh": "下一个 (N)", "ja": "次へ (N)",
               "ko": "다음 (N)", "ru": "Вперёд (N)", "ar": "التالي (N)"},
    "load_sub_tip": {"en": "Load subtitle (.srt)", "pt": "Carregar legenda (.srt)",
                     "es": "Cargar subtítulo (.srt)", "fr": "Charger un sous-titre (.srt)",
                     "de": "Untertitel laden (.srt)", "it": "Carica sottotitolo (.srt)",
                     "nl": "Ondertitel laden (.srt)", "zh": "加载字幕 (.srt)",
                     "ja": "字幕を読み込む (.srt)", "ko": "자막 불러오기 (.srt)",
                     "ru": "Загрузить субтитры (.srt)", "ar": "تحميل ترجمة (.srt)"},
    "fullscreen_f": {"en": "Fullscreen (F)", "pt": "Ecrã inteiro (F)", "es": "Pantalla completa (F)",
                     "fr": "Plein écran (F)", "de": "Vollbild (F)", "it": "Schermo intero (F)",
                     "nl": "Volledig scherm (F)", "zh": "全屏 (F)", "ja": "全画面 (F)",
                     "ko": "전체 화면 (F)", "ru": "Во весь экран (F)", "ar": "ملء الشاشة (F)"},
    "exit_fullscreen": {"en": "Exit fullscreen [Esc]", "pt": "Sair do ecrã inteiro [Esc]",
                        "es": "Salir de pantalla completa [Esc]", "fr": "Quitter le plein écran [Esc]",
                        "de": "Vollbild beenden [Esc]", "it": "Esci da schermo intero [Esc]",
                        "nl": "Volledig scherm afsluiten [Esc]", "zh": "退出全屏 [Esc]",
                        "ja": "全画面を終了 [Esc]", "ko": "전체 화면 종료 [Esc]",
                        "ru": "Выйти из полноэкранного режима [Esc]", "ar": "إنهاء ملء الشاشة [Esc]"},
    "study_mode_esc": {"en": "Study Mode — Esc to exit", "pt": "Modo Estudo — Esc para sair",
                       "es": "Modo Estudio — Esc para salir", "fr": "Mode Étude — Échap pour quitter",
                       "de": "Lernmodus — Esc zum Beenden", "it": "Modalità Studio — Esc per uscire",
                       "nl": "Studiemodus — Esc om te sluiten", "zh": "学习模式 — 按 Esc 退出",
                       "ja": "学習モード — Esc で終了", "ko": "학습 모드 — Esc로 종료",
                       "ru": "Режим обучения — Esc для выхода", "ar": "وضع الدراسة — Esc للخروج"},
    "sub_toggle_tip": {"en": "Click to toggle", "pt": "Clicar para alternar",
                       "es": "Clic para alternar", "fr": "Cliquer pour basculer",
                       "de": "Zum Umschalten klicken", "it": "Clicca per alternare",
                       "nl": "Klik om te wisselen", "zh": "点击切换", "ja": "クリックで切替",
                       "ko": "클릭하여 전환", "ru": "Нажмите для переключения", "ar": "انقر للتبديل"},

    # — Barra de prática —
    "practice": {"en": "Practice", "pt": "Prática", "es": "Práctica", "fr": "Pratique",
                 "de": "Übung", "it": "Pratica", "nl": "Oefening", "zh": "练习",
                 "ja": "練習", "ko": "연습", "ru": "Практика", "ar": "تدريب"},
    "repeat": {"en": "Repeat", "pt": "Repetir", "es": "Repetir", "fr": "Répéter",
               "de": "Wiederholen", "it": "Ripeti", "nl": "Herhalen", "zh": "重复",
               "ja": "リピート", "ko": "반복", "ru": "Повтор", "ar": "تكرار"},
    "previous": {"en": "Previous", "pt": "Anterior", "es": "Anterior", "fr": "Précédent",
                 "de": "Zurück", "it": "Precedente", "nl": "Vorige", "zh": "上一句",
                 "ja": "前へ", "ko": "이전", "ru": "Назад", "ar": "السابق"},
    "next": {"en": "Next", "pt": "Seguinte", "es": "Siguiente", "fr": "Suivant",
             "de": "Weiter", "it": "Successivo", "nl": "Volgende", "zh": "下一句",
             "ja": "次へ", "ko": "다음", "ru": "Вперёд", "ar": "التالي"},
    "loop": {"en": "Loop", "pt": "Loop", "es": "Bucle", "fr": "Boucle", "de": "Schleife",
             "it": "Loop", "nl": "Herhaling", "zh": "循环", "ja": "ループ", "ko": "반복 재생",
             "ru": "Повтор", "ar": "تكرار"},
    "autopause": {"en": "Auto-pause", "pt": "Auto-pausa", "es": "Auto-pausa", "fr": "Pause auto",
                  "de": "Auto-Pause", "it": "Pausa auto", "nl": "Auto-pauze", "zh": "自动暂停",
                  "ja": "自動一時停止", "ko": "자동 일시정지", "ru": "Авто-пауза", "ar": "إيقاف تلقائي"},
    "hide_sub": {"en": "Hide subtitle", "pt": "Esconder legenda", "es": "Ocultar subtítulo",
                 "fr": "Masquer le sous-titre", "de": "Untertitel ausblenden", "it": "Nascondi sottotitolo",
                 "nl": "Ondertitel verbergen", "zh": "隐藏字幕", "ja": "字幕を隠す",
                 "ko": "자막 숨기기", "ru": "Скрыть субтитры", "ar": "إخفاء الترجمة"},
    "loop_on": {"en": "Sentence loop on", "pt": "Loop da frase ligado",
                "es": "Bucle de frase activado", "fr": "Boucle de phrase activée",
                "de": "Satzschleife an", "it": "Loop della frase attivo",
                "nl": "Zinsherhaling aan", "zh": "句子循环已开启",
                "ja": "文のループ オン", "ko": "문장 반복 켜짐",
                "ru": "Повтор фразы включён", "ar": "تكرار الجملة مفعّل"},
    "loop_off": {"en": "Loop off", "pt": "Loop desligado", "es": "Bucle desactivado",
                 "fr": "Boucle désactivée", "de": "Schleife aus", "it": "Loop disattivato",
                 "nl": "Herhaling uit", "zh": "循环已关闭", "ja": "ループ オフ",
                 "ko": "반복 꺼짐", "ru": "Повтор выключен", "ar": "التكرار متوقّف"},
    "loop_need_sub": {"en": "Load a subtitle (.srt) to use the loop",
                      "pt": "Carrega uma legenda (.srt) para usar o loop",
                      "es": "Carga un subtítulo (.srt) para usar el bucle",
                      "fr": "Charge un sous-titre (.srt) pour la boucle",
                      "de": "Lade einen Untertitel (.srt) für die Schleife",
                      "it": "Carica un sottotitolo (.srt) per usare il loop",
                      "nl": "Laad een ondertitel (.srt) om de herhaling te gebruiken",
                      "zh": "请加载字幕 (.srt) 以使用循环",
                      "ja": "ループを使うには字幕 (.srt) を読み込んでください",
                      "ko": "반복을 사용하려면 자막(.srt)을 불러오세요",
                      "ru": "Загрузите субтитры (.srt) для повтора",
                      "ar": "حمّل ترجمة (.srt) لاستخدام التكرار"},
    "loop_no_line": {"en": "No line on screen — turn Loop on during a subtitle",
                     "pt": "Sem frase no ecrã — liga o Loop durante uma legenda",
                     "es": "Sin frase en pantalla — activa el bucle durante un subtítulo",
                     "fr": "Aucune phrase à l'écran — active la boucle pendant un sous-titre",
                     "de": "Kein Satz auf dem Bildschirm — Schleife während eines Untertitels einschalten",
                     "it": "Nessuna frase sullo schermo — attiva il loop durante un sottotitolo",
                     "nl": "Geen zin op het scherm — zet Herhaling aan tijdens een ondertitel",
                     "zh": "屏幕上没有字幕句 — 在字幕出现时开启循环",
                     "ja": "画面に文がありません — 字幕表示中にループをオンにしてください",
                     "ko": "화면에 문장이 없습니다 — 자막이 나올 때 반복을 켜세요",
                     "ru": "Нет фразы на экране — включите повтор во время субтитра",
                     "ar": "لا توجد جملة على الشاشة — فعّل التكرار أثناء الترجمة"},
    "autopause_on": {"en": "Per-sentence auto-pause: on", "pt": "Auto-pausa por frase: ligada",
                     "es": "Auto-pausa por frase: activada", "fr": "Pause auto par phrase : activée",
                     "de": "Auto-Pause pro Satz: an", "it": "Pausa automatica per frase: attiva",
                     "nl": "Auto-pauze per zin: aan", "zh": "逐句自动暂停：开启",
                     "ja": "文ごとの自動一時停止：オン", "ko": "문장별 자동 일시정지: 켜짐",
                     "ru": "Авто-пауза по фразам: вкл.", "ar": "إيقاف تلقائي لكل جملة: مفعّل"},
    "loop_mark_a": {"en": "Mark A first (and B must be after A)",
                    "pt": "Marca primeiro A (e B tem de ser depois de A)",
                    "es": "Marca primero A (y B debe ir después de A)",
                    "fr": "Marque d'abord A (et B doit être après A)",
                    "de": "Zuerst A markieren (und B muss nach A liegen)",
                    "it": "Segna prima A (e B deve essere dopo A)",
                    "nl": "Markeer eerst A (en B moet na A komen)",
                    "zh": "先标记 A（且 B 必须在 A 之后）",
                    "ja": "先に A を設定（B は A の後）",
                    "ko": "먼저 A를 표시하세요 (B는 A 다음이어야 함)",
                    "ru": "Сначала отметьте A (B должно быть после A)",
                    "ar": "حدّد A أولاً (ويجب أن يكون B بعد A)"},

    # — Legendas —
    "sub_active": {"en": "Subtitle on", "pt": "Legenda ativa", "es": "Subtítulo activo",
                   "fr": "Sous-titre activé", "de": "Untertitel an", "it": "Sottotitolo attivo",
                   "nl": "Ondertitel aan", "zh": "字幕已开启", "ja": "字幕オン",
                   "ko": "자막 켜짐", "ru": "Субтитры вкл.", "ar": "الترجمة مفعّلة"},
    "sub_off": {"en": "Subtitles off", "pt": "Legendas desligadas", "es": "Subtítulos desactivados",
                "fr": "Sous-titres désactivés", "de": "Untertitel aus", "it": "Sottotitoli disattivati",
                "nl": "Ondertitels uit", "zh": "字幕已关闭", "ja": "字幕オフ",
                "ko": "자막 꺼짐", "ru": "Субтитры выкл.", "ar": "الترجمة متوقّفة"},
    "no_subs": {"en": "No subtitles", "pt": "Sem legendas", "es": "Sin subtítulos",
                "fr": "Aucun sous-titre", "de": "Keine Untertitel", "it": "Nessun sottotitolo",
                "nl": "Geen ondertitels", "zh": "无字幕", "ja": "字幕なし",
                "ko": "자막 없음", "ru": "Нет субтитров", "ar": "لا توجد ترجمة"},
    "sub_load_fail": {"en": "Failed to load subtitle", "pt": "Falha ao carregar legenda",
                      "es": "Error al cargar el subtítulo", "fr": "Échec du chargement du sous-titre",
                      "de": "Untertitel konnte nicht geladen werden", "it": "Impossibile caricare il sottotitolo",
                      "nl": "Ondertitel laden mislukt", "zh": "字幕加载失败",
                      "ja": "字幕の読み込みに失敗", "ko": "자막 불러오기 실패",
                      "ru": "Не удалось загрузить субтитры", "ar": "فشل تحميل الترجمة"},
    "sub_hidden": {"en": "Subtitle hidden (move mouse to the bottom to see it)",
                   "pt": "Legenda escondida (rato em baixo para ver)",
                   "es": "Subtítulo oculto (mueve el ratón abajo para verlo)",
                   "fr": "Sous-titre masqué (place la souris en bas pour le voir)",
                   "de": "Untertitel ausgeblendet (Maus nach unten bewegen zum Anzeigen)",
                   "it": "Sottotitolo nascosto (sposta il mouse in basso per vederlo)",
                   "nl": "Ondertitel verborgen (beweeg de muis naar onder om te zien)",
                   "zh": "字幕已隐藏（将鼠标移到底部查看）",
                   "ja": "字幕を非表示（下にマウスを移動すると表示）",
                   "ko": "자막 숨김 (아래로 마우스를 옮기면 표시)",
                   "ru": "Субтитры скрыты (наведите мышь вниз, чтобы увидеть)",
                   "ar": "الترجمة مخفية (حرّك الفأرة للأسفل لرؤيتها)"},
    "load_sub_dialog": {"en": "Load subtitle", "pt": "Carregar legenda", "es": "Cargar subtítulo",
                        "fr": "Charger un sous-titre", "de": "Untertitel laden", "it": "Carica sottotitolo",
                        "nl": "Ondertitel laden", "zh": "加载字幕", "ja": "字幕を読み込む",
                        "ko": "자막 불러오기", "ru": "Загрузить субтитры", "ar": "تحميل الترجمة"},

    # — Abas (tools) —
    "tab_bookmarks": {"en": "Bookmarks", "pt": "Marcos", "es": "Marcadores", "fr": "Repères",
                      "de": "Lesezeichen", "it": "Segnalibri", "nl": "Bladwijzers", "zh": "书签",
                      "ja": "ブックマーク", "ko": "북마크", "ru": "Закладки", "ar": "العلامات"},
    "tab_videos": {"en": "Videos", "pt": "Vídeos", "es": "Vídeos", "fr": "Vidéos",
                   "de": "Videos", "it": "Video", "nl": "Video's", "zh": "视频",
                   "ja": "動画", "ko": "동영상", "ru": "Видео", "ar": "الفيديوهات"},
    "tab_notes": {"en": "Notes", "pt": "Notas", "es": "Notas", "fr": "Notes",
                  "de": "Notizen", "it": "Note", "nl": "Notities", "zh": "笔记",
                  "ja": "メモ", "ko": "노트", "ru": "Заметки", "ar": "الملاحظات"},
    "tab_playlist": {"en": "Playlist", "pt": "Playlist", "es": "Lista", "fr": "Playlist",
                     "de": "Playlist", "it": "Playlist", "nl": "Afspeellijst", "zh": "播放列表",
                     "ja": "プレイリスト", "ko": "재생목록", "ru": "Плейлист", "ar": "قائمة التشغيل"},
    "tab_tools": {"en": "Tools", "pt": "Ferramentas", "es": "Herramientas", "fr": "Outils",
                  "de": "Werkzeuge", "it": "Strumenti", "nl": "Hulpmiddelen", "zh": "工具",
                  "ja": "ツール", "ko": "도구", "ru": "Инструменты", "ar": "الأدوات"},
    "videos_vocab_title": {"en": "Videos vocabulary", "pt": "Vocabulário dos vídeos",
                           "es": "Vocabulario de los vídeos", "fr": "Vocabulaire des vidéos",
                           "de": "Video-Wortschatz", "it": "Vocabolario dei video",
                           "nl": "Videowoordenschat", "zh": "视频词汇",
                           "ja": "動画の語彙", "ko": "동영상 어휘",
                           "ru": "Словарь из видео", "ar": "مفردات الفيديوهات"},
    "videos_hint": {"en": "Words you saved with + in the player subtitles — only in this player, not your main vocabulary. Right-click a word to Add it to my vocabulary or Remove it.",
                    "pt": "Aqui ficam as palavras que guardaste com  +  nas legendas — só neste player, não no teu vocabulário principal. Clica com o botão direito numa palavra para a Adicionar ao meu vocabulário ou Remover.",
                    "es": "Palabras que guardaste con + en los subtítulos — solo en este reproductor, no en tu vocabulario principal. Haz clic derecho en una palabra para Añadirla a mi vocabulario o Quitarla.",
                    "fr": "Mots enregistrés avec + dans les sous-titres — seulement dans ce lecteur, pas dans ton vocabulaire principal. Clic droit sur un mot pour l'Ajouter à mon vocabulaire ou le Retirer.",
                    "de": "Wörter, die du mit + in den Untertiteln gespeichert hast — nur in diesem Player, nicht in deinem Hauptwortschatz. Rechtsklick auf ein Wort zum Hinzufügen oder Entfernen.",
                    "it": "Parole salvate con + nei sottotitoli — solo in questo player, non nel vocabolario principale. Clic destro su una parola per Aggiungerla al vocabolario o Rimuoverla.",
                    "nl": "Woorden die je met + in de ondertitels hebt opgeslagen — alleen in deze speler, niet in je hoofdwoordenschat. Rechtsklik op een woord om het toe te voegen of te verwijderen.",
                    "zh": "你在播放器字幕中用 + 保存的词 — 仅在此播放器中，不在主词汇里。右键单击词语可添加到我的词汇或移除。",
                    "ja": "プレーヤーの字幕で + で保存した単語 — このプレーヤー内のみで、メイン語彙には入りません。単語を右クリックして語彙に追加または削除できます。",
                    "ko": "플레이어 자막에서 +로 저장한 단어 — 이 플레이어에만 있고 기본 어휘에는 없습니다. 단어를 마우스 오른쪽 버튼으로 클릭해 어휘에 추가하거나 제거하세요.",
                    "ru": "Слова, сохранённые кнопкой + в субтитрах — только в этом плеере, не в основном словаре. Правый клик по слову — Добавить в словарь или Удалить.",
                    "ar": "كلمات حفظتها بزر + في الترجمة — في هذا المشغّل فقط، وليست في مفرداتك الأساسية. انقر بزر الفأرة الأيمن على كلمة لإضافتها إلى مفرداتي أو إزالتها."},
    "videos_empty": {"en": "No words yet. Press + on a subtitle while watching a video.",
                     "pt": "Ainda sem palavras. Carrega no  +  de uma legenda enquanto vês um vídeo.",
                     "es": "Aún no hay palabras. Pulsa + en un subtítulo mientras ves un vídeo.",
                     "fr": "Pas encore de mots. Appuie sur + sur un sous-titre en regardant une vidéo.",
                     "de": "Noch keine Wörter. Drücke + auf einem Untertitel während du ein Video ansiehst.",
                     "it": "Ancora nessuna parola. Premi + su un sottotitolo mentre guardi un video.",
                     "nl": "Nog geen woorden. Druk op + bij een ondertitel terwijl je een video kijkt.",
                     "zh": "还没有词语。观看视频时在字幕上点击 +。",
                     "ja": "まだ単語がありません。動画を見ながら字幕の + を押してください。",
                     "ko": "아직 단어가 없습니다. 동영상을 보면서 자막의 +를 누르세요.",
                     "ru": "Слов пока нет. Нажмите + на субтитре во время просмотра видео.",
                     "ar": "لا توجد كلمات بعد. اضغط + على ترجمة أثناء مشاهدة الفيديو."},
    "menu_add_vocab": {"en": "Add to my vocabulary", "pt": "Adicionar ao meu vocabulário",
                       "es": "Añadir a mi vocabulario", "fr": "Ajouter à mon vocabulaire",
                       "de": "Zu meinem Wortschatz hinzufügen", "it": "Aggiungi al mio vocabolario",
                       "nl": "Aan mijn woordenschat toevoegen", "zh": "添加到我的词汇",
                       "ja": "自分の語彙に追加", "ko": "내 어휘에 추가",
                       "ru": "Добавить в мой словарь", "ar": "أضف إلى مفرداتي"},
    "menu_remove": {"en": "Remove", "pt": "Remover", "es": "Quitar", "fr": "Retirer",
                    "de": "Entfernen", "it": "Rimuovi", "nl": "Verwijderen", "zh": "移除",
                    "ja": "削除", "ko": "제거", "ru": "Удалить", "ar": "إزالة"},
    "note_placeholder": {"en": "Note...", "pt": "Anotacao...", "es": "Nota...", "fr": "Note...",
                         "de": "Notiz...", "it": "Nota...", "nl": "Notitie...", "zh": "笔记...",
                         "ja": "メモ...", "ko": "메모...", "ru": "Заметка...", "ar": "ملاحظة..."},
    "tools_export": {"en": "Export study", "pt": "Exportar estudo", "es": "Exportar estudio",
                     "fr": "Exporter l'étude", "de": "Lernen exportieren", "it": "Esporta studio",
                     "nl": "Studie exporteren", "zh": "导出学习", "ja": "学習をエクスポート",
                     "ko": "학습 내보내기", "ru": "Экспорт занятий", "ar": "تصدير الدراسة"},
    "tools_updates": {"en": "Updates", "pt": "Atualizacoes", "es": "Actualizaciones",
                      "fr": "Mises à jour", "de": "Updates", "it": "Aggiornamenti",
                      "nl": "Updates", "zh": "更新", "ja": "更新", "ko": "업데이트",
                      "ru": "Обновления", "ar": "التحديثات"},
    "tools_data_folder": {"en": "Data folder", "pt": "Pasta de dados", "es": "Carpeta de datos",
                          "fr": "Dossier de données", "de": "Datenordner", "it": "Cartella dati",
                          "nl": "Gegevensmap", "zh": "数据文件夹", "ja": "データフォルダー",
                          "ko": "데이터 폴더", "ru": "Папка данных", "ar": "مجلد البيانات"},
    "tools_about": {"en": "About", "pt": "Sobre", "es": "Acerca de", "fr": "À propos",
                    "de": "Über", "it": "Informazioni", "nl": "Over", "zh": "关于",
                    "ja": "情報", "ko": "정보", "ru": "О программе", "ar": "حول"},

    # — Saved / sync —
    "saved_videos": {"en": "Videos", "pt": "Vídeos", "es": "Vídeos", "fr": "Vidéos",
                     "de": "Videos", "it": "Video", "nl": "Video's", "zh": "视频",
                     "ja": "動画", "ko": "동영상", "ru": "Видео", "ar": "الفيديوهات"},
    "saved_videos_web": {"en": "Videos + web (pending)", "pt": "Vídeos + web (pendente)",
                         "es": "Vídeos + web (pendiente)", "fr": "Vidéos + web (en attente)",
                         "de": "Videos + Web (ausstehend)", "it": "Video + web (in sospeso)",
                         "nl": "Video's + web (in afwachting)", "zh": "视频 + 网页（待定）",
                         "ja": "動画 + ウェブ（保留中）", "ko": "동영상 + 웹(대기 중)",
                         "ru": "Видео + веб (ожидает)", "ar": "الفيديوهات + الويب (قيد الانتظار)"},
    "saved_flash": {"en": "Saved · {where}", "pt": "Guardado · {where}", "es": "Guardado · {where}",
                    "fr": "Enregistré · {where}", "de": "Gespeichert · {where}", "it": "Salvato · {where}",
                    "nl": "Opgeslagen · {where}", "zh": "已保存 · {where}", "ja": "保存しました · {where}",
                    "ko": "저장됨 · {where}", "ru": "Сохранено · {where}", "ar": "تم الحفظ · {where}"},
    "saved_toast": {"en": "Saved in {where} — {text}", "pt": "Guardado em {where} — {text}",
                    "es": "Guardado en {where} — {text}", "fr": "Enregistré dans {where} — {text}",
                    "de": "Gespeichert in {where} — {text}", "it": "Salvato in {where} — {text}",
                    "nl": "Opgeslagen in {where} — {text}", "zh": "已保存到 {where} — {text}",
                    "ja": "{where} に保存 — {text}", "ko": "{where}에 저장됨 — {text}",
                    "ru": "Сохранено в {where} — {text}", "ar": "تم الحفظ في {where} — {text}"},
    "need_login_vocab": {"en": "Log in to add to your main vocabulary.",
                         "pt": "Faz login para adicionares ao teu vocabulário principal.",
                         "es": "Inicia sesión para añadir a tu vocabulario principal.",
                         "fr": "Connecte-toi pour ajouter à ton vocabulaire principal.",
                         "de": "Melde dich an, um zu deinem Hauptwortschatz hinzuzufügen.",
                         "it": "Accedi per aggiungere al tuo vocabolario principale.",
                         "nl": "Log in om aan je hoofdwoordenschat toe te voegen.",
                         "zh": "登录后即可添加到你的主词汇。",
                         "ja": "メイン語彙に追加するにはログインしてください。",
                         "ko": "기본 어휘에 추가하려면 로그인하세요.",
                         "ru": "Войдите, чтобы добавить в основной словарь.",
                         "ar": "سجّل الدخول للإضافة إلى مفرداتك الأساسية."},
}


# ── Línguas oferecidas no seletor do player ──────────────────────────────────
# As 12 primeiras são EMBUTIDAS (tradução completa). As restantes são traduzidas
# on-demand pela IA (deepseek) e guardadas em cache — por isso o player suporta
# basicamente qualquer língua. Nome em código ISO -> nome nativo (mostrado ao user).
LANGUAGE_CHOICES = [
    ("en", "English"), ("pt", "Português"), ("es", "Español"), ("fr", "Français"),
    ("de", "Deutsch"), ("it", "Italiano"), ("nl", "Nederlands"), ("zh", "中文"),
    ("ja", "日本語"), ("ko", "한국어"), ("ru", "Русский"), ("ar", "العربية"),
    # — traduzidas pela IA on-demand —
    ("hi", "हिन्दी"), ("bn", "বাংলা"), ("pa", "ਪੰਜਾਬੀ"), ("ur", "اردو"),
    ("id", "Bahasa Indonesia"), ("ms", "Bahasa Melayu"), ("vi", "Tiếng Việt"),
    ("th", "ไทย"), ("tr", "Türkçe"), ("pl", "Polski"), ("uk", "Українська"),
    ("ro", "Română"), ("el", "Ελληνικά"), ("cs", "Čeština"), ("sv", "Svenska"),
    ("da", "Dansk"), ("fi", "Suomi"), ("no", "Norsk"), ("hu", "Magyar"),
    ("he", "עברית"), ("fa", "فارسی"), ("sw", "Kiswahili"), ("yo", "Yorùbá"),
    ("ig", "Igbo"), ("ha", "Hausa"), ("zu", "isiZulu"), ("am", "አማርኛ"),
    ("ta", "தமிழ்"), ("te", "తెలుగు"), ("mr", "मराठी"), ("gu", "ગુજરાતી"),
    ("kn", "ಕನ್ನಡ"), ("ml", "മലയാളം"), ("fil", "Filipino"), ("my", "မြန်မာ"),
    ("km", "ខ្មែរ"), ("si", "සිංහල"), ("ne", "नेपाली"), ("sk", "Slovenčina"),
    ("bg", "Български"), ("hr", "Hrvatski"), ("sr", "Српски"), ("sl", "Slovenščina"),
    ("lt", "Lietuvių"), ("lv", "Latviešu"), ("et", "Eesti"), ("ca", "Català"),
    ("gl", "Galego"), ("eu", "Euskara"), ("af", "Afrikaans"), ("is", "Íslenska"),
    ("ga", "Gaeilge"), ("mt", "Malti"), ("sq", "Shqip"), ("hy", "Հայերեն"),
    ("ka", "ქართული"), ("az", "Azərbaycan"), ("kk", "Қазақ"), ("uz", "Oʻzbek"),
    ("mn", "Монгол"), ("lo", "ລາວ"),
]

# Nome em inglês de cada língua (para o prompt de tradução da IA).
LANGUAGE_EN_NAMES = {
    "hi": "Hindi", "bn": "Bengali", "pa": "Punjabi", "ur": "Urdu", "id": "Indonesian",
    "ms": "Malay", "vi": "Vietnamese", "th": "Thai", "tr": "Turkish", "pl": "Polish",
    "uk": "Ukrainian", "ro": "Romanian", "el": "Greek", "cs": "Czech", "sv": "Swedish",
    "da": "Danish", "fi": "Finnish", "no": "Norwegian", "hu": "Hungarian", "he": "Hebrew",
    "fa": "Persian", "sw": "Swahili", "yo": "Yoruba", "ig": "Igbo", "ha": "Hausa",
    "zu": "Zulu", "am": "Amharic", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
    "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "fil": "Filipino", "my": "Burmese",
    "km": "Khmer", "si": "Sinhala", "ne": "Nepali", "sk": "Slovak", "bg": "Bulgarian",
    "hr": "Croatian", "sr": "Serbian", "sl": "Slovenian", "lt": "Lithuanian", "lv": "Latvian",
    "et": "Estonian", "ca": "Catalan", "gl": "Galician", "eu": "Basque", "af": "Afrikaans",
    "is": "Icelandic", "ga": "Irish", "mt": "Maltese", "sq": "Albanian", "hy": "Armenian",
    "ka": "Georgian", "az": "Azerbaijani", "kk": "Kazakh", "uz": "Uzbek", "mn": "Mongolian",
    "lo": "Lao", "en": "English", "pt": "Portuguese", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "nl": "Dutch", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "ru": "Russian", "ar": "Arabic",
}

def language_display_name(code):
    code = _norm(code)
    for c, name in LANGUAGE_CHOICES:
        if c == code:
            return name
    return code

def language_en_name(code):
    return LANGUAGE_EN_NAMES.get(_norm(code), _norm(code))


# Chaves adicionais (seletor de idioma / restart) — via update p/ não mexer no literal.
STRINGS.update({
    "ui_language": {"en": "Interface language", "pt": "Idioma da interface",
                    "es": "Idioma de la interfaz", "fr": "Langue de l'interface",
                    "de": "Oberflächensprache", "it": "Lingua dell'interfaccia",
                    "nl": "Interfacetaal", "zh": "界面语言", "ja": "インターフェース言語",
                    "ko": "인터페이스 언어", "ru": "Язык интерфейса", "ar": "لغة الواجهة"},
    "lang_translating": {"en": "Translating the interface to {lang}…",
                         "pt": "A traduzir a interface para {lang}…",
                         "es": "Traduciendo la interfaz a {lang}…",
                         "fr": "Traduction de l'interface en {lang}…",
                         "de": "Oberfläche wird nach {lang} übersetzt…",
                         "it": "Traduzione dell'interfaccia in {lang}…",
                         "nl": "Interface wordt vertaald naar {lang}…",
                         "zh": "正在将界面翻译为 {lang}…", "ja": "インターフェースを {lang} に翻訳中…",
                         "ko": "인터페이스를 {lang}(으)로 번역 중…",
                         "ru": "Перевод интерфейса на {lang}…", "ar": "جارٍ ترجمة الواجهة إلى {lang}…"},
    "lang_failed": {"en": "Couldn't translate the interface. Try again later.",
                    "pt": "Não consegui traduzir a interface. Tenta mais tarde.",
                    "es": "No se pudo traducir la interfaz. Inténtalo más tarde.",
                    "fr": "Impossible de traduire l'interface. Réessaie plus tard.",
                    "de": "Oberfläche konnte nicht übersetzt werden. Versuche es später.",
                    "it": "Impossibile tradurre l'interfaccia. Riprova più tardi.",
                    "nl": "Kon de interface niet vertalen. Probeer later opnieuw.",
                    "zh": "无法翻译界面，请稍后再试。", "ja": "インターフェースを翻訳できませんでした。後でもう一度お試しください。",
                    "ko": "인터페이스를 번역할 수 없습니다. 나중에 다시 시도하세요.",
                    "ru": "Не удалось перевести интерфейс. Попробуйте позже.",
                    "ar": "تعذّرت ترجمة الواجهة. حاول لاحقًا."},
    "lang_restart_title": {"en": "Language changed", "pt": "Idioma alterado",
                           "es": "Idioma cambiado", "fr": "Langue modifiée",
                           "de": "Sprache geändert", "it": "Lingua cambiata",
                           "nl": "Taal gewijzigd", "zh": "语言已更改", "ja": "言語が変更されました",
                           "ko": "언어가 변경되었습니다", "ru": "Язык изменён", "ar": "تم تغيير اللغة"},
    "lang_restart_body": {"en": "Restart the player now to apply {lang}?",
                          "pt": "Reiniciar o player agora para aplicar {lang}?",
                          "es": "¿Reiniciar el reproductor ahora para aplicar {lang}?",
                          "fr": "Redémarrer le lecteur maintenant pour appliquer {lang} ?",
                          "de": "Player jetzt neu starten, um {lang} anzuwenden?",
                          "it": "Riavviare il player ora per applicare {lang}?",
                          "nl": "Speler nu herstarten om {lang} toe te passen?",
                          "zh": "立即重启播放器以应用 {lang}？", "ja": "{lang} を適用するために今すぐプレーヤーを再起動しますか？",
                          "ko": "{lang}을(를) 적용하려면 지금 플레이어를 다시 시작할까요?",
                          "ru": "Перезапустить плеер сейчас, чтобы применить {lang}?",
                          "ar": "إعادة تشغيل المشغّل الآن لتطبيق {lang}؟"},
    "restart_now": {"en": "Restart now", "pt": "Reiniciar agora", "es": "Reiniciar ahora",
                    "fr": "Redémarrer", "de": "Jetzt neu starten", "it": "Riavvia ora",
                    "nl": "Nu herstarten", "zh": "立即重启", "ja": "今すぐ再起動",
                    "ko": "지금 다시 시작", "ru": "Перезапустить", "ar": "إعادة التشغيل الآن"},
    "later": {"en": "Later", "pt": "Mais tarde", "es": "Más tarde", "fr": "Plus tard",
              "de": "Später", "it": "Più tardi", "nl": "Later", "zh": "稍后",
              "ja": "後で", "ko": "나중에", "ru": "Позже", "ar": "لاحقًا"},
})

STRINGS.update({
    "chat_welcome": {"en": "Ask about the video\n\nE.g.: \"Explain this concept\"\n\"Translate this part\"",
                     "pt": "Pergunta sobre o vídeo\n\nEx: \"Explica este conceito\"\n\"Traduz esta parte\"",
                     "es": "Pregunta sobre el vídeo\n\nEj.: \"Explica este concepto\"\n\"Traduce esta parte\"",
                     "fr": "Pose une question sur la vidéo\n\nEx. : \"Explique ce concept\"\n\"Traduis ce passage\"",
                     "de": "Frag etwas zum Video\n\nz. B.: \"Erkläre dieses Konzept\"\n\"Übersetze diesen Teil\"",
                     "it": "Chiedi sul video\n\nEs.: \"Spiega questo concetto\"\n\"Traduci questa parte\"",
                     "nl": "Vraag iets over de video\n\nBijv.: \"Leg dit concept uit\"\n\"Vertaal dit deel\"",
                     "zh": "就视频提问\n\n例如：“解释这个概念”\n“翻译这部分”",
                     "ja": "動画について質問\n\n例：「この概念を説明して」\n「この部分を翻訳して」",
                     "ko": "영상에 대해 질문하기\n\n예: \"이 개념을 설명해줘\"\n\"이 부분을 번역해줘\"",
                     "ru": "Спросите о видео\n\nНапр.: «Объясни это понятие»\n«Переведи эту часть»",
                     "ar": "اسأل عن الفيديو\n\nمثال: \"اشرح هذا المفهوم\"\n\"ترجم هذا الجزء\""},
    "login_loading": {"en": "Loading...", "pt": "A carregar...", "es": "Cargando...",
                      "fr": "Chargement...", "de": "Wird geladen...", "it": "Caricamento...",
                      "nl": "Laden...", "zh": "加载中...", "ja": "読み込み中...",
                      "ko": "불러오는 중...", "ru": "Загрузка...", "ar": "جارٍ التحميل..."},
    "login_contacting": {"en": "Contacting Lexio server...", "pt": "A contactar servidor Lexio...",
                         "es": "Contactando con el servidor de Lexio...", "fr": "Connexion au serveur Lexio...",
                         "de": "Verbindung zum Lexio-Server...", "it": "Connessione al server Lexio...",
                         "nl": "Verbinden met Lexio-server...", "zh": "正在连接 Lexio 服务器...",
                         "ja": "Lexio サーバーに接続中...", "ko": "Lexio 서버에 연결 중...",
                         "ru": "Подключение к серверу Lexio...", "ar": "جارٍ الاتصال بخادم Lexio..."},
})
