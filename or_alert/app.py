import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk
from . import __version__
from .core import validate_interval
from .storage import load_settings, save_settings
from .telegram import Telegram
from .windows import list_windows, Desktop, dpi_awareness, stop_pressed
from .monitor import Monitor, validate_config

LABELS = {
    'department': '진료과 선택 상자', 'doctor': '진료의 선택 상자', 'query': '조회 버튼',
    'date': '수술일 글자만', 'total': '총 건수 숫자만', 'table': '표 전체 (머리글 포함)',
    'status_filter': '수술상태 라디오 버튼 전체', 'room_filter': '수술방 필터 상자',
}


class Picker(tk.Toplevel):
    def __init__(self, parent, image, prompt, callback):
        super().__init__(parent)
        self.title(prompt)
        self.callback, self.original = callback, image
        self.scale = min(1, (self.winfo_screenwidth() - 100) / image.width,
                         (self.winfo_screenheight() - 180) / image.height)
        self.photo = ImageTk.PhotoImage(image.resize((int(image.width*self.scale), int(image.height*self.scale))))
        ttk.Label(self, text=prompt + ' — 왼쪽 위에서 오른쪽 아래로 드래그. Esc: 취소', padding=10).pack()
        self.canvas = tk.Canvas(self, width=self.photo.width(), height=self.photo.height(), highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.start = None
        self.box = None
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
        self.title(f'수술방 알림봇 {__version__} · 비공개 시험 버전')
        self.geometry('960x790')
        self.minsize(840, 700)
        self.option_add('*Font', ('맑은 고딕', 10))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', padding=(10, 7))
        style.configure('TNotebook.Tab', padding=(20, 9))
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.sample = None
        self.windows = []
        self.config = {}
        load_error = None
        try:
            self.config = load_settings()
        except Exception:
            load_error = '저장 설정을 복호화하지 못했습니다. 같은 Windows 계정인지 확인하세요.'
        self.token = tk.StringVar(value=self.config.get('token', ''))
        self.chat = tk.StringVar(value=self.config.get('chat_id', ''))
        self.interval = tk.StringVar(value=str(self.config.get('interval', 60)))
        self.preview = tk.BooleanVar(value=True)
        self.silent = tk.BooleanVar(value=self.config.get('silent_details', False))
        self.checked = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='중지됨 · 실제 EMR 자동조작은 화면 설정 후 시작하세요.')
        self.rect_labels = {}
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
        ttk.Label(title, text='진료과 순환 조회 · 상태별 변경 알림 · 캡처 전송').pack(anchor='w', pady=(4, 0))
        book = ttk.Notebook(self)
        book.pack(fill='both', expand=True, padx=18)
        connection = ttk.Frame(book, padding=18)
        settings = ttk.Frame(book, padding=18)
        screen = ttk.Frame(book, padding=18)
        book.add(connection, text='1. 텔레그램 연결')
        book.add(settings, text='2. 감시 설정')
        book.add(screen, text='3. 화면 설정')
        ttk.Label(connection, text='봇 토큰은 이 PC의 Windows 계정으로 암호화 저장됩니다.').pack(anchor='w')
        ttk.Label(connection, text='BotFather에서 받은 API 토큰').pack(anchor='w', pady=(18, 4))
        ttk.Entry(connection, textvariable=self.token, show='•', width=75).pack(fill='x')
        ttk.Label(connection, text='비공개 그룹 Chat ID (음수 숫자)').pack(anchor='w', pady=(16, 4))
        ttk.Entry(connection, textvariable=self.chat, width=45).pack(fill='x')
        buttons = ttk.Frame(connection)
        buttons.pack(fill='x', pady=12)
        ttk.Button(buttons, text='그룹 찾기', command=self.find_groups).pack(side='left')
        ttk.Button(buttons, text='테스트 메시지 보내기', command=self.test_connection).pack(side='left', padx=8)
        ttk.Label(connection, text='① BotFather로 봇 만들기 → 토큰 입력\n② 동료들만 있는 비공개 그룹에 봇 추가\n③ 그룹에서 /start 명령 전송 → 그룹 찾기\n④ 대상 그룹을 확인하고 테스트 메시지 보내기', justify='left').pack(anchor='w', pady=12)
        ttk.Label(connection, text='변경 캡처는 작은 글자가 유지되도록 원본 PNG 파일로 보냅니다.\n프로그램은 캡처와 인식한 환자정보를 디스크에 저장하지 않습니다.', justify='left').pack(anchor='w', pady=12)

        ttk.Label(settings, text='조회 버튼을 누르는 간격 (초, 최소 30)').pack(anchor='w')
        ttk.Spinbox(settings, from_=30, to=3600, increment=30, textvariable=self.interval, width=12).pack(anchor='w', pady=6)
        ttk.Label(settings, text='감시할 진료과: 한 줄에 “진료과 이름=드롭다운 순번”\n순번은 맨 위가 0입니다. 실제 목록을 보고 입력하세요. 임의 예시를 넣지 않았습니다.', justify='left').pack(anchor='w', pady=(12, 6))
        self.depts = tk.Text(settings, height=5, width=55)
        self.depts.pack(fill='x')
        self.depts.insert('1.0', '\n'.join(f'{d["name"]}={d["index"]}' for d in self.config.get('departments', [])))
        ttk.Checkbutton(settings, text='세부 변경은 텔레그램 무음 알림', variable=self.silent).pack(anchor='w', pady=12)
        ttk.Checkbutton(settings, text='로컬 시험 모드: EMR 조회와 변경 확인만 하고 텔레그램으로 보내지 않음', variable=self.preview).pack(anchor='w')
        ttk.Label(settings, text='예: 2개 과 · 60초 설정 → 각 과는 약 120초마다 확인합니다.\n수술일은 사람이 선택한 날짜를 유지합니다. F8은 긴급 중지입니다.\n첫 정상 조회는 기준만 만듭니다. 시작시간은 예정 시각으로 취급합니다.\n스크롤로 숨겨진 행이 있으면 총 건수 검증에서 중단됩니다.', justify='left').pack(anchor='w', pady=16)

        row = ttk.Frame(screen)
        row.pack(fill='x')
        self.window_choice = ttk.Combobox(row, state='readonly', width=56)
        self.window_choice.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='창 목록 갱신', command=self.refresh_windows).pack(side='left', padx=5)
        ttk.Button(screen, text='현재 화면 가져오기 (4초 뒤 캡처)', command=self.capture_setup).pack(anchor='w', pady=8)
        ttk.Label(screen, text='버튼을 누른 후 EMR 목록을 맨 앞으로 두세요. 캡처 위에서 영역을 지정합니다.\n이 설정 과정은 EMR의 버튼을 클릭하지 않습니다.', justify='left').pack(anchor='w')
        grid = ttk.Frame(screen)
        grid.pack(fill='x', pady=8)
        for i, (key, label) in enumerate(LABELS.items()):
            ttk.Button(grid, text=label, command=lambda k=key: self.pick(k)).grid(row=i//2, column=(i%2)*2, sticky='ew', pady=2)
            v = tk.StringVar(value='설정됨' if key in self.config.get('rects', {}) else '미설정')
            ttk.Label(grid, textvariable=v, width=9).grid(row=i//2, column=(i%2)*2+1)
            self.rect_labels[key] = v
        cols = ttk.Frame(screen)
        cols.pack(fill='x', pady=5)
        for key in ('등록번호', '수술명', '환자상태'):
            ttk.Button(cols, text=key+' 열 지정', command=lambda k=key: self.pick_column(k)).pack(side='left', padx=3)
        self.column_status = tk.StringVar(value='열 설정: ' + ', '.join(self.config.get('columns', {})))
        ttk.Label(screen, textvariable=self.column_status).pack(anchor='w')
        ttk.Label(screen, text='각 열은 표의 머리글 셀 전체를 드래그하세요. 환자 행을 선택하는 기능은 없습니다.').pack(anchor='w', pady=5)
        ttk.Checkbutton(screen, text='지정 영역과 진료과 순번을 확인했습니다. 다른 버튼은 자동 조작하지 않습니다.', variable=self.checked).pack(anchor='w', pady=6)

        bottom = ttk.Frame(self, padding=18)
        bottom.pack(fill='x')
        self.save_button = ttk.Button(bottom, text='설정 암호화 저장', command=self.save)
        self.save_button.pack(side='left')
        self.start_button = ttk.Button(bottom, text='감시 시작', command=self.start)
        self.start_button.pack(side='left', padx=8)
        ttk.Button(bottom, text='중지 (F8)', command=self.stop).pack(side='left')
        ttk.Button(bottom, text='최근 변경 캡처 보기', command=self.show_latest).pack(side='right')
        ttk.Label(self, textvariable=self.status, padding=(18, 4), wraplength=900).pack(fill='x')
        self.log = tk.Text(self, height=5, state='disabled', font=('맑은 고딕', 9))
        self.log.pack(fill='x', padx=18, pady=(0, 12))
        self.latest = None

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
            raise ValueError('EMR 수술 목록을 열고 창을 선택하세요.')
        return self.windows[idx]

    def capture_setup(self):
        if self.active():
            return
        try:
            window = self.chosen_window()
        except ValueError as error:
            messagebox.showerror('화면 설정', str(error))
            return
        self.status.set('4초 안에 EMR 목록을 맨 앞으로 두세요.')
        self.withdraw()
        def take():
            try:
                self.sample = Desktop(window).capture()
                self.config['size'] = list(self.sample.size)
                self.checked.set(False)
                self.status.set('캡처 완료. 화면 설정 탭에서 각 영역을 지정하세요.')
            except Exception:
                self.status.set('캡처 실패. EMR을 맨 앞으로 두고 가림·잠금·캡처 제한을 확인하세요.')
            finally:
                self.deiconify()
        self.after(4000, take)

    def pick(self, key):
        if self.active() or self.sample is None:
            messagebox.showinfo('화면 설정', '감시를 중지하고 먼저 현재 화면을 가져오세요.')
            return
        def selected(box):
            self.config.setdefault('rects', {})[key] = box
            self.rect_labels[key].set('설정됨')
            self.checked.set(False)
            if key == 'table':
                self.config['columns'] = {}
                self.column_status.set('표를 바꿨습니다. 세 열을 다시 지정하세요.')
        Picker(self, self.sample, LABELS[key], selected)

    def pick_column(self, key):
        if self.active() or self.sample is None or 'table' not in self.config.get('rects', {}):
            messagebox.showinfo('화면 설정', '먼저 캡처와 표 전체 영역을 지정하세요.')
            return
        image = self.sample.crop(self.config['rects']['table'])
        def selected(box):
            self.config.setdefault('columns', {})[key] = [box[0], box[2]]
            self.config['header_height'] = box[3]
            self.column_status.set('열 설정: ' + ', '.join(self.config['columns']))
            self.checked.set(False)
        Picker(self, image, key + ' 머리글 셀 전체', selected)

    def collect(self):
        config = dict(self.config)
        config.update(token=self.token.get().strip(), chat_id=self.chat.get().strip(),
                      interval=validate_interval(self.interval.get()), silent_details=self.silent.get())
        departments = []
        for line in self.depts.get('1.0', 'end').splitlines():
            if not line.strip():
                continue
            try:
                name, index = line.rsplit('=', 1)
                departments.append({'name': name.strip(), 'index': int(index.strip())})
            except ValueError:
                raise ValueError('진료과를 이름=순번 형식으로 입력하세요.') from None
        config['departments'] = departments
        return config

    def save(self):
        if self.active():
            return
        try:
            self.config = self.collect()
            save_settings(self.config)
            self.status.set('설정 저장 완료 · 이 Windows 계정에서만 복호화할 수 있습니다.')
        except Exception as error:
            messagebox.showerror('설정 저장', str(error) if isinstance(error, ValueError) else '설정을 저장할 수 없습니다.')

    def test_connection(self):
        try:
            client = Telegram(self.token.get(), self.chat.get())
            self.background(lambda: (client.test(), '환자정보 없는 테스트 메시지를 보냈습니다.')[1])
        except ValueError as error:
            messagebox.showerror('텔레그램 연결', str(error))

    def find_groups(self):
        try:
            client = Telegram(self.token.get(), '-1')
            self.background(client.groups, 'groups')
        except ValueError as error:
            messagebox.showerror('그룹 찾기', str(error))

    def background(self, function, kind='status'):
        def work():
            try:
                self.events.put((kind, function()))
            except Exception:
                self.events.put(('error', 'Telegram 연결 실패. 토큰·봇 권한·네트워크를 확인하세요.'))
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.active():
            return
        try:
            if not self.checked.get():
                raise ValueError('화면 설정 탭에서 영역과 순번을 확인하고 확인란을 선택하세요.')
            config = self.collect()
            validate_config(config)
            window = self.chosen_window()
            client = None if self.preview.get() else Telegram(config['token'], config['chat_id'])
            self.stop_event.clear()
            monitor = Monitor(window, config, self.stop_event, lambda kind, data: self.events.put((kind, data)), client)
            self.worker = threading.Thread(target=monitor.run, daemon=True)
            self.worker.start()
            self.start_button.configure(state='disabled')
            self.save_button.configure(state='disabled')
        except (ValueError, KeyError):
            messagebox.showerror('감시 시작', '입력값과 화면 영역을 모두 확인하세요. 진료과 순번, 30초 이상 간격, 세 열 설정과 확인란이 필요합니다.')

    def stop(self):
        self.stop_event.set()
        self.status.set('중지 요청됨 · 진행 중인 네트워크 요청은 완료까지 최대 20초 걸릴 수 있습니다.')

    def show_latest(self):
        if self.latest is None:
            messagebox.showinfo('최근 변경', '이번 실행에서 감지된 변경 캡처가 없습니다.')
            return
        Picker(self, self.latest, '최근 변경 캡처 (메모리에만 보관)', lambda _: None)

    def poll(self):
        if self.active() and stop_pressed():
            self.stop()
        while not self.events.empty():
            kind, data = self.events.get_nowait()
            if kind in ('status', 'error'):
                self.status.set(data)
                self.log.configure(state='normal')
                self.log.insert('end', data + '\n')
                self.log.see('end')
                self.log.configure(state='disabled')
            elif kind == 'change':
                caption, self.latest = data
                self.status.set(caption.replace('\n', ' | '))
            elif kind == 'stopped':
                self.start_button.configure(state='normal')
                self.save_button.configure(state='normal')
            elif kind == 'groups':
                if not data:
                    messagebox.showinfo('그룹 찾기', '그룹에 봇을 추가하고 /start를 보낸 뒤 다시 시도하세요. 웹훅을 쓰는 봇은 별도 Chat ID 입력이 필요합니다.')
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
