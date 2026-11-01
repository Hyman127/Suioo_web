"""Use the signed-in Windows user's existing Codex authentication for a small smoke test."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = root/'runtime'/'codex-verify'
work.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ)
if '--inherit-proxy' not in sys.argv:
    environment.update(HTTP_PROXY='http://127.0.0.1:18790', HTTPS_PROXY='http://127.0.0.1:18790', NO_PROXY='localhost,127.0.0.1,::1')
cli = shutil.which('codex.cmd') or shutil.which('codex.exe')
report = {'time':time.time(),'cli':cli,'model_round_trip_passed':False,'interactive_tui_checked':False,
          'inherited_proxy': '--inherit-proxy' in sys.argv,'proxy_environment_present':bool(environment.get('HTTPS_PROXY'))}
def run(args, timeout=15):
    return subprocess.run(subprocess.list2cmdline([cli,*args]),shell=True,cwd=work,
                          env=environment,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
try:
    if not cli:
        raise RuntimeError('Codex was not found in PATH')
    version = run(['--version'])
    report['version'] = version.stdout.decode('utf-8','replace').strip()
    login = run(['login','status'])
    report['login_status_exit'] = login.returncode
    report['auth_mode'] = 'ChatGPT' if b'ChatGPT' in login.stdout+login.stderr else 'other'
    output = work/'response.txt'
    output.unlink(missing_ok=True)
    result = run(['--sandbox','danger-full-access','--ask-for-approval','never','exec',
                  '--skip-git-repo-check','--ephemeral','--json','--output-last-message',str(output),
                  'Reply with exactly SUIOO_CODEX_OK. Do not use tools, inspect files, or modify files.'], 100)
    report['exec_exit'] = result.returncode
    report['model_round_trip_passed'] = result.returncode == 0 and output.exists() and output.read_text(encoding='utf-8').strip() == 'SUIOO_CODEX_OK'
    text = (result.stdout+result.stderr).decode('utf-8','replace')
    text = re.sub(r'sk-[A-Za-z0-9_-]+|(?i:Bearer)\s+\S+','[redacted]',text)
    report['diagnostic_tail'] = text[-3500:]
except Exception as error:
    report['error'] = str(error)
report['finished'] = time.time()
(root/'runtime'/'codex-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
