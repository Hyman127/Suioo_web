import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostics as d


def baseline():
    return {'time': 'test', 'checks': [
        {'name': 'baidu_direct', 'ok': True},
        {'name': 'google_204_proxy_v4', 'ok': True},
        {'name': 'google_page_proxy_v4', 'ok': True},
        {'name': 'google_logo_proxy_v4', 'ok': True}],
        'windows': {'browser_uses_suioo': True},
        'samples': [{'available': True, 'credentials_saved': True, 'ready': True, 'pid': 42}] * 7}


class DiagnosticTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows interpreter discovery')
    def test_interpreter_of_running_checkout_is_found_without_path(self):
        with tempfile.TemporaryDirectory(prefix='suioo diagnostics ') as directory:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', str(Path(__file__).with_name('Test-DiagnosticRunner.ps1')),
                '-PythonExecutable', sys.executable, '-TestRoot', directory], capture_output=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))

    def test_raw_credentials_errors_and_paths_never_enter_public_state(self):
        secret = 'private-diagnostic-fixture-abc123'
        state = {'core': {'error': secret, 'logs': [secret + ' server disconnected CSTP session: code 0xb0 Internal Error'],
            'pid': 42}, 'connection': {'username': secret, 'server': secret}, 'events': [secret], 'project': secret}
        result = d.public_state(state)
        self.assertNotIn(secret, json.dumps(result))
        self.assertTrue(result['signals']['server_disconnected'])
        self.assertTrue(result['signals']['server_internal_error'])

    def test_curl_stderr_is_not_exported_and_proxy_is_explicit(self):
        output = b'502|0|0.001|0|0|0.004|0|0|502'
        process = Mock(returncode=56, stdout=output, stderr=b'private proxy password fixture')
        with patch('diagnostics.subprocess.run', return_value=process) as run:
            row = d.probe('curl', {}, 18790, 'google', 'https://www.google.com/')
        self.assertFalse(row['ok'])
        self.assertEqual(row['connect_status'], 502)
        self.assertNotIn('private proxy password fixture', json.dumps(row))
        args = run.call_args.args[0]
        self.assertEqual(args[1], '--disable')
        self.assertIn('http://127.0.0.1:18790', args)
        self.assertNotIn('--insecure', args)
        self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_historical_disconnect_and_google_direct_failure_do_not_blame_current_session(self):
        report = baseline()
        report['historical_log_signals'] = {'server_disconnected': True}
        report['checks'].append({'name': 'google_204_direct_reference', 'ok': False})
        codes = {f['code'] for f in d.classify(report)}
        self.assertNotIn('SERVER_DISCONNECT', codes)
        self.assertNotIn('DIRECT_BASELINE_FAILED', codes)

    def test_small_request_success_does_not_mark_page_success(self):
        report = baseline()
        report['checks'][2]['ok'] = False
        self.assertIn('PAGE_FAILED', {f['code'] for f in d.classify(report)})
        report['samples'][-1] = {**report['samples'][-1], 'pid': 99}
        self.assertIn('TUNNEL_UNSTABLE', {f['code'] for f in d.classify(report)})

    def test_report_zip_does_not_collect_nearby_private_files(self):
        report = baseline();report['findings'] = d.classify(report)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir();(root / 'data/connection.dpapi').write_bytes(b'private-fixture')
            target = d.save_report(report, root)
            with zipfile.ZipFile(target / '诊断报告.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'report.json', '报告.txt'})
                self.assertNotIn(b'private-fixture', b''.join(archive.read(n) for n in archive.namelist()))

    def test_other_project_cannot_receive_mutations(self):
        app = d.LocalApp()
        with patch.object(app, 'get', return_value={'app': 'suioo-console-v1', 'project_id': 'other'}), patch.object(app.opener, 'open') as request:
            with self.assertRaisesRegex(ValueError, 'OTHER_PROJECT'):
                app.post('/api/integration', {'enabled': True})
            request.assert_not_called()
        report = baseline();report['samples'][0] = {'other_project': True}
        self.assertEqual(d.repair(app, report)[0]['code'], 'SKIPPED_OTHER_PROJECT')

    def test_other_proxy_is_never_overwritten(self):
        report = baseline();report['windows']['browser_other_proxy'] = True
        app = Mock()
        self.assertEqual(d.repair(app, report)[0]['code'], 'SKIPPED_OTHER_PROXY')
        app.post.assert_not_called()

    def test_failed_integration_attempt_rolls_back_and_keeps_error_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = {'preferences': {'enabled': False}, 'internet': {}, 'environment': {}, 'vscode_files': {}}
            (root / 'settings-before.json').write_text(json.dumps(snapshot))
            app = Mock(root=root, proxy_port=18790)
            fake = types.SimpleNamespace(ROOT=root)
            with (patch.dict(sys.modules, {'integration': fake}),
                  patch('launcher.ensure_user_integration', side_effect=RuntimeError('private-error-fixture')),
                  patch('diagnostics.backup_settings', return_value=root),
                  patch('diagnostics.restore_settings') as restore):
                result = d.repair(app, baseline())
            restore.assert_called_once_with(snapshot, fake)
            self.assertEqual(result[0]['code'], 'REPAIR_FAILED')
            self.assertNotIn('private-error-fixture', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
