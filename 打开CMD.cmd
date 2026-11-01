@echo off
setlocal
chcp 65001 >nul
call "%~dp0安装Codex.cmd" -Quiet
if errorlevel 1 (
  pause
  exit /b 1
)
set "PATH=%LOCALAPPDATA%\Suioo\bin;%PATH%"
cd /d "%~dp0"
echo Codex is ready. Run: codex
"%ComSpec%" /k
endlocal
