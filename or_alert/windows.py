"""Restricted Windows adapter: only department, doctor and query inputs.

No file patching, memory access, patient-row actions, filter/date writes or
background input. Every action validates the chosen foreground window.
"""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import time
from PIL import ImageGrab, ImageStat

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)
u.GetForegroundWindow.restype = W.HWND
u.GetAncestor.argtypes = [W.HWND, W.UINT]
u.GetAncestor.restype = W.HWND
u.IsWindow.argtypes = [W.HWND]
u.IsWindowVisible.argtypes = [W.HWND]
u.IsIconic.argtypes = [W.HWND]
u.GetWindowTextLengthW.argtypes = [W.HWND]
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
u.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u.SetForegroundWindow.argtypes = [W.HWND]
u.SetForegroundWindow.restype = W.BOOL
u.GetAsyncKeyState.argtypes = [C.c_int]
u.GetAsyncKeyState.restype = C.c_short
u.WindowFromPoint.argtypes = [W.POINT]
u.WindowFromPoint.restype = W.HWND
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
k.CloseHandle.argtypes = [W.HANDLE]
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
u.EnumWindows.argtypes = [CALLBACK, W.LPARAM]


class GuardError(Exception):
    def __init__(self, message, recoverable=True):
        super().__init__(message)
        self.recoverable = recoverable


# Exact handles of our own capture-excluded outline; never ignore other windows.
OUTLINE_HANDLES = set()


def belongs_to_target(hit, target):
    root = u.GetAncestor(hit, 2)
    return root == target or root in OUTLINE_HANDLES



@dataclass
class Window:
    handle: int
    title: str
    executable: str


def dpi_awareness():
    try:
        u.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
        u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:
        u.SetProcessDPIAware()


def title(hwnd):
    buffer = C.create_unicode_buffer(u.GetWindowTextLengthW(hwnd) + 1)
    u.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def executable(hwnd):
    pid = W.DWORD()
    u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    process = k.OpenProcess(0x1000, False, pid.value)
    if not process:
        return ''
    try:
        buffer, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        return buffer.value if not k.QueryFullProcessImageNameW(process, 0, buffer, C.byref(size)) else buffer.value
    finally:
        k.CloseHandle(process)


def list_windows():
    found = []
    @CALLBACK
    def visit(hwnd, _):
        if u.IsWindowVisible(hwnd) and '진료대상리스트' in title(hwnd):
            path = executable(hwnd)
            if path.lower().endswith('xplatform.exe'):
                found.append(Window(hwnd, title(hwnd), path))
        return True
    u.EnumWindows(visit, 0)
    return found


def client_box(hwnd):
    rect, point = W.RECT(), W.POINT(0, 0)
    if not u.GetClientRect(hwnd, C.byref(rect)) or not u.ClientToScreen(hwnd, C.byref(point)):
        raise GuardError('EMR 창 위치를 읽을 수 없습니다.')
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom


def input_tick():
    class Last(C.Structure):
        _fields_ = [('size', W.UINT), ('tick', W.DWORD)]
    last = Last(C.sizeof(Last), 0)
    if not u.GetLastInputInfo(C.byref(last)):
        raise GuardError('사용자 입력 상태를 확인할 수 없습니다.')
    return last.tick


def idle_seconds():
    return ((k.GetTickCount() - input_tick()) & 0xffffffff) / 1000


def stop_pressed():
    return bool(u.GetAsyncKeyState(0x77) & 0x8000)  # F8


