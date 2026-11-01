"""Expose vendor domain lists as searchable HTTPS candidates, not verified websites."""
import functools
import hashlib
import json
from storage import ROOT
import regional

@functools.lru_cache(maxsize=1)
def sites():
    result = []
    seen = set()
    if (ROOT/'rules/regions.json').exists():
        doc=regional.load()
        for row in doc['entries']:
            host=row['value']
            if host in seen:continue
            seen.add(host)
            result.append({'id':'domain-'+hashlib.sha256(host.encode()).hexdigest()[:16],
                           'name':host,'url':'https://'+host+'/', 'group':row['group'],
                           'region':regional.classify(host,doc)['region']})
        return sorted(result,key=lambda s:(s['group'],s['name']))
    for family in ('tencent','oray','bytedance','alibaba','baidu'):
        document = json.loads((ROOT/'rules'/(family+'.json')).read_text(encoding='utf-8'))
        for rule in document['rules']:
            for host in rule.get('domain',[]) + rule.get('domain_suffix',[]):
                host = host.lstrip('.')
                if '.' not in host or host in seen:
                    continue
                seen.add(host)
                result.append({'id':'domain-'+hashlib.sha256(host.encode()).hexdigest()[:16],
                               'name':host,'url':'https://'+host+'/', 'group':family})
    return sorted(result,key=lambda s:(s['group'],s['name']))
