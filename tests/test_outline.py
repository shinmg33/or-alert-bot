import subprocess
import sys
import unittest


class OutlineIntegrationTest(unittest.TestCase):
    def test_nonactivating_visible_capture_excluded_border(self):
        code=r'''
import tkinter as tk
import ctypes as C
from ctypes import wintypes as W
from or_alert.windows import u,Window,dpi_awareness
from or_alert.outline import Outline
dpi_awareness()
root=tk.Tk()
root.geometry('400x250+100+100')
root.update()
handle=u.GetAncestor(root.winfo_id(),2)
before=u.GetForegroundWindow()
outline=Outline(root,Window(handle,'test','test'))
root.update_idletasks()
assert len(outline.parts)==4
assert before==u.GetForegroundWindow()
u.GetWindowDisplayAffinity.argtypes=[W.HWND,C.POINTER(W.DWORD)]
for part,hwnd in outline.parts:
    assert u.IsWindowVisible(hwnd)
    affinity=W.DWORD()
    assert u.GetWindowDisplayAffinity(hwnd,C.byref(affinity)) and affinity.value==0x11
    style=u.GetWindowLongW(hwnd,-20)
    assert style & 0x08000000 and style & 0x20
outline.close()
root.destroy()
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
