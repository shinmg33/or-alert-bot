"""Packaged check with only synthetic pixels and a hidden Tk window."""
import json
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont
from .ocr import Reader
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
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        report['winrt_imports'] = True
        if OcrEngine.try_create_from_language(Language('ko-KR')) is None:
            report['korean_ocr'] = 'language_pack_missing'
            Path(path).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            return
        image = Image.new('RGB', (500, 80), 'white')
        ImageDraw.Draw(image).text((5, 5), '환자상태 수술중 퇴실',
                                  font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 24), fill='black')
        report['korean_ocr'] = Reader().text(image) == '환자상태수술중퇴실'
    except Exception as error:
        report['error_type'] = type(error).__name__
    Path(path).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
