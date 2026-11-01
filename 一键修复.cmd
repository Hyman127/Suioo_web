@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Run-Diagnostics.ps1" -Repair %*
set "SUIOO_EXIT=%ERRORLEVEL%"
pause
endlocal & exit /b %SUIOO_EXIT%
