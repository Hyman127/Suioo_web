import copy,json,sys,unittest
import socket,threading,time
import io
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import DEFAULTS
from engine import compile_config,Manager,Instance
from policy import Policy
class Tests(unittest.TestCase):
 def test_offline_restore_preserves_manual_environment_changes(self):
  import integration,types,tempfile
  class Store:
   def __init__(self,values):self.values=dict(values)
   def read(self,keys):return {k:self.values.get(k) for k in keys}
   def write(self,values):self.values.update(values)
  internet=Store(integration.PROXY);environment=Store({'HTTP_PROXY':'manual','HTTPS_PROXY':integration.ENVIRONMENT['HTTPS_PROXY']})
  backup={'internet':{'ProxyEnable':0,'ProxyServer':'old'},'environment':{'HTTPS_PROXY':None},'vscode':{}}
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'Code/User/settings.json';path.parent.mkdir(parents=True);path.write_text('{"unrelated":true,"terminal.integrated.env.windows":{"HTTP_PROXY":"manual","HTTPS_PROXY":"http://127.0.0.1:18790"}}')
   with patch('integration.os',types.SimpleNamespace(environ={'APPDATA':directory})),patch('integration.Registry',side_effect=[internet,environment]),patch('integration.read_json',return_value=backup),patch('integration.configure') as configure,patch('integration.notify'):
    integration.restore_now();configure.assert_called_once_with(False)
   value=json.loads(path.read_text());self.assertTrue(value['unrelated']);self.assertEqual(value['terminal.integrated.env.windows'],{'HTTP_PROXY':'manual'})
  self.assertEqual(internet.values['ProxyEnable'],0);self.assertEqual(environment.values['HTTP_PROXY'],'manual');self.assertIsNone(environment.values['HTTPS_PROXY'])
 def test_browser_proxy_restores_after_three_health_failures(self):
  import integration,types
  class Store:
   def __init__(self,values):self.values=dict(values);self.writes=[]
   def read(self,keys):return {k:self.values.get(k) for k in keys}
   def write(self,values):self.values.update(values);self.writes.append(dict(values))
  internet=Store(integration.PROXY);environment=Store({});original={'ProxyEnable':0,'ProxyServer':'previous','ProxyOverride':None,'AutoConfigURL':None}
  backup={'internet':original,'environment':{},'vscode':{}};opener=Mock();opener.open.side_effect=OSError('service down')
  with patch('integration.os',types.SimpleNamespace(name='nt',environ={'APPDATA':'/tmp'})),patch('integration.Registry',side_effect=[internet,environment]),patch('integration.read_json',return_value=backup),patch('integration.preferences',return_value={'enabled':True}),patch('integration.urllib.request.build_opener',return_value=opener),patch('integration.atomic_json') as status,patch('integration.notify'),patch('integration.keep_control_tunnel'),patch('integration.acquire_user_mutex'),patch('integration.time.sleep',side_effect=[None,None,KeyboardInterrupt]):
   with self.assertRaises(KeyboardInterrupt):integration.run()
  self.assertEqual(internet.writes,[original]);self.assertEqual([x.args[1]['consecutive_failures'] for x in status.call_args_list],[1,2,3])
 def test_jsonc_preserves_comments_and_other_settings(self):
  from integration import edit_setting,clean_jsonc
  source='{\n // keep this comment\n "unrelated": "https://example.com/x,}",\n}'
  updated=edit_setting(source,'terminal.integrated.env.windows',{'HTTPS_PROXY':'http://127.0.0.1:18790'})
  self.assertIn('// keep this comment',updated);self.assertEqual(json.loads(clean_jsonc(updated))['unrelated'],'https://example.com/x,}')
  again=edit_setting(updated,'terminal.integrated.env.windows',{'A':'B'});self.assertEqual(json.loads(clean_jsonc(again))['terminal.integrated.env.windows'],{'A':'B'})
 def test_integration_restore_keeps_user_changes(self):
  from integration import owned_restore
  restored=owned_restore({'HTTP_PROXY':'manual','HTTPS_PROXY':'ours','OTHER':'x'}, {'HTTP_PROXY':'old','HTTPS_PROXY':None},{'HTTP_PROXY':'ours','HTTPS_PROXY':'ours'})
  self.assertEqual(restored,{'HTTP_PROXY':'manual','OTHER':'x'})
 def test_bad_new_credentials_do_not_replace_saved_credentials(self):
  m=Manager();old=Mock();m.current=old
  with patch('engine.Instance.start',side_effect=ValueError('authentication failed')),patch('engine.vault.save') as save:
   with self.assertRaises(ValueError):m.apply({'username':'new-user','password':'wrong-password'},persist_credentials=True)
   save.assert_not_called()
  self.assertIs(m.current,old)
 def test_verified_credentials_are_saved_and_connected(self):
  m=Manager();candidate=Mock(running=True,transport_dead=False,transport_ready=True,port=19001,forced_port=19002)
  with patch('engine.Instance',return_value=candidate),patch('engine.socket.create_connection'),patch('engine.subprocess.run',return_value=Mock(returncode=0,stdout=b'204',stderr=b'')),patch('engine.vault.save') as save,patch('engine.event'):
   credentials={'username':'new-user','password':'new-password'};m.apply(credentials,persist_credentials=True);save.assert_called_once_with(credentials)
  self.assertIs(m.current,candidate)
 def test_launcher_waits_for_tunnel_not_only_web(self):
  from launcher import wait_ready
  first={'core':{'ready':True,'health':None,'applying':True},'proxy':{'running':True},'config':{'proxy_enabled':True,'auto_start':True},'connection':{'password_saved':True}}
  second=copy.deepcopy(first);second['core']['health']={'page_ok':True}
  opener=Mock();opener.open.side_effect=[io.StringIO(json.dumps(first)),io.StringIO(json.dumps(second))]
  with patch('launcher.urllib.request.build_opener',return_value=opener),patch('launcher.time.sleep'):
   wait_ready('http://127.0.0.1:18789')
  self.assertEqual(opener.open.call_count,2)
 def test_connect_facade_relays_bytes(self):
  import proxy
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
  def echo():
   peer,_=listener.accept()
   with peer:peer.sendall(peer.recv(64))
  threading.Thread(target=echo,daemon=True).start()
  manager=Mock();manager.acquire.return_value=Mock(port=9999,profile=DEFAULTS,id='test')
  policy=Mock();policy.match.return_value={'mode':'direct','group':'other'}
  with patch('proxy.socks_connect',side_effect=lambda *args:socket.create_connection(listener.getsockname())),patch('proxy.event'):
   server=proxy.start_proxy(0,policy,manager);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with socket.create_connection(server.server_address,timeout=2) as client:
     client.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
     headers=b''
     while b'\r\n\r\n' not in headers:headers+=client.recv(1)
     self.assertIn(b'200 Connection Established',headers);client.sendall(b'ping');self.assertEqual(client.recv(4),b'ping')
    time.sleep(.02);manager.release.assert_called_once()
   finally:server.shutdown();server.server_close();listener.close()
 def test_isolation_and_redaction(self):
  c=compile_config(DEFAULTS,{'username':'private-user','password':'secret-value'},11000,11001,True)
  self.assertFalse(c['endpoints'][0]['system']);self.assertNotIn('secret-value',json.dumps(c));self.assertNotIn('private-user',json.dumps(c));self.assertEqual([i['type'] for i in c['inbounds']],['mixed','socks']);self.assertFalse(c['endpoints'][0]['tls']['insecure'])
 def test_vendor_and_boundary(self):
  p=Policy()
  for host,family in [('mp.weixin.qq.com','tencent'),('sunlogin.oray.com','oray'),('www.douyin.com','bytedance'),('www.taobao.com','alibaba'),('pan.baidu.com','baidu')]:self.assertEqual(p.match(host,DEFAULTS)['group'],family);self.assertEqual(p.match(host,DEFAULTS)['mode'],'direct')
  self.assertEqual(p.match('notqq.com',DEFAULTS)['group'],'other')
 def test_custom_precedence(self):
  c=copy.deepcopy(DEFAULTS);c['custom_rules']=[{'domain':'qq.com','mode':'vpn'}];self.assertEqual(Policy().match('mp.qq.com',c)['mode'],'vpn')
 def test_validation_failure_preserves_old_session(self):
  m=Manager();old=Mock();m.current=old
  with patch('engine.vault.load',return_value={'username':'u','password':'p'}),patch('engine.Instance.start',side_effect=ValueError('invalid')):
   with self.assertRaises(ValueError):m.apply()
  self.assertIs(m.current,old);self.assertFalse(m.applying)
 def test_active_lease_survives_release(self):
  m=Manager();old=Mock(running=True,clients=0);m.current=old;x=m.acquire();self.assertEqual(old.clients,1);m.current=Mock(running=True,clients=0);m.retired.append(old);m.release(x);self.assertEqual(old.clients,0);old.stop.assert_not_called()
 def test_logs_hide_credentials(self):
  i=Instance(DEFAULTS,{'username':'private-user','password':'secret-value'});r=i.redact('private-user secret-value Cookie: abc123');self.assertNotIn('private-user',r);self.assertNotIn('secret-value',r);self.assertNotIn('abc123',r)
if __name__=='__main__':unittest.main()
