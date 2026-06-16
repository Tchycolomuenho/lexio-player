# ─── Lexio Scene Agent (brain) — porta do trabalho feito no lexio-app (React) ───
# Transforma o filme em treino ativo: deteta os melhores momentos das legendas e
# cria "missões" (assumir personagem, shadowing, boss de compreensão, raio-X
# gramatical, caça à gíria, advogado do diabo) e avalia a resposta do utilizador
# com IA real (DeepSeek, via o MESMO backend que o player já usa).
#
# Sem dependências de PyQt — só lógica + urllib, por isso é testável e a UI
# (lexio_player.py) só precisa de chamar build_scene_missions() e
# evaluate_scene_mission().

import json
import re
import time
import datetime
from pathlib import Path
from urllib.request import Request, urlopen

# Log partilhado com o player (para as falhas da IA deixarem de ser silenciosas).
_LOG = Path.home() / ".lexio-player" / "debug.log"


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%H:%M:%S}] scene_agent: {msg}\n")
    except Exception:
        pass


LEXIO_API_DEFAULT = "https://lexio-app-five.vercel.app"
# IA via OpenRouter (proxy /api/vision). DeepSeek-via-OpenRouter = barato + bom.
OPENROUTER_MODEL = "deepseek/deepseek-chat"

# ── Tipos de missão ──
KINDS = (
    "dialogue_takeover", "deep_shadowing", "boss_recap",
    "grammar_xray", "slang_miner", "devil_advocate",
    # Exercícios próprios do player (UI própria + avaliação dedicada): a IA
    # tece-os no decorrer do filme. O player routeia estes kinds para os seus
    # diálogos (Fluência, Paráfrase, Descrever cena/take), não para o genérico.
    "fluency_translate", "paraphrase_line", "describe_scene", "describe_take",
    "dialogue_roleplay",
)

# Kinds tratados pelos diálogos próprios do player (não pelo SceneMissionDialog).
PLAYER_EXERCISE_KINDS = frozenset((
    "fluency_translate", "paraphrase_line", "describe_scene", "describe_take",
    "dialogue_roleplay",
))

KIND_LABELS = {
    "dialogue_takeover": "Diálogo vivo",
    "deep_shadowing": "Shadowing",
    "boss_recap": "Boss",
    "grammar_xray": "Grammar X-ray",
    "slang_miner": "Caça à gíria",
    "devil_advocate": "Advogado do diabo",
    "fluency_translate": "Fluência",
    "paraphrase_line": "Paráfrase",
    "describe_scene": "Descrever cena",
    "describe_take": "Descrever take",
    "dialogue_roleplay": "Diálogo",
}

# light / balanced / god — quão agressivo é o agente a interromper o filme
MIN_GAP = {"light": 85, "balanced": 52, "god": 28}
MAX_MISSIONS = {"light": 10, "balanced": 18, "god": 34}

_SLANG_RE = re.compile(
    r"\b(gonna|wanna|gotta|ain't|kinda|sorta|dude|bro|buddy|hell|damn|crap|"
    r"screw|y'all|lemme|gimme|nah|yeah|yep|nope)\b", re.I)
_GRAMMAR_RE = re.compile(
    r"\b(would|could|should|might|must have|would have|could have|should have|"
    r"used to|going to|if|unless|although|even though|rather than|as if)\b", re.I)
_MORAL_RE = re.compile(
    r"\b(steal|lie|kill|betray|revenge|fault|blame|guilty|innocent|wrong|right|"
    r"deserve|forgive|trust|secret|promise)\b", re.I)


class SceneMission:
    __slots__ = ("id", "kind", "title", "label", "prompt", "timestamp",
                 "end_timestamp", "scene_text", "target_line", "focus_terms",
                 "difficulty")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def _scene_window(subs, i):
    """Texto da mini-cena à volta da legenda i (1 antes, 2 depois)."""
    s = max(0, i - 1)
    e = min(len(subs) - 1, i + 2)
    win = subs[s:e + 1]
    start = win[0].start if win else subs[i].start
    end = win[-1].end if win else subs[i].end
    text = " ".join(x.text for x in win)
    return start, end, text


