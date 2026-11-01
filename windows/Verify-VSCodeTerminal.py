"""Runs inside a real VS Code terminal without supplying or repairing its environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
root=Path(__file__).resolve().parents[1]
work=root/'runtime'/'vscode-network-check'
version=(work/'powershell-codex-version.txt').read_text(encoding='utf-8-sig',errors='replace')
report={'time':time.time(),'term_program':os.environ.get('TERM_PROGRAM'),'proxy_environment_present':
        os.environ.get('HTTPS_PROXY')=='http://127.0.0.1:18790','powershell_codex_resolved': 'codex-cli ' in version,
        'model_round_trip_passed':False,'working_directory':str(Path.cwd())}
try:
    if report['term_program']!='vscode':raise RuntimeError('Not an actual VS Code terminal')
    if not report['proxy_environment_present']:raise RuntimeError('VS Code terminal still has no usable proxy')
    if not report['powershell_codex_resolved']:raise RuntimeError('PowerShell failed to start codex; inspect powershell-codex-version.txt')
    result=subprocess.run([sys.executable,'-B',str(root/'windows'/'Verify-Codex.py'),'--inherit-proxy'],stdin=subprocess.DEVNULL,timeout=140)
    model=json.loads((root/'runtime'/'codex-verification.json').read_text(encoding='utf-8'))
    report['model_round_trip_passed']=model.get('model_round_trip_passed',False)
    report['cli_version']=model.get('version')
except Exception as error:report['error']=str(error)
report['finished']=time.time()
(root/'runtime'/'vscode-terminal-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
