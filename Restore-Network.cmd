@echo off
setlocal
cd /d "%~dp0"
set "SUIOO_PY=C:\PythonDev\python\python\python.exe"
if exist "%~dp0runtime\python\python.exe" set "SUIOO_PY=%~dp0runtime\python\python.exe"
if exist "%SUIOO_PY%" (
  "%SUIOO_PY%" -B "%~dp0integration.py" --restore
) else (
  py.exe -3 -B "%~dp0integration.py" --restore
)
pause
endlocal
