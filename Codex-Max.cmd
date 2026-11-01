@echo off
setlocal
pushd "%~dp0"
call "%~dp0start.cmd" --wait-ready --no-browser
set "SUIOO_READY=%ERRORLEVEL%"
popd
if not "%SUIOO_READY%"=="0" exit /b %SUIOO_READY%
set "PATH=%LOCALAPPDATA%\Suioo\bin;%PATH%"
set "HTTP_PROXY=http://127.0.0.1:18790"
set "HTTPS_PROXY=http://127.0.0.1:18790"
set "NO_PROXY=localhost,127.0.0.1,::1"
where codex.cmd >nul 2>nul
if errorlevel 1 (
  codex.exe --sandbox danger-full-access --ask-for-approval never -c check_for_update_on_startup=false %*
) else (
  call codex.cmd --sandbox danger-full-access --ask-for-approval never -c check_for_update_on_startup=false %*
)
endlocal