def _is_fast_exchange(i, subs):
    if i + 2 >= len(subs):
        return False
    cur, nxt, aft = subs[i], subs[i + 1], subs[i + 2]
    return (aft.end - cur.start < 9 and
            all(len(x.text.split()) <= 12 for x in (cur, nxt, aft)))


def _pick_mission(entry, scene_text, focus_terms, i, subs, seq=0):
    text = (entry.text or "").strip()
    if not text:
        return None
    wc = len([w for w in text.split() if w])
    dense = len(scene_text.split()) >= 34
    # Silêncio depois desta fala = plano "segurado" → bom para descrever o TAKE
    # (pausa no fotograma e a visão compara o que se vê com o que foi dito).
    gap_after = (subs[i + 1].start - entry.end) if i + 1 < len(subs) else 99.0

    if "?" in text:
        return ("dialogue_takeover", "Assume uma personagem",
                "O filme fez uma pergunta. Pausa e responde fora do guião, como se "
                "fosses uma das personagens.", "hard" if wc > 12 else "medium")
    if _SLANG_RE.search(text):
        return ("slang_miner", "Caça à gíria da cena",
                "Explica a expressão informal desta fala e cria uma frase tua com o "
                "mesmo tom.", "medium")
    if _GRAMMAR_RE.search(text):
        return ("grammar_xray", "Raio-X gramatical",
                "Identifica a estrutura gramatical usada e reescreve a ideia com uma "
                "frase tua.", "hard" if wc > 14 else "medium")
    if _MORAL_RE.search(scene_text):
        return ("devil_advocate", "Defende o indefensável",
                "Defende durante 20-30s a decisão mais duvidosa desta cena. Improviso "
                "conta mais que perfeição.", "hard")
    # Plano segurado (fala curta + pausa a seguir) → descrever o take com visão.
    if gap_after >= 3.5 and wc <= 12:
        return ("describe_take", "Descreve o take",
                "O filme pausa neste plano. Descreve o que vês — a visão compara com a "
                "fala.", "medium")
    if dense:
        # Passagem densa: alterna entre resumir de memória e traduzir com fluência.
        if seq % 2 == 0:
            return ("fluency_translate", "Traduz a passagem",
                    "Traduz esta passagem de forma fluente para a tua língua.", "medium")
        return ("boss_recap", "Boss battle de compreensão",
                "Sem rever as legendas, resume o que acabou de acontecer nesta cena.",
                "hard")
    if _is_fast_exchange(i, subs):
        # Troca rápida = há DIÁLOGO aqui. Roda entre: role-play do diálogo (o aluno
        # faz uma das vozes), descrever a cena (loop+visão) e resumir de memória.
        pick = seq % 3
        if pick == 0:
            return ("dialogue_roleplay", "Faz o diálogo",
                    "Assume uma das personagens: o filme pára quando é a tua fala e "
                    "continua quando fala a outra.", "medium")
        if pick == 1:
            return ("describe_scene", "Descreve a cena",
                    "A cena entra em loop. Descreve o que está a acontecer.", "medium")
        return ("boss_recap", "Boss battle de compreensão",
                "Sem rever as legendas, resume o que acabou de acontecer nesta cena.",
                "medium")
    if 4 <= wc <= 16:
        # Fala isolada: alterna entre shadowing e paráfrase.
        if seq % 2 == 0:
            return ("paraphrase_line", "Reescreve a fala",
                    "Reescreve esta fala de outra forma, na mesma língua.", "medium")
        return ("deep_shadowing", "Diz no timing da personagem",
                "Repete a fala com o mesmo ritmo. Depois escreve/dita o que conseguiste "
                "reproduzir.", "medium" if wc > 10 else "easy")
    if focus_terms:
        return ("boss_recap", "Cena para o teu corpus",
                "Reconta esta cena usando pelo menos uma das palavras-chave.", "medium")
    return None


