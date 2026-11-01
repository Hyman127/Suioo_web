$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Security
$root=Split-Path $PSScriptRoot -Parent
$text=[Console]::In.ReadToEnd()
$data=$text|ConvertFrom-Json
if(!$data.server -or !$data.username -or !$data.password){throw 'Missing connection fields'}
$bytes=[Text.Encoding]::UTF8.GetBytes($text)
$entropy=[Text.Encoding]::UTF8.GetBytes('SuiooWebV1')
$protected=[Security.Cryptography.ProtectedData]::Protect($bytes,$entropy,[Security.Cryptography.DataProtectionScope]::LocalMachine)
New-Item -ItemType Directory -Path (Join-Path $root 'data') -Force|Out-Null
[IO.File]::WriteAllBytes((Join-Path $root 'data\connection.dpapi'),$protected)
[Array]::Clear($bytes,0,$bytes.Length)
$text=$null;$data=$null
Write-Output 'Connection saved using local-machine DPAPI; no credentials printed.'
