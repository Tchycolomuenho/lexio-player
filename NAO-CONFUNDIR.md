# REGRA ABSOLUTA: LEXIO WEB APP vs LEXIO DESKTOP PLAYER

**⚠️ NUNCA CONFUNDIR OS DOIS PROJETOS ⚠️**

## Lexio Web App
- Local: `C:\Users\tchic\Downloads\lexio-app\`
- Tecnologia: React + TypeScript + Vite (web/PWA)
- Deploy: Vercel (`lexio-app-five.vercel.app`)
- Branch: `main`
- Repo: `github.com/Tchycolomuenho/lexio-app`
- Features: Chat IA, vocabulario, exercicios online, books, player web
- O usuario refere-se a este como: "lexio web", "a web", "o site", "a app"

## Lexio Desktop Player
- Local: `C:\Users\tchic\lexio-player\`
- Ficheiro principal: `lexio_player.py`
- Tecnologia: PyQt5 + VLC embutido + PyInstaller .exe
- Branch: `main`
- Repo: `github.com/Tchycolomuenho/lexio-player`
- Features: Player de video offline, legendas srt, exercicios locais, edge-tts
- O usuario refere-se a este como: "lexio desktop", "desktop player", "o player", "lexio player"

## SE O USUARIO FALAR DE:
- "chat twitch", "cartoes twitch", "books", "aba XXX" (web app features) → e **WEB APP**
- "botoes", "letras grandes/cortadas", "player", "instalar exe" → e **DESKTOP PLAYER**

## NUNCA:
- Modificar o lexio_player.py quando o usuario esta falando de features web
- Modificar a web app (lexio-app) quando o usuario esta falando do player desktop
- Assumir que um bug/melhoria se aplica aos dois projetos
