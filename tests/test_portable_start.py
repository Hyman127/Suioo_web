import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == 'win32', 'Windows bootstrap behavior')
class PortableStartTests(unittest.TestCase):
    def test_launcher_returns_while_owned_service_child_is_still_running(self):
        script = Path(__file__).resolve().parents[1] / 'windows/Start-Portable.ps1'
        with tempfile.TemporaryDirectory(prefix='suioo portable start ') as directory:
            root = Path(directory)
            launcher = "import subprocess,sys,pathlib\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(40)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\npathlib.Path(__file__).with_name('child.pid').write_text(str(p.pid))\n"
            (root / 'launcher.py').write_text(launcher, encoding='utf-8')
            started = time.monotonic()
            try:
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(script), '-ProjectRoot', str(root), '-PythonExecutable', sys.executable,
                    '-SkipCodexInstall', '-NoBrowser', '-NoIntegration'], capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertLess(time.monotonic() - started, 15)
                self.assertTrue((root / 'child.pid').exists(), result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
            finally:
                if (root / 'child.pid').exists():
                    os.kill(int((root / 'child.pid').read_text()), 15)


if __name__ == '__main__':
    unittest.main()
