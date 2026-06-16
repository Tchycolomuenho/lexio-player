# ✅ ESTE É O LEXIO DESKTOP PLAYER — É AQUI QUE SE TRABALHA

**Se o utilizador disser "lexio desktop", "lexio player", "o player", "o executável",
"a versão 3.x", ou pedir correções/features no player de vídeo desktop → É ESTE PROJETO.**

- Ficheiro principal: `lexio_player.py` (PyQt5 + VLC embutido, ~4900 linhas).
- App: **Lexio Study Player** — versão em `APP_VERSION` no `lexio_player.py` (atual 3.8.x).
- Executável instalado pelo user: `C:\Program Files\Lexio Study Player\LexioStudyPlayer.exe`.
- Atalhos no Desktop do user (`Lexio Player.lnk`, `Lexio Study Player.lnk`) apontam para AQUI.
- Repo próprio: `github.com/amandioestevao/lexio-player`. Build: `LexioStudyPlayer.spec`
  (PyInstaller). Upload do instalador: scripts `api_upload.py` (MediaFire).

## ⛔ NÃO confundir com o outro projeto
`C:\Users\tchic\Downloads\lexio-app` é a **APP WEB** (React/Vite) + um wrapper Electron
**diferente**. NÃO é o player desktop do user. NUNCA fazer aqui o trabalho que pertence lá,
nem o contrário. Já aconteceu várias vezes o agente trabalhar no `lexio-app` quando o user
queria o `lexio-player` — NÃO repetir.

## Arquitetura (lexio_player.py)
- `PlayerEngine` — VLC (play, seek, subtitle timing, autopause de shadowing).
- `VideoOverlay` — pinta legendas (em baixo) + **cartões de vocabulário estilo Twitch**
  (deslizam da direita). O user chama aos cartões "legendas twitch".
- `ChatPanel` — chat IA (chama `LEXIO_API/api/deepseek-chat`).
- `StudyMgr`, `ExerciseDialog` (escolha-múltipla via DeepSeek), `PronunciationPanel`,
  `WordDetailsPanel`, `SubSearchDialog`, `LoginDialog`.
- `MainWindow` — junta tudo.

## Backend partilhado
`LEXIO_API = "https://lexio-app-five.vercel.app"`. O player chama os MESMOS endpoints que
a web: `/api/deepseek-chat`, `/api/media-search`, `/api/auth`, e (novo) `/api/vision`
(visão via OpenRouter — definido no repo `lexio-app`, precisa de estar deployado na Vercel).
Padrão de chamada: `urllib.request` (`Request`/`urlopen`) com corpo JSON.

## Regras de trabalho
- Validar sempre com `python -m py_compile lexio_player.py` após editar.
- Há quase sempre mudanças NÃO commitadas no working tree — não fazer `git` destrutivo;
  commitar só os ficheiros que eu mexo.
- Testar = correr o player com um vídeo+legenda (o user costuma testar a seguir).
