"""Per-user proxy integration. A separate logged-in user agent restores browser routing on failure."""
import copy
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from storage import ROOT, RUNTIME, atomic_json

PREFERENCES = ROOT/'data'/'integration.json'
BACKUP = ROOT/'data'/'integration-backup.json'
ENVIRONMENT = {'HTTP_PROXY':'http://127.0.0.1:18790','HTTPS_PROXY':'http://127.0.0.1:18790',
               'NO_PROXY':'localhost,127.0.0.1,::1'}
PROXY = {'ProxyEnable':1,'ProxyServer':'127.0.0.1:18790','ProxyOverride':'<local>;localhost;127.*;[::1]','AutoConfigURL':None}

def read_json(path, default):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return copy.deepcopy(default)

def preferences():return read_json(PREFERENCES,{'enabled':False})

def configure(enabled):
    PREFERENCES.parent.mkdir(exist_ok=True)
    atomic_json(PREFERENCES,{'enabled':bool(enabled)})

def status():
    state=read_json(RUNTIME/'integration-status.json',{})
    state['enabled']=preferences()['enabled']
    state['stale']=time.time()-state.get('time',0)>20
    return state

def clean_jsonc(text, trailing=True):
    """Mask comments and trailing commas without changing character offsets."""
    result=list(text);quoted=False;escaped=False;i=0
    while i<len(text):
        c=text[i]
        if quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
            i+=1;continue
        if c=='"':quoted=True;i+=1;continue
        if text[i:i+2] in ('//','/*'):
            end=text.find('\n',i+2) if text[i:i+2]=='//' else text.find('*/',i+2)
            end=len(text) if end<0 else end if text[i:i+2]=='//' else end+2
            for k in range(i,end):
                if text[k] not in '\r\n':result[k]=' '
            i=end;continue
        i+=1
    masked=''.join(result);quoted=False;escaped=False
    if not trailing:return masked
    for i,c in enumerate(masked):
        if quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True
        elif c==',':
            rest=masked[i+1:].lstrip()
            if rest.startswith(('}',']')):result[i]=' '
    return ''.join(result)

def edit_setting(text,key,value):
    clean=clean_jsonc(text);document=json.loads(clean);decoder=json.JSONDecoder();i=clean.index('{')+1
    while i<len(clean):
        while i<len(clean) and clean[i].isspace():i+=1
        if clean[i]=='}':break
        name,end=decoder.raw_decode(clean,i);i=end
        while clean[i].isspace():i+=1
        if clean[i]!=':':raise ValueError('Invalid settings JSON')
        i+=1
        while clean[i].isspace():i+=1
        start=i;_,end=decoder.raw_decode(clean,i)
        if name==key:
            return text[:start]+json.dumps(value,ensure_ascii=False,indent=2)+text[end:]
        i=end
        while clean[i].isspace():i+=1
        if clean[i]==',':i+=1
    at=clean.rfind('}');prefix=',' if document and not clean_jsonc(text,False)[:at].rstrip().endswith(',') else ''
    return text[:at]+prefix+'\n  '+json.dumps(key)+': '+json.dumps(value,ensure_ascii=False,indent=2)+'\n'+text[at:]

def owned_restore(current,previous,managed):
    result=dict(current)
    for key,value in managed.items():
        if current.get(key)==value:
            if previous.get(key) is None:result.pop(key,None)
            else:result[key]=previous[key]
    return result

class Registry:
    def __init__(self,path):
        import winreg
        self.winreg=winreg;self.path=path
    def read(self,keys):
        result={};w=self.winreg
        with w.CreateKey(w.HKEY_CURRENT_USER,self.path) as handle:
            for key in keys:
                try:result[key]=w.QueryValueEx(handle,key)[0]
                except FileNotFoundError:result[key]=None
        return result
    def write(self,values):
        w=self.winreg
        with w.CreateKey(w.HKEY_CURRENT_USER,self.path) as handle:
            for key,value in values.items():
                if value is None:
                    try:w.DeleteValue(handle,key)
                    except FileNotFoundError:pass
                else:w.SetValueEx(handle,key,0,w.REG_DWORD if isinstance(value,int) else w.REG_SZ,value)

