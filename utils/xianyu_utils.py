import json
import subprocess
from functools import partial
subprocess.Popen = partial(subprocess.Popen, encoding="utf-8")
import execjs

try:
    xianyu_js = execjs.compile(open(r'../static/xianyu_js_version_2.js', 'r', encoding='utf-8').read())
except:
    xianyu_js = execjs.compile(open(r'static/xianyu_js_version_2.js', 'r', encoding='utf-8').read())

def trans_cookies(cookies_str):
    cookies = dict()
    for i in cookies_str.split("; "):
        try:
            cookies[i.split('=')[0]] = '='.join(i.split('=')[1:])
        except:
            continue
    return cookies


def generate_mid():
    mid = xianyu_js.call('generate_mid')
    return mid

def generate_uuid():
    uuid = xianyu_js.call('generate_uuid')
    return uuid

def generate_device_id(user_id):
    device_id = xianyu_js.call('generate_device_id', user_id)
    return device_id

def generate_sign(t, token, data):
    sign = xianyu_js.call('generate_sign', t, token, data)
    return sign

def decrypt(data):
    res = xianyu_js.call('decrypt', data)
    return res
