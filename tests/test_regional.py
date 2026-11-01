import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import regional
from engine import compile_config
from policy import Policy
from storage import DEFAULTS,ROOT

def matches_native(rule,host):
    if rule.get('type')=='logical':
        parts=[matches_native(r,host) for r in rule['rules']]
        value=all(parts) if rule['mode']=='and' else any(parts)
    else:
        value=host in rule.get('domain',[]) or any(host==d or host.endswith('.'+d) for d in rule.get('domain_suffix',[]))
    return not value if rule.get('invert') else value

class RegionalTests(unittest.TestCase):
    def test_metadata_and_native_rules_agree(self):
        document=regional.load()
        rules=[r for g in regional.FAMILIES for r in regional.native_document(g,document)['rules']]
        cases={'mp.weixin.qq.com':'direct','www.taobao.com':'direct','www.feishu.cn':'direct','pan.baidu.com':'direct',
               'sunlogin.oray.com':'direct','www.tencentcloud.com':'vpn','intl.cloud.tencent.com':'vpn',
               'wetv.qq.com':'vpn','www.alibabacloud.com':'vpn','www.alibaba.com':'vpn','www.byteplus.com':'vpn',
               'www.tiktok.com':'vpn','www.larksuite.com':'vpn','intl.cloud.baidu.com':'vpn',
               'hkg.bcebos.com':'vpn','bj.bcebos.com':'direct','account-cn.alibabacloud.com':'direct',
               'x.account-cn.alibabacloud.com':'vpn','lingma.alibabacloud.com':'direct',
               'x.lingma.alibabacloud.com':'vpn','aweray.com':'vpn','notqq.com':'vpn',
               'github.com':'vpn','api.github.com':'vpn','raw.githubusercontent.com':'vpn','qq.github.io':'vpn'}
        for host,mode in cases.items():
            with self.subTest(host=host):
                self.assertEqual(regional.classify(host,document)['mode'],mode)
                self.assertEqual('direct' if any(matches_native(r,host) for r in rules) else 'vpn',mode)
    def test_github_overrides_domestic_child_and_manual_direct(self):
        doc=regional.load();doc['entries'].append({'group':'tencent','kind':'domain_suffix','value':'test.github.io','region':'cn','source':'test'})
        self.assertEqual(regional.classify('test.github.io',doc)['mode'],'vpn')
        self.assertFalse(any(matches_native(r,'test.github.io') for r in regional.native_document('tencent',doc)['rules']))
        cfg=copy.deepcopy(DEFAULTS);cfg['custom_rules']=[{'domain':'github.com','mode':'direct'}]
        self.assertEqual(Policy().match('api.github.com',cfg)['mode'],'vpn')
        compiled=compile_config(cfg,{},19000,19001)
        self.assertEqual(compiled['route']['rules'][1]['outbound'],'suioo')
        self.assertIn('github.com',compiled['route']['rules'][1]['domain_suffix'])
    def test_all_source_entries_and_children_consistent(self):
        doc=regional.load();rules=[r for g in regional.FAMILIES for r in regional.native_document(g,doc)['rules']]
        for row in doc['entries']:
            for host in (row['value'],'regional-check.'+row['value']):
                decision=regional.classify(host,doc)
                self.assertEqual(any(matches_native(r,host) for r in rules),decision['mode']=='direct',host)

if __name__=='__main__':unittest.main()
