param([string]$Project=(Split-Path $PSScriptRoot -Parent),[switch]$Repair,[switch]$NoOpen)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)

function Read-JsonFile($path) {try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}catch{return $null}}
function Valid-Port($value,$fallback) {if($value -is [int] -and $value-ge1024-and$value-le65535){return $value};return $fallback}
function Signal-Flags([string]$text) {
 return @{server_disconnected=($text-match'server disconnected CSTP session');server_internal_error=($text-match'code 0xb0 Internal Error');
  authentication_failed=($text-match'authentication failed|login failed|invalid credentials');certificate_error=($text-match'certificate verify failed|CERT_[A-Z_]+');
  dns_error=($text-match'no such host|name resolution|could not resolve');timeout=($text-match'timed out|deadline exceeded')}
}
function Local-Json([string]$path) {
 $request=[Net.HttpWebRequest]::Create($script:base+$path);$request.Proxy=$null;$request.Timeout=2000;$request.ReadWriteTimeout=2000
 $response=$null;$reader=$null
 try {
  $response=$request.GetResponse()
  if($response.ContentLength-gt4000000){throw 'Too large'}
  $reader=New-Object IO.StreamReader ($response.GetResponseStream()),([Text.Encoding]::UTF8)
  return $reader.ReadToEnd()|ConvertFrom-Json
 } finally {if($reader){$reader.Dispose()};if($response){$response.Dispose()}}
}
function Safe-Sample {
 try {
  $health=Local-Json '/api/health'
  if($health.app-ne'suioo-console-v1'-or$health.project_id-ne$script:identity){return @{available=$false;other_project=$true}}
  $state=Local-Json '/api/state'
  if($state.project_id-ne$script:identity){return @{available=$false;other_project=$true}}
  $core=$state.core;$connection=$state.connection;$text=[string]$core.error+"`n"+($core.logs-join"`n")
  $processId=$null;if($core.pid-is[int]-or$core.pid-is[long]){$processId=$core.pid}
  return @{available=$true;ready=[bool]$core.ready;running=[bool]$core.running;applying=[bool]$core.applying;desired=[bool]$core.desired;pid=$processId;
   credentials_saved=([bool]$connection.username_saved-and[bool]$connection.password_saved);proxy_running=[bool]$state.proxy.running;
   integration_enabled=[bool]$state.integration.enabled;browser_proxy_active=[bool]$state.integration.browser_proxy_active;
   terminal_proxy_configured=[bool]$state.integration.new_terminals_configured;signals=(Signal-Flags $text)}
 } catch {return @{available=$false}}
}
function Start-Captured([string]$file,[string]$arguments,[int]$limit) {
 $p=New-Object Diagnostics.Process
 try {
  $p.StartInfo.FileName=$file;$p.StartInfo.Arguments=$arguments;$p.StartInfo.UseShellExecute=$false;$p.StartInfo.CreateNoWindow=$true
  $p.StartInfo.RedirectStandardOutput=$true;$p.StartInfo.RedirectStandardError=$true
  [void]$p.Start()
  return @{p=$p;stdout=$p.StandardOutput.ReadToEndAsync();stderr=$p.StandardError.ReadToEndAsync();clock=[Diagnostics.Stopwatch]::StartNew();limit=$limit;timed_out=$false}
 } catch {$p.Dispose();return $null}
}
function Stop-Expired($job) {if($job-and-not$job.p.HasExited-and$job.clock.Elapsed.TotalSeconds-gt$job.limit){try{$job.p.Kill();$job.timed_out=$true}catch{}}}
function Finish-Captured($job) {
 if(!$job){return @{exit=-2;stdout='';failed=$true}}
 try {
  if(-not$job.p.WaitForExit(1000)){$job.p.Kill();$job.timed_out=$true;$job.p.WaitForExit()}
  return @{exit=$job.p.ExitCode;stdout=$job.stdout.Result;timed_out=$job.timed_out}
 } catch {return @{exit=-2;stdout='';failed=$true}} finally {$job.p.Dispose()}
}
function Numeric-CurlRow($definition,$result) {
 $row=@{name=$definition.name;via_proxy=$definition.proxy;ipv4=$definition.v4;http1_forced=$definition.http1;exit=$result.exit;ok=$false}
 $parts=([string]$result.stdout).Trim()-split'\|'
 if($parts.Count-eq9){
  $keys=@('status','dns_s','connect_s','tls_end_s','ttfb_s','total_s','bytes','bytes_per_second','connect_status')
  try {for($i=0;$i-lt9;$i++){$row[$keys[$i]]=[double]::Parse($parts[$i],[Globalization.CultureInfo]::InvariantCulture)}}catch{}
 }
 $row.error_kind=switch($result.exit){0{'none'}5{'proxy_dns'}6{'dns'}7{'connection'}28{'timeout'}35{'tls'}51{'certificate'}60{'certificate'}56{'tunnel_or_receive'}63{'response_too_large'}default{'curl_error'}}
 if($result.timed_out){$row.error_kind='process_timeout'}
 $row.ok=($result.exit-eq0-and$row.status-ge200-and$row.status-lt400)
 return $row
}

