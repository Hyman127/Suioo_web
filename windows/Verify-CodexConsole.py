"""Observe a disposable real Windows console; never attach to a user's existing terminal."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from winjob import WindowsJob
work=root/'runtime'/'codex-console-verify';work.mkdir(exist_ok=True)
project=Path(sys.argv[sys.argv.index('--project')+1]) if '--project' in sys.argv else work
if not project.is_dir():raise RuntimeError('Verification project does not exist')
script=work/'run.cmd'
script.write_text('@echo off\r\ntitle Suioo Codex Console Verification\r\ncall codex.cmd --sandbox danger-full-access --ask-for-approval never\r\n',encoding='ascii')
report={'time':time.time(),'interactive_tui_checked':True,'passed':False,
        'proxy_environment_present':bool(os.environ.get('HTTPS_PROXY')),'shell':'Windows PowerShell with user profile','project':str(project)}
class Coord(ctypes.Structure):_fields_=[('X',w.SHORT),('Y',w.SHORT)]
class Rect(ctypes.Structure):_fields_=[('Left',w.SHORT),('Top',w.SHORT),('Right',w.SHORT),('Bottom',w.SHORT)]
class Info(ctypes.Structure):_fields_=[('size',Coord),('cursor',Coord),('attributes',w.WORD),('window',Rect),('maximum',Coord)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.AttachConsole.argtypes=[w.DWORD];k.AttachConsole.restype=w.BOOL
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE];k.CreateFileW.restype=w.HANDLE
k.GetConsoleScreenBufferInfo.argtypes=[w.HANDLE,ctypes.POINTER(Info)];k.GetConsoleScreenBufferInfo.restype=w.BOOL
k.ReadConsoleOutputCharacterW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,Coord,ctypes.POINTER(w.DWORD)];k.ReadConsoleOutputCharacterW.restype=w.BOOL
k.CloseHandle.argtypes=[w.HANDLE]
process=None;job=None
try:
    process=subprocess.Popen(['powershell.exe','-NoLogo','-NoExit','-Command',
                              "$Host.UI.RawUI.WindowTitle='Suioo Codex Console Verification'; codex --sandbox danger-full-access --ask-for-approval never"],cwd=project,creationflags=subprocess.CREATE_NEW_CONSOLE)
    job=WindowsJob(process)
    for _ in range(35):
        time.sleep(1)
        k.FreeConsole()
        if not k.AttachConsole(process.pid):
            report['attach_error']=ctypes.get_last_error();continue
        handle=k.CreateFileW('CONOUT$',0x80000000|0x40000000,3,None,3,0,None)
        try:
            info=Info()
            if not k.GetConsoleScreenBufferInfo(handle,ctypes.byref(info)):continue
            count=min(info.size.X*(info.window.Bottom-info.window.Top+1),50000)
            buf=ctypes.create_unicode_buffer(count+1);read=w.DWORD()
            if k.ReadConsoleOutputCharacterW(handle,buf,count,Coord(0,info.window.Top),ctypes.byref(read)):
                text=buf.value
                text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]+','[email]',text)
                report['screen']=re.sub(r'\s+',' ',text).strip()[-6000:]
                report['passed']=bool(re.search(r'Codex|OpenAI',text,re.I) and re.search(r'context left|shortcuts|gpt-6|help|message',text,re.I) and 'Error loading' not in text)
                if report['passed']:break
        finally:k.CloseHandle(handle);k.FreeConsole()
        if process.poll() is not None:break
    report['test_process_id']=process.pid
except Exception as error:report['error']=str(error)
finally:
    k.FreeConsole()
    if job:job.close()
    elif process and process.poll() is None:process.terminate()
report['finished']=time.time()
(root/'runtime'/'codex-console-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
