param([switch]$Repair,[switch]$NoOpen,[switch]$Native)
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'Find-Python.ps1')
$python=$null
if(-not $Native){$python=Get-SuiooPython $project}
if($python){
 $argsList=@($python.prefix)+@('-B',(Join-Path $project 'diagnostics.py'))
 if($Repair){$argsList+='--repair'}
 if($NoOpen){$argsList+='--no-open'}
 $env:SUIOO_DIAGNOSTIC_PYTHON_SOURCE=$python.source
 & $python.path @argsList
 exit $LASTEXITCODE
}
$nativeArgs=@{Project=$project}
if($Repair){$nativeArgs.Repair=$true}
if($NoOpen){$nativeArgs.NoOpen=$true}
& (Join-Path $PSScriptRoot 'Native-Diagnostics.ps1') @nativeArgs
exit $LASTEXITCODE
