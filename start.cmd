@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PATH=%LOCALAPPDATA%\Suioo\bin;%PATH%"
set "SUIOO_PY="
if exist "%~dp0runtime\python\python.exe" set "SUIOO_PY=%~dp0runtime\python\python.exe"
if not defined SUIOO_PY if exist "C:\PythonDev\python\python\python.exe" set "SUIOO_PY=C:\PythonDev\python\python\python.exe"
if defined SUIOO_PY (
  "%SUIOO_PY%" -B "%~dp0launcher.py" %*
) else (
  where py.exe >nul 2>nul
  if errorlevel 1 (
    python.exe -B "%~dp0launcher.py" %*
  ) else (
    py.exe -3 -B "%~dp0launcher.py" %*
  )
)
set "SUIOO_EXIT=%ERRORLEVEL%"
if not "%SUIOO_EXIT%"=="0" (
  echo Startup failed. See runtime\server.log and runtime\startup-error.txt
  if "%~1"=="" pause
)
if not "%SUIOO_EXIT%"=="0" (
  endlocal & exit /b %SUIOO_EXIT%
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install-Codex.ps1" -Quiet
set "SUIOO_EXIT=%ERRORLEVEL%"
if not "%SUIOO_EXIT%"=="0" (
  echo Suioo panel started, but Codex installation failed. Retry with 安装Codex.cmd after checking network access.
  if "%~1"=="" pause
)
endlocal & exit /b %SUIOO_EXIT%
