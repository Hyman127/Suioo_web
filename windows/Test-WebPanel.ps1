#requires -Version 5.1
param([string]$Url='http://127.0.0.1:18789/#rules',[string]$Label='suioo-panel',[switch]$SystemProxy)
$ErrorActionPreference='Stop'
$dir=Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime'
$profile=Join-Path $dir ('desktop-browser-'+$Label+'-check')
$edge='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$proxyArgument=''
$edgeArguments='--user-data-dir="'+$profile+'" --no-first-run --no-default-browser-check'+$proxyArgument+' --force-renderer-accessibility --new-window '+$Url
$null=Start-Process -FilePath $edge -ArgumentList $edgeArguments -PassThru
$rows=@();$window=$null;$success=$false
try{
    for($attempt=0;$attempt -lt 12;$attempt++){
        Start-Sleep -Seconds 4
        $processes=@(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'"|Where-Object {$_.CommandLine -like ('*'+$profile+'*') -and $_.CommandLine -notlike '*--type=*'})
        foreach($item in $processes){
            $p=Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
            if(!$p -or $p.MainWindowHandle -eq 0){continue}
            $window=[Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
            $documents=$window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Document))
            $texts=@()
            foreach($doc in $documents){
                if($doc.Current.Name -notmatch 'Suioo'){continue}
                $text='';$pattern=$null
                if($doc.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern,[ref]$pattern)){$text=$pattern.DocumentRange.GetText(18000)}
                $texts+=[pscustomobject]@{name=$doc.Current.Name;text=$text}
            }
            $controls=$window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.OrCondition]::new([Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Edit),[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Button)))
            $names=@();foreach($control in $controls){if($control.Current.Name){$names+=$control.Current.Name}}
            $row=[pscustomobject]@{attempt=$attempt;title=$p.MainWindowTitle;process_id=$p.Id;session_id=$p.SessionId;documents=$texts;controls=$names;time_utc=[DateTime]::UtcNow.ToString('o')}
            $rows+=$row
        }
        if($rows.Count){
            $text=$rows[-1].documents|ConvertTo-Json -Compress
            $success=($rows[-1].title -match 'Suioo' -and $text -match 'GitHub' -and $text -match '国内 624' -and $text -match '海外 79' -and $text -match '固定代理')
            if($success){break}
        }
    }
    $report=[ordered]@{computer=$env:COMPUTERNAME;browser='Microsoft Edge interactive desktop, isolated profile, UI Automation observation';url=$Url;certificate_errors_ignored=$false;account_login_performed=$false;passed=$success;proxy=$(if($SystemProxy){'Windows user system proxy'}else{'Local panel; no external proxy required'});observations=$rows}
    $report|ConvertTo-Json -Depth 10|Set-Content (Join-Path $dir ('desktop-'+$Label+'-verification.json')) -Encoding UTF8
}catch{
    @{error=$_.Exception.ToString();time_utc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content (Join-Path $dir ('desktop-'+$Label+'-error.json')) -Encoding UTF8
}finally{
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe'"|Where-Object {$_.CommandLine -like ('*'+$profile+'*')}|ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
}
