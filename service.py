"""Capture service startup failures before importing the application."""
import os
import sys
import traceback
from pathlib import Path
root = Path(__file__).resolve().parent
os.chdir(root)
(root / 'runtime').mkdir(exist_ok=True)
log = (root / 'runtime' / 'server.log').open('a', encoding='utf-8', buffering=1)
sys.stdout = log
sys.stderr = log
try:
    import app
    app.run()
except BaseException:
    traceback.print_exc()
    raise SystemExit(1)