def build_scene_missions(subs, intensity="balanced", vocab_terms_at=None):
    """subs: lista de objetos com .start/.end/.text (SubEntry do player).
    vocab_terms_at(start, end) -> lista de palavras-foco para a janela (opcional).
    Devolve lista de SceneMission ordenada por tempo."""
    if not subs:
        return []
    missions = []
    min_gap = MIN_GAP.get(intensity, 52)
    max_missions = MAX_MISSIONS.get(intensity, 18)
    last_ts = -9999.0
    for i, entry in enumerate(subs):
        if not getattr(entry, "text", "") :
            continue
        if entry.start - last_ts < min_gap:
            continue
        s_start, s_end, s_text = _scene_window(subs, i)
        focus = []
        if vocab_terms_at:
            try:
                focus = list(vocab_terms_at(s_start - 3, s_end + 3))[:4]
            except Exception:
                focus = []
        picked = _pick_mission(entry, s_text, focus, i, subs, seq=len(missions))
        if not picked:
            continue
        kind, title, prompt, difficulty = picked
        missions.append(SceneMission(
            id="scene-%s-%d" % (kind, round(entry.start)),
            kind=kind, title=title, label=KIND_LABELS[kind], prompt=prompt,
            timestamp=entry.start, end_timestamp=max(entry.end, entry.start + 8),
            scene_text=s_text, target_line=entry.text.strip(),
            focus_terms=focus, difficulty=difficulty,
        ))
        last_ts = entry.start
        if len(missions) >= max_missions:
            break
    return missions


# ── Avaliação por IA (DeepSeek, via backend partilhado) ──

_KIND_RUBRIC = {
    "dialogue_takeover":
        "O aluno improvisa uma resposta NO PAPEL da personagem, fora do guião. NÃO "
        "penalizar por diferir da fala original — premiar diálogo natural e plausível. "
        "Avaliar adequação à cena, gramática e fluência.",
    "deep_shadowing":
        "O aluno repete a fala-alvo tentando o mesmo ritmo. Avaliar fidelidade às "
        "palavras e ordem da fala-alvo. Pequenas diferenças de filler tudo bem; "
        "palavras-chave em falta/trocadas não.",
    "boss_recap":
        "O aluno resume a cena de memória, sem legendas. Avaliar compreensão e "
        "cobertura dos eventos-chave, depois gramática e fluência.",
    "grammar_xray":
        "O aluno identifica a estrutura gramatical da fala E reescreve a ideia com "
        "uma frase própria correta. Premiar uso correto da mesma estrutura; gramática "
        "avaliada com rigor.",
    "slang_miner":
        "O aluno explica a expressão informal e usa-a numa frase nova com o mesmo tom. "
        "Premiar explicação correta + reutilização natural.",
    "devil_advocate":
        "O aluno argumenta (improvisado) a favor de uma decisão duvidosa da cena. "
        "Premiar improviso fluente, coerente e persuasivo — não concordância moral. "
        "Avaliar gramática e fluência, não moral.",
}


def _clamp(v, fb=0):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return fb
    return max(0, min(100, n))


def _local_score(mission, answer):
    """Fallback offline: heurística simples (sobreposição + tamanho + focus)."""
    answer = (answer or "").strip()
    if not answer:
        return {"score": 0, "feedback": "Sem resposta. Esta cena fica marcada para repetir.",
                "ai_graded": False}
    def toks(t):
        return set(w for w in re.sub(r"[^\w' ]", " ", t.lower()).split() if len(w) > 2)
    aw = toks(answer)
    sw = toks(mission.scene_text or "")
    overlap = len(aw & sw)
    focus_hits = sum(1 for term in (mission.focus_terms or [])
                     if term.lower() in answer.lower())
    score = max(10, min(100, min(40, len(aw) * 2) + min(35, overlap * 5) + min(25, focus_hits * 8)))
    fb = ("Forte. Já dá para mandar para revisão." if score >= 82 else
          "Boa base. Repete a cena e puxa mais vocabulário." if score >= 58 else
          "Resposta curta. O Lexio guarda esta cena para voltares.")
    return {"score": score, "feedback": fb, "ai_graded": False}