def notify():
    ctypes.windll.wininet.InternetSetOptionW(None,39,None,0)
    ctypes.windll.wininet.InternetSetOptionW(None,37,None,0)
    from ctypes import wintypes as w
    send=ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPCWSTR,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
    result=ctypes.c_size_t()
    send(65535,0x1A,0,'Environment',2,2000,ctypes.byref(result))

def settings_paths():
    standard=Path(os.environ['APPDATA'])/'Code'/'User'/'settings.json'
    roots=set()
    if os.name=='nt':
        query=r'''[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);$r=@(Get-CimInstance Win32_Process -Filter "Name='Code.exe'"|ForEach-Object{if($_.CommandLine -match '--(?:vscode-)?user-data-dir[= ](?:"([^"]+)"|(\S+))'){if($Matches[1]){$Matches[1]}else{$Matches[2]}};if($_.ExecutablePath){$p=Join-Path (Split-Path $_.ExecutablePath -Parent) 'data\user-data';if(Test-Path $p){$p}}});ConvertTo-Json -InputObject @($r|Sort-Object -Unique) -Compress'''
        try:
            p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',query],capture_output=True,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
            if p.returncode==0:roots.update(json.loads(p.stdout.decode('utf-8-sig')))
        except Exception:pass
    paths={standard}
    for value in roots:
        user=Path(value)/'User';paths.add(user/'settings.json')
        if (user/'profiles').is_dir():paths.update((user/'profiles').glob('*/settings.json'))
    return sorted(paths,key=str)

def apply_terminal_settings(backup,paths):
    standard=Path(os.environ['APPDATA'])/'Code'/'User'/'settings.json'
    records=backup.setdefault('vscode_files',{})
    for settings in paths:
        text=settings.read_text(encoding='utf-8-sig') if settings.exists() else '{}'
        doc=json.loads(clean_jsonc(text));env=dict(doc.get('terminal.integrated.env.windows') or {})
        if str(settings) not in records:
            records[str(settings)]=backup.get('vscode',{}) if settings==standard else {k:env.get(k) for k in ENVIRONMENT}
            atomic_json(BACKUP,backup)
        updated=dict(env);updated.update(ENVIRONMENT)
        if updated!=env:
            settings.parent.mkdir(parents=True,exist_ok=True)
            settings.write_text(edit_setting(text,'terminal.integrated.env.windows',updated),encoding='utf-8')

def restore_terminal_settings(backup):
    standard=Path(os.environ['APPDATA'])/'Code'/'User'/'settings.json'
    records=backup.get('vscode_files',{str(standard):backup.get('vscode',{})})
    for filename,previous in records.items():
        settings=Path(filename)
        if settings.exists():
            text=settings.read_text(encoding='utf-8-sig');doc=json.loads(clean_jsonc(text))
            env=owned_restore(doc.get('terminal.integrated.env.windows') or {},previous,ENVIRONMENT)
            settings.write_text(edit_setting(text,'terminal.integrated.env.windows',env),encoding='utf-8')

