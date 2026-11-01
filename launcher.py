import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path
from bootstrap import ensure_engine

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
RUNTIME.mkdir(exist_ok=True)
PROJECT_ID = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]


def current_url():
    try:
        value = json.loads((RUNTIME / 'server.json').read_text())
        url = 'http://127.0.0.1:' + str(value['port'])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/health', timeout=1) as response:
            data = json.load(response)
        return url if data.get('project_id') == PROJECT_ID and data.get('app') == 'suioo-console-v1' else None
    except Exception:
        return None


def task_matches_project(name,entry):
    """A checkout must never start a scheduled task belonging to another directory."""
    if os.name!='nt':return False
    try:
        result=subprocess.run(['schtasks.exe','/Query','/TN',name,'/XML'],capture_output=True,
                              timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:return False
        raw=result.stdout
        text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
        document=ET.fromstring(text)
        expected=str((ROOT/entry).resolve()).replace('/','\\').casefold()
        for node in document.iter():
            if node.tag.endswith('Arguments'):
                value=(node.text or '').strip()
                # Only accept the exact service/agent script argument, not a directory prefix.
                import shlex
                parts=[p.strip('"').replace('/','\\').casefold() for p in shlex.split(value,posix=False)]
                if expected in parts:return True
    except (OSError,ValueError,ET.ParseError,subprocess.TimeoutExpired,UnicodeError):pass
    return False


def browser_url(url,state):
    saved=state.get('connection',{})
    return url if saved.get('username_saved') and saved.get('password_saved') else url+'/#connection'


def ensure_user_integration():
    if os.name!='nt':return
    try:
        value=json.loads((RUNTIME/'integration-status.json').read_text(encoding='utf-8-sig'))
        if time.time()-value.get('time',0)<40 and value.get('user')==os.environ.get('USERNAME'):return
    except (OSError,ValueError):pass
    if task_matches_project('Suioo-Web-UserIntegration','integration.py'):
        subprocess.run(['schtasks.exe','/Run','/TN','Suioo-Web-UserIntegration'],capture_output=True,
                       timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        return
    interpreter=Path(sys.executable);hidden=interpreter.with_name('pythonw.exe')
    if not hidden.exists():hidden=interpreter
    with (RUNTIME/'integration-launch.log').open('ab') as log:
        subprocess.Popen([str(hidden),'-B',str(ROOT/'integration.py')],cwd=ROOT,stdin=subprocess.DEVNULL,
                         stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)


def wait_ready(url, timeout=90):
    """Gate clients on a validated tunnel, not just a listening web server."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    last = ''
    while time.monotonic() < deadline:
        with opener.open(url + '/api/state', timeout=4) as response:
            state = json.load(response)
        core = state['core']
        if (core.get('ready') and state['proxy'].get('running') and
                state['config'].get('proxy_enabled') and (core.get('health') or {}).get('page_ok')):
            return
        last = core.get('error', '')
        if not core.get('applying'):
            if not state['connection'].get('password_saved'):
                raise RuntimeError('请先打开 ' + url + '/#connection，填写 Suioo 接入账号（不是 ChatGPT 账号），点击验证账号并连接')
            if not state['config'].get('proxy_enabled') or not state['config'].get('auto_start'):
                raise RuntimeError('本地代理或自动连接已关闭，请在连接设置中启用：' + url + '/#connection')
        time.sleep(1)
    raise RuntimeError('代理通道未通过连通性检查，未启动外网客户端：' + last[:500])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--wait-ready', action='store_true')
    parser.add_argument('--no-integration', action='store_true',help='Open the proxy dashboard without starting the Windows user agent')
    args = parser.parse_args()
    if os.name=='nt' and sys.version_info<(3,12):raise RuntimeError('Please install Python 3.12 or newer, with Python added to PATH')
    ensure_engine()
    url = current_url()
    if not url:
        interpreter = Path(sys.executable)
        # CREATE_NO_WINDOW already hides the console. Keep the same executable as
        # the installer/firewall rule rather than switching the server to pythonw.
        hidden = interpreter.with_name('python.exe') if os.name=='nt' and interpreter.name.lower()=='pythonw.exe' else interpreter
        if not hidden.exists():
            hidden = interpreter
        scheduled = False
        if os.name == 'nt' and task_matches_project('Suioo-Web-Service','service.py'):
            result = subprocess.run(['schtasks.exe', '/Run', '/TN', 'Suioo-Web-Service'],
                                    capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            scheduled = result.returncode == 0
        if not scheduled:
            log = (RUNTIME / 'server.log').open('ab')
            subprocess.Popen([str(hidden), '-B', str(ROOT / 'service.py')], cwd=ROOT,
                             stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            log.close()
        for _ in range(50):
            time.sleep(.2)
            url = current_url()
            if url:
                break
    if not url:
        raise RuntimeError('启动失败，请查看 runtime/server.log')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url+'/api/state',timeout=5) as response:state=json.load(response)
    destination=browser_url(url,state)
    (RUNTIME / 'console-url.txt').write_text(destination, encoding='utf-8')
    if not args.no_integration:ensure_user_integration()
    if args.wait_ready:
        wait_ready(url)
    if not args.no_browser:
        webbrowser.open(destination)
    print(destination)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        (RUNTIME / 'startup-error.txt').write_text(str(error), encoding='utf-8')
        print(str(error), file=sys.stderr)
        sys.exit(1)
