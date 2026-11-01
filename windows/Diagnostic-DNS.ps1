param([ValidateSet('www.google.com','www.baidu.com')][string]$TargetHost='www.google.com')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$records=@();$ok=$false
try{$records=@(Resolve-DnsName -Name $TargetHost -Type A -DnsOnly -QuickTimeout -ErrorAction Stop);$ok=$true}catch{}
@{resolved=$ok;ipv4_records=@($records|Where-Object {$_.Type-eq'A'}).Count}|ConvertTo-Json -Compress
