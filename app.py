import concurrent.futures
import csv
import hashlib
import hmac
import http.server
import io
import json
import os
import secrets
import socketserver
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from storage import ROOT, RUNTIME, add_probe, atomic_json, config, event, events, probes, save_config
from network import FLAGS, interfaces, probe, snapshot
from policy import Policy
from proxy import start_proxy
from engine import Manager
import vault
import catalog
import integration

PROJECT_ID = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
TOKEN = secrets.token_urlsafe(32)
POLICY = Policy()
MANAGER = Manager()
JOB_LOCK = threading.Lock()
JOB = {'id': None, 'running': False, 'done': 0, 'total': 0, 'results': []}
PROXY_STATUS = {'running': False}


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return fallback


def state():
    network = read_json(RUNTIME / 'network.json', {})
    physical, vpn = interfaces(network) if network else (None, None)
    core = MANAGER.status()
    guard = {'time':time.time(),'state':'online' if core['running'] else 'backoff' if core['desired'] else 'paused',
             'stale':False,'attempts':core['attempts'],'next_attempt':core['next_attempt'],
             'online_since':core['since'],'heartbeat':core['health']}
    vpn = {'name':'AnyConnect 用户态协议栈','ips':[core['connection'].get('server','')]} if core['running'] else None
    with JOB_LOCK:
        job = dict(JOB)
        job['results'] = list(JOB['results'])
    return {'time': time.time(), 'project_id': PROJECT_ID, 'project': str(ROOT),
            'network': network, 'physical': physical, 'vpn': vpn, 'guard': guard,
            'reconnect': {'time':time.time(),'message':core['error'] or '独立协议内核持续保活；无 OpenConnect GUI、无系统 TUN 网卡'},
            'core':core, 'connection':core['connection'], 'integration':integration.status(),
            'config': config(), 'rule_counts': POLICY.counts(), 'job': job,
            'proxy': PROXY_STATUS, 'events': events(), 'probes': probes(),
            'scope': '本地代理只作用于显式配置它的应用；代理协议运行在用户态，不修改系统网卡、路由和 DNS。'}


def network_watch():
    while True:
        current = read_json(RUNTIME / 'network.json', {})
        if time.time() - current.get('time', 0) > 25:
            try:
                snapshot(force=True)
            except Exception as error:
                event('network-error', str(error)[:250])
        time.sleep(15)


def start_job(data):
    cfg = config()
    identifiers = data.get('site_ids', ['wechat', 'sunlogin', 'douyin', 'taobao', 'baidu', 'google', 'chatgpt'])
    modes = data.get('modes', ['system'])
    repeats = int(data.get('repeats', 1))
    if not isinstance(identifiers, list) or not identifiers or len(identifiers) > 40:
        raise ValueError('请选择 1 至 40 个网站')
    if not isinstance(modes, list) or not modes or any(mode not in ('system', 'direct', 'vpn') for mode in modes):
        raise ValueError('出口类型无效')
    if not 1 <= repeats <= 3:
        raise ValueError('重复次数应为 1 至 3')
    selected = [site for site in cfg['sites'] + catalog.sites() if site['id'] in identifiers]
    if not selected:
        raise ValueError('没有有效网站')
    queue = [(site, mode) for _ in range(repeats) for site in selected for mode in dict.fromkeys(modes)]
    with JOB_LOCK:
        if JOB['running']:
            raise ValueError('已有测速正在运行，请等待完成')
        JOB.update(id=secrets.token_hex(6), running=True, done=0, total=len(queue), results=[])

    def work():
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(probe, site, mode, MANAGER) for site, mode in queue]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    add_probe(result)
                    with JOB_LOCK:
                        JOB['results'].append(result)
                        JOB['done'] += 1
        except Exception as error:
            event('probe-error', str(error)[:300])
        finally:
            with JOB_LOCK:
                JOB['running'] = False
            event('probe', '网站连接测速已完成', {'count': len(queue)})
    threading.Thread(target=work, daemon=True).start()
    return {'started': True}


