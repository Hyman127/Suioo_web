"""Validate then atomically hot-reload local rule sets; never restart the VPN core."""
import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from storage import atomic_json,config
from engine import compile_config
import regional
import vault
parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
stage=root/'runtime/region-staging';families=regional.FAMILIES
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def state():return json.load(opener.open('http://127.0.0.1:18789/api/state',timeout=8))
before=state();profile=config()
if profile['default_mode']!='vpn' or any(profile['groups'][g]!='direct' for g in families):
    raise RuntimeError('Live profile differs from fixed domestic-direct / overseas-proxy policy; not applied')
document=json.loads((stage/'regions.json').read_text(encoding='utf-8'))
for g in families:
    actual=json.loads((stage/(g+'.json')).read_text(encoding='utf-8'))
    if actual!=regional.native_document(g,document):raise RuntimeError('Generated native rules differ: '+g)
compiled=compile_config(profile,vault.load(),19091,19092)
compiled['route']['final']='suioo'
compiled['route']['rules'].insert(1,{'domain_suffix':list(regional.GITHUB_DOMAINS),'action':'route','outbound':'suioo'})
for row in compiled['route']['rule_set']:row['path']=str(stage/(row['tag'][7:]+'.json'))
checked=subprocess.run([str(root/'runtime/engine/sing-box.exe'),'check','-c','stdin'],
                       input=json.dumps(compiled).encode(),capture_output=True,timeout=25,creationflags=0x08000000)
if checked.returncode:raise RuntimeError('Native sing-box validation failed; no live files changed')
report={'time':time.time(),'native_validation_passed':True,'applied':False,'core_pid_before':before['core']['pid'],
        'session_uptime_before_seconds':before['time']-before['core'].get('since',before['time']),
        'sha256':{g:hashlib.sha256((stage/(g+'.json')).read_bytes()).hexdigest() for g in families},'counts':document['counts']}
if args.apply:
    rollback=root/'data'/('regional-backup-'+str(int(time.time())));rollback.mkdir(parents=True)
    for name in [g+'.json' for g in families]+['regions.json','region-overlay.json']:
        if (root/'rules'/name).exists():shutil.copyfile(root/'rules'/name,rollback/name)
    shutil.copyfile(root/'config.json',rollback/'config.json')
    connection=http.client.HTTPSConnection('127.0.0.1',18790,timeout=15,context=ssl.create_default_context())
    connection.set_tunnel('www.google.com',443)
    def ping():
        connection.request('GET','/generate_204',headers={'Host':'www.google.com','Connection':'keep-alive'})
        response=connection.getresponse();response.read()
        if response.status!=204:raise RuntimeError('Held Google connection failed')
        if connection.sock is None:raise RuntimeError('Google closed verification connection')
        return connection.sock
    try:
        first_socket=ping()
        for g in families:
            live=root/'rules'/(g+'.json');temporary=live.with_suffix('.next')
            shutil.copyfile(stage/(g+'.json'),temporary);os.replace(temporary,live)
            time.sleep(.35)
        for name in ('regions.json','region-overlay.json'):
            atomic_json(root/'rules'/name,json.loads((stage/name).read_text(encoding='utf-8')))
        # Compatibility metadata for the already-running UI matcher; native hot files implement routing.
        profile=config();manual=[r for r in profile.get('custom_rules',[]) if not r.get('_managed_region')]
        profile['custom_rules']=regional.legacy_overlay(document)+manual
        additions=[('github','GitHub','https://github.com/','other'),
                   ('tencent-global','Tencent Cloud 国际','https://www.tencentcloud.com/','tencent'),
                   ('alibaba-global','Alibaba Cloud 国际','https://www.alibabacloud.com/','alibaba'),
                   ('tiktok','TikTok 国际','https://www.tiktok.com/','bytedance'),
                   ('byteplus','BytePlus 国际','https://www.byteplus.com/','bytedance'),
                   ('baidu-global','百度智能云国际','https://intl.cloud.baidu.com/','baidu')]
        known={s['id'] for s in profile['sites']}
        for sid,name,url,group in additions:
            if sid not in known and len(profile['sites'])<40:profile['sites'].append({'id':sid,'name':name,'url':url,'group':group})
        atomic_json(root/'config.json',profile)
        time.sleep(2)
        report['existing_tls_connection_survived']=ping() is first_socket
        after=state();report['core_pid_after']=after['core']['pid']
        report['same_core_pid']=report['core_pid_before']==report['core_pid_after']
        report['core_ready_after']=after['core'].get('ready',False)
        if not report['same_core_pid']:raise RuntimeError('Unexpected core PID change')
        report['applied']=True;report['rollback_directory']=str(rollback)
    except Exception:
        # Restore watched files and profile without killing or re-authenticating any sessions.
        for saved in rollback.iterdir():
            live=root/'config.json' if saved.name=='config.json' else root/'rules'/saved.name
            temporary=live.with_suffix('.rollback');shutil.copyfile(saved,temporary);os.replace(temporary,live)
        raise
    finally:connection.close()
report['finished']=time.time()
atomic_json(root/'runtime/regional-update-verification.json',report)
print(json.dumps(report))
