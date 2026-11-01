import json
from storage import ROOT, config
import regional


class Policy:
    def __init__(self):
        self.regions = regional.load() if (ROOT/'rules/regions.json').exists() else None
        self.rules = {}
        for family in ['tencent', 'oray', 'bytedance', 'alibaba', 'baidu']:
            path = ROOT / 'rules' / (family + '.json')
            document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'rules': []}
            self.rules[family] = document['rules']

    def match(self, hostname, cfg=None):
        cfg = cfg or config()
        host = hostname.rstrip('.').lower().encode('idna').decode()
        if self.regions and any(host==d or host.endswith('.'+d) for d in self.regions.get('forced_proxy_domains',[])):
            return {'group':'github','region':'overseas','mode':'vpn','rule':'GitHub 强制代理'}
        for custom in cfg.get('custom_rules', []):
            if custom.get('_managed_region'):continue
            suffix = custom['domain'].lower().rstrip('.')
            if host == suffix or host.endswith('.' + suffix):
                return {'group': 'custom', 'mode': custom['mode'], 'rule': suffix}
        if self.regions:
            decision=regional.classify(host,self.regions)
            if decision['region']=='cn':decision['mode']=cfg['groups'][decision['group']]
            return decision
        for family, rules in self.rules.items():
            for rule in rules:
                if host in rule.get('domain', []):
                    return {'group': family, 'mode': cfg['groups'][family], 'rule': host}
                for suffix in rule.get('domain_suffix', []):
                    if host == suffix or host.endswith('.' + suffix):
                        return {'group': family, 'mode': cfg['groups'][family], 'rule': suffix}
        return {'group': 'other', 'mode': cfg.get('default_mode', 'vpn'), 'rule': '默认规则'}

    def counts(self):
        if self.regions:return {family:sum(counts.values()) for family,counts in self.regions['counts'].items()}
        return {family: sum(len(rule.get('domain', [])) + len(rule.get('domain_suffix', [])) for rule in rules)
                for family, rules in self.rules.items()}
