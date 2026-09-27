"""Locally calibrated filter controls; OCR reads only control labels."""
import calendar
import re
from datetime import date, timedelta


def parse_date(value, today=None):
    today = today or date.today()
    aliases = {'today': 0, '오늘': 0, 'tomorrow': 1, '내일': 1, 'yesterday': -1, '어제': -1}
    if value.lower() in aliases:
        return today + timedelta(days=aliases[value.lower()])
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('/date YYYY-MM-DD 또는 /date 오늘·내일·어제')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('존재하지 않는 날짜입니다.') from None


def read_date(text):
    match = re.fullmatch(r'(\d{4})\D*(\d{2})\D*(\d{2})', text.strip())
    if not match:
        raise ValueError('수술일 숫자를 확인하지 못했습니다. 날짜 숫자 영역을 다시 지정하세요.')
    return date(*map(int, match.groups()))


def read_month(text):
    match = re.fullmatch(r'(\d{4})[.년/\-]*(\d{1,2})월?', text.replace(' ', ''))
    if not match or not 1 <= int(match[2]) <= 12:
        raise ValueError('달력의 연월을 확인하지 못했습니다. 달력 설정을 확인하세요.')
    return int(match[1]), int(match[2])


def day_rect(grid, target):
    # The supplied EMR calendar has Sunday first and six date rows.
    offset = (calendar.monthrange(target.year, target.month)[0] + 1) % 7
    row, col = divmod(offset + target.day - 1, 7)
    left, top, right, bottom = grid
    w, h = (right-left)/7, (bottom-top)/6
    x, y = left+(col+.5)*w, top+(row+.5)*h
    return [int(x-2), int(y-2), int(x+3), int(y+3)]


def validate_rect(rect, size):
    if (not isinstance(rect, (list, tuple)) or len(rect) != 4 or
            not all(isinstance(n, int) for n in rect) or
            not 0 <= rect[0] < rect[2] <= size[0] or
            not 0 <= rect[1] < rect[3] <= size[1]):
        raise ValueError('저장된 영역이 창 범위와 맞지 않습니다. 위치를 다시 지정하세요.')
    return rect


class FilterControls:
    def __init__(self, desktop, config, stop):
        self.desktop, self.config, self.stop = desktop, config, stop
        from .ocr import Reader
        self.reader = Reader(clean=True)
        self.checkpoint = lambda: None

    def rects(self, names):
        controls = self.config.get('remote_controls', {})
        if controls.get('size') != self.config['query_size']:
            raise ValueError('원격 제어 위치를 먼저 지정하세요. 창 크기도 일치해야 합니다.')
        result = {}
        for name in names:
            if name not in controls:
                raise ValueError('원격 제어 설정 누락: '+name)
            result[name] = validate_rect(controls[name], controls['size'])
        return result

    def wait(self):
        if self.stop.wait(.35):
            raise ValueError('원격 제어가 중지되었습니다.')
        self.checkpoint()
        self.desktop.guard()

    def text(self, rect):
        return self.reader.text(self.desktop.capture().crop(rect))

    def set_department(self, expected):
        rects = self.rects(['department', 'department_button'])
        rect, button = rects['department'], rects['department_button']
        self.desktop.critical_regions = [rect, button]
        expected = ''.join(expected.split())
        if not expected or len(expected) > 40:
            raise ValueError('/dept 산부인과처럼 정확한 진료과 이름을 입력하세요.')
        if self.text(rect) == expected:
            return expected
        self.desktop.select('department', button, 0)
        previous = None
        for _ in range(200):
            self.wait()
            current = self.text(rect)
            if current == expected:
                return expected
            if not current or current == previous:
                break
            previous = current
            self.desktop.select_next('department', button)
        raise ValueError('해당 진료과를 확인하지 못했습니다. 현재 선택을 PC에서 확인하세요. 조회와 감시는 대기합니다.')

    def set_date(self, target):
        r = self.rects(['date', 'calendar_button', 'calendar_title', 'calendar_prev', 'calendar_next', 'calendar_grid'])
        self.desktop.critical_regions = [r['date'], r['calendar_button']]
        if read_date(self.text(r['date'])) == target:
            return target.isoformat()
        self.desktop.click('calendar', r['calendar_button'])
        self.desktop.allow_owned_popup = True
        self.desktop.critical_regions = [r[n] for n in ('calendar_title', 'calendar_prev', 'calendar_next', 'calendar_grid')]
        try:
            self.wait()
            current = read_month(self.text(r['calendar_title']))
            delta = (target.year-current[0])*12 + target.month-current[1]
            if abs(delta) > 24:
                raise ValueError('현재 달력에서 24개월 이내 날짜만 선택할 수 있습니다.')
            for _ in range(abs(delta)):
                self.desktop.click('calendar', r['calendar_next' if delta > 0 else 'calendar_prev'])
                self.wait()
                actual = read_month(self.text(r['calendar_title']))
                expected_index = current[0]*12+current[1]-1+(1 if delta > 0 else -1)
                expected = (expected_index//12, expected_index%12+1)
                if actual != expected:
                    raise ValueError('달력 월 이동을 확인하지 못했습니다. PC에서 달력을 확인하세요.')
                current = actual
            self.desktop.click('calendar', day_rect(r['calendar_grid'], target))
        finally:
            self.desktop.allow_owned_popup = False
            self.desktop.critical_regions = [r['date'], r['calendar_button']]
        self.wait()
        if read_date(self.text(r['date'])) != target:
            raise ValueError('선택된 날짜가 요청과 다릅니다. 달력 숫자 영역을 다시 지정하세요. 조회와 감시는 대기합니다.')
        return target.isoformat()
