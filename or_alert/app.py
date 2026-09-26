import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk
from . import __version__
from .core import validate_interval
from .storage import load_settings, save_settings
from .telegram import Telegram, DeliveryError
from .windows import list_windows, Desktop, dpi_awareness, stop_pressed, GuardError
from .monitor import Monitor
from .layout import auto_layout
from .ocr import Reader


class Picker(tk.Toplevel):
    def __init__(self, parent, image, prompt, callback=None):
        super().__init__(parent)
        self.title(prompt)
        self.callback, self.original = callback, image
        self.scale = min(1, (self.winfo_screenwidth()-100)/image.width,
                         (self.winfo_screenheight()-180)/image.height)
        self.photo = ImageTk.PhotoImage(image.resize((int(image.width*self.scale), int(image.height*self.scale))))
        hint = ' — 해당 상자만 드래그하세요. Esc: 취소' if callback else ' — Esc: 닫기'
        ttk.Label(self, text=prompt+hint, padding=10).pack()
        self.canvas = tk.Canvas(self, width=self.photo.width(), height=self.photo.height(), highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.start = None
        self.box = None
        if callback:
            self.canvas.bind('<ButtonPress-1>', self.begin)
            self.canvas.bind('<B1-Motion>', self.drag)
            self.canvas.bind('<ButtonRelease-1>', self.finish)
        self.bind('<Escape>', lambda _: self.destroy())
        self.grab_set()

    def begin(self, event):
        self.start = (event.x, event.y)
        if self.box:
            self.canvas.delete(self.box)
        self.box = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#ef4444', width=2)

    def drag(self, event):
        if self.start:
            self.canvas.coords(self.box, *self.start, event.x, event.y)

    def finish(self, event):
        if not self.start:
            return
        x1, x2 = sorted((self.start[0], event.x))
        y1, y2 = sorted((self.start[1], event.y))
        box = [max(0, int(x1/self.scale)), max(0, int(y1/self.scale)),
               min(self.original.width, int(x2/self.scale)), min(self.original.height, int(y2/self.scale))]
        if box[2]-box[0] < 5 or box[3]-box[1] < 5:
            return
        self.callback(box)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'수술방 알림봇 {__version__}')
        self.geometry('860x740')
        self.minsize(800, 700)
        self.option_add('*Font', ('맑은 고딕', 10))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', padding=(10, 7))
        style.configure('TNotebook.Tab', padding=(20, 9))
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.sample = None
        self.latest = None
        self.windows = []
        self.network_busy = False
        self.capture_busy = False
        self.config = {}
        load_error = None
        try:
            self.config = load_settings()
        except Exception:
            load_error = '저장 설정을 읽지 못했습니다. 같은 Windows 계정인지 확인하세요.'
        # Old manual table geometry is no longer used or required.
        for key in ('rects', 'columns', 'header_height', 'size', 'auto_layout', 'layout_version'):
            self.config.pop(key, None)
        self.token = tk.StringVar(value=self.config.get('token', ''))
        self.chat = tk.StringVar(value=self.config.get('chat_id', ''))
        self.interval = tk.StringVar(value=str(self.config.get('interval', 60)))
        self.preview = tk.BooleanVar(value=True)
        self.silent = tk.BooleanVar(value=self.config.get('silent_details', False))
        self.status = tk.StringVar(value='중지됨 · 진료과 이름을 입력하고 감시 시작을 누르세요.')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.build()
        self.refresh_windows()
        self.after(150, self.poll)
        if load_error:
            self.after(200, lambda: messagebox.showwarning('설정 읽기', load_error))

    def build(self):
        title = ttk.Frame(self, padding=18)
        title.pack(fill='x')
        ttk.Label(title, text='수술방 알림봇', font=('맑은 고딕', 22, 'bold')).pack(anchor='w')
        ttk.Label(title, text='수술 목록을 열어두면 화면을 자동으로 찾아 감시합니다.').pack(anchor='w', pady=(4, 0))
        book = ttk.Notebook(self)
        book.pack(fill='both', expand=True, padx=18)
        settings = ttk.Frame(book, padding=18)
        connection = ttk.Frame(book, padding=18)
        book.add(settings, text='감시')
        book.add(connection, text='텔레그램 연결')

        row = ttk.Frame(settings)
        row.pack(fill='x')
        self.window_choice = ttk.Combobox(row, state='readonly', width=55)
        self.window_choice.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='창 찾기', command=self.refresh_windows).pack(side='left', padx=5)
        ttk.Label(settings, text='감시할 진료과 이름 (한 줄에 하나)').pack(anchor='w', pady=(16, 5))
        self.depts = tk.Text(settings, height=3, width=55)
        self.depts.pack(fill='x')
        self.depts.insert('1.0', '\n'.join(d['name'] for d in self.config.get('departments', [])))
        ttk.Label(settings, text='예: 산부인과 / 외과를 각각 한 줄에 입력하세요. 목록 순번은 필요 없습니다.').pack(anchor='w', pady=4)
        timing = ttk.Frame(settings)
        timing.pack(fill='x', pady=8)
        ttk.Label(timing, text='조회 간격 (최소 30초)').pack(side='left')
        ttk.Spinbox(timing, from_=30, to=3600, increment=30, textvariable=self.interval, width=10).pack(side='left', padx=12)
        ttk.Checkbutton(settings, text='로컬 시험 모드: 화면 확인만 하고 텔레그램에 보내지 않음', variable=self.preview).pack(anchor='w', pady=4)
        ttk.Checkbutton(settings, text='세부 변경은 무음 알림', variable=self.silent).pack(anchor='w', pady=4)
        ttk.Label(settings, text='진료의는 전체로 맞춥니다. 수술일과 다른 버튼은 변경하지 않습니다.\n환자상태·행 변경은 주요 알림, 다른 내용 수정은 세부 알림으로 보냅니다.', justify='left').pack(anchor='w', pady=8)
        optional = ttk.Frame(settings)
        optional.pack(fill='x')
        ttk.Button(optional, text='화면 자동 확인', command=self.capture_setup).pack(side='left')
        ttk.Button(optional, text='위치 보정 ▾', command=self.toggle_corrections).pack(side='left', padx=6)
        self.corrections = ttk.Frame(settings)
        for key, label in [('department', '진료과'), ('doctor', '진료의'), ('query', '조회')]:
            ttk.Button(self.corrections, text=label, command=lambda k=key: self.pick_control(k)).pack(side='left', padx=3)
        ttk.Button(self.corrections, text='자동 위치로 복원', command=self.reset_overrides).pack(side='left', padx=3)

        ttk.Label(connection, text='BotFather에서 받은 API 토큰').pack(anchor='w')
        ttk.Entry(connection, textvariable=self.token, show='•', width=75).pack(fill='x', pady=6)
        ttk.Label(connection, text='비공개 그룹 Chat ID (그룹 선택 시 자동 입력)').pack(anchor='w', pady=(12, 3))
        ttk.Entry(connection, textvariable=self.chat).pack(fill='x')
        buttons = ttk.Frame(connection)
        buttons.pack(fill='x', pady=12)
        self.network_buttons = []
        for text, command in [('연결 진단', self.diagnose), ('그룹 찾기', self.find_groups), ('테스트 메시지 보내기', self.test_connection)]:
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side='left', padx=(0, 6))
            self.network_buttons.append(button)
        ttk.Label(connection, text='① 토큰 입력 → 연결 진단\n② 비공개 그룹에 봇 추가\n③ 그룹에서 /start@봇사용자이름 전송 → 그룹 찾기\n④ 그룹 선택 → 테스트 메시지 보내기', justify='left').pack(anchor='w', pady=8)
        ttk.Label(connection, text='연결 진단은 메시지를 보내지 않습니다. 오류 원인과 해결 방법을 표시합니다.\n토큰은 이 Windows 계정으로 암호화 저장하며 GitHub에는 올리지 않습니다.', justify='left', wraplength=750).pack(anchor='w', pady=12)

        bottom = ttk.Frame(self, padding=18)
        bottom.pack(fill='x')
        self.save_button = ttk.Button(bottom, text='설정 저장', command=self.save)
        self.save_button.pack(side='left')
        self.start_button = ttk.Button(bottom, text='감시 시작', command=self.start)
        self.start_button.pack(side='left', padx=8)
        ttk.Button(bottom, text='중지 (F8)', command=self.stop).pack(side='left')
        ttk.Button(bottom, text='최근 캡처', command=self.show_latest).pack(side='right')
        ttk.Label(self, textvariable=self.status, padding=(18, 4), wraplength=790).pack(fill='x')
        self.log = tk.Text(self, height=5, state='disabled', font=('맑은 고딕', 9))
        self.log.pack(fill='x', padx=18, pady=(0, 12))

    def active(self):
        return self.worker is not None and self.worker.is_alive()

    def refresh_windows(self):
        if self.active():
            return
        self.windows = list_windows()
        self.window_choice['values'] = [w.title for w in self.windows]
        if len(self.windows) == 1:
            self.window_choice.current(0)

    def chosen_window(self):
        idx = self.window_choice.current()
        if idx < 0 or idx >= len(self.windows):
            raise ValueError('EMR 수술 목록을 열고 창 찾기를 누르세요.')
        return self.windows[idx]

    def capture_setup(self):
        if self.active() or self.capture_busy:
            return
        try:
            window = self.chosen_window()
        except ValueError as error:
            messagebox.showerror('화면 확인', str(error))
            return
        self.capture_busy = True
        self.status.set('EMR 화면을 자동 확인합니다.')
        self.withdraw()
        def take():
            try:
                desktop = Desktop(window)
                desktop.activate()
                self.sample = desktop.capture()
                image = self.sample
                overrides = dict(self.config.get('control_overrides', {}))
                def check():
                    try:
                        auto_layout(image, Reader(clean=True), overrides)
                        self.events.put(('status', '화면 자동 확인 완료. 표·열 지정 없이 감시 시작을 누르면 됩니다.'))
                    except ValueError as error:
                        self.events.put(('error', str(error)))
                    except Exception:
                        self.events.put(('error', '화면 인식에 실패했습니다. 한국어 OCR와 EMR 화면을 확인하세요.'))
                    finally:
                        self.events.put(('capture_done', None))
                threading.Thread(target=check, daemon=True).start()
            except Exception as error:
                self.capture_busy = False
                self.deiconify()
                self.status.set(str(error) if isinstance(error, GuardError) else '화면 캡처 실패. EMR이 가려지거나 잠겨 있는지 확인하세요.')
        self.after(1500, take)

    def toggle_corrections(self):
        if self.corrections.winfo_manager():
            self.corrections.pack_forget()
        else:
            self.corrections.pack(fill='x', pady=5)

    def pick_control(self, key):
        if self.active() or self.sample is None:
            messagebox.showinfo('위치 보정', '먼저 화면 자동 확인을 누르세요. 보정은 선택 사항입니다.')
            return
        def selected(box):
            self.config.setdefault('control_overrides', {})[key] = box
            self.status.set('입력 위치를 보정했습니다. 표와 열은 자동으로 인식합니다.')
        Picker(self, self.sample, {'department':'진료과', 'doctor':'진료의', 'query':'조회'}[key], selected)

    def reset_overrides(self):
        self.config.pop('control_overrides', None)
        self.status.set('자동 위치 인식으로 복원했습니다.')

    def collect(self):
        config = dict(self.config)
        config.update(token=self.token.get().strip(), chat_id=self.chat.get().strip(),
                      interval=validate_interval(self.interval.get()), silent_details=self.silent.get())
        departments = []
        for line in self.depts.get('1.0', 'end').splitlines():
            name = line.strip()
            if name:
                departments.append({'name': name})
        if len({d['name'] for d in departments}) != len(departments):
            raise ValueError('진료과 이름이 중복됩니다.')
        config['departments'] = departments
        return config

    def save(self):
        if self.active():
            return
        try:
            self.config = self.collect()
            save_settings(self.config)
            self.status.set('설정을 암호화 저장했습니다.')
        except Exception as error:
            messagebox.showerror('설정 저장', str(error) if isinstance(error, ValueError) else '설정을 저장할 수 없습니다.')

    def diagnose(self):
        try:
            self.background(Telegram(self.token.get()).diagnose)
        except ValueError as error:
            messagebox.showerror('연결 진단', str(error))

    def test_connection(self):
        try:
            client = Telegram(self.token.get(), self.chat.get())
            self.background(lambda: (client.test(), '테스트 메시지를 보냈습니다. 그룹에서 확인하세요.')[1])
        except ValueError as error:
            messagebox.showerror('텔레그램 연결', str(error))

    def find_groups(self):
        try:
            self.background(Telegram(self.token.get()).groups, 'groups')
        except ValueError as error:
            messagebox.showerror('그룹 찾기', str(error))

    def background(self, function, kind='status'):
        if self.network_busy:
            return
        self.network_busy = True
        for button in self.network_buttons:
            button.configure(state='disabled')
        self.status.set('Telegram에 확인 중입니다…')
        def work():
            try:
                self.events.put((kind, function()))
            except DeliveryError as error:
                self.events.put(('error', f'[{error.code}] {error}'))
            except ValueError as error:
                self.events.put(('error', str(error)))
            except Exception as error:
                self.events.put(('error', f'프로그램 내부 오류 ({type(error).__name__}). 토큰을 제외하고 이 오류 이름을 알려주세요.'))
            finally:
                self.events.put(('network_done', None))
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.active() or self.capture_busy:
            return
        try:
            config = self.collect()
            window = self.chosen_window()
            client = None if self.preview.get() else Telegram(config['token'], config['chat_id'])
            self.stop_event.clear()
            monitor = Monitor(window, config, self.stop_event, lambda kind, data: self.events.put((kind, data)), client)
            self.worker = threading.Thread(target=monitor.run, daemon=True)
            self.worker.start()
            self.start_button.configure(state='disabled')
            self.save_button.configure(state='disabled')
            self.withdraw()
        except ValueError as error:
            messagebox.showerror('감시 시작', str(error))

    def stop(self):
        self.stop_event.set()
        self.status.set('중지 요청됨 · 진행 중인 전송은 완료까지 최대 20초 걸릴 수 있습니다.')
        self.deiconify()

    def show_latest(self):
        if self.latest is None:
            messagebox.showinfo('최근 변경', '이번 실행에서 감지된 변경 캡처가 없습니다.')
            return
        Picker(self, self.latest, '최근 변경 캡처')

    def poll(self):
        if self.active() and stop_pressed():
            self.stop()
        while not self.events.empty():
            kind, data = self.events.get_nowait()
            if kind in ('status', 'error'):
                self.status.set(data)
                self.log.configure(state='normal')
                self.log.insert('end', data+'\n')
                self.log.see('end')
                self.log.configure(state='disabled')
                if kind == 'error':
                    self.deiconify()
            elif kind == 'change':
                caption, self.latest = data
                self.status.set(caption.replace('\n', ' | '))
            elif kind == 'stopped':
                self.start_button.configure(state='normal')
                self.save_button.configure(state='normal')
                self.deiconify()
            elif kind == 'capture_done':
                self.capture_busy = False
                self.deiconify()
            elif kind == 'network_done':
                self.network_busy = False
                for button in self.network_buttons:
                    button.configure(state='normal')
            elif kind == 'groups':
                if not data:
                    messagebox.showinfo('그룹 찾기', '서버 연결은 정상이지만 최근 그룹 메시지가 없습니다. 그룹에서 /start@실제봇이름 을 보내고 다시 눌러주세요.')
                else:
                    dialog = tk.Toplevel(self)
                    dialog.title('수신 그룹 선택')
                    ttk.Label(dialog, text='알림을 받을 비공개 그룹을 선택하세요.', padding=12).pack()
                    for chat_id, name in data.items():
                        ttk.Button(dialog, text=f'{name} ({chat_id})', command=lambda c=chat_id: (self.chat.set(c), dialog.destroy())).pack(fill='x', padx=12, pady=4)
        self.after(150, self.poll)

    def close(self):
        self.stop_event.set()
        self.destroy()


def main():
    dpi_awareness()
    App().mainloop()
