function Get-SuiooPython([string]$Project) {
    $candidates=New-Object Collections.Generic.List[object]
    $candidates.Add(@{path=(Join-Path $Project 'runtime\python\python.exe');source='project_runtime'})
    try {
        $info=Get-Content -LiteralPath (Join-Path $Project 'runtime\server.json') -Raw -Encoding UTF8|ConvertFrom-Json
        if($info.pid -is [int] -or $info.pid -is [long]) {
            $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$info.pid) -ErrorAction Stop
            $matchesProject=$false
            foreach($entry in @('service.py','app.py')) {
                $escaped=[regex]::Escape((Join-Path $Project $entry))
                if($process.CommandLine -match ('(?i)(?:^|[\s"])'+$escaped+'(?:[\s"]|$)')){$matchesProject=$true}
            }
            if($matchesProject -and [IO.Path]::GetFileName($process.ExecutablePath) -match '^pythonw?\.exe$') {
                $interpreter=$process.ExecutablePath
                if([IO.Path]::GetFileName($interpreter)-ieq'pythonw.exe'){$interpreter=Join-Path (Split-Path $interpreter -Parent) 'python.exe'}
                $candidates.Add(@{path=$interpreter;source='running_service'})
            }
        }
    } catch {}
    $candidates.Add(@{path='C:\PythonDev\python\python\python.exe';source='launcher_location'})
    foreach($name in @('python.exe','py.exe')) {
        $found=Get-Command $name -ErrorAction SilentlyContinue
        if($found){$candidates.Add(@{path=$found.Source;source='path'})}
    }
    foreach($registry in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach($key in @(Get-ChildItem -LiteralPath $registry -ErrorAction SilentlyContinue)) {
            try {
                $install=Get-Item -LiteralPath ($key.PSPath+'\InstallPath') -ErrorAction Stop
                $path=[string]$install.GetValue('ExecutablePath')
                if(-not $path){$path=Join-Path ([string]$install.GetValue('')) 'python.exe'}
                $candidates.Add(@{path=$path;source='registry'})
            } catch {}
        }
    }
    $seen=@{}
    foreach($candidate in $candidates) {
        $path=[string]$candidate.path
        if(-not $path -or $seen.ContainsKey($path) -or $path -match '\\Microsoft\\WindowsApps\\'){continue}
        $seen[$path]=$true
        if(-not(Test-Path -LiteralPath $path)){continue}
        $prefix=@();if([IO.Path]::GetFileName($path)-ieq'py.exe'){$prefix=@('-3')}
        $check=New-Object Diagnostics.Process
        try {
            $check.StartInfo.FileName=$path
            $check.StartInfo.Arguments=($prefix -join ' ')+' -c "import sys;sys.exit(0 if sys.version_info >= (3,12) else 1)"'
            $check.StartInfo.UseShellExecute=$false;$check.StartInfo.CreateNoWindow=$true
            $check.StartInfo.RedirectStandardOutput=$true;$check.StartInfo.RedirectStandardError=$true
            [void]$check.Start();$done=$check.WaitForExit(5000)
            if(-not $done){$check.Kill()}
            if($done-and$check.ExitCode-eq0){return @{path=$path;source=$candidate.source;prefix=$prefix}}
        } catch {} finally {$check.Dispose()}
    }
    return $null
}
