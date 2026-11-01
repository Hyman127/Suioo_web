@echo off
setlocal
cd /d "%~dp0"
call "%~dp0start.cmd" --wait-ready --no-browser
if errorlevel 1 (
  pause
  exit /b 1
)
set "HTTP_PROXY=http://127.0.0.1:18790"
set "HTTPS_PROXY=http://127.0.0.1:18790"
set "NO_PROXY=localhost,127.0.0.1,::1"
echo Proxy is enabled only inside this new shell. Existing Codex sessions are unchanged.
cmd.exe /k
endlocal
