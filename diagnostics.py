"""Bounded, allowlisted network diagnostics; shareable reports contain no raw config/logs."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
SIGNALS = {
    'server_disconnected': r'server disconnected CSTP session',
    'server_internal_error': r'code 0xb0 Internal Error',
    'authentication_failed': r'authentication failed|login failed|invalid credentials',
    'certificate_error': r'certificate verify failed|certificate signed by unknown|CERT_[A-Z_]+',
    'dns_error': r'no such host|name resolution|could not resolve',
    'timeout': r'timed out|deadline exceeded',
}


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {} if default is None else default


def port(value, default):
    return value if type(value) is int and 1024 <= value <= 65535 else default


def flags_from_text(text):
    return {key: bool(re.search(pattern, text, re.I)) for key, pattern in SIGNALS.items()}


class LocalApp:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        cfg = load(self.root / 'config.json')
        info = load(self.root / 'runtime/server.json')
        self.web_port = port(info.get('port', cfg.get('web_port')), 18789)
        self.proxy_port = port(cfg.get('proxy_port'), 18790)
        self.base = 'http://127.0.0.1:' + str(self.web_port)
        self.identity = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()[:16]
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        with self.opener.open(self.base + path, timeout=3) as response:
            return json.loads(response.read(4_000_000))

    def state(self):
        health = self.get('/api/health')
        if health.get('app') != 'suioo-console-v1' or health.get('project_id') != self.identity:
            raise ValueError('OTHER_PROJECT')
        state = self.get('/api/state')
        if state.get('project_id') != self.identity:
            raise ValueError('OTHER_PROJECT')
        self.proxy_port = port(state.get('config', {}).get('proxy_port'), self.proxy_port)
        return state

    def post(self, path, data):
        self.state()  # Never modify a different checkout that happens to own the port.
        with self.opener.open(self.base + '/', timeout=3) as response:
            html = response.read(1_000_000).decode('utf-8')
        match = re.search(r'<meta\s+name="api-token"\s+content="([A-Za-z0-9_-]+)"', html)
        if not match:
            raise ValueError('TOKEN_MISSING')
        request = urllib.request.Request(self.base + path, json.dumps(data).encode(),
            {'Content-Type': 'application/json', 'X-Suioo-Token': match[1], 'Origin': self.base})
        self.state()
        with self.opener.open(request, timeout=8) as response:
            return json.loads(response.read(100_000))


def public_state(state):
    core = state.get('core', {})
    connection = state.get('connection', {})
    integration = state.get('integration', {})
    # Do not serialize raw state, errors, events, URLs, saved account names or logs.
    text = str(core.get('error', '')) + '\n' + '\n'.join(str(s) for s in core.get('logs', []))
    return {'available': True, 'ready': bool(core.get('ready')), 'running': bool(core.get('running')),
        'applying': bool(core.get('applying')), 'desired': bool(core.get('desired')),
        'pid': core.get('pid') if type(core.get('pid')) is int else None,
        'attempts': core.get('attempts') if type(core.get('attempts')) is int else 0,
        'credentials_saved': bool(connection.get('username_saved') and connection.get('password_saved')),
        'proxy_running': bool(state.get('proxy', {}).get('running')),
        'integration_enabled': bool(integration.get('enabled')),
        'browser_proxy_active': bool(integration.get('browser_proxy_active')),
        'terminal_proxy_configured': bool(integration.get('new_terminals_configured')),
        'signals': flags_from_text(text)}


def windows_snapshot(proxy_port=18790):
    if os.name != 'nt':
        return {'supported': False}
    script = ROOT / 'windows/Diagnostic-State.ps1'
    try:
        p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(script), '-ProxyPort', str(proxy_port)], capture_output=True, timeout=18, creationflags=FLAGS)
        return json.loads(p.stdout.decode('utf-8-sig')) if p.returncode == 0 else {'collection_failed': True}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'collection_failed': True}


def dns_probe(host):
    start = time.monotonic()
    try:
        p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT / 'windows/Diagnostic-DNS.ps1'), '-TargetHost', host],
            capture_output=True, timeout=10, creationflags=FLAGS)
        data = json.loads(p.stdout.decode('utf-8-sig')) if p.returncode == 0 else {'resolved': False}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = {'resolved': False, 'timed_out_or_tool_failed': True}
    return {'host': host, 'duration_s': round(time.monotonic() - start, 3), **data}


def curl_info():
    exe = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/curl.exe') if os.name == 'nt' else 'curl'
    try:
        p = subprocess.run([exe, '--version'], capture_output=True, timeout=4, creationflags=FLAGS)
        text = p.stdout.decode('utf-8', 'replace')
        match = re.search(r'curl (\d+)\.(\d+)\.(\d+)', text)
        version = tuple(map(int, match.groups())) if match else (0, 0, 0)
        return exe, {'available': p.returncode == 0, 'version': '.'.join(map(str, version)),
            'http2': 'HTTP2' in text, 'best_effort_revocation': os.name == 'nt' and version >= (7, 70, 0)}
    except (OSError, subprocess.TimeoutExpired):
        return exe, {'available': False}


METRICS = ('status', 'dns_s', 'connect_s', 'tls_end_s', 'ttfb_s', 'total_s', 'bytes', 'bytes_per_second', 'connect_status')


def probe(exe, capabilities, proxy_port, name, url, via_proxy=True, ipv4=True, http1=False):
    row = {'name': name, 'via_proxy': via_proxy, 'ipv4': ipv4, 'http1_forced': http1}
    args = [exe, '--silent', '--show-error', '--connect-timeout', '5', '--max-time', '12',
        '--max-filesize', '2097152', '--output', os.devnull,
        '--write-out', '%{http_code}|%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}|%{time_total}|%{size_download}|%{speed_download}|%{http_connect}']
    if ipv4:
        args.append('-4')
    if http1:
        args.append('--http1.1')
    if capabilities.get('best_effort_revocation'):
        args.append('--ssl-revoke-best-effort')
    args += ['--proxy', 'http://127.0.0.1:' + str(proxy_port), '--noproxy', ''] if via_proxy else ['--noproxy', '*']
    # Avoid curl's user config and inherited proxy overrides affecting the comparison.
    args.insert(1, '--disable')
    try:
        p = subprocess.run(args + [url], capture_output=True, timeout=15, creationflags=FLAGS)
        values = p.stdout.decode('ascii', 'replace').strip().split('|')
        if len(values) == len(METRICS):
            for key, value in zip(METRICS, values):
                row[key] = float(value)
            for key in ('status', 'connect_status', 'bytes'):
                row[key] = int(row[key])
        row['exit'] = p.returncode
        # Error codes classify failures; stderr can contain usernames/proxy credentials.
        row['error_kind'] = {5: 'proxy_dns', 6: 'dns', 7: 'connection', 28: 'timeout', 35: 'tls',
            51: 'certificate', 60: 'certificate', 56: 'tunnel_or_receive', 63: 'response_too_large'}.get(p.returncode, 'none' if p.returncode == 0 else 'curl_error')
        row['ok'] = p.returncode == 0 and 200 <= row.get('status', 0) < 400
    except subprocess.TimeoutExpired:
        row.update(exit=-1, error_kind='process_timeout', ok=False)
    except (OSError, ValueError):
        row.update(exit=-2, error_kind='tool_or_metrics_error', ok=False)
    return row


def sample(app, seconds=18):
    rows = []
    for n in range(7):
        try:
            rows.append(public_state(app.state()))
        except ValueError:
            rows.append({'available': False, 'other_project': True})
        except Exception:
            rows.append({'available': False})
        if n < 6:
            time.sleep(seconds / 6)
    return rows


def log_signals(root=ROOT):
    result = dict.fromkeys(SIGNALS, False)
    # Read only a bounded tail; retain flags only, never copy lines to the report.
    try:
        with (Path(root) / 'runtime/core.log').open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 100_000))
            result = flags_from_text(stream.read().decode('utf-8', 'replace'))
    except OSError:
        pass
    return result


def classify(report):
    findings = []
    samples = report['samples']
    checks = {r['name']: r for r in report['checks']}
    windows = report.get('windows', {})
    def add(code, text):
        findings.append({'code': code, 'message': text})
    if any(s.get('other_project') for s in samples):
        add('OTHER_PROJECT', '本地端口由另一个项目副本使用；本次不修改该副本。请在实际启动项目的目录运行诊断。')
    elif not any(s.get('available') for s in samples):
        add('APP_UNAVAILABLE', '本项目面板未启动或无法响应；先运行启动Suioo.cmd。')
    elif not any(s.get('credentials_saved') for s in samples):
        add('LOGIN_REQUIRED', '本项目没有保存完整账号；请在连接页输入自己的 Suioo 账号。')
    elif not any(s.get('ready') for s in samples):
        if not any(s.get('desired') or s.get('applying') for s in samples):
            add('CONNECTION_STOPPED', '连接尚未开启；请在连接页点击连接后重新诊断。')
        else:
            add('TUNNEL_NOT_READY', '隧道没有就绪，请结合当前错误信号和请求结果排查。')
    pids = {s.get('pid') for s in samples if s.get('pid')}
    current_signals = {k: any(s.get('signals', {}).get(k) for s in samples) for k in SIGNALS}
    if current_signals['server_disconnected']:
        add('SERVER_DISCONNECT', '当前会话记录到服务端主动断开；核查账号并发限制及服务端线路，修改本机 DNS 不能修复这类断线。')
    if len(pids) > 1 or (any(s.get('ready') for s in samples) and any(s.get('available') and not s.get('ready') for s in samples)):
        add('TUNNEL_UNSTABLE', '观察期间隧道进程切换或就绪状态丢失，可能造成网页反复等待。')
    if current_signals['authentication_failed']:
        add('AUTH_FAILED', '当前会话存在认证失败信号；请核实账号、密码和同时在线设备。')
    if checks.get('baidu_direct', {}).get('ok') is False:
        add('DIRECT_BASELINE_FAILED', '国内直连基线也失败，需同时检查目标环境本身的网络。')
    google = checks.get('google_204_proxy_v4', {})
    html = checks.get('google_page_proxy_v4', {})
    if report.get('curl', {}).get('available') is False:
        add('CURL_MISSING', '系统 curl.exe 不可用，无法完成 HTTP 对比；请使用受支持且完整的 Windows 环境。')
    elif not google.get('ok'):
        add('PROXY_GOOGLE_FAILED', '显式通过本地代理的 Google 检查失败；不是仅凭浏览器主观变慢得出的判断。')
    if any(r.get('error_kind') == 'certificate' for r in report['checks']):
        add('CERTIFICATE_CHECK_FAILED', '请求遇到证书校验错误；核实系统时间、系统证书和网络中的 HTTPS 检查，保留证书校验。')
    if google.get('ok') and (google.get('total_s', 0) > 3 or html.get('total_s', 0) > 5):
        add('PROXY_GOOGLE_SLOW', '显式代理请求也慢；重点查看报告中的 CONNECT、TLS、首字节和下载耗时，候选原因是隧道或远端链路。')
    if google.get('ok') and not html.get('ok'):
        add('PAGE_FAILED', 'Google 小请求成功但首页请求失败；通道检查成功不足以证明网页能正常打开。')
    if windows.get('browser_uses_pac'):
        add('PAC_PRESENT', '浏览器存在 PAC 配置，可能覆盖手动代理；本工具保留 PAC，需核实浏览器实际策略。')
    if google.get('ok') and not windows.get('browser_uses_suioo'):
        add('BROWSER_NOT_CONNECTED', '显式代理可访问 Google，但 Windows 浏览器没有使用本项目代理；可运行一键修复重新接入。')
    if google.get('ok') and html.get('ok') and windows.get('browser_uses_suioo'):
        add('BROWSER_COMPARE', '命令行经代理可访问 Google；若浏览器仍慢，继续核查浏览器扩展、独立代理、企业策略或安全 DNS，当前报告不能单独确定哪项导致。')
    if windows.get('proxy_env_conflict'):
        add('PROXY_ENV_CONFLICT', '部分终端代理变量指向其他地址；不会自动覆盖其他代理软件设置。')
    if windows.get('browser_cmd_proxy_override'):
        add('BROWSER_OVERRIDE', '浏览器启动参数包含独立代理设置，可能覆盖 Windows 代理。')
    if windows.get('hosts_overrides_google'):
        add('HOSTS_OVERRIDE', 'hosts 中存在 Google 相关映射；保留原文件，请核实是否为预期配置。')
    if report.get('rules', {}).get('google_mode') in ('direct', 'system'):
        add('GOOGLE_RULE_DIRECT', '当前规则将 Google 分配到直连；自定义规则可能覆盖默认代理规则，需要核实分流设置。')
    if not findings:
        add('NO_CONFIRMED_CAUSE', '本次未确认单一原因；保留报告，结合问题发生时的浏览器现象判断。')
    return findings


def collect(app, quick=False):
    print('检查本地面板、代理和 Windows 设置...', flush=True)
    try:
        initial = app.state()
    except Exception:
        initial = {}
    exe, capabilities = curl_info()
    report = {'schema': 1, 'time': time.strftime('%Y-%m-%d %H:%M:%S %z'),
        'privacy': 'Allowlisted fields only; no credentials, paths, raw logs, request bodies or config.',
        'curl': capabilities, 'checks': [], 'rules': {}, 'samples': [], 'historical_log_signals': log_signals(app.root)}
    source = os.environ.get('SUIOO_DIAGNOSTIC_PYTHON_SOURCE', '')
    report['diagnostics_backend'] = 'python'
    report['python_discovery'] = source if source in ('project_runtime', 'running_service', 'launcher_location', 'path', 'registry') else 'direct'
    if initial:
        try:
            rule = app.post('/api/rule-test', {'host': 'www.google.com'})
            report['rules'] = {'google_mode': rule.get('mode') if rule.get('mode') in ('direct', 'vpn', 'system') else 'unknown'}
        except Exception:
            report['rules'] = {'query_failed': True}
    jobs = [
        ('baidu_direct', 'https://www.baidu.com/', False, True, False),
        ('baidu_proxy', 'https://www.baidu.com/', True, True, False),
        ('google_204_proxy_v4', 'https://www.google.com/generate_204', True, True, False),
        ('google_page_proxy_v4', 'https://www.google.com/', True, True, False),
        ('google_logo_proxy_v4', 'https://www.gstatic.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png', True, True, False),
        ('google_204_proxy_auto', 'https://www.google.com/generate_204', True, False, False),
        ('google_204_proxy_http1', 'https://www.google.com/generate_204', True, True, True),
        ('google_204_direct_reference', 'https://www.google.com/generate_204', False, True, False),
    ]
    print('对比国内直连、Google 首页和静态资源，观察隧道约 18 秒...', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        observation = pool.submit(sample, app, 0 if quick else 18)
        network = pool.submit(windows_snapshot, app.proxy_port)
        dns = [pool.submit(dns_probe, host) for host in ('www.google.com', 'www.baidu.com')] if os.name == 'nt' else []
        futures = [pool.submit(probe, exe, capabilities, app.proxy_port, *job) for job in jobs] if capabilities['available'] else []
        report['checks'] = [f.result() for f in futures]
        report['samples'] = observation.result()
        report['windows'] = network.result()
        report['system_dns'] = [f.result() for f in dns]
    report['findings'] = classify(report)
    return report


def repair(app, report):
    """Reapply this project's integration only after stable, successful explicit proxy checks."""
    actions = []
    samples = report['samples']
    checks = {r['name']: r for r in report['checks']}
    if any(s.get('other_project') for s in samples):
        return [{'code': 'SKIPPED_OTHER_PROJECT', 'message': '另一个项目副本占用端口，未执行修复。'}]
    stable = (len(samples) >= 7 and all(s.get('ready') and not s.get('applying') for s in samples)
        and len({s.get('pid') for s in samples}) == 1 and samples[0].get('pid') is not None)
    healthy = all(checks.get(k, {}).get('ok') for k in ('google_204_proxy_v4', 'google_page_proxy_v4', 'google_logo_proxy_v4'))
    if report.get('windows', {}).get('browser_uses_pac') or report.get('windows', {}).get('browser_other_proxy') or report.get('windows', {}).get('proxy_env_conflict'):
        return [{'code': 'SKIPPED_OTHER_PROXY', 'message': '检测到 PAC 或其他代理配置，保留其设置，避免覆盖其他网络工具。'}]
    # Local backup is private and deliberately never added to the report ZIP.
    import integration
    from launcher import ensure_user_integration
    if integration.ROOT.resolve() != app.root.resolve() or app.proxy_port != 18790:
        return [{'code': 'SKIPPED_UNSUPPORTED_LOCATION', 'message': '项目目录或代理端口与当前接入模块不一致，保留设置。'}]
    if not (stable and healthy):
        if report.get('windows', {}).get('browser_uses_suioo') and integration.BACKUP.is_file():
            backup = backup_settings(app, integration)
            integration.restore_now()
            return [{'code': 'STALE_PROXY_RESTORED', 'message': '已备份设置，并请求恢复本项目留下的失效代理；Google 仍需有效隧道。'}]
        return [{'code': 'SKIPPED_UNHEALTHY_TUNNEL', 'message': '代理通道没有持续通过检查，保留原设置；请按诊断结论排查连接或服务端。'}]
    backup = backup_settings(app, integration)
    snapshot = load(backup / 'settings-before.json')
    try:
        app.post('/api/integration', {'enabled': True})
        ensure_user_integration()
        for _ in range(6):
            time.sleep(2)
            if app.state().get('integration', {}).get('browser_proxy_active'):
                actions.append({'code': 'INTEGRATION_REAPPLIED', 'message': '已备份本机设置并重新接入 Windows 浏览器及新终端。已有终端请重新打开。'})
                break
        else:
            restore_settings(snapshot, integration)
            actions.append({'code': 'INTEGRATION_NOT_CONFIRMED', 'message': '接入没有确认成功，已请求恢复修复前设置；请查看修复后诊断。'})
    except Exception:
        try:
            restore_settings(snapshot, integration)
        except Exception:
            pass
        actions.append({'code': 'REPAIR_FAILED', 'message': '重新接入未完成，已尝试恢复修复前设置；本机保留备份。'})
    return actions


