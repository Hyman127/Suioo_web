param([int]$ProxyPort=18790)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$internet=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
$server=[string]$internet.ProxyServer
$expected='127.0.0.1:'+$ProxyPort
$enabled=$internet.ProxyEnable -eq 1
$ours=$server -eq $expected -or $server -eq ('http='+$expected+';https='+$expected)
$hasPac=-not [string]::IsNullOrWhiteSpace([string]$internet.AutoConfigURL)
$envChecks=@()
foreach($scope in @('Process','User')){
 foreach($name in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')){
  $value=[Environment]::GetEnvironmentVariable($name,$scope)
  $matches=$false
  if($value){$matches=$value.TrimEnd('/') -eq ('http://'+$expected)}
  $envChecks+=@{scope=$scope;name=$name;present=([bool]$value);matches_suioo=$matches}
 }
}
$adapters=@(Get-NetAdapter -ErrorAction SilentlyContinue)
$defaults=@(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
$v6=@(Get-NetRoute -DestinationPrefix '::/0' -ErrorAction SilentlyContinue)
$dns=@(Get-DnsClientServerAddress -ErrorAction SilentlyContinue|Where-Object {$_.ServerAddresses.Count-gt0})
$stats=@(Get-NetAdapterStatistics -ErrorAction SilentlyContinue)
$browserOverride=@(Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" -ErrorAction SilentlyContinue|Where-Object {$_.CommandLine-match'--(proxy-server|proxy-pac-url|no-proxy-server)'}).Count-gt0
$hostsOverride=$false
$hostsFile=Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
if(Test-Path -LiteralPath $hostsFile){$hostsOverride=@(Get-Content -LiteralPath $hostsFile -ErrorAction SilentlyContinue|Where-Object {$_-notmatch'^\s*#'-and$_-match'\b(google\.com|gstatic\.com)\b'}).Count-gt0}
$portListening=$false
$client=New-Object Net.Sockets.TcpClient
try{$pending=$client.BeginConnect('127.0.0.1',$ProxyPort,$null,$null);if($pending.AsyncWaitHandle.WaitOne(700)){$client.EndConnect($pending);$portListening=$true}}catch{}finally{$client.Dispose()}
@{supported=$true;browser_proxy_enabled=$enabled;browser_uses_suioo=($enabled-and$ours-and!$hasPac);browser_other_proxy=($enabled-and!$ours);browser_uses_pac=$hasPac;
 proxy_env_conflict=(@($envChecks|Where-Object {$_.present-and!$_.matches_suioo}).Count-gt0);proxy_env=$envChecks;local_proxy_listening=$portListening;
 adapters_up=@($adapters|Where-Object {$_.Status-eq'Up'}).Count;physical_adapters_up=@($adapters|Where-Object {$_.Status-eq'Up'-and$_.HardwareInterface}).Count;
 default_ipv4_route_count=$defaults.Count;default_ipv6_route_count=$v6.Count;dns_configured_interfaces=$dns.Count;
 adapter_receive_errors=($stats|Measure-Object -Property ReceivedPacketErrors -Sum).Sum;adapter_outbound_errors=($stats|Measure-Object -Property OutboundPacketErrors -Sum).Sum;
 browser_cmd_proxy_override=$browserOverride;hosts_overrides_google=$hostsOverride;codex_on_path=([bool](Get-Command codex -ErrorAction SilentlyContinue))}|ConvertTo-Json -Depth 5 -Compress