def evaluate_scene_mission(mission, answer, native_lang="pt", target_lang="en",
                           level="B1", api_base=LEXIO_API_DEFAULT, auth_header=None,
                           timeout=60):
    """Avalia a resposta com DeepSeek. Devolve dict com score, feedback, corrected,
    meaning/grammar/fluency, ai_graded. Cai para heurística local em erro/offline."""
    answer = (answer or "").strip()
    if not answer:
        return _local_score(mission, answer)

    system = ("Tu és o Lexio Scene Agent, um treinador de línguas rigoroso mas "
              "encorajador a avaliar a resposta a uma missão interativa de filme. "
              "Devolve APENAS JSON válido. Sem markdown.")
    user = f"""Avalia esta resposta a uma missão de filme.

Nível (CEFR): {level}
Língua-alvo (a praticar): {target_lang}
Língua nativa (feedback nesta): {native_lang}

Tipo de missão: {mission.kind}
Rubrica: {_KIND_RUBRIC.get(mission.kind, "")}
Tarefa dada ao aluno: "{mission.prompt}"
Contexto da cena: "{mission.scene_text}"
{('Fala-chave: "%s"' % mission.target_line) if mission.target_line else ""}
{('Vocabulário a reforçar: %s' % ", ".join(mission.focus_terms)) if mission.focus_terms else ""}

Resposta do aluno (pode ser transcrição de voz, tolera ruído de pontuação): "{answer}"

Devolve APENAS este JSON:
{{"score":0-100,"meaningScore":0-100,"grammarScore":0-100,"fluencyScore":0-100,
"correctedAnswer":"versão {target_lang} natural (vazio se já bom)",
"feedbackNative":"2 frases curtas em {native_lang}"}}

Pontuação (rigor): 90-100 natural+correto; 75-89 bom, falhas menores; 60-74 ideia
passa com erros; 40-59 parcial; 0-39 fora. finalScore = meaning*0.4 + grammar*0.35 + fluency*0.25"""

    try:
        hdrs = {"Content-Type": "application/json", "User-Agent": "LexioPlayer"}
        if auth_header:
            hdrs["Authorization"] = auth_header
        # IA via OpenRouter (proxy servidor /api/vision; chave fica no servidor).
        # Modelo: DeepSeek via OpenRouter (texto, JSON).
        body = json.dumps({
            "prompt": user,
            "system": system,
            "model": OPENROUTER_MODEL,
            "json": True,
            "maxTokens": 600,
            "temperature": 0.2,
        }).encode()
        r = urlopen(Request(api_base + "/api/vision", data=body, headers=hdrs),
                    timeout=timeout)
        d = json.loads(r.read().decode())
        raw = d.get("text") or ""
        parsed = _parse_json(raw)
        if not parsed or "score" not in parsed:
            _log(f"eval: resposta da IA sem score (cai p/ heuristica). raw[:200]={raw[:200]!r}")
            return _local_score(mission, answer)

        meaning = _clamp(parsed.get("meaningScore"))
        grammar = _clamp(parsed.get("grammarScore"))
        fluency = _clamp(parsed.get("fluencyScore"))
        calc = round(meaning * 0.4 + grammar * 0.35 + fluency * 0.25)
        ai = _clamp(parsed.get("score"), calc)
        final = calc if abs(ai - calc) > 8 else ai
        corrected = (parsed.get("correctedAnswer") or "").strip()
        return {
            "score": final,
            "feedback": (parsed.get("feedbackNative") or "").strip() or _default_fb(final),
            "corrected": corrected if corrected and corrected.lower() != answer.lower() else "",
            "meaning": meaning, "grammar": grammar, "fluency": fluency,
            "ai_graded": True,
        }
    except Exception as e:
        _log(f"eval FALHOU (cai p/ heuristica): {type(e).__name__}: {e}")
        return _local_score(mission, answer)


def _default_fb(score):
    return ("Forte. Já dá para mandar para revisão." if score >= 80 else
            "Boa base. Repete a cena e puxa mais vocabulário." if score >= 60 else
            "Resposta curta. O Lexio guarda esta cena para voltares.")


def _parse_json(text):
    if not text:
        return None
    try:
        clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None