def update_config(data):
    cfg = config()
    for key in ('guard_enabled', 'keep_awake', 'proxy_enabled'):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError('开关值无效')
            cfg[key] = data[key]
    if 'default_mode' in data:
        if data['default_mode'] not in ('direct', 'vpn', 'system'):
            raise ValueError('默认出口无效')
        cfg['default_mode'] = data['default_mode']
    if 'groups' in data:
        if not isinstance(data['groups'], dict) or set(data['groups']) - set(cfg['groups']):
            raise ValueError('厂商组无效')
        if any(value not in ('direct', 'vpn', 'system') for value in data['groups'].values()):
            raise ValueError('出口无效')
        cfg['groups'].update(data['groups'])
    if 'custom_rules' in data:
        rows = data['custom_rules']
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError('规则数量无效')
        for row in rows:
            host = row.get('domain', '').strip().lower().rstrip('.')
            if not host or any(c in host for c in '/:@ ?#') or len(host) > 253 or row.get('mode') not in ('direct', 'vpn', 'system'):
                raise ValueError('域名规则无效')
            host.encode('idna')
            row['domain'] = host
        cfg['custom_rules'] = rows
    if 'sites' in data:
        sites = data['sites']
        if not isinstance(sites, list) or not 1 <= len(sites) <= 40:
            raise ValueError('网站数量应为 1 至 40')
        seen = set()
        for site in sites:
            uri = urllib.parse.urlsplit(site.get('url', ''))
            if uri.scheme not in ('http', 'https') or not uri.hostname or uri.username or uri.password:
                raise ValueError('请输入不含账号密码的 HTTP(S) 链接')
            if not site.get('name') or len(site['name']) > 70 or site.get('group') not in cfg['groups']:
                raise ValueError('网站名称或分组无效')
            if not site.get('id') or site['id'] in seen or len(site['id']) > 80:
                raise ValueError('网站编号无效或重复')
            seen.add(site['id'])
        cfg['sites'] = sites
    save_config(cfg)
    event('config', '已保存本项目配置；现有系统路由、DNS、代理未切换')
    return {'saved': True}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def trusted(self):
        try:
            return urllib.parse.urlsplit('http://' + self.headers.get('Host', '')).hostname in ('127.0.0.1', 'localhost')
        except ValueError:
            return False

    def send(self, status, payload, content_type='application/json; charset=utf-8', attachment=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename=' + attachment)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.trusted():
            return self.send(403, {'error': '仅允许本机访问'})
        uri = urllib.parse.urlsplit(self.path)
        if uri.path == '/api/health':
            return self.send(200, {'app': 'suioo-console-v1', 'project_id': PROJECT_ID})
        if uri.path == '/api/state':
            return self.send(200, state())
        if uri.path == '/api/config-preview':
            return self.send(200, MANAGER.preview())
        if uri.path == '/api/catalog':
            query = urllib.parse.parse_qs(uri.query)
            group = query.get('group',[''])[0]
            search = query.get('q',[''])[0].lower()[:200]
            try: offset = max(0,int(query.get('offset',['0'])[0]))
            except ValueError: offset = 0
            rows = [s for s in catalog.sites() if (not group or s['group']==group) and search in s['name']]
            return self.send(200,{'total':len(rows),'offset':offset,'sites':rows[offset:offset+40]})
        if uri.path == '/api/export.csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['time', 'name', 'mode', 'http_status', 'dns_ms', 'tcp_ms', 'tls_ms', 'ttfb_ms', 'total_ms', 'interface', 'remote_ip', 'error'])
            keys = ['time', 'name', 'mode', 'http_status', 'dns_ms', 'tcp_ms', 'tls_ms', 'ttfb_ms', 'total_ms', 'interface', 'remote_ip', 'error']
            for row in probes(2000):
                values = [str(row.get(key, '')) for key in keys]
                writer.writerow(["'" + value if value.startswith(('=', '+', '-', '@')) else value for value in values])
            return self.send(200, output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', 'suioo-probes.csv')
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if uri.path in assets:
            name, content_type = assets[uri.path]
            body = (ROOT / 'assets' / name).read_bytes().replace(b'__API_TOKEN__', TOKEN.encode())
            return self.send(200, body, content_type)
        self.send(404, {'error': '路径不存在'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        if not self.trusted() or not hmac.compare_digest(self.headers.get('X-Suioo-Token', ''), TOKEN):
            return self.send(403, {'error': '请求校验失败，请刷新控制台'})
        if origin and origin not in ('http://' + self.headers.get('Host', ''),):
            return self.send(403, {'error': '来源校验失败'})
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 150000:
                raise ValueError('请求大小无效')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('请求格式无效')
            if self.path == '/api/probe':
                result = start_job(data)
            elif self.path == '/api/config':
                result = update_config(data)
            elif self.path == '/api/integration':
                enabled=data.get('enabled')
                if not isinstance(enabled,bool):raise ValueError('启用状态无效')
                if enabled and not MANAGER.status()['ready']:raise ValueError('请先验证 Suioo 接入账号并连接成功')
                integration.configure(enabled)
                event('user-proxy','启用 Windows 用户代理及新终端接入' if enabled else '恢复原 Windows 用户代理及新终端设置')
                result={'accepted':True,'enabled':enabled}
            elif self.path == '/api/connection':
                if not PROXY_STATUS.get('running'):
                    raise ValueError('本地代理入口未就绪或被其他副本占用；请使用已运行的项目目录，避免重新认证影响现有连接')
                values = vault.load()
                server = str(data.get('server', values.get('server',''))).strip()
                parsed = urllib.parse.urlsplit(server)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('接入地址应为不带账号、参数或片段的 HTTPS 地址')
                values['server'] = server
                for key in ('username','password'):
                    if data.get(key):
                        values[key] = str(data[key])
                if not values.get('username') or not values.get('password'):
                    raise ValueError('首次配置需要账号和密码')
                values['protocol'] = 'anyconnect'
                values['no_udp'] = bool(data.get('no_udp',values.get('no_udp',False)))
                values['dpd_interval'] = '5s'
                values['reconnect_timeout'] = '24h'
                if MANAGER.applying:
                    raise ValueError('正在验证另一条连接，请等待验证结束')
                def verify_credentials():
                    try:
                        MANAGER.apply(values, persist_credentials=True)
                        cfg = config(); cfg['auto_start'] = True; cfg['guard_enabled'] = True; cfg['guard_pause_until'] = 0; save_config(cfg)
                        event('connection-config','Suioo 账号与 HTTPS 验证通过，已加密保存并连接')
                    except Exception:
                        event('connection-error','新 Suioo 接入配置验证失败；原有已保存凭据未被替换')
                threading.Thread(target=verify_credentials,daemon=True).start()
                result = {'accepted':True,'saved':False,'message':'正在验证 Suioo 账号和 HTTPS 通道，通过后自动保存并连接'}
            elif self.path == '/api/core':
                action = data.get('action')
                if action == 'apply':
                    cfg = config(); cfg['auto_start'] = True; save_config(cfg)
                    def apply_session():
                        try: MANAGER.apply()
                        except Exception as error: event('connection-error',str(error)[:500])
                    threading.Thread(target=apply_session,daemon=True).start()
                elif action == 'stop':
                    cfg = config(); cfg['auto_start'] = False; save_config(cfg)
                    MANAGER.stop()
                else:
                    raise ValueError('代理操作无效')
                result = {'accepted':True}
            elif self.path == '/api/rule-test':
                host = data.get('host', '').strip()
                if '://' in host:
                    host = urllib.parse.urlsplit(host).hostname or ''
                if not host or len(host) > 253:
                    raise ValueError('请输入有效域名')
                result = POLICY.match(host)
            elif self.path == '/api/guard':
                cfg = config()
                action = data.get('action')
                if action == 'pause':
                    cfg['guard_pause_until'] = time.time() + 1800
                elif action == 'resume':
                    cfg['guard_pause_until'] = 0
                    cfg['guard_enabled'] = True
                    cfg['auto_start'] = True
                elif action == 'check':
                    MANAGER.health_time = 0
                    MANAGER.next_attempt = 0
                else:
                    raise ValueError('守护操作无效')
                save_config(cfg)
                event('guard-action', '守护操作：' + action)
                result = {'ok': True}
            else:
                return self.send(404, {'error': '接口不存在'})
            self.send(200, result)
        except (ValueError, TypeError, KeyError) as error:
            self.send(400, {'error': str(error)})
        except Exception as error:
            event('api-error', str(error)[:300])
            self.send(500, {'error': str(error)[:300]})


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


def run():
    cfg = config()
    atomic_json(RUNTIME / 'server-stage.json', {'stage': 'bind', 'time': time.time()})
    server = None
    for port in range(cfg['web_port'], cfg['web_port'] + 10):
        try:
            server = Server(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError('控制台端口不可用')
    atomic_json(RUNTIME / 'server.json', {'pid': os.getpid(), 'port': server.server_port, 'project_id': PROJECT_ID})
    try:
        atomic_json(RUNTIME / 'server-stage.json', {'stage': 'proxy', 'time': time.time()})
        proxy = start_proxy(cfg['proxy_port'], POLICY, MANAGER)
        PROXY_STATUS.update(running=True, port=cfg['proxy_port'])
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
    except OSError as error:
        PROXY_STATUS.update(running=False, error=str(error))
        event('proxy-error', '本地代理端口不可用；原有程序和代理保持不变')
    threading.Thread(target=network_watch, daemon=True).start()
    if PROXY_STATUS.get('running'):
        threading.Thread(target=MANAGER.supervise, daemon=True).start()
    else:
        # A second checkout must not re-authenticate and evict the active VPN session.
        MANAGER.desired=False
        MANAGER.last_error='本地代理入口被占用；请使用已运行的项目目录，未启动新的认证会话'
    atomic_json(RUNTIME / 'server-stage.json', {'stage': 'serve', 'time': time.time()})
    event('server', '本地控制台已启动', {'port': server.server_port})
    server.serve_forever()


if __name__ == '__main__':
    run()
