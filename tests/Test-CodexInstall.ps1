$ErrorActionPreference='Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'windows\Install-Codex.ps1')
$bin='C:\Users\Example User\AppData\Local\Suioo\bin'
$old='%USERPROFILE%\tools;C:\Tools;'+('C:\LongPath;'*700)
$updated=Add-CodexPath $old $bin
if($updated -cne ($bin+';'+$old.TrimEnd(';'))){throw 'Existing PATH entries or variable references were changed.'}
if((Add-CodexPath $updated $bin) -cne $updated){throw 'Repeated installation duplicated PATH.'}
if((Add-CodexPath ($bin.ToUpper()+'\;C:\Tools') $bin) -cne ($bin+';C:\Tools')){throw 'Equivalent PATH entry was not deduplicated.'}
if((Add-CodexPath '' $bin) -cne $bin){throw 'Empty PATH was not handled.'}
Write-Output 'PATH preservation, long PATH, empty PATH and idempotence passed; no registry written.'
