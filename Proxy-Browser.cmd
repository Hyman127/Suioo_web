@echo off
setlocal
set "SUIOO_DIR=%~dp0"
call "%SUIOO_DIR%start.cmd" --wait-ready --no-browser
if errorlevel 1 (
  pause
  exit /b 1
)
set "SUIOO_EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%SUIOO_EDGE%" set "SUIOO_EDGE=C:\Program Files\Microsoft\Edge\Application\msedge.exe"
start "Suioo Browser" "%SUIOO_EDGE%" --user-data-dir="%SUIOO_DIR%runtime\browser" --proxy-server="http://127.0.0.1:18790" --new-window https://www.google.com/ https://chatgpt.com/
endlocal
