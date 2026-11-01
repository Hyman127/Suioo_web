"""Service-region classification, with more specific exceptions winning over parent domains."""
import functools
import json
from storage import ROOT

FAMILIES=('tencent','oray','bytedance','alibaba','baidu')
GITHUB_DOMAINS=('github.com','githubusercontent.com','githubassets.com','github.io','github.dev','githubapp.com','github.blog','githubstatus.com','githubcopilot.com','githubcopilot.dev')
def load():return json.loads((ROOT/'rules'/'regions.json').read_text(encoding='utf-8'))
def matches(row,host):return host==row['value'] or row['kind']=='domain_suffix' and host.endswith('.'+row['value'])
def specificity(row):return len(row['value'])*2+(row['kind']=='domain')
def classify(host,document=None):
    document=load() if document is None else document
    host=host.rstrip('.').lower().encode('idna').decode()
    if any(host==d or host.endswith('.'+d) for d in document.get('forced_proxy_domains',GITHUB_DOMAINS)):
        return {'group':'github','region':'overseas','mode':'vpn','rule':'GitHub 强制代理'}
    rows=[r for r in document['entries'] if matches(r,host)]
    if not rows:return {'group':'other','region':'unknown','mode':'vpn','rule':'未识别站点默认代理'}
    row=max(rows,key=lambda r:(specificity(r),r.get('priority',0),r['region']=='overseas'))
    return {'group':row['group'],'region':row['region'],'mode':'direct' if row['region']=='cn' else 'vpn',
            'rule':row['value'],'source':row['source']}

def native_document(family,document):
    direct=[r for r in document['entries'] if r['group']==family and r['region']=='cn']
    foreign=[r for r in document['entries'] if r['region']=='overseas']
    foreign += [{'kind':'domain_suffix','value':d,'force':True} for d in document.get('forced_proxy_domains',[])]
    flat={};rules=[]
    for row in direct:
        denied=[f for f in foreign if (f.get('force') or specificity(f)>=specificity(row)) and
                (matches(row,f['value']) or matches(f,row['value']))]
        if denied:
            negative={}
            for f in denied:negative.setdefault(f['kind'],[]).append(f['value'])
            rules.append({'type':'logical','mode':'and','rules':[
                {row['kind']:[row['value']]},dict(negative,invert=True)]})
        else:flat.setdefault(row['kind'],[]).append(row['value'])
    if flat:rules.insert(0,{k:sorted(set(v)) for k,v in flat.items()})
    return {'version':3,'rules':rules}

def legacy_overlay(document):
    """Keep the already-running v1 matcher compatible while core rules reload without reconnection."""
    foreign=[r for r in document['entries'] if r['region']=='overseas']
    exceptions=[r for r in document['entries'] if r['region']=='cn' and any(matches(f,r['value']) and specificity(r)>specificity(f) for f in foreign)]
    rows=sorted(foreign+exceptions,key=lambda r:(specificity(r),r.get('priority',0)),reverse=True)
    seen=set();result=[]
    for row in rows:
        if row['value'] in seen:continue
        seen.add(row['value']);result.append({'domain':row['value'],'mode':'direct' if row['region']=='cn' else 'vpn',
                                           '_managed_region':True,'region':row['region'],'vendor':row['group']})
    pinned=[{'domain':d,'mode':'vpn','_managed_region':True,'region':'overseas','vendor':'github'} for d in document.get('forced_proxy_domains',[])]
    return pinned+result
