"""Explicit, optional query conditions; no OCR or saved desired values."""
import re
from datetime import datetime

FIELDS = {'date': '수술일', 'department': '진료과', 'doctor': '진료교수'}
HELP = '''Alert Bot 명령어
/date 20260929 — 수술일 변경 (YYYYMMDD)
/department 산부인과 — 진료과 정확한 명칭 입력
/doctor 홍길동 — 진료교수 정확한 명칭 입력
/capture — 현재 목록 캡처
/stop — 감시 대기 (미처리 조건 변경 취소)
/restart — 감시 재개
/help — 이 안내
조건 변경은 PC에서 해당 입력칸 위치를 지정해야 합니다.
더블클릭 → 입력 → Enter → 조회 후 감시를 계속합니다.
OCR로 실제 선택값을 확인하지 않으므로 결과 캡처를 확인하세요.
영역 지정만으로 값이 바뀌지는 않습니다.'''


def validate_value(field, value):
    value = value.strip()
    if field not in FIELDS:
        raise ValueError('지원하지 않는 조건입니다.')
    if field == 'date':
        if not re.fullmatch(r'[0-9]{8}', value):
            raise ValueError('/date 20260929처럼 날짜 8자리를 입력하세요.')
        try:
            datetime.strptime(value, '%Y%m%d')
        except ValueError:
            raise ValueError('존재하지 않는 날짜입니다.') from None
    elif not value or len(value) > 80 or any(ord(c) < 32 or not c.isprintable() for c in value):
        raise ValueError('정확한 명칭을 한 줄, 1~80자로 입력하세요.')
    return value
