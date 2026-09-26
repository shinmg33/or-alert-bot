"""Per-Windows-user encrypted settings. No screenshots are persisted."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows 사용자 암호화 저장소를 읽거나 쓸 수 없습니다.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def settings_path():
    return Path(os.environ['LOCALAPPDATA']) / 'ORAlertBot' / 'settings.bin'


def save_settings(settings, path=None):
    path = path or settings_path()
    payload = crypt(json.dumps(settings, ensure_ascii=False).encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.new')
    temporary.write_bytes(payload)
    temporary.replace(path)


def load_settings(path=None):
    path = path or settings_path()
    return json.loads(crypt(path.read_bytes(), decrypt=True)) if path.exists() else {}
