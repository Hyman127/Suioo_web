"""Isolated user-space AnyConnect sessions, stable local proxy, lease-based draining."""
import collections
import copy
import json
import logging
import logging.handlers
import os
import select
import socket
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path
import vault
import regional
from winjob import WindowsJob
from storage import ROOT, RUNTIME, config, event

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
LOG = logging.getLogger('suioo-core')
if not LOG.handlers:
    handler = logging.handlers.RotatingFileHandler(RUNTIME / 'core.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def compile_config(profile, credentials, normal_port, forced_port, redacted=False):
    families = ['tencent', 'oray', 'bytedance', 'alibaba', 'baidu']
    def outbound(mode):
        return 'direct' if mode in ('direct', 'system') else 'suioo'
    rules = [{'inbound': ['forced'], 'action': 'route', 'outbound': 'suioo'},
             {'domain_suffix':list(regional.GITHUB_DOMAINS),'action':'route','outbound':'suioo'},
             {'ip_is_private': True, 'action': 'route', 'outbound': 'direct'}]
    for custom in profile.get('custom_rules', []):
        if custom.get('_managed_region'):continue
        rules.append({'domain_suffix': [custom['domain']], 'action': 'route', 'outbound': outbound(custom['mode'])})
    for family in families:
        rules.append({'rule_set': ['vendor-' + family], 'action': 'route', 'outbound': outbound(profile['groups'][family])})
    endpoint = {'type': 'openconnect', 'tag': 'suioo', 'system': False,
                'server': credentials.get('server', 'https://node.anyconnect.cloud'), 'flavor': 'anyconnect',
                'username': credentials.get('username', ''), 'password': credentials.get('password', ''),
                'no_udp': credentials.get('no_udp', False), 'tcp_keep_alive_enabled': True,
                'dpd_interval': credentials.get('dpd_interval', '5s'),
                'reconnect_timeout': credentials.get('reconnect_timeout', '24h'),
                'domain_resolver': 'direct-dns', 'tls': {'insecure': False}}
    if redacted:
        endpoint['username'] = '***'
        endpoint['password'] = '***'
    return {
        'log': {'level': 'info', 'timestamp': True},
        'endpoints': [endpoint],
        'inbounds': [{'type': 'mixed', 'tag': 'policy', 'listen': '127.0.0.1', 'listen_port': normal_port},
                     {'type': 'socks', 'tag': 'forced', 'listen': '127.0.0.1', 'listen_port': forced_port}],
        'outbounds': [{'type': 'direct', 'tag': 'direct', 'domain_resolver': 'direct-dns'}],
        'dns': {'servers': [{'type': 'udp', 'tag': 'direct-dns', 'server': '223.5.5.5'},
                            {'type': 'udp', 'tag': 'proxy-dns', 'server': '8.8.8.8', 'detour': 'suioo'}],
                'final': 'proxy-dns', 'strategy': 'ipv4_only'},
        'route': {'rules': rules, 'final': 'suioo' if (ROOT/'rules/regions.json').exists() else outbound(profile.get('default_mode', 'vpn')),
                  'default_domain_resolver': 'proxy-dns',
                  'rule_set': [{'type': 'local', 'tag': 'vendor-' + name, 'format': 'source',
                                'path': str(ROOT / 'rules' / (name + '.json'))} for name in families]},
    }


def recv_exact(sock, size):
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise OSError('代理连接提前关闭')
        data += part
    return data


def socks_connect(port, host, target_port, timeout=12):
    sock = socket.create_connection(('127.0.0.1', port), timeout)
    try:
        sock.sendall(b'\x05\x01\x00')
        if recv_exact(sock, 2) != b'\x05\x00':
            raise OSError('内部 SOCKS 握手失败')
        encoded = host.encode('idna')
        if len(encoded) > 253:
            raise ValueError('目标域名过长')
        sock.sendall(b'\x05\x01\x00\x03' + bytes([len(encoded)]) + encoded + struct.pack('!H', target_port))
        header = recv_exact(sock, 4)
        if header[1] != 0:
            raise OSError('代理上游拒绝连接，SOCKS 状态 ' + str(header[1]))
        size = 4 if header[3] == 1 else 16 if header[3] == 4 else recv_exact(sock, 1)[0]
        recv_exact(sock, size + 2)
        return sock
    except Exception:
        sock.close()
        raise


class Instance:
    def __init__(self, profile, credentials):
        self.id = uuid.uuid4().hex[:10]
        self.profile = copy.deepcopy(profile)
        self.port, self.forced_port = free_port(), free_port()
        self.document = compile_config(profile, credentials, self.port, self.forced_port)
        self.credentials = credentials
        self.process = None
        self.job = None
        self.clients = 0
        self.created = time.time()
        self.lines = collections.deque(maxlen=80)
        self.transport_dead = False
        self.transport_ready = False

    def redact(self, text):
        for key in ('password', 'username'):
            if self.credentials.get(key):
                text = text.replace(self.credentials[key], '***')
        import re
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        return re.sub(r'(?i)((?:cookie|authorization|token|password)\s*[:=]\s*)\S+', r'\1***', text)[:1500]

    def start(self):
        executable = ROOT / 'runtime' / 'engine' / 'sing-box.exe'
        if not executable.exists():
            raise RuntimeError('协议内核缺失：runtime/engine/sing-box.exe')
        payload = json.dumps(self.document, ensure_ascii=False).encode('utf-8')
        checked = subprocess.run([str(executable), 'check', '-c', 'stdin'], input=payload,
                                 capture_output=True, timeout=20, creationflags=FLAGS)
        if checked.returncode:
            raise ValueError(self.redact(checked.stderr.decode('utf-8', 'replace'))[-700:])
        environment = dict(os.environ)
        for key in list(environment):
            if key.upper() in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
                environment.pop(key)
        self.process = subprocess.Popen([str(executable), 'run', '-c', 'stdin'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT,
                                        env=environment, creationflags=FLAGS)
        self.job = WindowsJob(self.process)
        self.process.stdin.write(payload)
        self.process.stdin.close()
        threading.Thread(target=self.read_logs, daemon=True).start()

    def read_logs(self):
        for raw in iter(self.process.stdout.readline, b''):
            line = self.redact(raw.decode('utf-8', 'replace').strip())
            if line:
                self.lines.append(line)
                LOG.info('%s %s', self.id, line)
                if 'client terminated:' in line:
                    self.transport_dead = True
                    self.transport_ready = False
                elif 'tunnel established' in line:
                    self.transport_ready = True

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.running:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.job:
            self.job.close()
            self.job = None


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.current = None
        self.retired = []
        self.desired = bool(config().get('auto_start', True))
        self.last_error = ''
        self.next_attempt = 0
        self.attempts = 0
        self.health = None
        self.health_time = 0
        self.applying = False
        self.connection = vault.public()
        self.generation = 0
        self.health_failures = 0

    def acquire(self):
        with self.lock:
            if not self.current or not self.current.running:
                raise RuntimeError('Suioo 代理通道尚未就绪，请查看连接设置与内核日志')
            self.current.clients += 1
            return self.current

    def release(self, instance):
        with self.lock:
            instance.clients = max(0, instance.clients - 1)

    def apply(self, credentials=None, persist_credentials=False):
        with self.lock:
            if self.applying:
                raise RuntimeError('已有连接建立请求正在运行')
            self.applying = True
            generation = self.generation
        candidate = None
        try:
            credentials = copy.deepcopy(credentials) if credentials is not None else vault.load()
            if not credentials.get('username') or not credentials.get('password'):
                raise ValueError('请先保存 Suioo 接入账号和密码')
            candidate = Instance(config(), credentials)
            candidate.start()
            deadline = time.time() + 35
            ready = False
            while time.time() < deadline and candidate.running:
                if candidate.transport_dead:
                    break
                if not candidate.transport_ready:
                    time.sleep(.4)
                    continue
                try:
                    with socket.create_connection(('127.0.0.1', candidate.port), timeout=.5):
                        ready = True
                        break
                except OSError:
                    time.sleep(.4)
            if not ready:
                raise RuntimeError('连接尚未建立：' + (' | '.join(candidate.lines)[-600:] or '请检查接入地址和认证'))
            curl = r'C:\Windows\System32\curl.exe' if os.name == 'nt' else 'curl'
            args = [curl, '--silent', '--show-error', '--head', '--proxy',
                    'socks5h://127.0.0.1:' + str(candidate.forced_port), '--noproxy', '',
                    '--connect-timeout', '8', '--max-time', '18', '--output', os.devnull,
                    '--write-out', '%{http_code}', 'https://www.google.com/generate_204']
            if os.name == 'nt':
                args.insert(1, '--ssl-revoke-best-effort')
            checked = subprocess.run(args, capture_output=True, timeout=22, creationflags=FLAGS)
            if checked.returncode or not checked.stdout.strip().startswith((b'2',b'3')):
                raise RuntimeError('新会话未通过 Google HTTPS 验证，保留原会话：' + candidate.redact(checked.stderr.decode('utf-8','replace'))[-300:] + ' | ' + ' | '.join(candidate.lines)[-350:])
            with self.lock:
                if self.generation != generation:
                    raise RuntimeError('连接请求已被停止操作取消')
                if persist_credentials:
                    vault.save(credentials)
                old = self.current
                self.current = candidate
                if old:
                    self.retired.append(old)
                self.connection = vault.public(credentials)
                self.last_error = ''
                self.desired = True
                self.attempts = 0
                self.next_attempt = 0
                self.health = None
                self.health_time = 0
                self.health_failures = 0
            event('connection', '已切换新代理会话；旧会话在现有连接结束后回收')
        except Exception as error:
            if candidate:
                candidate.stop()
            self.last_error = str(error)[:900]
            raise
        finally:
            with self.lock:
                self.applying = False

    def stop(self):
        with self.lock:
            self.desired = False
            self.generation += 1
            active = [x for x in [self.current, *self.retired] if x]
            self.current = None
            self.retired = []
        for instance in active:
            instance.stop()
        event('connection', '本项目代理已停止；系统网络设置保持原样')

    def status(self):
        with self.lock:
            instance = self.current
            return {'running': bool(instance and instance.running), 'desired': self.desired,
                    'ready': bool(instance and instance.running and instance.transport_ready and not instance.transport_dead),
                    'applying': self.applying, 'attempts': self.attempts, 'next_attempt': self.next_attempt,
                    'error': self.last_error, 'health': self.health,
                    'pid': instance.process.pid if instance and instance.running else None,
                    'since': instance.created if instance else None,
                    'active_connections': instance.clients if instance else 0,
                    'draining_sessions': len(self.retired),
                    'logs': list(instance.lines) if instance else [], 'connection': self.connection}

    def preview(self):
        return compile_config(config(), vault.load(), 19700, 19701, redacted=True)

    def supervise(self):
        while True:
            try:
                cfg = config()
                self.desired = bool(cfg.get('auto_start',True) and cfg.get('guard_enabled',True) and time.time() >= cfg.get('guard_pause_until',0))
                if os.name == 'nt':
                    import ctypes
                    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if cfg.get('keep_awake') and self.desired else 0x80000000)
                with self.lock:
                    for old in self.retired[:]:
                        if not old.clients:
                            old.stop()
                            self.retired.remove(old)
                    start = self.desired and not self.applying and (not self.current or not self.current.running or self.current.transport_dead or self.health_failures >= 3) and time.time() >= self.next_attempt
                if start and vault.load().get('password'):
                    try:
                        self.apply()
                    except Exception as error:
                        self.attempts += 1
                        self.next_attempt = time.time() + min(300, 5 * 2 ** min(self.attempts, 6))
                        event('reconnect', '代理会话重试失败，已退避等待', {'attempt': self.attempts, 'error': str(error)[:300]})
                if self.current and self.current.running and time.time() - self.health_time > 15:
                    self.health_time = time.time()
                    from network import probe
                    from storage import add_probe
                    result = probe({'id': '_heartbeat', 'name': '通道保活', 'url': 'https://www.google.com/generate_204', 'group': 'other'}, 'vpn', self)
                    self.health = result
                    self.health_failures = 0 if result['transport_ok'] else self.health_failures + 1
                    add_probe(result)
            except Exception as error:
                self.last_error = str(error)[:400]
            time.sleep(2)
