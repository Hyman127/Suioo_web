import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bootstrap
import launcher

class FirstRunTests(unittest.TestCase):
    def test_occupied_proxy_port_never_starts_another_vpn_login(self):
        import app
        from storage import DEFAULTS
        server=Mock();server.serve_forever.side_effect=RuntimeError('end isolated server test')
        manager=Mock()
        with patch('app.config',return_value=dict(DEFAULTS)),patch('app.Server',return_value=server),patch('app.start_proxy',side_effect=OSError('occupied')),patch('app.PROXY_STATUS',{'running':False}),patch('app.MANAGER',manager),patch('app.atomic_json'),patch('app.event'),patch('app.threading.Thread') as thread:
            with self.assertRaisesRegex(RuntimeError,'end isolated'):app.run()
        self.assertFalse(manager.desired)
        self.assertNotIn(manager.supervise,[call.kwargs.get('target') for call in thread.call_args_list])
    def test_first_launch_requests_account_and_saved_launch_does_not(self):
        url='http://127.0.0.1:18789'
        self.assertEqual(launcher.browser_url(url,{'connection':{'username_saved':False,'password_saved':False}}),url+'/#connection')
        self.assertEqual(launcher.browser_url(url,{'connection':{'username_saved':True,'password_saved':True}}),url)
        self.assertEqual(launcher.browser_url(url,{'connection':{'username_saved':True,'password_saved':False}}),url+'/#connection')
    def test_engine_install_is_verified_and_never_overwrites_existing_files(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);vendor=root/'vendor';vendor.mkdir();archive=vendor/bootstrap.ENGINE_ARCHIVE
            with zipfile.ZipFile(archive,'w') as z:
                for name in bootstrap.ENGINE_FILES:z.writestr('sing-box-1.14.4-windows-amd64/'+name,b'fixture '+name.encode())
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch('bootstrap.ENGINE_SHA256',digest):self.assertTrue(bootstrap.ensure_engine(root))
            exe=root/'runtime/engine/sing-box.exe';exe.write_bytes(b'already running installation')
            with patch('bootstrap.download_engine') as download:
                self.assertFalse(bootstrap.ensure_engine(root));download.assert_not_called()
            self.assertEqual(exe.read_bytes(),b'already running installation')
    def test_corrupt_archive_never_extracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'vendor').mkdir();(root/'vendor'/bootstrap.ENGINE_ARCHIVE).write_bytes(b'tampered')
            with self.assertRaises(RuntimeError):bootstrap.ensure_engine(root)
            self.assertFalse((root/'runtime/engine/sing-box.exe').exists())
    def test_failed_download_does_not_leave_installable_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/bootstrap.ENGINE_ARCHIVE
            with patch('bootstrap.urllib.request.urlopen',return_value=io.BytesIO(b'not the official release')):
                with self.assertRaises(RuntimeError):bootstrap.download_engine(target)
            self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.download').exists())
    @unittest.skipUnless(sys.platform=='win32','Windows DPAPI integration')
    def test_windows_encrypted_credentials_survive_reload_without_a_second_prompt(self):
        import vault
        with tempfile.TemporaryDirectory() as directory,patch('vault.ROOT',Path(directory)):
            value={'username':'example-local-account-only','password':'example-local-test-password','server':'https://example.invalid'}
            vault.save(value);raw=(Path(directory)/'data/connection.dpapi').read_bytes()
            self.assertNotIn(value['password'].encode(),raw);self.assertNotIn(value['username'].encode(),raw)
            self.assertEqual(vault.load(),value);self.assertEqual(vault.load(),value)
            self.assertEqual(launcher.browser_url('http://127.0.0.1:18789',{'connection':vault.public()}),'http://127.0.0.1:18789')
    def test_task_for_another_checkout_is_not_reused(self):
        task=b'<Task><Actions><Exec><Arguments>-B &quot;C:\\another-copy\\service.py&quot;</Arguments></Exec></Actions></Task>'
        with patch('launcher.os',types.SimpleNamespace(name='nt')),patch('launcher.subprocess.CREATE_NO_WINDOW',0,create=True),patch('launcher.subprocess.run',return_value=Mock(returncode=0,stdout=task)):
            self.assertFalse(launcher.task_matches_project('Suioo-Web-Service','service.py'))

    def test_publish_guard_rejects_forced_private_file_and_saved_secret(self):
        spec=importlib.util.spec_from_file_location('publish_check',Path(__file__).resolve().parents[1]/'windows/Check-Publish.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);subprocess.run(['git','init','-q',directory],check=True)
            (root/'publish-files.json').write_text(json.dumps({'files':['public.py']}))
            (root/'public.py').write_text('message="public text"')
            subprocess.run(['git','-C',directory,'add','public.py'],check=True)
            self.assertTrue(module.inspect_index(root)['passed'])
            (root/'public.py').write_text('value="fixture-sensitive-publish-test"')
            subprocess.run(['git','-C',directory,'add','public.py'],check=True)
            self.assertFalse(module.inspect_index(root,['fixture-sensitive-publish-test'])['passed'])
            (root/'data').mkdir();(root/'data/connection.dpapi').write_bytes(b'fixture encrypted data')
            subprocess.run(['git','-C',directory,'add','data/connection.dpapi'],check=True)
            self.assertTrue(any(e['reason']=='private or unapproved path' for e in module.inspect_index(root)['errors']))

if __name__=='__main__':unittest.main()
