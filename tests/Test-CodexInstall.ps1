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

# Exercise installation in an isolated fixture, never touching the user's active Codex.
$temp=Join-Path ([IO.Path]::GetTempPath()) ('suioo-component-test-'+[Guid]::NewGuid().ToString('N'))
try {
    $project=Join-Path $temp 'project'
    $vendor=Join-Path $project 'vendor'
    $inputDir=Join-Path $temp 'input'
    $installed=Join-Path $temp 'installed'
    [void][IO.Directory]::CreateDirectory($vendor)
    [void][IO.Directory]::CreateDirectory($inputDir)
    $member='test-host.exe'
    $source=Join-Path $inputDir $member
    [IO.File]::WriteAllBytes($source,[Text.Encoding]::ASCII.GetBytes('isolated component fixture'))
    $archive=Join-Path $vendor 'host.tar.gz'
    & (Join-Path $env:SystemRoot 'System32\tar.exe') -czf $archive -C $inputDir -- $member
    if($LASTEXITCODE -ne 0){throw 'Fixture archive creation failed.'}
    $component=[pscustomobject]@{target='host.exe';archive='host.tar.gz';member=$member;url='https://example.invalid/not-used';sha256=(Get-FileHash $archive).Hash;exe_sha256=(Get-FileHash $source).Hash}
    if(-not (Install-SuiooCodexComponent $project $installed $component)){throw 'Missing companion was not installed.'}
    $exe=Join-Path $installed 'host.exe'
    if((Get-FileHash $exe).Hash -ne $component.exe_sha256){throw 'Installed fixture mismatch.'}
    $timestamp=(Get-Item $exe).LastWriteTimeUtc
    if(Install-SuiooCodexComponent $project $installed $component){throw 'Correct companion was reinstalled.'}
    if((Get-Item $exe).LastWriteTimeUtc -ne $timestamp){throw 'Correct companion was overwritten.'}
    [IO.File]::WriteAllText($exe,'corrupted installation')
    if(-not (Install-SuiooCodexComponent $project $installed $component)){throw 'Corrupt installed companion was not repaired.'}
    Remove-Item -LiteralPath $exe
    [IO.File]::WriteAllText($archive,'corrupted archive')
    $rejected=$false
    try {$null=Install-SuiooCodexComponent $project $installed $component} catch {
        if($_.Exception.Message -notlike '*checksum mismatch*'){throw}
        $rejected=$true
    }
    if(-not $rejected -or (Test-Path $exe)){throw 'Corrupt archive was installed.'}
    Write-Output 'Companion installation, hash verification, repair and idempotence passed.'
} finally {
    $resolved=[IO.Path]::GetFullPath($temp)
    $allowed=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\suioo-component-test-'
    if(-not $resolved.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected fixture directory.'}
    if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
}
