param([switch]$Quiet)
$ErrorActionPreference='Stop'

function Add-CodexPath([string]$Existing,[string]$Bin) {
    $parts=@($Existing -split ';' | Where-Object { $_ -and [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -ine $Bin.TrimEnd('\') })
    return (@($Bin)+$parts) -join ';'
}

function Install-SuiooCodex {
    if(-not [Environment]::Is64BitOperatingSystem){throw 'Codex requires Windows x64.'}
    $project=Split-Path $PSScriptRoot -Parent
    $release=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'codex-release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $base=Join-Path $env:LOCALAPPDATA 'Suioo'
    $versionDir=Join-Path $base ('Codex\'+$release.version)
    $bin=Join-Path $base 'bin'
    $exe=Join-Path $versionDir 'codex.exe'
    $installed=(Test-Path -LiteralPath $exe) -and ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ieq $release.exe_sha256)
    if(-not $installed){
        $temp=Join-Path ([IO.Path]::GetTempPath()) ('suioo-codex-'+[Guid]::NewGuid().ToString('N'))
        [void][IO.Directory]::CreateDirectory($temp)
        try {
            $archive=Join-Path $project ('vendor\'+$release.archive)
            if(-not(Test-Path -LiteralPath $archive)){
                $archive=Join-Path (Split-Path $project -Parent) ('环境组件\'+$release.archive)
            }
            if(-not(Test-Path -LiteralPath $archive)){
                $archive=Join-Path $temp $release.archive
                [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $release.url -OutFile $archive -UseBasicParsing -TimeoutSec 180
            }
            if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $release.sha256){throw 'Codex archive checksum mismatch; installation stopped.'}
            $tar=Join-Path $env:SystemRoot 'System32\tar.exe'
            if(-not(Test-Path -LiteralPath $tar)){throw 'Windows tar.exe is required (Windows 10 1803 or newer).'}
            & $tar -xzf $archive -C $temp -- $release.member
            if($LASTEXITCODE -ne 0){throw 'Codex archive extraction failed.'}
            $source=Join-Path $temp $release.member
            if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ine $release.exe_sha256){throw 'Codex executable checksum mismatch.'}
            [void][IO.Directory]::CreateDirectory($versionDir)
            Copy-Item -LiteralPath $source -Destination $exe -Force
        } finally {
            # Only remove this invocation's GUID directory under the system temp root.
            $resolved=[IO.Path]::GetFullPath($temp)
            $allowed=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\suioo-codex-'
            if(-not $resolved.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected temporary directory.'}
            if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
        }
    }
    $version=& $exe --version
    if($LASTEXITCODE -ne 0 -or $version -ne ('codex-cli '+$release.version)){throw 'Installed Codex did not pass its version check.'}
    [void][IO.Directory]::CreateDirectory($bin)
    $shim=Join-Path $bin 'codex.cmd'
    $body='@echo off'+"`r`n"+'"%~dp0..\Codex\'+$release.version+'\codex.exe" %*'+"`r`n"+'exit /b %ERRORLEVEL%'+"`r`n"
    [IO.File]::WriteAllText($shim,$body,[Text.Encoding]::ASCII)
    # Preserve registry value type and unexpanded variables; do not use setx (PATH truncation).
    $key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        $old=[string]$key.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $updated=Add-CodexPath $old $bin
        if($updated -cne $old){
            $kind=[Microsoft.Win32.RegistryValueKind]::ExpandString
            if($key.GetValueNames() -contains 'Path'){$kind=$key.GetValueKind('Path')}
            $key.SetValue('Path',$updated,$kind)
        }
    } finally {$key.Dispose()}
    $env:Path=Add-CodexPath $env:Path $bin
    if(-not ('SuiooEnvironmentNotice' -as [type])){
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public class SuiooEnvironmentNotice {
 [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,UIntPtr w,string l,uint f,uint t,out UIntPtr r);
}
'@
    }
    $notice=[UIntPtr]::Zero
    [void][SuiooEnvironmentNotice]::SendMessageTimeout([IntPtr]0xffff,0x1a,[UIntPtr]::Zero,'Environment',2,5000,[ref]$notice)
    if(-not $Quiet){Write-Output ($version+"`nInstalled for current user. New CMD: codex`n"+$bin)}
}

if($MyInvocation.InvocationName -ne '.'){
    try {Install-SuiooCodex;exit 0} catch {Write-Error $_;exit 1}
}