def backup_settings(app, integration):
    from storage import atomic_json
    backup = app.root / 'data/diagnostic-backups' / uuid.uuid4().hex
    backup.mkdir(parents=True, exist_ok=False)
    internet = integration.Registry(r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
    environment = integration.Registry('Environment')
    snapshot = {'internet': internet.read(integration.PROXY), 'environment': environment.read(integration.ENVIRONMENT),
        'preferences': integration.preferences(), 'vscode_files': {}}
    for settings in integration.settings_paths():
        text = settings.read_text(encoding='utf-8-sig') if settings.exists() else '{}'
        env = json.loads(integration.clean_jsonc(text)).get('terminal.integrated.env.windows') or {}
        snapshot['vscode_files'][str(settings)] = {k: env.get(k) for k in integration.ENVIRONMENT}
    atomic_json(backup / 'settings-before.json', snapshot)
    return backup


def restore_settings(snapshot, integration):
    integration.configure(snapshot['preferences'].get('enabled', False))
    internet = integration.Registry(r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
    environment = integration.Registry('Environment')
    internet.write(integration.owned_restore(internet.read(integration.PROXY), snapshot['internet'], integration.PROXY))
    environment.write(integration.owned_restore(environment.read(integration.ENVIRONMENT), snapshot['environment'], integration.ENVIRONMENT))
    integration.restore_terminal_settings(snapshot)
    integration.notify()


def render(report):
    lines = ['Suioo 网络诊断', report['time'], '', '判断：']
    lines += ['- ' + f['message'] for f in report['findings']]
    if report.get('repair_actions'):
        lines += ['', '修复结果：'] + ['- ' + a['message'] for a in report['repair_actions']]
    windows = report.get('windows', {})
    lines += ['', '本地检查：',
        '面板可响应：' + str(any(s.get('available') for s in report['samples'])),
        '代理端口监听：' + str(windows.get('local_proxy_listening', '未收集')),
        'Windows 浏览器已接入：' + str(windows.get('browser_uses_suioo', '未收集')),
        'PAC 配置：' + str(windows.get('browser_uses_pac', '未收集')),
        '隧道就绪采样：' + str(sum(bool(s.get('ready')) for s in report['samples'])) + '/' + str(len(report['samples']))]
    for row in report.get('system_dns', []):
        lines.append('系统 DNS ' + row['host'] + '：' + ('成功' if row.get('resolved') else '失败') + '，含工具启动 ' + str(row['duration_s']) + ' 秒')
    lines += ['', '请求对比（时间为累计秒数；直连 Google 仅为参考，不要求它必须成功）：',
        '检查 | 状态 | curl | DNS | TCP连接 | TLS完成 | 首字节 | 总时间 | 下载字节']
    for row in report['checks']:
        lines.append(' | '.join(str(row.get(k, '-')) for k in ('name', 'status', 'exit', 'dns_s', 'connect_s', 'tls_end_s', 'ttfb_s', 'total_s', 'bytes')))
    lines += ['', 'HTTP 403/429 是服务端限制，不代表网页正常。代理 DNS 通常在远端完成，curl 本地 DNS 时间不能代表远端解析耗时。',
        '代理测试的 TCP 是连接本地代理的耗时；TLS完成包含 CONNECT 等待。-4 只限制客户端连接，不证明远端采用 IPv4。',
        '历史日志信号与本次会话分开记录；历史断线不证明当前仍然断线。',
        '仅修改能够确认属于本项目的接入设置；未更改 DNS、防火墙、网卡、路由或证书校验。',
        '可分享：同目录的诊断报告.zip（仅报告.txt、report.json）。本机备份不在 ZIP 中。']
    return '\n'.join(lines) + '\n'


def save_report(report, root=ROOT):
    destination = Path(root) / 'runtime/diagnostics' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    destination.mkdir(parents=True, exist_ok=False)
    body = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    text = render(report).encode('utf-8-sig')
    (destination / 'report.json').write_bytes(body)
    (destination / '报告.txt').write_bytes(text)
    with zipfile.ZipFile(destination / '诊断报告.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.json', body)
        archive.writestr('报告.txt', text)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    app = LocalApp()
    report = collect(app)
    if args.repair:
        print('根据诊断结果处理本项目接入设置...', flush=True)
        try:
            report['repair_actions'] = repair(app, report)
        except Exception:
            report['repair_actions'] = [{'code': 'REPAIR_FAILED', 'message': '自动修复未确认完成，已保留诊断结果；本机可能需要检查写入权限。'}]
        if any(a['code'] in ('INTEGRATION_REAPPLIED', 'STALE_PROXY_RESTORED', 'INTEGRATION_NOT_CONFIRMED', 'REPAIR_FAILED') for a in report['repair_actions']):
            before = report
            report = collect(app)
            report['repair_actions'] = before['repair_actions']
            report['before_repair'] = {'findings': before['findings'], 'windows': before['windows']}
    destination = save_report(report)
    print(render(report))
    print('报告已保存：' + str(destination))
    if os.name == 'nt' and not args.no_open:
        try:
            os.startfile(str(destination))
        except OSError:
            pass
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('诊断未能完成：' + type(error).__name__ + '。请确认项目完整解压且可写。')
        raise SystemExit(1)
