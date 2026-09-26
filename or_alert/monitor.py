import re
import time
from datetime import datetime
from .core import Tracker, compact, validate_interval
from .ocr import Reader, parse_table
from .windows import Desktop, GuardError, idle_seconds

RECT_NAMES = ('department', 'doctor', 'query', 'date', 'total', 'table', 'status_filter', 'room_filter')


def validate_config(config):
    validate_interval(config['interval'])
    if not config.get('departments'):
        raise ValueError('감시할 진료과를 지정하세요.')
    if len({d['name'] for d in config['departments']}) != len(config['departments']):
        raise ValueError('진료과 이름이 중복됩니다.')
    for dept in config['departments']:
        if not dept['name'] or not 0 <= dept['index'] <= 200:
            raise ValueError('진료과 이름과 목록 순번(0~200)을 확인하세요.')
    width, height = config['size']
    for name in RECT_NAMES:
        box = config['rects'].get(name)
        if not box or len(box) != 4 or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError(f'화면 영역을 다시 지정하세요: {name}')
    table = config['rects']['table']
    if not 0 < config['header_height'] < table[3] - table[1]:
        raise ValueError('표 머리글 높이를 확인하세요.')
    ranges = []
    for name in ('등록번호', '수술명', '환자상태'):
        left, right = config['columns'][name]
        if not 0 <= left < right <= table[2] - table[0]:
            raise ValueError('표 열 범위를 확인하세요.')
        ranges.append((left, right))
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError('표 열 범위가 겹칩니다.')
    # Do not allow a configured click region to overlap the patient table.
    for name in ('department', 'doctor', 'query'):
        r = config['rects'][name]
        if r[2] > table[0] and r[0] < table[2] and r[3] > table[1] and r[1] < table[3]:
            raise ValueError('입력 영역은 환자 표와 겹칠 수 없습니다.')


class Monitor:
    def __init__(self, window, config, stop, emit, telegram=None):
        validate_config(config)
        self.config, self.stop, self.emit, self.telegram = config, stop, emit, telegram
        self.desktop = Desktop(window, config['size'], stop.is_set)
        self.tracker = Tracker()
        self.reader = None
        self.date = None
        self.filters = None
        self.last_query = None

    def crop(self, image, name):
        return image.crop(self.config['rects'][name])

    def text(self, image, name):
        return self.reader.text(self.crop(image, name))

    def inspect(self, image, department):
        if self.text(image, 'department') != compact(department):
            raise GuardError('진료과 표시가 선택한 과와 다릅니다. 입력을 중단했습니다.')
        if self.text(image, 'doctor') != '전체':
            raise GuardError('진료의가 전체로 확인되지 않습니다.')
        self.check_context(image)
        total = self.text(image, 'total')
        if not re.fullmatch(r'\d{1,3}', total):
            raise GuardError('총 건수 숫자를 인식할 수 없습니다. 숫자 영역만 지정하세요.')
        words = self.reader.words(self.crop(image, 'table'))
        header = compact(''.join(w.text for w in words if w.y < self.config['header_height']))
        if not all(text in header for text in ('등록번호', '환자상태', '수술명')):
            raise GuardError('수술 표의 머리글을 확인할 수 없습니다.')
        return parse_table(words, self.config['columns'], self.config['header_height'],
                           int(total), self.date, department)

    def check_context(self, image):
        date = self.text(image, 'date')
        if not re.fullmatch(r'\d{4}[-./]\d{2}[-./]\d{2}', date):
            raise GuardError('수술일을 인식할 수 없습니다. 날짜 글자만 지정하세요.')
        # Pixel signatures retain radio-button selection, which OCR alone misses.
        filters = tuple(self.crop(image, key).tobytes() for key in ('status_filter', 'room_filter'))
        if self.date is None:
            self.date, self.filters = date, filters
        elif date != self.date or filters != self.filters:
            raise GuardError('수술일·수술상태·수술방 조건이 바뀌었습니다. 다시 시작해 기준을 설정하세요.')
        if '조회' not in self.text(image, 'query'):
            raise GuardError('조회 버튼을 확인할 수 없습니다.')

    def select_department(self, dept):
        image = self.desktop.capture()
        self.check_context(image)
        if self.text(image, 'department') != compact(dept['name']):
            self.desktop.select('department', self.config['rects']['department'], dept['index'])
            if self.stop.wait(0.5):
                return False
            image = self.desktop.capture()
            if self.text(image, 'department') != compact(dept['name']):
                raise GuardError('진료과 선택 실패. 목록 순번을 확인하세요. 조회하지 않았습니다.')
        if self.text(image, 'doctor') != '전체':
            self.desktop.select('doctor', self.config['rects']['doctor'], 0)
            if self.stop.wait(0.5):
                return False
            image = self.desktop.capture()
            if self.text(image, 'doctor') != '전체':
                raise GuardError('진료의 전체 선택 실패. 조회하지 않았습니다.')
        self.check_context(image)
        return True

    def run(self):
        try:
            self.reader = Reader()
            self.emit('status', '5초 뒤 시작합니다. EMR 목록을 맨 앞으로 두세요. F8로 중지할 수 있습니다.')
            if self.stop.wait(5):
                return
            index = 0
            while not self.stop.is_set():
                if idle_seconds() < 3:
                    self.emit('status', '사용자 입력 대기 중 — 3초 이상 입력이 없으면 계속합니다.')
                    if self.stop.wait(1):
                        break
                    continue
                dept = self.config['departments'][index]
                self.desktop.arm_user_input()
                if not self.select_department(dept):
                    break
                self.desktop.click('query', self.config['rects']['query'])
                self.last_query = time.monotonic()
                if self.stop.wait(3):
                    break
                first_image = self.desktop.capture()
                first = self.inspect(first_image, dept['name'])
                if self.stop.wait(2):
                    break
                second_image = self.desktop.capture()
                second = self.inspect(second_image, dept['name'])
                changes = self.tracker.stage(first, second)
                when = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.emit('status', f'{when} | {dept["name"]} | {len(second.rows)}건 정상 확인')
                if changes:
                    text = '\n'.join(f'[{change.level}] {change.message}' for change in changes)
                    caption = f'수술방 알림 | {dept["name"]}\n수술일 {second.date} · 감지 {when}\n{text}'
                    capture = self.crop(second_image, 'table')
                    if self.stop.is_set():
                        break
                    if self.telegram:
                        from .telegram import DeliveryError
                        while not self.stop.is_set():
                            try:
                                self.telegram.send_capture(capture, caption,
                                    silent=self.config.get('silent_details', False) and all(c.level == '세부' for c in changes))
                                break
                            except DeliveryError:
                                self.emit('status', '전송 실패: 캡처를 메모리에 보관하고 30초 뒤 재시도합니다. 조회는 대기합니다. 중복 수신 가능성이 있습니다.')
                                self.stop.wait(30)
                        if self.stop.is_set():
                            break
                    self.tracker.acknowledge(second)
                    self.emit('change', (caption, capture))
                index = (index + 1) % len(self.config['departments'])
                remaining = max(0, self.config['interval'] - (time.monotonic() - self.last_query))
                if self.stop.wait(remaining):
                    break
        except (ValueError, GuardError) as error:
            self.emit('error', str(error))
        except Exception as error:
            # Do not surface HTTP URLs, OCR content, or exception tracebacks in logs.
            from .telegram import DeliveryError
            self.emit('error', str(error) if isinstance(error, DeliveryError) else '감시 오류로 중단했습니다. 화면·OCR·설정을 점검하세요.')
        finally:
            self.emit('stopped', None)
