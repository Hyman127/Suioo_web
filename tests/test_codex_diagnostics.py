import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostics as d


class CodexDiagnosticsTests(unittest.TestCase):
    def report(self, auth=200, chatgpt=200, api=401):
        return {'codex_requested': True, 'codex_runtime': {'found': True, 'login': 'logged_in'},
                'checks': [{'name': name, 'exit': 0, 'connect_status': 200, 'status': status}
                           for (name, _), status in zip(d.CODEX_ENDPOINTS, (auth, chatgpt, api))]}

    def test_google_success_does_not_hide_openai_connect_failure(self):
        report = self.report()
        report['checks'][0].update(exit=56, status=0, connect_status=502)
        report['checks'].append({'name': 'google_204_proxy_v4', 'ok': True})
        self.assertIn('CODEX_TRANSPORT_FAILED', {x['code'] for x in d.codex_findings(report)})

    def test_api_401_is_auth_requirement_not_model_success(self):
        self.assertEqual([x['code'] for x in d.codex_findings(self.report())], ['CODEX_API_AUTH_REQUIRED'])

    def test_web_challenge_and_login_are_separate(self):
        report = self.report(auth=403)
        report['codex_runtime']['login'] = 'not_logged_in'
        codes = {x['code'] for x in d.codex_findings(report)}
        self.assertIn('CODEX_LOGIN_PAGE_RESTRICTED', codes)
        self.assertIn('CODEX_LOGIN_REQUIRED', codes)

    def test_default_diagnostics_does_not_opt_in_to_openai(self):
        self.assertEqual(d.codex_findings({'checks': []}), [])

    def test_suioo_install_is_found_without_refreshed_path_and_output_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / 'Suioo/Codex/0.166.0/codex.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'fixture')
            version = Mock(stdout=b'codex-cli 0.166.0', stderr=b'', returncode=0)
            login = Mock(stdout=b'', stderr=b'Not logged in PRIVATE_ACCOUNT_FIXTURE', returncode=1)
            with patch('diagnostics.shutil.which', return_value=None), patch('diagnostics.subprocess.run', side_effect=[version, login]) as run:
                result = d.codex_runtime({'LOCALAPPDATA': directory, 'PATH': ''})
            self.assertEqual(result['source'], 'suioo_user_install')
            self.assertEqual(result['version'], '0.166.0')
            self.assertEqual(result['login'], 'not_logged_in')
            self.assertNotIn(directory, json.dumps(result))
            self.assertNotIn('PRIVATE_ACCOUNT_FIXTURE', json.dumps(result))
            self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
