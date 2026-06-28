#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Lexio Study Player — build + instalador, num só passo (a forma CANÓNICA).
#
# Porque existe: já aconteceu o agente editar lexio_player.py mas o user continuar
# a correr o .exe ANTIGO (Program Files) → as correções nunca chegavam. Este script
# garante que o que está no código vira sempre uma build instalável e atualizada.
#
# Uso:
#   ./build.sh            → compila o .exe + o instalador (installer/...-Setup.exe)
#   ./build.sh --install  → o mesmo, e lança o instalador no fim (pede UAC admin)
#
# Pré-requisitos: PyInstaller, VLC 64-bit (C:\Program Files\VideoLAN\VLC ou
# $LEXIO_VLC_DIR), Inno Setup 6 (ISCC.exe). Tudo já instalado nesta máquina.
# ─────────────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Lexio Study Player — build canónica ==="

# [1/5] Sanidade: o código tem de compilar ANTES de empacotar (falha cedo).
echo "[1/5] py_compile (lexio_player.py, scene_agent.py, i18n.py)..."
/c/Python314/python.exe -m py_compile lexio_player.py scene_agent.py i18n.py

# [2/5] Sincronizar version.txt com APP_VERSION (o instalador lê o version.txt; já
#       houve dessincronização 3.7.0 vs 3.8.0). Fonte de verdade = APP_VERSION.
VER="$(grep -oE 'APP_VERSION = "[^"]+"' lexio_player.py | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [ -z "$VER" ]; then echo "ERRO: não consegui ler APP_VERSION"; exit 1; fi
printf '%s\n' "$VER" > version.txt
echo "[2/5] versão = $VER (version.txt sincronizado)"

# [3/5] PyInstaller (one-dir, VLC embutido) — usa SEMPRE o spec, nunca flags soltas.
echo "[3/5] PyInstaller (pode demorar alguns minutos)..."
/c/Python314/python.exe -m PyInstaller --noconfirm --clean LexioStudyPlayer.spec
test -f "dist/LexioStudyPlayer/LexioStudyPlayer.exe" || { echo "ERRO: exe não gerado"; exit 1; }

# [4/5] Instalador Inno Setup.
echo "[4/5] Inno Setup (ISCC)..."
ISCC=""
for p in "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" "/c/Program Files/Inno Setup 6/ISCC.exe"; do
  [ -f "$p" ] && ISCC="$p" && break
done
if [ -z "$ISCC" ]; then echo "ERRO: ISCC.exe (Inno Setup 6) não encontrado"; exit 1; fi
"$ISCC" installer.iss | tail -3

SETUP="installer/LexioStudyPlayer-${VER}-Setup.exe"
test -f "$SETUP" || { echo "ERRO: instalador não gerado ($SETUP)"; exit 1; }

# [5/5] Pronto. Opcionalmente instala.
echo "[5/5] OK → $SETUP"
ls -la "$SETUP" | awk '{print "        ", $5, "bytes  ", $6, $7, $8}'

if [ "$1" = "--install" ]; then
  echo ">>> A lançar o instalador (aceita o UAC; fecha a app se estiver aberta)..."
  start "" "$(cygpath -w "$SETUP" 2>/dev/null || echo "$SETUP")"
else
  echo ">>> Para instalar: ./build.sh --install   (ou dá duplo-clique em $SETUP)"
fi
echo "=== Feito (v$VER) ==="
