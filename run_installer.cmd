@echo off
echo Tentando executar o instalador...
echo Tentativa 1: direto
"C:\Users\tchic\lexio-player\installer\LexioStudyPlayer-3.9.6-Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /LOG="C:\Users\tchic\lexio-player\installer\install_log.txt"
echo EXIT_CODE=%ERRORLEVEL%
echo.
echo Tentativa 2: com ShellExecute via cscript
cscript //nologo "C:\Users\tchic\lexio-player\run_installer_helper.vbs"
echo CSCRIPT_DONE
pause
