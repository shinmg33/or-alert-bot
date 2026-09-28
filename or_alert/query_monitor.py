"""Query monitoring with explicitly calibrated optional condition inputs."""
import time
import threading
import math
import queue
from datetime import datetime
from .core import compare, validate_interval
from .layout import detect_grid, LayoutError
from .visual import digest, row_boundaries, visual_snapshot
from .windows import Desktop, GuardError, idle_seconds
from .telegram import DeliveryError
from .commands import FIELDS, HELP, validate_value


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
        self.pending_conditions = {}
        self.condition_capture = False
        self.replies = queue.Queue()
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
        self.calibrating = False
        self.state = 'recovering'
        self.notices = queue.Queue()
        self.capture_requested = False
        self.initial_sent = False
        self.next_query = 0
        self.next_recovery = 0
        self.automatic_pause_since = None
        self.pause_reported = False
        self.desktop.critical_regions = [config['query_rect']]

    def request_stop(self, reason):
        first = False
        with self.reason_lock:
            if self.stop_reason is None:
                self.stop_reason = reason
                first = True
        self.stop.set()
        if first:
            self.emit('stopping', self.stop_reason)

    def pause(self, reason, automatic=False):
        with self.desktop_lock:
            if self.stop.is_set(): return
            if not automatic:
                self.pending_conditions.clear()
            target = 'recovering' if automatic else 'paused'
            if self.state == 'paused' and automatic: return
            if self.state == target: return
            self.state = target
            self.emit('paused', reason)
            suffix = ' 입력이 5초 이상 없으면 자동 복구합니다.' if automatic else ' /restart로 재개할 수 있습니다.'
            if automatic:
                self.automatic_pause_since = time.monotonic()
                self.pause_reported = False
            else:
                self.automatic_pause_since = None
                self.notices.put('감시 대기: '+reason+suffix)

    def begin_calibration(self):
        with self.desktop_lock:
            self.calibrating = True
            self.pause('조회 버튼 위치 지정 중')

    def end_calibration(self, window=None, rectangle=None, size=None):
        with self.desktop_lock:
            if rectangle is not None:
                if tuple(size) != tuple(self.config['query_size']) or window != self.desktop.window:
                    self.config.pop('condition_fields', None)
                self.config['query_rect'] = list(rectangle)
                self.config['query_size'] = list(size)
                self.desktop.window = window
                self.desktop.size = list(size)
                self.desktop.critical_regions = [list(rectangle)]
                self.desktop.expected_input = None
                self.region = self.columns = None
                self.baseline = self.baseline_rows = None
                self.initial_sent = False
                self.capture_requested = False
            self.calibrating = False

    def restart(self):
        with self.desktop_lock:
            if self.calibrating:
                self.notices.put('조회 위치 지정 중입니다. 완료 후 /restart를 요청하세요.')
                return
            if self.stop.is_set(): return
            self.state = 'recovering'
            self.next_recovery = 0
            self.emit('resuming', None)
            self.notices.put('재시작 요청 접수. 사용자 입력이 5초 이상 없으면 EMR을 복구합니다.')

    def check_lifecycle(self):
        if self.stop.is_set(): return
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.timed_out = True
            self.request_stop(f'예약한 {self.hours:g}시간이 지나 자동 종료했습니다.')
            return
        with self.desktop_lock:
            if self.state == 'running' and self.desktop.expected_input is not None:
                try:
                    self.desktop.guard()
                except GuardError as error:
                    self.pause(str(error), automatic=error.recoverable)

    def flush_notices(self):
        while not self.replies.empty():
            text = self.replies.get()
            self.emit('status', text)
            if self.telegram:
                try: self.telegram.send_notice(text, silent=True)
                except DeliveryError as error: self.emit('status', f'명령 응답 실패 [{error.code}]: {error}')
        if self.state == 'recovering' and self.automatic_pause_since is not None and not self.pause_reported and time.monotonic()-self.automatic_pause_since >= 120:
            self.notices.put('핵심 영역 또는 사용자 입력 때문에 2분 이상 감시를 기다리고 있습니다.')
            self.pause_reported = True
        while not self.notices.empty():
            text = 'Alert Bot | [시스템] '+self.notices.get()
            self.emit('status',text)
            if self.telegram and self.config.get('system_notifications','silent') != 'off':
                try: self.telegram.send_notice(text, silent=self.config.get('system_notifications','silent') != 'sound')
                except DeliveryError as error:
                    self.emit('status',f'상태 알림 실패 [{error.code}]: {error}')

    def recover(self):
        if self.state != 'recovering' or idle_seconds() < 5 or time.monotonic() < self.next_recovery:
            return False
        self.next_recovery = time.monotonic()+5
        with self.desktop_lock:
            if self.state != 'recovering' or self.stop.is_set(): return False
            self.desktop.activate()
            self.desktop.arm_user_input()
        if self.stop.wait(.5): return False
        with self.desktop_lock:
            if self.state != 'recovering': return False
            image = self.desktop.capture()
            self.setup(image)
            self.update_regions(image)
            self.desktop.guard()
            self.state = 'running'
            self.next_query = 0
            self.emit('watching', self.desktop.window)
        if not self.initial_sent:
            self.send_current(image,'감시 시작 · 현재 화면')
            self.initial_sent = True
        elif self.pause_reported:
            self.notices.put('EMR 화면 확인 완료. 감시를 재개했습니다.')
        self.automatic_pause_since = None
        self.pause_reported = False
        return True

    def watch(self):
        while not self.watch_done.wait(.25):
            self.check_lifecycle()
            if self.stop.is_set(): break

    def capture(self):
        with self.desktop_lock:
            image = self.desktop.capture()
            self.update_regions(image)
            self.desktop.guard()
            return image

    def visible_region(self, image):
        if not self.columns: return self.region
        left,top,right,bottom = self.region
        boundaries = row_boundaries(image.crop(self.region),self.header_height)
        last = self.header_height-1
        for value in boundaries[1:]:
            if not 12 <= value-last <= 80: break
            last = value
        return (left,top,right,min(bottom,top+last+2))

    def update_regions(self, image):
        if self.region:
            self.desktop.critical_regions = [self.config['query_rect'],self.visible_region(image)]

    def notification_image(self, image):
        return image.crop(self.visible_region(image)) if self.region else image

    def notify_stopped(self):
        reason = self.stop_reason or '사용자가 감시를 중지했습니다.'
        text = 'Alert Bot | [시스템] 감시 중단\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n'+reason
        self.emit('status',text)
        if self.telegram and self.config.get('system_notifications','silent') != 'off':
            try:
                self.telegram.send_notice(text, silent=self.config.get('system_notifications','silent') != 'sound')
            except DeliveryError as error:
                self.emit('error',f'감시는 중단됐지만 중단 알림 전송 실패 [{error.code}]: {error}')
            except Exception:
                self.emit('error','감시는 중단됐지만 중단 알림 전송에 실패했습니다.')

    def setup(self, image):
        self.columns = None
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
        table = image.crop(self.visible_region(image))
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
        caption = 'Alert Bot | [목록 변경] 현재 선택한 목록\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n'+text
        if self.telegram:
            while not self.stop.is_set() and self.state == 'running':
                try:
                    self.telegram.send_capture(self.notification_image(second),caption,silent=self.config.get('change_notifications','sound') == 'silent')
                    break
                except DeliveryError as error:
                    if not error.retryable: raise
                    self.emit('status',f'[{error.code}] {error} 전송을 재시도합니다.')
                    if self.wait_interval(max(30,error.retry_after)): return
            if self.stop.is_set() or self.state != 'running': return
        self.baseline,self.baseline_rows = key,rows
        self.emit('change',(caption,second))

    def send_current(self, image, reason):
        caption = 'Alert Bot | '+reason+'\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if self.telegram:
            while not self.stop.is_set() and self.state == 'running':
                try:
                    self.telegram.send_capture(self.notification_image(image),caption,silent=self.config.get('system_notifications','silent') != 'sound')
                    break
                except DeliveryError as error:
                    if not error.retryable: raise
                    self.emit('status',f'[{error.code}] {error} 캡처 전송 재시도 중')
                    if self.wait_interval(max(30,error.retry_after)): return
            if self.stop.is_set() or self.state != 'running': return
        self.emit('change',(caption,image))

    def command(self, update):
        message = update.get('message',{})
        if str(message.get('chat',{}).get('id')) != self.telegram.chat_id:
            return None
        if message.get('date',0) < self.command_since or message.get('from',{}).get('is_bot'):
            return None
        text = message.get('text','').strip().split()
        if not text: return None
        pieces = text[0].lower().split('@')
        if len(pieces)>2 or (len(pieces)==2 and pieces[1] != self.bot_username.lower()): return None
        return pieces[0] if pieces[0] in ('/capture','/stop','/restart','/help','/date','/department','/doctor') else None

    def accepts_command(self, update):
        return self.command(update) is not None

    def poll_commands(self):
        if not self.commands_enabled or time.monotonic() < self.next_poll: return
        self.next_poll = time.monotonic()+2
        try:
            if self.bot_username is None:
                self.bot_username = self.telegram.identity()['username']
            for update in self.telegram.updates(self.command_offset):
                if self.command_offset is not None and update['update_id'] < self.command_offset: continue
                self.command_offset = update['update_id']+1
                command = self.command(update)
                if command == '/help': self.replies.put(HELP)
                elif command in ('/date','/department','/doctor'):
                    parts = update['message']['text'].strip().split(maxsplit=1)
                    self.request_condition(command[1:], parts[1] if len(parts) == 2 else '')
                elif command == '/stop':
                    self.capture_requested = False
                    self.pause('Telegram /stop 명령')
                elif command == '/restart': self.restart()
                elif command == '/capture':
                    if self.state == 'running': self.capture_requested = True
                    else: self.notices.put('현재 감시 대기 중입니다. /restart 후 /capture를 요청하세요.')
        except DeliveryError as error:
            self.next_poll = time.monotonic()+max(30,error.retry_after)
            self.emit('status',f'명령 수신 오류 [{error.code}]: {error} 30초 이후 다시 확인합니다.')

    def request_condition(self, field, value):
        try:
            value = validate_value(field, value)
            with self.desktop_lock:
                if self.calibrating:
                    raise ValueError('위치 지정 완료 후 다시 명령을 보내세요.')
                spec = self.config.get('condition_fields', {}).get(field)
                if not spec:
                    raise ValueError(f'PC에서 {FIELDS[field]} 입력칸 위치를 먼저 지정하세요.')
                if tuple(spec['size']) != tuple(self.config['query_size']):
                    raise ValueError('창 크기가 달라졌습니다. 입력칸 위치를 다시 지정하세요.')
                self.pending_conditions[field] = value
                self.capture_requested = False
                self.restart()
            self.replies.put(f'{FIELDS[field]} 변경 요청 접수: {value}. 입력 후 조회를 재개합니다.')
        except ValueError as error:
            self.replies.put(str(error))

    def apply_conditions(self):
        with self.desktop_lock:
            if self.state != 'running' or self.calibrating or self.stop.is_set(): return
            if not self.pending_conditions: return
            pending = self.pending_conditions.copy()
            self.pending_conditions.clear()
            original = self.desktop.critical_regions
            try:
                for field in FIELDS:
                    if field not in pending: continue
                    spec = self.config.get('condition_fields', {}).get(field)
                    if not spec or tuple(spec['size']) != tuple(self.config['query_size']):
                        raise ValueError('입력칸 위치를 다시 지정하세요.')
                    self.desktop.critical_regions = list(original or []) + [spec['rect']]
                    self.desktop.replace_text(field, spec['rect'], pending[field])
            except Exception:
                self.baseline = self.baseline_rows = None
                self.pause('조건 입력이 중단됐습니다. EMR 값을 직접 확인한 뒤 다시 명령을 보내세요.')
                self.replies.put('조건 입력 중단: 일부 값이 입력됐을 수 있습니다. EMR 확인이 필요합니다.')
                raise
            finally:
                self.desktop.critical_regions = original
            self.baseline = self.baseline_rows = None
            self.condition_capture = True
            self.next_query = 0

    def wait_interval(self, seconds):
        deadline = time.monotonic()+seconds
        while not self.stop.is_set():
            self.poll_commands()
            self.check_lifecycle()
            if self.state != 'running' or self.pending_conditions: return True
            remaining = deadline-time.monotonic()
            if remaining <= 0: return False
            if self.stop.wait(min(2,remaining)): return True
        return True

    def run(self):
        try:
            self.deadline = time.monotonic()+self.hours*3600 if self.hours else None
            self.watch_thread = threading.Thread(target=self.watch,daemon=True)
            self.watch_thread.start()
            while not self.stop.is_set():
                try:
                    self.poll_commands()
                    self.flush_notices()
                    if self.state == 'recovering': self.recover()
                    if self.state != 'running':
                        self.stop.wait(.5)
                        continue
                    if self.pending_conditions:
                        self.apply_conditions()
                    if self.capture_requested:
                        self.capture_requested = False
                        self.send_current(self.capture(),'수동 캡처 /capture')
                    if time.monotonic() < self.next_query:
                        self.wait_interval(min(2,self.next_query-time.monotonic()))
                        continue
                    with self.desktop_lock:
                        if self.state != 'running' or self.stop.is_set(): continue
                        self.desktop.click('query',self.config['query_rect'])
                    self.next_query = time.monotonic()+self.config['interval']
                    if self.wait_interval(3): continue
                    first = self.capture()
                    if self.wait_interval(2): continue
                    second = self.capture()
                    if self.condition_capture and self.sample(first)[0] == self.sample(second)[0]:
                        self.send_current(second, '조회 조건 변경 후 화면 · 실제 선택값 확인 필요')
                        self.condition_capture = False
                    self.process(first,second)
                except GuardError as error:
                    self.pause(str(error),automatic=error.recoverable)
                except (ValueError,DeliveryError) as error:
                    self.pause(str(error))
        except Exception as error:
            self.request_stop(f'감시 오류 ({type(error).__name__}).')
            self.emit('error',self.stop_reason)
        finally:
            self.watch_done.set()
            if self.watch_thread: self.watch_thread.join(timeout=1)
            self.emit('outline_hide',None)
            self.notify_stopped()
            self.emit('stopped',self.timed_out)

