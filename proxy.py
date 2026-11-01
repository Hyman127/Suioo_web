import http.server
import select
import socket
import socketserver
import time
import urllib.parse
from engine import socks_connect
from storage import config, event


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    rbufsize = 0
    manager = None
    policy = None

    def log_message(self, *args):
        pass

    def relay(self, remote):
        while True:
            ready, _, _ = select.select([self.connection, remote], [], [], 30)
            if not ready:
                continue
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (remote if source is self.connection else self.connection).sendall(data)

    def forward_request(self, connect):
        remote = None
        instance = None
        host = ''
        try:
            cfg = config()
            if not cfg['proxy_enabled']:
                raise RuntimeError('本地代理入口已暂停')
            uri = urllib.parse.urlsplit('//' + self.path if connect else self.path)
            host = uri.hostname
            port = uri.port or (443 if connect else 80)
            if not host or uri.username or uri.password or (not connect and uri.scheme != 'http'):
                raise ValueError('代理请求地址无效')
            if host in ('localhost','127.0.0.1') and port in (cfg['web_port'],cfg['proxy_port']):
                raise ValueError('拒绝连接回控制台自身')
            instance = self.manager.acquire()
            start = time.perf_counter()
            remote = socks_connect(instance.port, host, port)
            remote.settimeout(None)
            self.connection.settimeout(None)
            for stream in (remote,self.connection):
                stream.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
            decision = self.policy.match(host, instance.profile)
            event('proxy', host+' → '+decision['mode'], {'group':decision['group'],'port':port,
                  'session':instance.id,'connect_ms':round((time.perf_counter()-start)*1000)})
            if connect:
                self.send_response(200,'Connection Established')
                self.end_headers()
                self.wfile.flush()
            else:
                path = urllib.parse.urlunsplit(('', '', uri.path or '/', uri.query, ''))
                lines = [self.command+' '+path+' HTTP/1.1']
                for key,value in self.headers.items():
                    if key.lower() not in ('proxy-authorization','proxy-connection','connection'):
                        lines.append(key+': '+value)
                remote.sendall(('\r\n'.join(lines+['Connection: close','',''])).encode('latin-1'))
            self.relay(remote)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as error:
            if remote is None:
                self.send_error(502,'Suioo proxy is not ready')
            event('proxy-error',host+'：'+str(error)[:250])
        finally:
            if remote:
                remote.close()
            if instance:
                self.manager.release(instance)
            self.close_connection = True

    def do_CONNECT(self):self.forward_request(True)
    def do_GET(self):self.forward_request(False)
    do_HEAD=do_GET
    do_POST=do_GET
    do_PUT=do_GET
    do_PATCH=do_GET
    do_DELETE=do_GET
    do_OPTIONS=do_GET


class Server(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name='127.0.0.1'
        self.server_port=self.server_address[1]


def start_proxy(port,policy,manager):
    Handler.manager=manager
    Handler.policy=policy
    return Server(('127.0.0.1',port),Handler)
