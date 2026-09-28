"""Packaged check with only synthetic pixels and a hidden Tk window."""
import json
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont
from . import __version__
from .app import App
from .windows import Input
import ctypes
from .storage import crypt


def run(path):
    report = {}
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        report['tk'] = True
        plain = b'synthetic-self-check'
        report['dpapi'] = crypt(crypt(plain), decrypt=True) == plain
        report['version'] = __version__
        report['input_structure'] = ctypes.sizeof(Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        report['app_import'] = App is not None
    except Exception as error:
        report['error_type'] = type(error).__name__
    Path(path).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')

