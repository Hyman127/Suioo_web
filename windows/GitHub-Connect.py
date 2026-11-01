"""OpenSSH ProxyCommand: GitHub traffic through the stable local CONNECT proxy."""
import os
import socket
import sys
import threading

def main():
    host,port=sys.argv[1],int(sys.argv[2])
    if host.lower() not in ('github.com','ssh.github.com') or port not in (22,443):
        raise ValueError('This connector only accepts GitHub SSH endpoints')
    if os.name=='nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    with socket.create_connection(('127.0.0.1',18790),20) as peer:
        peer.sendall(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode('ascii'))
        headers=b''
        while not headers.endswith(b'\r\n\r\n'):
            part=peer.recv(1)
            if not part or len(headers)>32768:raise OSError('Invalid CONNECT response')
            headers+=part
        if headers.split(b' ',2)[1]!=b'200':raise OSError('GitHub proxy CONNECT failed')
        peer.settimeout(None)
        def upload():
            try:
                while data:=os.read(sys.stdin.fileno(),65536):peer.sendall(data)
                peer.shutdown(socket.SHUT_WR)
            except OSError:pass
        threading.Thread(target=upload,daemon=True).start()
        while data:=peer.recv(65536):
            view=memoryview(data)
            while view:view=view[os.write(sys.stdout.fileno(),view):]

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Suioo GitHub SSH proxy: '+str(error),file=sys.stderr)
        sys.exit(1)
