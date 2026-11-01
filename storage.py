import copy
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
RUNTIME.mkdir(exist_ok=True)
LOCK = threading.RLock()
DEFAULTS = {
    'version': 2, 'web_port': 18789, 'proxy_port': 18790, 'proxy_enabled': True, 'auto_start': True,
    'vpn_alias': 'Suioo', 'profile': 'Suioo', 'default_mode': 'vpn',
    'groups': {'tencent': 'direct', 'oray': 'direct', 'bytedance': 'direct',
               'alibaba': 'direct', 'baidu': 'direct', 'other': 'vpn'},
    'custom_rules': [], 'guard_enabled': True, 'guard_pause_until': 0,
    'guard_interval': 15, 'guard_failures': 2, 'keep_awake': True,
    'sites': [
        {'id': 'wechat', 'name': '微信公众平台', 'url': 'https://mp.weixin.qq.com/', 'group': 'tencent'},
        {'id': 'tencent', 'name': '腾讯云', 'url': 'https://cloud.tencent.com/', 'group': 'tencent'},
        {'id': 'sunlogin', 'name': '向日葵', 'url': 'https://sunlogin.oray.com/', 'group': 'oray'},
        {'id': 'douyin', 'name': '抖音', 'url': 'https://www.douyin.com/', 'group': 'bytedance'},
        {'id': 'feishu', 'name': '飞书', 'url': 'https://www.feishu.cn/', 'group': 'bytedance'},
        {'id': 'doubao', 'name': '豆包', 'url': 'https://www.doubao.com/', 'group': 'bytedance'},
        {'id': 'aliyun', 'name': '阿里云', 'url': 'https://www.aliyun.com/', 'group': 'alibaba'},
        {'id': 'taobao', 'name': '淘宝', 'url': 'https://www.taobao.com/', 'group': 'alibaba'},
        {'id': 'quark', 'name': '夸克', 'url': 'https://www.quark.cn/', 'group': 'alibaba'},
        {'id': 'baidu', 'name': '百度', 'url': 'https://www.baidu.com/', 'group': 'baidu'},
        {'id': 'netdisk', 'name': '百度网盘', 'url': 'https://pan.baidu.com/', 'group': 'baidu'},
        {'id': 'google', 'name': 'Google', 'url': 'https://www.google.com/generate_204', 'group': 'other'},
        {'id': 'chatgpt', 'name': 'ChatGPT', 'url': 'https://chatgpt.com/', 'group': 'other'},
        {'id': 'ip', 'name': '出口 IP 查询', 'url': 'https://myip.ipip.net/', 'group': 'other'},
    ],
}


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.' + str(threading.get_ident()) + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def config():
    with LOCK:
        path = ROOT / 'config.json'
        if not path.exists():
            atomic_json(path, DEFAULTS)
        saved = json.loads(path.read_text(encoding='utf-8-sig'))
        result = copy.deepcopy(DEFAULTS)
        result.update(saved)
        return result


def save_config(data):
    with LOCK:
        atomic_json(ROOT / 'config.json', data)


def db():
    connection = sqlite3.connect(RUNTIME / 'history.sqlite3', timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, time REAL, kind TEXT, message TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS probes(id INTEGER PRIMARY KEY, time REAL, site_id TEXT, mode TEXT, payload TEXT);
    ''')
    return connection


def event(kind, message, detail=None):
    with db() as connection:
        connection.execute('INSERT INTO events(time,kind,message,detail) VALUES(?,?,?,?)',
                           (time.time(), kind, message, json.dumps(detail or {}, ensure_ascii=False)))
        connection.execute('DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-10000 FROM events)')


def events(limit=80):
    with db() as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))]


def add_probe(row):
    with db() as connection:
        connection.execute('INSERT INTO probes(time,site_id,mode,payload) VALUES(?,?,?,?)',
                           (row['time'], row['site_id'], row['mode'], json.dumps(row, ensure_ascii=False)))
        connection.execute('DELETE FROM probes WHERE id < (SELECT COALESCE(MAX(id),0)-20000 FROM probes)')


def probes(limit=500):
    with db() as connection:
        return [json.loads(row[0]) for row in connection.execute('SELECT payload FROM probes ORDER BY id DESC LIMIT ?', (limit,))]
