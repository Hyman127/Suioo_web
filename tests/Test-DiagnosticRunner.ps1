param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$TestRoot)
$ErrorActionPreference='Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'windows\Find-Python.ps1')
[void][IO.Directory]::CreateDirectory((Join-Path $TestRoot 'runtime'))
[IO.File]::WriteAllText((Join-Path $TestRoot 'runtime\server.json'),'{"pid":314159}',[Text.UTF8Encoding]::new($false))
$script:fakeCommand='"'+$PythonExecutable+'" -B "'+(Join-Path $TestRoot 'service.py')+'"'
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction);return @{ExecutablePath=$PythonExecutable;CommandLine=$script:fakeCommand}}
$savedPath=$env:Path
try {
 $env:Path="$env:SystemRoot\System32;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
 $found=Get-SuiooPython $TestRoot
 if(!$found-or$found.source-ne'running_service'-or$found.path-ne$PythonExecutable){throw 'Running project interpreter was not discovered without PATH.'}
 $script:fakeCommand='"'+$PythonExecutable+'" -B "C:\another-copy\service.py"'
 $found=Get-SuiooPython $TestRoot
 if($found-and$found.source-eq'running_service'){throw 'Interpreter from another project was trusted.'}
 Write-Output 'Interpreter discovery without PATH and cross-project protection passed.'
} finally {$env:Path=$savedPath}
