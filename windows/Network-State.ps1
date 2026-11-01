$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$adapters=@(Get-NetAdapter -ErrorAction SilentlyContinue)
$ips=@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue)
$ifs=@(Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue)
$interfaces=@(foreach($adapter in $adapters){
 $ipif=$ifs|Where-Object {$_.InterfaceIndex -eq $adapter.ifIndex}|Select-Object -First 1
 $forward=if($ipif){$ipif.Forwarding.ToString()}else{'Unknown'}
 [ordered]@{name=$adapter.Name;index=$adapter.ifIndex;up=($adapter.Status -eq 'Up');physical=[bool]$adapter.HardwareInterface;ips=@($ips|Where-Object {$_.InterfaceIndex -eq $adapter.ifIndex -and $_.AddressState -eq 'Preferred'}|Select-Object -ExpandProperty IPAddress);metric=$ipif.InterfaceMetric;forwarding=$forward}
})
$routes=@(Get-NetRoute -AddressFamily IPv4 -ErrorAction SilentlyContinue|ForEach-Object {[ordered]@{prefix=$_.DestinationPrefix;index=$_.InterfaceIndex;gateway=$_.NextHop;metric=$_.RouteMetric}})
[ordered]@{time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();computer=$env:COMPUTERNAME;interfaces=$interfaces;routes=$routes}|ConvertTo-Json -Depth 7 -Compress
