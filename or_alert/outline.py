"""Click-through, non-activating EMR outline owned by the Tk UI thread."""
import ctypes as C
from ctypes import wintypes as W
import tkinter as tk
from .windows import u, client_box

u.GetWindowLongW.argtypes=[W.HWND,C.c_int]
u.SetWindowLongW.argtypes=[W.HWND,C.c_int,W.LONG]
u.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
u.SetWindowDisplayAffinity.argtypes=[W.HWND,W.DWORD]


def edges(box, thickness=3):
    x1,y1,x2,y2=box
    return [(x1,y1,x2-x1,thickness),(x1,y2-thickness,x2-x1,thickness),
            (x1,y1,thickness,y2-y1),(x2-thickness,y1,thickness,y2-y1)]


class Outline:
    def __init__(self, parent, window):
        self.parent,self.window=parent,window
        self.parts=[]
        self.timer=None
        for _ in range(4):
            part=tk.Toplevel(parent)
            part.withdraw()
            part.overrideredirect(True)
            part.configure(background='#00c878')
            part.update_idletasks()
            hwnd=u.GetAncestor(part.winfo_id(),2)
            # TOOLWINDOW | TRANSPARENT | NOACTIVATE; cannot take focus or clicks.
            style=u.GetWindowLongW(hwnd,-20)
            u.SetWindowLongW(hwnd,-20,style|0x80|0x20|0x08000000|0x80000)
            u.SetLayeredWindowAttributes.argtypes=[W.HWND,W.DWORD,W.BYTE,W.DWORD]
            u.SetLayeredWindowAttributes(hwnd,0,255,2)
            if not u.SetWindowDisplayAffinity(hwnd,0x11):
                # Never draw an outline that could contaminate captured pixels.
                part.destroy()
                self.close()
                raise RuntimeError('이 Windows 환경에서는 캡처 제외 테두리를 표시할 수 없습니다.')
            self.parts.append((part,hwnd))
        self.refresh()

    def refresh(self):
        if not self.parts: return
        try:
            if not u.IsWindow(self.window.handle) or u.IsIconic(self.window.handle):
                self.close(); return
            for (_,hwnd),(x,y,w,h) in zip(self.parts,edges(client_box(self.window.handle))):
                u.SetWindowPos(hwnd,W.HWND(-1),x,y,w,h,0x10|0x40)
            self.timer=self.parent.after(250,self.refresh)
        except Exception:
            self.close()

    def close(self):
        if self.timer:
            self.parent.after_cancel(self.timer)
            self.timer=None
        for part,_ in self.parts: part.destroy()
        self.parts=[]
