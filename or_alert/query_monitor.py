"""Query-only monitoring. No OCR and no department/doctor input."""
import time
from datetime import datetime
from .core import compare, validate_interval
from .layout import detect_grid, LayoutError
from .visual import digest, row_boundaries, visual_snapshot
from .windows import Desktop, GuardError, idle_seconds
from .telegram import DeliveryError


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
        caption = '수술방 알림 | 현재 선택한 목록\n'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n'+text
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

    def run(self):
        try:
            if self.stop.wait(2): return
            self.desktop.activate()
            if self.stop.wait(.5): return
            self.setup(self.desktop.capture())
            while not self.stop.is_set():
                if idle_seconds() < 3:
                    if self.stop.wait(1): break
                    continue
                self.desktop.arm_user_input()
                self.desktop.click('query',self.config['query_rect'])
                started = time.monotonic()
                if self.stop.wait(3): break
                first = self.desktop.capture()
                if self.stop.wait(2): break
                second = self.desktop.capture()
                self.process(first,second)
                if self.stop.wait(max(0,self.config['interval']-(time.monotonic()-started))): break
        except (ValueError,GuardError,DeliveryError) as error:
            self.emit('error',str(error))
        except Exception as error:
            self.emit('error',f'감시 중단 ({type(error).__name__}).')
        finally:
            self.emit('stopped',None)
