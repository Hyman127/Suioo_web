"""Build auditable regional rules from the pinned community inputs plus reviewed service exceptions."""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from regional import FAMILIES,GITHUB_DOMAINS,native_document,legacy_overlay
inputs=root/'rules/upstream'
rows={}
def add(family,kind,value,region,source,priority=0):
    key=(family,kind,value)
    row={'group':family,'kind':kind,'value':value,'region':region,'source':source,'priority':priority}
    old=rows.get(key)
    if old is None or (priority,region=='overseas')>=(old['priority'],old['region']=='overseas'):rows[key]=row
def expand(family,name,stack=()):
    if name in stack:raise ValueError('Include cycle: '+name)
    result=[]
    for line in (inputs/name).read_text(encoding='utf-8').splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        token,*attrs=line.split();attrs={a[1:] for a in attrs if a.startswith('@')}
        if token.startswith('include:'):
            nested=expand(family,token[8:],stack+(name,))
            if attrs:nested=[r for r in nested if attrs.issubset(r['attributes'])]
            result.extend(nested);continue
        if token.startswith('full:'):kind,value='domain',token[5:]
        elif token.startswith('domain:'):kind,value='domain_suffix',token[7:]
        elif ':' not in token:kind,value='domain_suffix',token
        else:raise ValueError('Unsupported source syntax: '+token)
        region='overseas' if '!cn' in attrs or name in ('tiktok','bytedance-ai-!cn','dola','webnovel') else 'cn'
        if 'cn' in attrs:region='cn'
        result.append({'kind':kind,'value':value,'region':region,'source':name,'attributes':attrs})
    return result
for family in FAMILIES:
    if family=='oray':
        for host in ['oray.com','oray.net','oray.com.cn','oray.net.cn','orayimg.com','oraycdn.com','sunlogin.net','sunlogin.com','sunlogin.com.cn','sunlogin.oray.com','oray.cn','oray.link']:
            add(family,'domain_suffix',host,'cn','oray-reviewed')
        continue
    for row in expand(family,family):add(family,row['kind'],row['value'],row['region'],'community:'+row['source'])
reviewed={
 'tencent':['tencentcloud.com','intl.cloud.tencent.com','console.intl.cloud.tencent.com','wechat.com','wetv.qq.com','gameloop.com','proximabeta.com','midasbuy.com','bcfmglobal.com','tcfmglobal.com'],
 'alibaba':['alibaba.com','aliexpress.com','aliexpress.us','aliexpress-media.com','lazada.com','lazada.sg','lazada.co.th','lazada.com.my','lazada.co.id','lazada.com.ph','lazada.vn','aliglobal.com'],
 'bytedance':['larksuite.com','larksuitecdn.com','larksuiteimg.com','larksuite-pre.com','larksuiteimg-pre.com','larksuiteimg-boe.com','byteplus.com','byteintl.net','dreamina.capcut.com','capcut.com'],
 'baidu':['intl.cloud.baidu.com','global.baidu.com','hkg.bcebos.com','hkg.baidubce.com','duapps.com'],
 'oray':['oray.com.tw','aweray.com','aweray.net','awesun.com','awesun.net']}
for family,hosts in reviewed.items():
    for host in hosts:add(family,'domain_suffix',host,'overseas','reviewed-service-region',1)
add('alibaba','domain','lingma.alibabacloud.com','cn','Alibaba Qoder CN official firewall documentation',2)
document={'version':1,'definition':'中国大陆服务站点直连；海外/国际服务代理；以服务域名和来源属性区分，不按域名后缀或CDN IP猜测',
          'forced_proxy_domains':list(GITHUB_DOMAINS),
          'unknown_policy':'vpn','upstream_commit':'1daade8c4bb957d21d1f5c09c2b050d699e8e96c',
          'entries':sorted(rows.values(),key=lambda r:(r['group'],r['value'],r['kind']))}
document['counts']={family:{region:sum(r['group']==family and r['region']==region for r in rows.values()) for region in ('cn','overseas')} for family in FAMILIES}
for family in FAMILIES:
    (root/'rules'/(family+'.json')).write_text(json.dumps(native_document(family,document),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(root/'rules/regions.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(root/'rules/region-overlay.json').write_text(json.dumps(legacy_overlay(document),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
asset=root/'assets/app.js'
source=asset.read_text(encoding='utf-8')
if '/*REGIONAL_DATA_START*/' in source:
    embedded='/*REGIONAL_DATA_START*/\nconst REGION_POLICY='+json.dumps(document,ensure_ascii=False,separators=(',',':'))+';\n/*REGIONAL_DATA_END*/'
    asset.write_text(re.sub(r'/\*REGIONAL_DATA_START\*/.*?/\*REGIONAL_DATA_END\*/',lambda _:embedded,source,flags=re.S),encoding='utf-8')
print(json.dumps({'counts':document['counts'],'overlay_rules':len(legacy_overlay(document))},ensure_ascii=False))
