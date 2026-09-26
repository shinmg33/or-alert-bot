"""Query-only monitoring. No OCR and no department/doctor input."""
import time
import threading
import math
from datetime import datetime
from .core import compare, validate_interval
from .layout import detect_grid, LayoutError
from .visual import digest, row_boundaries, visual_snapshot
from .windows import Desktop, GuardError, idle_seconds
from .telegram import DeliveryError


def shutdown_hours(value):
    try:
        value = float(value or 0)
    except (ValueError, TypeError):
        raise ValueError('자동 종료 시간은 0~168시간으로 입력하세요. 0은 사용 안 함입니다.') from None
    if not math.isfinite(value) or not 0 <= value <= 168:
        raise ValueError('자동 종료 시간은 0~168시간으로 입력하세요. 0은 사용 안 함입니다.')
    return value


class Monitor:
    def __init__(self, window, config, stop, emit, telegram=None):
        validate_interval(config['interval'])
        if not config.get('query_rect') or not config.get('query_size'):
            raise ValueError('조회 버튼 위치를 한 번 지정해주세요.')
        self.config, self.stop, self.emit, self.telegram = config, stop, emit, telegram
        self.desktop = Desktop(window, size=config['query_size'], stopped=stop.is_set)
        self.region = None
        self.columns = None
        self.baseline = None
        self.baseline_rows = None
        self.command_offset = None
        self.command_since = int(time.time())
        self.bot_username = None
        self.commands_enabled = bool(telegram)
        self.next_poll = 0
        self.hours = shutdown_hours(config.get('shutdown_hours', 0))
        self.deadline = None
        self.timed_out = False
        self.stop_reason = None
        self.reason_lock = threading.Lock()
        self.desktop_lock = threading.RLock()
        self.watch_done = threading.Event()
        self.watch_thread = None

    def request_stop(self, reason):
        first = False
        with self.reason_lock:
            if self.stop_reason is None:
                self.stop_reason = reason
                first = True
        self.stop.set()
        if first:
            self.emit('stopping', self.stop_reason)

    def check_lifecycle(self):
        if self.stop.is_set(): return
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.timed_out = True
            self.request_stop(f'예약한 {self.hours:g}시간이 지나 자동 종료했습니다.')
            return
        with self.desktop_lock:
            if self.desktop.expected_input is not None:
                try:
                    self.desktop.guard()
                except GuardError as error:
                    self.request_stop(str(error))

    def watch(self):
        while not self.watch_done.wait(.25):
            self.check_lifecycle()
            if self.stop.is_set(): break

    def capture(self):
        with self.desktop_lock:
            return self.desktop.capture()

    def notify_stopped(self):
        reason = self.stop_reason or '사용자가 감시를 중지했습니다.'
        text = 'Alert Bot | 감시 중단\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n'+reason
        self.emit('status',text)
        if self.telegram:
            try:
                self.telegram.send_notice(text)
            except DeliveryError as error:
                self.emit('error',f'감시는 중단됐지만 중단 알림 전송 실패 [{error.code}]: {error}')
            except Exception:
                self.emit('error','감시는 중단됐지만 중단 알림 전송에 실패했습니다.')

    def setup(self, image):
        x1,y1,x2,y2 = self.config['query_rect']
        if tuple(image.size) != tuple(self.config['query_size']) or not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
            raise ValueError('창 크기가 바뀌었습니다. 조회 버튼 위치를 다시 지정해주세요.')
        try:
            lines,top,bottom = detect_grid(image)
        except LayoutError:
            # Still report changes when optional row classification is unavailable.
            self.region = (0,y2,image.width,image.height)
            self.emit('status','조회 버튼 아래 화면을 비교합니다. 변경 시 캡처를 전송합니다.')
        else:
            if y2 >= top:
                raise ValueError('조회 버튼 위치가 표와 겹칩니다. 조회 버튼만 지정해주세요.')
            self.region = (lines[0],top,lines[-1]+1,image.height)
            self.header_height = bottom-top+1
            self.columns = {name:[lines[i]-lines[0]+1,lines[i+1]-lines[0]]
                            for name,i in [('등록번호',9),('수술명',12),('환자상태',19)]}

    def sample(self, image):
        table = image.crop(self.region)
        rows = None
        if self.columns:
            try:
                count = len(row_boundaries(table,self.header_height))-1
                rows = visual_snapshot(table,self.columns,self.header_height,count,'선택한 날짜','현재 화면')
            except ValueError:
                pass
        return digest(table), rows

    def process(self, first, second):
        first_key,_ = self.sample(first)
        key,rows = self.sample(second)
        if first_key != key:
            self.emit('status','화면 갱신 중입니다. 다음 조회에서 다시 확인합니다.')
            return
        if self.baseline is None:
            self.baseline,self.baseline_rows = key,rows
            self.emit('status','기준 화면 저장 완료. 이후 변경부터 알림을 보냅니다.')
            return
        if key == self.baseline:
            self.emit('status','변경 없음 · '+datetime.now().strftime('%H:%M:%S'))
            return
        changes = compare(self.baseline_rows,rows) if self.baseline_rows is not None and rows is not None else []
        text = '\n'.join(f'[{c.level}] {c.message}' for c in changes) or '[변경] 화면 내용 변경 — 캡처 확인'
        caption = 'Alert Bot | 현재 선택한 목록\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n'+text
        if self.telegram:
            while not self.stop.is_set():
                try:
                    self.telegram.send_capture(second,caption,silent=bool(changes) and self.config.get('silent_details',False) and all(c.level=='세부' for c in changes))
                    break
                except DeliveryError as error:
                    if not error.retryable: raise
                    self.emit('status',f'[{error.code}] {error} 전송을 재시도합니다.')
                    self.stop.wait(max(30,error.retry_after))
            if self.stop.is_set(): return
        self.baseline,self.baseline_rows = key,rows
        self.emit('change',(caption,second))

    def send_current(self, image, reason):
        caption = 'Alert Bot | '+reason+'\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if self.telegram:
            while not self.stop.is_set():
                try:
                    self.telegram.send_capture(image,caption)
                    break
                except DeliveryError as error:
                    if not error.retryable: raise
                    self.emit('status',f'[{error.code}] {error} 캡처 전송 재시도 중')
                    self.stop.wait(max(30,error.retry_after))
            if self.stop.is_set(): return
        self.emit('change',(caption,image))

    def accepts_command(self, update):
        message = update.get('message',{})
        if str(message.get('chat',{}).get('id')) != self.telegram.chat_id:
            return False
        if message.get('date',0) < self.command_since or message.get('from',{}).get('is_bot'):
            return False
        text = message.get('text','').strip().split()
        if not text: return False
        command = text[0].lower()
        return command == '/capture' or command == '/capture@'+self.bot_username.lower()

    def poll_commands(self):
        if not self.commands_enabled or time.monotonic() < self.next_poll: return
        self.next_poll = time.monotonic()+2
        try:
            if self.bot_username is None:
                self.bot_username = self.telegram.identity()['username']
            updates = self.telegram.updates(self.command_offset)
            requested = False
            for update in updates:
                if self.command_offset is not None and update['update_id'] < self.command_offset: continue
                self.command_offset = update['update_id']+1
                requested = self.accepts_command(update) or requested
            if requested:
                # No refresh or baseline change: send the current EMR client only.
                self.send_current(self.capture(),'수동 캡처 /capture')
        except DeliveryError as error:
            if error.retryable:
                self.next_poll = time.monotonic()+max(30,error.retry_after)
            else:
                self.commands_enabled = False
            self.emit('status',f'명령 수신 오류 [{error.code}]: {error} 자동 감시는 계속됩니다.')

    def wait_interval(self, seconds):
        deadline = time.monotonic()+seconds
        while not self.stop.is_set():
            self.poll_commands()
            remaining = deadline-time.monotonic()
            if remaining <= 0: return False
            if self.stop.wait(min(2,remaining)): return True
        return True

    def run(self):
        try:
            if self.stop.wait(2): return
            self.desktop.activate()
            if self.stop.wait(.5): return
            initial = self.capture()
            self.deadline = time.monotonic()+self.hours*3600 if self.hours else None
            with self.desktop_lock:
                self.desktop.arm_user_input()
            self.watch_thread = threading.Thread(target=self.watch,daemon=True)
            self.watch_thread.start()
            self.emit('watching', self.desktop.window)
            self.setup(initial)
            self.send_current(initial,'감시 시작 · 현재 화면')
            if self.stop.is_set(): return
            self.emit('status','사용 중 · 자동 조회와 /capture 명령 대기')
            while not self.stop.is_set():
                if idle_seconds() < 3:
                    if self.stop.wait(1): break
                    continue
                with self.desktop_lock:
                    # Keep the original input tick: never erase intervening user input.
                    self.desktop.click('query',self.config['query_rect'])
                started = time.monotonic()
                if self.stop.wait(3): break
                first = self.capture()
                if self.stop.wait(2): break
                second = self.capture()
                self.process(first,second)
                if self.wait_interval(max(0,self.config['interval']-(time.monotonic()-started))): break
        except (ValueError,GuardError,DeliveryError) as error:
            self.request_stop(str(error))
            self.emit('error',str(error))
        except Exception as error:
            self.request_stop(f'감시 오류 ({type(error).__name__}).')
            self.emit('error',self.stop_reason)
        finally:
            self.watch_done.set()
            if self.watch_thread: self.watch_thread.join(timeout=1)
            self.emit('outline_hide',None)
            self.notify_stopped()
            self.emit('stopped',self.timed_out)
