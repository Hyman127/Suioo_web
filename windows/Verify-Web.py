import concurrent.futures,json,os,subprocess,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
report={'time':time.time(),'context':os.environ.get('USERNAME'),'checks':[]}
try:
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open('http://127.0.0.1:18789/api/state',timeout=5) as f:s=json.load(f)
 report.update(web_ok=True,core={k:s['core'][k] for k in ('running','applying','error','pid','since','health')})
except Exception as e:report.update(web_ok=False,web_error=str(e))
def check(item):
 name,url=item
 p=subprocess.run(['curl.exe','--silent','--show-error','--ssl-revoke-best-effort','--noproxy','','--proxy','http://127.0.0.1:18790','--max-time','18','--head','--output','NUL','--write-out','%{json}',url],capture_output=True,timeout=22)
 try:r=json.loads(p.stdout)
 except ValueError:r={}
 return {'name':name,'url':url,'exit':p.returncode,'status':r.get('http_code'),'total_ms':round(r.get('time_total',0)*1000),'error':p.stderr.decode('utf-8','replace')[:200]}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:report['checks']=list(pool.map(check,[('Google','https://www.google.com/generate_204'),('ChatGPT','https://chatgpt.com/'),('Tencent','https://mp.weixin.qq.com/'),('Oray','https://sunlogin.oray.com/'),('ByteDance','https://www.douyin.com/'),('Alibaba','https://www.taobao.com/'),('Baidu','https://www.baidu.com/')]))
(root/'runtime'/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
