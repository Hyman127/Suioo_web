"""Request fresh policy measurements visible in the existing Web dashboard."""
from html.parser import HTMLParser
import json
import urllib.request

class Token(HTMLParser):
    value=''
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='meta' and values.get('name')=='api-token':self.value=values['content']

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
base='http://127.0.0.1:18789'
state=json.load(opener.open(base+'/api/state',timeout=8))
if state['job']['running']:print('An existing measurement is running; it was preserved')
else:
    parser=Token();parser.feed(opener.open(base+'/',timeout=8).read().decode())
    if not parser.value:raise RuntimeError('Local dashboard token unavailable')
    payload=json.dumps({'site_ids':['github','google','wechat','tencent-global','baidu','byteplus'],'modes':['system']}).encode()
    request=urllib.request.Request(base+'/api/probe',data=payload,headers={'Content-Type':'application/json','X-Suioo-Token':parser.value})
    print(opener.open(request,timeout=8).read().decode())
