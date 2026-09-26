"""Pure change detection. Never infer actual start from a scheduled time."""
from collections import Counter, defaultdict
from dataclasses import dataclass


def compact(value):
    return ''.join(value.split())


@dataclass(frozen=True)
class Row:
    patient_id: str
    operation: str
    status: str
    details: tuple[tuple[str, str], ...] = ()

    @property
    def identity(self):
        return self.patient_id, self.operation


@dataclass(frozen=True)
class Snapshot:
    date: str
    department: str
    rows: tuple[Row, ...]

    @property
    def scope(self):
        return self.date, self.department

    @property
    def signature(self):
        # Sorting/reordering alone must not produce alerts; duplicates are retained.
        return tuple(sorted((r.patient_id, r.operation, r.status, r.details) for r in self.rows))


@dataclass(frozen=True)
class Change:
    level: str
    message: str


def compare(before, after):
    if before.scope != after.scope:
        raise ValueError('감시 날짜 또는 진료과가 다릅니다.')
    if before.signature == after.signature:
        return []
    old, new = defaultdict(list), defaultdict(list)
    for row in before.rows:
        old[row.identity].append(row)
    for row in after.rows:
        new[row.identity].append(row)
    # Multiple indistinguishable operations cannot safely be matched.
    if any(len(v) > 1 for v in list(old.values()) + list(new.values())):
        return [Change('확인 필요', '동일 환자의 중복 수술 행 변경 — 캡처 확인')]
    result = []
    removed, added = set(old) - set(new), set(new) - set(old)
    removed_ids = Counter(key[0] for key in removed)
    added_ids = Counter(key[0] for key in added)
    ambiguous = removed_ids.keys() & added_ids.keys()
    if ambiguous:
        result.append(Change('확인 필요', '수술명 또는 행 식별 정보 변경 — 신규/삭제 판정 보류'))
    n_added = sum(key[0] not in ambiguous for key in added)
    n_removed = sum(key[0] not in ambiguous for key in removed)
    if n_added:
        result.append(Change('주요', f'신규 행 {n_added}건'))
    if n_removed:
        result.append(Change('주요', f'목록에서 사라진 행 {n_removed}건 (취소·종료 여부는 직접 확인)'))
    for key in sorted(set(old) & set(new)):
        a, b = old[key][0], new[key][0]
        if a.status != b.status:
            message = ('환자상태 표시 변경 — 캡처 확인' if a.status.startswith('화면:') or b.status.startswith('화면:')
                       else f'환자상태: {a.status} → {b.status}')
            result.append(Change('주요', message))
        if a.details != b.details:
            da, db = dict(a.details), dict(b.details)
            fields = sorted(k for k in da.keys() | db.keys() if da.get(k) != db.get(k))
            result.append(Change('세부', '항목 수정: ' + ', '.join(fields)))
    return result or [Change('확인 필요', '표 내용 변경 — 캡처 확인')]


class Tracker:
    """Acknowledge only after delivery. Failed sends retain the old baseline."""
    def __init__(self):
        self.baselines = {}

    def stage(self, first, second):
        if first.scope != second.scope or first.signature != second.signature:
            raise ValueError('조회 결과가 아직 안정되지 않았거나 인식 결과가 일치하지 않습니다.')
        if second.scope not in self.baselines:
            self.baselines[second.scope] = second
            return []
        return compare(self.baselines[second.scope], second)

    def acknowledge(self, snapshot):
        self.baselines[snapshot.scope] = snapshot


def validate_interval(seconds):
    value = int(seconds)
    if not 30 <= value <= 3600:
        raise ValueError('조회 간격은 30~3600초로 설정하세요.')
    return value
