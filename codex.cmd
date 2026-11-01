@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install-Codex.ps1" -Quiet
if errorlevel 1 exit /b 1
"%LOCALAPPDATA%\Suioo\Codex\0.166.0\codex.exe" %*
set "SUIOO_EXIT=%ERRORLEVEL%"
endlocal & exit /b %SUIOO_EXIT%
