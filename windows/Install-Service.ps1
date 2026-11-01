$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Split-Path $PSScriptRoot -Parent
$python=Join-Path $root 'runtime\python\python.exe'
if(!(Test-Path $python)){$python='C:\PythonDev\python\python\python.exe'}
if(!(Test-Path $python)){$python=(Get-Command python.exe -ErrorAction Stop).Source}
$python=(& $python -c 'from pathlib import Path;import sys;print(Path(sys.executable).resolve())').Trim()
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if(!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run this installer as Administrator'}
$sid=$identity.User.Value
& icacls.exe $root /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q | Out-Null
& icacls.exe (Join-Path $root '*') /reset /T /Q | Out-Null
if($LASTEXITCODE){throw 'Project ACL update failed'}
foreach($item in @(@('Suioo-Web-Local-Python',$python),@('Suioo-Web-Local-Core',(Join-Path $root 'runtime\engine\sing-box.exe')))){
 Get-NetFirewallRule -Name $item[0] -ErrorAction SilentlyContinue|Remove-NetFirewallRule
 New-NetFirewallRule -Name $item[0] -DisplayName $item[0] -Direction Inbound -Action Allow -Program $item[1] -Protocol TCP -LocalAddress 127.0.0.1 -RemoteAddress 127.0.0.1 -Profile Any|Out-Null
}
$action=New-ScheduledTaskAction -Execute $python -Argument ('-B "'+(Join-Path $root 'service.py')+'"') -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtStartup
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$account=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'Suioo-Web-Service' -Action $action -Trigger $trigger -Settings $settings -Principal $account -Force | Out-Null
Start-ScheduledTask -TaskName 'Suioo-Web-Service'
$pythonw=Join-Path (Split-Path $python -Parent) 'pythonw.exe'
if(!(Test-Path $pythonw)){$pythonw=$python}
$userAction=New-ScheduledTaskAction -Execute $pythonw -Argument ('-B "'+(Join-Path $root 'integration.py')+'"') -WorkingDirectory $root
$userTrigger=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$userPrincipal=New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'Suioo-Web-UserIntegration' -Action $userAction -Trigger $userTrigger -Settings $settings -Principal $userPrincipal -Force|Out-Null
Start-ScheduledTask -TaskName 'Suioo-Web-UserIntegration'
Write-Output 'Suioo service and user integration installed: unlimited lifetime; no system TUN, DNS or route changes.'
