param(
    [string]$PythonExecutable,
    [string]$ProjectRoot=(Split-Path $PSScriptRoot -Parent),
    [switch]$NoBrowser,
    [switch]$NoIntegration,
    [switch]$SkipCodexInstall
)
$ErrorActionPreference='Stop'
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
if(!(Test-Path -LiteralPath (Join-Path $ProjectRoot 'launcher.py'))){throw 'Suioo project is incomplete.'}
if(!$PythonExecutable){
    $candidates=@((Join-Path $ProjectRoot 'runtime\python\python.exe'),"$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",'C:\PythonDev\python\python\python.exe')
    $PythonExecutable=$candidates|Where-Object {Test-Path -LiteralPath $_ -PathType Leaf}|Select-Object -First 1
    if(!$PythonExecutable){
        $candidate=Get-Command python.exe -ErrorAction SilentlyContinue|Select-Object -First 1
        if($candidate -and $candidate.Source -notmatch 'WindowsApps'){$PythonExecutable=$candidate.Source}
    }
}
if(!$PythonExecutable -or !(Test-Path -LiteralPath $PythonExecutable -PathType Leaf)){throw 'Python 3.12+ not found. Supply -PythonExecutable; Windows Store aliases are not supported.'}
& $PythonExecutable -c 'import sys;sys.exit(0 if sys.version_info >= (3,12) else 1)'
if($LASTEXITCODE -ne 0){throw 'Python 3.12+ is required.'}
if(!$SkipCodexInstall){
    & (Join-Path $ProjectRoot 'windows\Install-Codex.ps1') -Quiet
    if($LASTEXITCODE -ne 0){throw 'Codex install was not confirmed.'}
}
$arguments=@('-B',(Join-Path $ProjectRoot 'launcher.py'))
if($NoBrowser){$arguments+='--no-browser'}
if($NoIntegration){$arguments+='--no-integration'}
# 只等待启动器退出，不用Start-Process -Wait等待后台服务整个进程树。
& $PythonExecutable @arguments
exit $LASTEXITCODE
