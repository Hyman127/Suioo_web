"""Local-machine DPAPI storage. The surrounding project ACL restricts file access."""
import ctypes
import json
import os
import re
import subprocess
from ctypes import wintypes
from storage import ROOT


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(raw):
    buffer = ctypes.create_string_buffer(raw)
    return Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def transform(raw, encrypt):
    if os.name != 'nt':
        raise RuntimeError('凭据保护需要 Windows DPAPI')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    pointer = ctypes.POINTER(Blob)
    crypt.CryptProtectData.argtypes = [pointer, wintypes.LPCWSTR, pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pointer]
    crypt.CryptUnprotectData.argtypes = [pointer, ctypes.c_void_p, pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pointer]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source, source_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(b'SuiooWebV1')
    target = Blob()
    if encrypt:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'SuiooWeb', ctypes.byref(entropy), None, None, 4, ctypes.byref(target))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def load():
    path = ROOT / 'data' / 'connection.dpapi'
    if not path.exists():
        return {}
    return json.loads(transform(path.read_bytes(), False).decode('utf-8'))


def save(data):
    directory = ROOT / 'data'
    directory.mkdir(exist_ok=True)
    if os.name=='nt':
        flags=subprocess.CREATE_NO_WINDOW
        identity=subprocess.run(['whoami.exe','/user','/fo','csv','/nh'],capture_output=True,timeout=8,creationflags=flags)
        sid=re.search(rb'S-1-5-[0-9-]+',identity.stdout)
        if identity.returncode or not sid:raise RuntimeError('Cannot determine the local credential owner')
        restricted=subprocess.run(['icacls.exe',str(directory),'/inheritance:r','/grant:r',
                                   '*'+sid.group().decode('ascii')+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F',
                                   '*S-1-5-32-544:(OI)(CI)F','/Q'],capture_output=True,timeout=10,creationflags=flags)
        if restricted.returncode:raise RuntimeError('Cannot restrict local credential directory access')
    temporary = directory / 'connection.next'
    temporary.write_bytes(transform(json.dumps(data, ensure_ascii=False).encode('utf-8'), True))
    os.replace(temporary, directory / 'connection.dpapi')


def public(data=None):
    data = load() if data is None else data
    user = data.get('username', '')
    return {'server': data.get('server', 'https://node.anyconnect.cloud'), 'protocol': data.get('protocol', 'anyconnect'),
            'username_masked': user[:2] + '***' + user[-2:] if user else '',
            'username_saved': bool(user), 'password_saved': bool(data.get('password')),
            'no_udp': data.get('no_udp', False), 'reconnect_timeout': data.get('reconnect_timeout', '24h'),
            'dpd_interval': data.get('dpd_interval', '5s'), 'tls_verify': True,
            'system_interface': False, 'backend': 'sing-box 1.14.4 / AnyConnect 用户态协议栈'}
