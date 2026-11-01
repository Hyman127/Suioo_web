import json
import os
import subprocess
import threading
import time
from storage import ROOT, RUNTIME, atomic_json, config

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
_lock = threading.Lock()
_cached = {}


def snapshot(force=False):
    global _cached
    with _lock:
        if _cached and not force and time.time() - _cached['time'] < 25:
            return _cached
        if os.name == 'nt':
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                'Bypass', '-File', str(ROOT / 'windows' / 'Network-State.ps1')],
                capture_output=True, timeout=25, creationflags=FLAGS)
            if result.returncode:
                raise RuntimeError('Windows 网络状态读取失败')
            _cached = json.loads(result.stdout.decode('utf-8-sig', 'replace'))
        else:
            _cached = {'time': time.time(), 'interfaces': [], 'routes': [], 'computer': 'DEVELOPMENT'}
        atomic_json(RUNTIME / 'network.json', _cached)
        return _cached


def interfaces(state=None):
    state = state or _cached
    candidates = []
    for interface in state.get('interfaces', []):
        if interface['up'] and interface['physical'] and interface['ips']:
            defaults = [r for r in state['routes'] if r['index'] == interface['index'] and r['prefix'] == '0.0.0.0/0']
            if defaults:
                candidates.append((min(r['metric'] for r in defaults) + (interface.get('metric') or 0), interface))
    return (min(candidates, key=lambda row: row[0])[1] if candidates else None), None


def probe(site, mode='system', manager=None):
    row = {'time': time.time(), 'site_id': site['id'], 'name': site['name'], 'url': site['url'],
           'group': site['group'], 'mode': mode, 'transport_ok': False, 'page_ok': False}
    instance = None
    try:
        curl = r'C:\Windows\System32\curl.exe' if os.name == 'nt' else 'curl'
        args = [curl, '--silent', '--show-error', '-4', '--head', '--connect-timeout', '6',
                '--max-time', '12', '--output', os.devnull, '--write-out', '%{json}']
        if os.name == 'nt':
            args += ['--ssl-revoke-best-effort']
        if mode == 'direct':
            args += ['--noproxy', '*']
            row['interface'] = '直连 / 系统路由'
            row['outbound'] = 'direct'
        else:
            if manager is None:
                raise RuntimeError('代理管理器不可用')
            instance = manager.acquire()
            if mode == 'vpn':
                args += ['--proxy', 'socks5h://127.0.0.1:' + str(instance.forced_port), '--noproxy', '']
                row['outbound'] = 'suioo'
            else:
                args += ['--proxy', 'socks5h://127.0.0.1:' + str(instance.port), '--noproxy', '']
                from policy import Policy
                from urllib.parse import urlsplit
                decision = Policy().match(urlsplit(site['url']).hostname, instance.profile)
                row['outbound'] = 'direct' if decision['mode'] in ('direct', 'system') else 'suioo'
            row['interface'] = '用户态代理 · ' + ('直连' if row['outbound'] == 'direct' else 'Suioo')
        process = subprocess.run(args + [site['url']], capture_output=True, timeout=16, creationflags=FLAGS)
        metrics = json.loads(process.stdout.decode('utf-8', 'replace'))
        row.update(exit_code=process.returncode, http_status=int(metrics.get('http_code', 0)),
                   remote_ip=metrics.get('remote_ip', ''), local_ip=metrics.get('local_ip', ''),
                   dns_ms=round(float(metrics.get('time_namelookup', 0))*1000, 2) if mode == 'direct' else None,
                   tcp_ms=round(float(metrics.get('time_connect', 0))*1000, 2),
                   tls_ms=round(max(0, float(metrics.get('time_appconnect', 0))-float(metrics.get('time_connect', 0)))*1000, 2),
                   ttfb_ms=round(float(metrics.get('time_starttransfer', 0))*1000, 2),
                   total_ms=round(float(metrics.get('time_total', 0))*1000, 2),
                   error=process.stderr.decode('utf-8', 'replace').strip()[:400])
        row['transport_ok'] = process.returncode == 0 and row['http_status'] > 0
        row['page_ok'] = row['transport_ok'] and 200 <= row['http_status'] < 400
        if mode != 'direct':
            row['note'] = 'SOCKS 远端解析；DNS 阶段包含在代理握手中，不单独伪报 DNS 耗时'
        if row['http_status'] in (401,403,429):
            row['note'] = '服务器已响应，但有认证/验证/限流；不代表页面正常'
    except Exception as error:
        row['error'] = str(error)[:500]
    finally:
        if instance is not None:
            manager.release(instance)
    return row
