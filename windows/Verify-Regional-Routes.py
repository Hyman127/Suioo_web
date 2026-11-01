"""Compare expected policy with native per-connection outbound logs, not UI predictions."""
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from storage import atomic_json
import regional
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def state():return json.load(opener.open('http://127.0.0.1:18789/api/state',timeout=8))
before=state();log=root/'runtime/core.log';offset=0 if '--logs-only' in sys.argv else log.stat().st_size
targets=['mp.weixin.qq.com','www.taobao.com','www.feishu.cn','www.baidu.com','sunlogin.oray.com',
         'www.tencentcloud.com','www.alibabacloud.com','www.tiktok.com','www.byteplus.com','intl.cloud.baidu.com',
         'github.com','api.github.com','raw.githubusercontent.com','ssh.github.com',
         'www.google.com','chatgpt.com','account-cn.alibabacloud.com']
def check(host):
    try:result=subprocess.run(['curl.exe','--silent','--show-error','--ssl-revoke-best-effort','--noproxy','','--proxy',
                           'http://127.0.0.1:18790','--max-time','10','--head','--output','NUL','--write-out','%{http_code}',
                           'https://'+host+('/generate_204' if host=='www.google.com' else '/')],
                          stdin=subprocess.DEVNULL,capture_output=True,timeout=15,creationflags=0x08000000)
    except subprocess.TimeoutExpired:return {'host':host,'expected':regional.classify(host)['mode'],'curl_exit':124,'http_status':None,'error':'Isolated curl test exceeded its time budget'}
    return {'host':host,'expected':regional.classify(host)['mode'],'curl_exit':result.returncode,
            'http_status':result.stdout.decode('ascii','replace').strip(),
            'error':result.stderr.decode('utf-8','replace')[:160]}
if '--logs-only' in sys.argv:rows=[{'host':h,'expected':regional.classify(h)['mode']} for h in targets]
else:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(check,targets))
time.sleep(.5)
with log.open('rb') as stream:
    stream.seek(offset if log.stat().st_size>=offset else 0);lines=stream.read().decode('utf-8','replace').splitlines()
if '--logs-only' in sys.argv:
    from datetime import datetime
    applied=json.loads((root/'runtime/regional-update-verification.json').read_text(encoding='utf-8'))['finished']
    start=datetime.fromtimestamp(applied).strftime('%Y-%m-%d %H:%M:%S')
    lines=[line for line in lines if (m:=re.search(r'(2026-\d+-\d+ \d+:\d+:\d+)',line)) and m.group(1)>=start]
for row in rows:
    ids={m.group(1) for line in lines if ('inbound connection to '+row['host']+':443') in line and (m:=re.search(r'INFO \[(\d+) ',line))}
    outbound=[line for line in lines if any('['+i+' ' in line for i in ids) and 'outbound connection to '+row['host']+':443' in line]
    modes={'direct' if 'outbound/direct[direct]' in line else 'vpn' if 'endpoint/openconnect[suioo]' in line else 'unknown' for line in outbound}
    row['native_outbound']=sorted(modes);row['route_passed']=modes=={row['expected']}
    row['native_evidence']=outbound[:2]
after=state()
report={'time':time.time(),'core_pid_before':before['core']['pid'],'core_pid_after':after['core']['pid'],
        'same_core_pid':before['core']['pid']==after['core']['pid'],'core_ready':after['core']['ready'],
        'session_uptime_seconds':after['time']-after['core']['since'],'routes':rows,
        'all_routes_passed':all(row['route_passed'] for row in rows)}
atomic_json(root/'runtime/regional-route-verification.json',report)
print(json.dumps(report))
