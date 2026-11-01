@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install-Codex.ps1" %*
set "SUIOO_EXIT=%ERRORLEVEL%"
if not "%SUIOO_EXIT%"=="0" echo Codex installation failed.
endlocal & exit /b %SUIOO_EXIT%
