@echo off
echo A instalar Lexio Study Player v3.9.6...
echo Isto vai pedir UAC (Controlo de Conta de Utilizador) - aceita.
timeout /t 2 /nobreak >nul
start /WAIT "" "C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe"
echo.
echo Instalacao concluida (ou cancelada). ExitCode=%ERRORLEVEL%
pause
