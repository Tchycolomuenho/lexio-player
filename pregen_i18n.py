# -*- coding: utf-8 -*-
"""Pré-gera as traduções de UI para TODAS as línguas oferecidas (não embutidas) e
grava em i18n-bundled/ui_<code>.json, para irem no instalador e funcionarem offline
sem depender da IA em runtime. Resumível: salta chaves já traduzidas; pode-se correr
várias vezes."""
import os, sys, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n

LEXIO_API = os.environ.get("LEXIO_API", "https://lexio-app-five.vercel.app")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n-bundled")
os.makedirs(OUT, exist_ok=True)
BATCH = 90

BASE = i18n.base_strings()
TODO = [i18n._norm(c) for c, _ in i18n.LANGUAGE_CHOICES if i18n._norm(c) not in i18n.SUPPORTED]


def translate_batch(lang_en, subset):
    sys_p = (
        "You are a professional software UI translator. You receive a JSON object of "
        f"UI strings. Translate every VALUE into {lang_en}. Keep every KEY exactly as-is. "
        "Preserve placeholders such as {where}, {text}, {err}, {score}, {lang}, {name} "
        "verbatim. Keep translations short (buttons, labels, tooltips). Reply with ONLY "
        "the translated JSON object — no markdown, no prose.")
    body = json.dumps({"model": "deepseek-chat", "max_tokens": 8000, "temperature": 0.1,
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": json.dumps(subset, ensure_ascii=False)}]}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        f"{LEXIO_API}/api/deepseek-chat", data=body,
        headers={"Content-Type": "application/json"}), timeout=120)
    d = json.loads(r.read().decode())
    raw = (d.get("text") or "").strip()
    if not raw and d.get("choices"):
        raw = d["choices"][0].get("message", {}).get("content", "")
    raw = raw.strip().strip("`")
    mapping = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    return {k: str(v) for k, v in mapping.items() if k in subset and v}


def main():
    total = len(TODO)
    for n, code in enumerate(TODO, 1):
        path = os.path.join(OUT, "ui_%s.json" % code)
        have = {}
        if os.path.exists(path):
            try:
                have = json.load(open(path, encoding="utf-8"))
            except Exception:
                have = {}
        missing = [k for k in BASE if k not in have]
        if not missing:
            print(f"[{n}/{total}] {code}: completo ({len(have)})", flush=True)
            continue
        lang_en = i18n.language_en_name(code)
        print(f"[{n}/{total}] {code} ({lang_en}): faltam {len(missing)}", flush=True)
        for i in range(0, len(missing), BATCH):
            keys = missing[i:i + BATCH]
            subset = {k: BASE[k] for k in keys}
            for attempt in (1, 2, 3):
                try:
                    out = translate_batch(lang_en, subset)
                    if len(out) >= max(1, len(subset) // 2):
                        have.update(out)
                        json.dump(have, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                        print(f"    +{len(out)} (lote {i//BATCH+1}, total {len(have)}/{len(BASE)})", flush=True)
                        break
                    raise RuntimeError(f"poucas chaves: {len(out)}/{len(subset)}")
                except Exception as e:
                    print(f"    tentativa {attempt} falhou: {e}", flush=True)
                    time.sleep(2 * attempt)
    print("=== PREGEN DONE ===", flush=True)
    done = sum(1 for c in TODO if os.path.exists(os.path.join(OUT, "ui_%s.json" % c)))
    print(f"ficheiros: {done}/{total}", flush=True)


if __name__ == "__main__":
    main()