class Desktop:
    def __init__(self, window, size=None, stopped=lambda: False):
        self.window, self.size, self.stopped = window, size, stopped
        self.expected_input = None
        self.critical_regions = None

    def arm_user_input(self):
        self.expected_input = input_tick()

    def activate(self):
        if not u.IsWindow(self.window.handle) or title(self.window.handle) != self.window.title:
            raise GuardError('EMR 목록 창이 바뀌었습니다. 다시 열어주세요.', False)
        if u.IsIconic(self.window.handle):
            u.ShowWindow.argtypes = [W.HWND, C.c_int]
            u.ShowWindow(self.window.handle, 9)
        u.SetForegroundWindow(self.window.handle)

    def guard(self):
        hwnd = self.window.handle
        if self.stopped() or stop_pressed():
            raise GuardError('사용자가 감시를 중지했습니다.')
        if self.expected_input is not None and self.expected_input != input_tick():
            raise GuardError('감시 동작 중 사용자 입력을 감지해 중단했습니다.')
        if any(u.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12)):
            raise GuardError('Shift·Ctrl·Alt가 눌려 있어 입력을 중단했습니다.')
        if not u.IsWindow(hwnd) or u.IsIconic(hwnd) or (self.critical_regions is None and u.GetForegroundWindow() != hwnd):
            raise GuardError('EMR 목록 창을 맨 앞으로 두세요. 입력과 감시를 중단했습니다.')
        if title(hwnd) != self.window.title or executable(hwnd) != self.window.executable:
            raise GuardError('대상 창이 변경되었습니다.', False)
        box = client_box(hwnd)
        if self.size and tuple(self.size) != (box[2] - box[0], box[3] - box[1]):
            raise GuardError('창 크기 또는 배율이 변경되었습니다. 화면 설정을 다시 하세요.', False)
        regions = self.critical_regions or [(0,0,box[2]-box[0],box[3]-box[1])]
        for left,top,right,bottom in regions:
            # Check the query and visible table, not empty workspace or unrelated controls.
            xs = list(range(left+2,max(left+3,right-2),60))+[(left+right)//2,right-3]
            ys = list(range(top+2,max(top+3,bottom-2),12))+[(top+bottom)//2,bottom-3]
            for x in xs:
                for y in ys:
                    hit = u.WindowFromPoint(W.POINT(box[0]+x,box[1]+y))
                    if not belongs_to_target(hit, hwnd):
                        raise GuardError('조회 버튼 또는 수술 목록이 가려져 잠시 대기합니다.')
        return box

    def capture_preview(self):
        """Local manual picker only: the user reviews the image before selecting.

        No occlusion gate: regions are precisely what the user is configuring.
        This method never sends an image or clicks an EMR control.
        """
        hwnd = self.window.handle
        if not u.IsWindow(hwnd) or u.IsIconic(hwnd) or title(hwnd) != self.window.title or executable(hwnd) != self.window.executable:
            raise GuardError('선택한 EMR 창을 확인할 수 없습니다. 창 찾기를 다시 눌러주세요.')
        box = client_box(hwnd)
        return ImageGrab.grab(bbox=box, all_screens=True).convert('RGB')

    def capture(self):
        box = self.guard()
        image = ImageGrab.grab(bbox=box, all_screens=True).convert('RGB')
        self.guard()
        if max(ImageStat.Stat(image).stddev) < 2:
            raise GuardError('캡처가 검거나 비어 있습니다. 보안 캡처 제한을 확인하세요.')
        return image

    def click(self, kind, rectangle):
        if kind not in ('department', 'doctor', 'query'):
            raise GuardError('허용되지 않은 입력 대상입니다.')
        box = self.guard()
        x = box[0] + (rectangle[0] + rectangle[2]) // 2
        y = box[1] + (rectangle[1] + rectangle[3]) // 2
        if not (box[0] <= x < box[2] and box[1] <= y < box[3]):
            raise GuardError('입력 위치가 EMR 창 밖입니다.')
        if not belongs_to_target(u.WindowFromPoint(W.POINT(x, y)), self.window.handle):
            raise GuardError('입력 위치가 가려져 있습니다.')
        u.SetCursorPos(x, y)
        self.expected_input = input_tick()
        self.guard()
        u.mouse_event(0x0002, 0, 0, 0, 0)
        u.mouse_event(0x0004, 0, 0, 0, 0)
        self.expected_input = input_tick()

    def select(self, kind, rectangle, index):
        if kind not in ('department', 'doctor') or not 0 <= index <= 200:
            raise GuardError('선택 항목 또는 순번이 잘못되었습니다.')
        self._select_keys(kind, rectangle, [0x24] + [0x28] * index + [0x0D])

    def select_next(self, kind, rectangle):
        if kind not in ('department', 'doctor'):
            raise GuardError('허용되지 않은 선택 대상입니다.')
        self._select_keys(kind, rectangle, [0x28, 0x0D])

    def _select_keys(self, kind, rectangle, keys):
        self.click(kind, rectangle)
        time.sleep(0.2)
        # Only navigation within the selected combo; never type arbitrary text.
        for vk in keys:
            if self.stopped() or stop_pressed() or u.GetForegroundWindow() != self.window.handle or self.expected_input != input_tick():
                raise GuardError('선택 중 창이 바뀌었거나 중지되었습니다.')
            u.keybd_event(vk, 0, 0, 0)
            u.keybd_event(vk, 0, 2, 0)
            self.expected_input = input_tick()
            time.sleep(0.025)