try {
 $config=Read-JsonFile (Join-Path $Project 'config.json');$info=Read-JsonFile (Join-Path $Project 'runtime\server.json')
 $webPort=Valid-Port $info.port (Valid-Port $config.web_port 18789);$proxyPort=Valid-Port $config.proxy_port 18790
 $script:base='http://127.0.0.1:'+$webPort
 $hash=[Security.Cryptography.SHA256]::Create()
 try{$script:identity=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Project))))).Replace('-','').ToLowerInvariant().Substring(0,16)}finally{$hash.Dispose()}
 Write-Output '使用 Windows 原生诊断，不需要 Python。正在对比访问并观察代理状态...'
 $ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $snapshot=Start-Captured $ps ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'Diagnostic-State.ps1')+'" -ProxyPort '+$proxyPort) 18
 $dnsJobs=@()
 foreach($hostName in @('www.google.com','www.baidu.com')){
  $dnsJobs+=@{hostName=$hostName;job=(Start-Captured $ps ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'Diagnostic-DNS.ps1')+'" -TargetHost '+$hostName) 10)}
 }
 $definitions=@(
  @{name='baidu_direct';url='https://www.baidu.com/';proxy=$false;v4=$true},
  @{name='baidu_proxy';url='https://www.baidu.com/';proxy=$true;v4=$true},
  @{name='google_204_proxy_v4';url='https://www.google.com/generate_204';proxy=$true;v4=$true},
  @{name='google_page_proxy_v4';url='https://www.google.com/';proxy=$true;v4=$true},
  @{name='google_logo_proxy_v4';url='https://www.gstatic.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png';proxy=$true;v4=$true},
  @{name='google_204_proxy_auto';url='https://www.google.com/generate_204';proxy=$true;v4=$false},
  @{name='google_204_proxy_http1';url='https://www.google.com/generate_204';proxy=$true;v4=$true;http1=$true},
  @{name='google_204_direct_reference';url='https://www.google.com/generate_204';proxy=$false;v4=$true}
 )
 $curl=Join-Path $env:SystemRoot 'System32\curl.exe'
 $curlVersion='';$revoke=''
 if(Test-Path -LiteralPath $curl){
  $versionJob=Start-Captured $curl '--version' 3;$v=Finish-Captured $versionJob
  if($v.stdout-match'curl (\d+\.\d+\.\d+)'){$curlVersion=$Matches[1];if([version]$curlVersion-ge[version]'7.70.0'){$revoke=' --ssl-revoke-best-effort'}}
 }
 $requests=@()
 foreach($definition in $definitions){
  $arguments='--disable --silent --show-error --connect-timeout 5 --max-time 12 --max-filesize 2097152 --output NUL --write-out "%{http_code}|%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}|%{time_total}|%{size_download}|%{speed_download}|%{http_connect}"'+$revoke
  if($definition.v4){$arguments+=' -4'};if($definition.http1){$arguments+=' --http1.1'}
  if($definition.proxy){$arguments+=' --proxy http://127.0.0.1:'+$proxyPort+' --noproxy ""'}else{$arguments+=' --noproxy "*"'}
  $arguments+=' '+$definition.url
  $requests+=@{definition=$definition;job=(Start-Captured $curl $arguments 15)}
 }
 $samples=New-Object Collections.Generic.List[object];$clock=[Diagnostics.Stopwatch]::StartNew();$next=0
 while($samples.Count-lt7){
  if($clock.Elapsed.TotalSeconds-ge$next){$samples.Add((Safe-Sample));$next+=3}
  foreach($request in $requests){Stop-Expired $request.job};Stop-Expired $snapshot
  foreach($dnsJob in $dnsJobs){Stop-Expired $dnsJob.job}
  Start-Sleep -Milliseconds 100
 }
 $checks=@(foreach($request in $requests){Numeric-CurlRow $request.definition (Finish-Captured $request.job)})
 $snapshotResult=Finish-Captured $snapshot;$windows=@{collection_failed=$true}
 try{if($snapshotResult.exit-eq0){$windows=$snapshotResult.stdout|ConvertFrom-Json}}catch{}
 $dns=@(foreach($dnsJob in $dnsJobs){$result=Finish-Captured $dnsJob.job;$resolved=$false;try{$resolved=[bool](($result.stdout|ConvertFrom-Json).resolved)}catch{};@{host=$dnsJob.hostName;resolved=$resolved;process_timed_out=[bool]$result.timed_out}})
 $findings=New-Object Collections.Generic.List[object]
 function Finding($code,$message){$findings.Add(@{code=$code;message=$message})}
 $lookup=@{};foreach($check in $checks){$lookup[$check.name]=$check}
 if(@($samples|Where-Object {$_.other_project}).Count){Finding 'OTHER_PROJECT' '端口由其他项目副本使用，本次只诊断，不执行修复。'}
 elseif(-not@($samples|Where-Object {$_.available}).Count){Finding 'APP_UNAVAILABLE' '本项目面板未响应，请先运行启动Suioo.cmd。'}
 elseif(-not@($samples|Where-Object {$_.credentials_saved}).Count){Finding 'LOGIN_REQUIRED' '请在连接页填写自己的 Suioo 账号并连接。'}
 elseif(-not@($samples|Where-Object {$_.ready}).Count){Finding 'TUNNEL_NOT_READY' '本地端口在监听不等于隧道可用；本轮没有采样到就绪通道。'}
 if(@($samples|Where-Object {$_.signals.server_disconnected}).Count){Finding 'SERVER_DISCONNECT' '当前会话记录到服务端主动断开，请检查服务端线路及账号并发限制。'}
 $pids=@($samples|Where-Object {$_.pid}|ForEach-Object {$_.pid}|Select-Object -Unique)
 if($pids.Count-gt1-or(@($samples|Where-Object {$_.ready}).Count-gt0-and@($samples|Where-Object {$_.available-and-not$_.ready}).Count-gt0)){Finding 'TUNNEL_UNSTABLE' '观察期间隧道进程切换或就绪状态丢失，可能造成网页反复等待。'}
 if(-not$lookup.baidu_direct.ok){Finding 'DIRECT_BASELINE_FAILED' '国内直连基线也失败，请同时检查目标环境本身的网络。'}
 if(-not$lookup.google_204_proxy_v4.ok){Finding 'PROXY_GOOGLE_FAILED' '经本地代理访问 Google 失败，请查看 CONNECT 状态及隧道采样。'}
 elseif($lookup.google_204_proxy_v4.total_s-gt3-or$lookup.google_page_proxy_v4.total_s-gt5){Finding 'PROXY_GOOGLE_SLOW' '显式代理请求也慢，请结合 TLS、首字节及下载耗时排查远端链路。'}
 if($lookup.google_204_proxy_v4.ok-and-not$lookup.google_page_proxy_v4.ok){Finding 'PAGE_FAILED' '小请求成功但 Google 首页失败。'}
 if($lookup.google_204_proxy_v4.ok-and-not$windows.browser_uses_suioo){Finding 'BROWSER_NOT_CONNECTED' '显式代理可用，但 Windows 浏览器未接入本项目代理。'}
 if(@($checks|Where-Object {$_.error_kind-eq'certificate'}).Count){Finding 'CERTIFICATE_CHECK_FAILED' '请求出现证书校验错误，请核实系统时间、系统证书和网络 HTTPS 检查。'}
 if($windows.browser_uses_pac){Finding 'PAC_PRESENT' '存在 PAC 配置，需核实浏览器实际使用的代理策略。'}
 if($windows.proxy_env_conflict){Finding 'PROXY_ENV_CONFLICT' '终端变量包含其他代理地址，本工具保留这些设置。'}
 if($findings.Count-eq0){Finding 'NO_CONFIRMED_CAUSE' '本次未确认单一原因，请结合浏览器现象继续排查。'}
 $history=@{}
 try{$tail=Get-Content -LiteralPath (Join-Path $Project 'runtime\core.log') -Tail 120 -ErrorAction Stop;$history=Signal-Flags ($tail-join"`n")}catch{}
 $actions=@();if($Repair){$actions=@(@{code='NATIVE_DIAGNOSIS_ONLY';message='已完成原生网络诊断；当前模式不修改设置，扩展修复需要可用的 Python。'})}
 $report=@{schema=2;diagnostics_backend='powershell';python_used=$false;time=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz');windows=$windows;samples=@($samples.ToArray());checks=$checks;system_dns=$dns;findings=@($findings.ToArray());historical_log_signals=$history;repair_actions=$actions;repair_performed=$false;curl=@{available=(Test-Path -LiteralPath $curl);version=$curlVersion};privacy='Fixed fields only; no credentials, raw logs, config, local paths or addresses.'}
 $lines=@('Suioo 网络诊断（Windows 原生，无需 Python）',$report.time,'','判断：')
 $lines+=@($findings|ForEach-Object {'- '+$_.message})
 if($Repair){$lines+=@('','修复结果：',$actions[0].message)}
 $lines+=@('','访问对比：检查 | HTTP | CONNECT | curl | TCP累计秒 | TLS完成累计秒 | 首字节累计秒 | 总秒 | 下载字节')
 $lines+=@($checks|ForEach-Object {($_.name,$_.status,$_.connect_status,$_.exit,$_.connect_s,$_.tls_end_s,$_.ttfb_s,$_.total_s,$_.bytes)-join' | '})
 $lines+=@('','隧道就绪采样：'+@($samples|Where-Object {$_.ready}).Count+'/7','Windows 浏览器接入：'+$windows.browser_uses_suioo)
 $lines+=@($dns|ForEach-Object {'系统 DNS '+$_.host+'：'+$_.resolved})
 $lines+=@('','历史信号单独保存，不代表本次仍在断线。代理 TCP 只测到本地代理，TLS 完成包含 CONNECT 等待；客户端 -4 不证明远端出口为 IPv4。','本次未修改代理、账号、DNS、防火墙、网卡或路由。仅分享同目录的诊断报告.zip。')
 $output=Join-Path $Project ('runtime\diagnostics\'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,6))
 [void][IO.Directory]::CreateDirectory($output)
 [IO.File]::WriteAllText((Join-Path $output 'report.json'),($report|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
 [IO.File]::WriteAllText((Join-Path $output '报告.txt'),($lines-join"`r`n"),[Text.UTF8Encoding]::new($true))
 Add-Type -AssemblyName System.IO.Compression,System.IO.Compression.FileSystem
 $zip=[IO.Compression.ZipFile]::Open((Join-Path $output '诊断报告.zip'),[IO.Compression.ZipArchiveMode]::Create)
 try{foreach($name in @('report.json','报告.txt')){[void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,(Join-Path $output $name),$name)}}finally{$zip.Dispose()}
 Write-Output ($lines-join"`r`n");Write-Output ('报告已保存：'+$output)
 if(-not$NoOpen){Invoke-Item -LiteralPath $output}
 exit 0
} catch {Write-Output ('原生诊断未完成：'+$_.Exception.GetType().Name+'，检查点 '+$_.InvocationInfo.ScriptLineNumber+'。请确认项目完整解压且目录可写。');exit 1}
