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
    @unittest.skipUnless(sys.platform=='win32','Windows PATH handling')
    def test_codex_path_preserves_existing_environment_without_registry_writes(self):
        script=Path(__file__).with_name('Test-CodexInstall.ps1')
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))

    def test_codex_package_rejects_corrupt_offline_archive(self):
        import hashlib
        spec=importlib.util.spec_from_file_location('package_build_codex',Path(__file__).resolve().parents[1]/'windows/Build-Package.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'windows').mkdir();(root/'vendor').mkdir()
            (root/'publish-files.json').write_text(json.dumps({'files':['public.py']}))
            (root/'public.py').write_text('print("public")')
            body=b'public archive fixture'
            (root/'windows/codex-release.json').write_text(json.dumps({'archive':'codex.tar.gz','sha256':hashlib.sha256(body).hexdigest()}))
            archive=root/'vendor/codex.tar.gz';archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'Codex archive checksum mismatch'):module.build(root,root/'out',include_codex=True)
            self.assertFalse((root/'out').exists())
            archive.write_bytes(body)
            result=module.build(root,root/'out',include_codex=True)
            with zipfile.ZipFile(result['file']) as package:
                self.assertEqual(package.read('Suioo_web/vendor/codex.tar.gz'),body)
                self.assertTrue(json.loads(package.read('Suioo_web/MANIFEST.json'))['codex_bundled'])

    def test_codex_package_requires_verified_companion_components(self):
        import hashlib
        spec=importlib.util.spec_from_file_location('package_build_components',Path(__file__).resolve().parents[1]/'windows/Build-Package.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'windows').mkdir();(root/'vendor').mkdir()
            (root/'publish-files.json').write_text(json.dumps({'files':['public.py']}))
            (root/'public.py').write_text('print("public")')
            components=[]
            for name,body in [('codex.tar.gz',b'primary fixture'),('host.tar.gz',b'companion fixture')]:
                (root/'vendor'/name).write_bytes(body)
                components.append({'archive':name,'sha256':hashlib.sha256(body).hexdigest()})
            release=dict(components[0],components=components[1:])
            (root/'windows/codex-release.json').write_text(json.dumps(release))
            host=root/'vendor/host.tar.gz';original=host.read_bytes();host.write_bytes(b'corrupt companion')
            with self.assertRaisesRegex(ValueError,'checksum mismatch: host'):module.build(root,root/'out',include_codex=True)
            self.assertFalse((root/'out').exists())
            host.unlink()
            with self.assertRaises(FileNotFoundError):module.build(root,root/'out',include_codex=True)
            host.write_bytes(original)
            result=module.build(root,root/'out',include_codex=True)
            with zipfile.ZipFile(result['file']) as package:
                self.assertEqual(package.read('Suioo_web/vendor/host.tar.gz'),original)
                self.assertEqual(package.read('Suioo_web/vendor/codex.tar.gz'),b'primary fixture')

    def test_package_verifier_checks_all_codex_components(self):
        import hashlib
        project=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('package_build_verify',project/'windows/Build-Package.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'windows').mkdir();(root/'vendor').mkdir()
            for name in ['bootstrap.py','windows/Verify-Package.py']:
                (root/name).write_bytes((project/name).read_bytes())
            files=['publish-files.json','windows/codex-release.json','bootstrap.py','windows/Verify-Package.py']
            (root/'publish-files.json').write_text(json.dumps({'files':files}))
            components=[]
            for name,body in [('codex.tar.gz',b'primary fixture'),('host.tar.gz',b'companion fixture')]:
                (root/'vendor'/name).write_bytes(body)
                components.append({'archive':name,'sha256':hashlib.sha256(body).hexdigest()})
            (root/'windows/codex-release.json').write_text(json.dumps(dict(components[0],components=components[1:])))

            def verify(path):
                result=subprocess.run([sys.executable,str(root/'windows/Verify-Package.py'),str(path)],capture_output=True)
                self.assertIn(result.returncode,(0,1),result.stderr.decode(errors='replace'))
                return json.loads(result.stdout)

            source=module.build(root,root/'source')
            self.assertTrue(verify(source['file'])['passed'])
            bundled=module.build(root,root/'bundled',include_codex=True)
            self.assertTrue(verify(bundled['file'])['passed'])
            with zipfile.ZipFile(bundled['file']) as archive:
                original={name:archive.read(name) for name in archive.namelist()}
            prefix='Suioo_web/'
            for scenario in ['missing','corrupt','false_flag']:
                with self.subTest(scenario=scenario):
                    payload=dict(original);manifest=json.loads(payload[prefix+'MANIFEST.json'])
                    if scenario=='missing':
                        del payload[prefix+'vendor/host.tar.gz']
                        manifest['files']=[row for row in manifest['files'] if row['path']!='vendor/host.tar.gz']
                    elif scenario=='corrupt':
                        body=b'tampered companion';payload[prefix+'vendor/host.tar.gz']=body
                        for row in manifest['files']:
                            if row['path']=='vendor/host.tar.gz':
                                row.update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
                    else:
                        manifest['codex_bundled']=False
                    payload[prefix+'MANIFEST.json']=json.dumps(manifest).encode()
                    payload[prefix+'SHA256SUMS']=''.join(row['sha256']+'  '+row['path']+'\n' for row in manifest['files']).encode()
                    path=root/(scenario+'.zip')
                    with zipfile.ZipFile(path,'w') as archive:
                        for name,body in payload.items():archive.writestr(name,body)
                    report=verify(path)
                    self.assertFalse(report['passed'])
                    self.assertTrue(any('Codex' in error for error in report['errors']),report)

    def test_migration_package_only_contains_public_allowlist(self):
        spec=importlib.util.spec_from_file_location('package_build',Path(__file__).resolve().parents[1]/'windows/Build-Package.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'publish-files.json').write_text(json.dumps({'files':['public.py']}))
            (root/'public.py').write_text('print("public")')
            for name in ('.git/config','data/connection.dpapi','runtime/uat/private.txt','干净迁移包/old.txt'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('private-fixture')
            result=module.build(root,root/'干净迁移包')
            with zipfile.ZipFile(result['file']) as archive:
                self.assertEqual(set(archive.namelist()),{'Suioo_web/public.py','Suioo_web/MANIFEST.json','Suioo_web/SHA256SUMS'})
                self.assertNotIn(b'private-fixture',b''.join(archive.read(n) for n in archive.namelist()))
            (root/'publish-files.json').write_text(json.dumps({'files':['../outside.py']}))
            with self.assertRaises(ValueError):module.build(root,root/'output')

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