def restore_now():
    configure(False)
    backup=read_json(BACKUP,{})
    if not backup:return
    internet=Registry(r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
    current=internet.read(PROXY)
    if current.get('ProxyServer')==PROXY['ProxyServer'] and current.get('ProxyEnable')==1:
        internet.write(backup['internet'])
    environment=Registry('Environment')
    restored=owned_restore(environment.read(ENVIRONMENT),backup['environment'],ENVIRONMENT)
    environment.write({k:restored.get(k) for k in ENVIRONMENT})
    restore_terminal_settings(backup)
    notify()


def keep_control_tunnel():
    """Reuse the existing trusted SSH config; leave an already-running tunnel alone."""
    config=Path(os.environ['USERPROFILE'])/'.ssh'/'vscode_remote_config'
    if not config.exists():return
    flags=subprocess.CREATE_NO_WINDOW
    query=r"""@(Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" | Where-Object {$_.CommandLine -match '127\.0\.0\.1:2223:127\.0\.0\.1:22'}).Count"""
    check=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',query],capture_output=True,timeout=10,creationflags=flags)
    if check.returncode==0 and check.stdout.strip().isdigit() and int(check.stdout.strip())>0:return
    if check.returncode:return
    log=RUNTIME/'control-tunnel.log'
    if log.exists() and log.stat().st_size>2_000_000:log.replace(log.with_suffix('.previous.log'))
    with log.open('ab') as stream:
        subprocess.Popen(['ssh.exe','-F',str(config),'-NT','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
                          '-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                          '-R','127.0.0.1:2223:127.0.0.1:22','tencent-vscode'],stdin=subprocess.DEVNULL,
                         stdout=stream,stderr=stream,creationflags=flags)

def acquire_user_mutex():
    # Prevent a double-click launcher and a logon task from creating duplicate user agents.
    import hashlib
    name='Local\\SuiooWebUser-'+hashlib.sha256((str(ROOT).casefold()+'|'+os.environ.get('USERNAME','')).encode()).hexdigest()[:24]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    mutex=kernel.CreateMutexW(None,True,name)
    if not mutex:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:kernel.CloseHandle(mutex);raise SystemExit(0)
    import atexit
    atexit.register(kernel.CloseHandle,mutex)

def run():
    if os.name!='nt':raise RuntimeError('Windows user integration requires Windows')
    acquire_user_mutex()
    internet=Registry(r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
    environment=Registry('Environment')
    settings=Path(os.environ['APPDATA'])/'Code'/'User'/'settings.json'
    backup=read_json(BACKUP,{})
    targets=settings_paths();settings_checked=time.monotonic()
    failures=0;terminal_applied=False;restored=False;control_checked=0
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
        try:
            wanted=preferences()['enabled'];healthy=False;error=''
            if time.monotonic()-settings_checked>60:
                settings_checked=time.monotonic();found=settings_paths()
                if found!=targets:targets=found;terminal_applied=False
            if time.monotonic()-control_checked>30:
                control_checked=time.monotonic()
                try:keep_control_tunnel()
                except Exception:pass
            try:
                with opener.open('http://127.0.0.1:18789/api/state',timeout=2) as response:s=json.load(response)
                c=s['core'];healthy=bool(c.get('ready') and (c.get('health') or {}).get('page_ok') and s['proxy'].get('running') and s['config']['proxy_enabled'])
            except Exception as exc:error=str(exc)[:180]
            failures=0 if healthy else failures+1
            current=internet.read(PROXY)
            if wanted and healthy:
                restored=False
                if not backup:
                    text=settings.read_text(encoding='utf-8-sig') if settings.exists() else '{}'
                    document=json.loads(clean_jsonc(text));old_env=document.get('terminal.integrated.env.windows') or {}
                    backup={'internet':current,'environment':environment.read(ENVIRONMENT),
                            'vscode':{k:old_env.get(k) for k in ENVIRONMENT}}
                    BACKUP.parent.mkdir(exist_ok=True);atomic_json(BACKUP,backup)
                if current!=PROXY:internet.write(PROXY);notify()
                if not terminal_applied:
                    apply_terminal_settings(backup,targets)
                    environment.write(ENVIRONMENT);notify();terminal_applied=True
            elif backup and (not wanted or failures>=3):
                if current.get('ProxyServer')==PROXY['ProxyServer'] and current.get('ProxyEnable')==1:
                    internet.write(backup['internet']);notify()
                if not wanted and not restored:
                    restore_terminal_settings(backup)
                    restored_env=owned_restore(environment.read(ENVIRONMENT),backup['environment'],ENVIRONMENT)
                    environment.write({k:restored_env.get(k) for k in ENVIRONMENT});notify();terminal_applied=False;restored=True
            now=internet.read(PROXY)
            atomic_json(RUNTIME/'integration-status.json',{'time':time.time(),'user':os.environ.get('USERNAME'),
                        'browser_proxy_active':now.get('ProxyEnable')==1 and now.get('ProxyServer')==PROXY['ProxyServer'],
                        'new_terminals_configured':terminal_applied,'vscode_settings_paths':[str(p) for p in targets],'healthy':healthy,'consecutive_failures':failures,'error':error})
        except Exception as exc:
            atomic_json(RUNTIME/'integration-status.json',{'time':time.time(),'error':str(exc)[:250]})
        time.sleep(5)

if __name__=='__main__':
    if '--restore' in sys.argv:restore_now();print('Original user proxy and new-terminal settings restored.')
    else:run()
