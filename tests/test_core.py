import unittest
from or_alert.core import Row, Snapshot, Tracker, compare, validate_interval
from or_alert.ocr import Word, parse_table
from or_alert.monitor import validate_config


def row(pid='12345678', status='확정', time='12:00', operation='가상 수술'):
    return Row(pid, operation, status, (('시작시간', time),))


def snap(*rows, dept='가상과', date='2026-09-26'):
    return Snapshot(date, dept, tuple(rows))


class ChangesTest(unittest.TestCase):
    def test_new_and_removed_are_not_surgical_state(self):
        changes = compare(snap(row()), snap(row(), row('87654321')))
        self.assertEqual(changes[0].message, '신규 행 1건')
        removed = compare(snap(row()), snap())
        self.assertIn('목록에서 사라진', removed[0].message)

    def test_scheduled_time_is_minor(self):
        changes = compare(snap(row()), snap(row(time='15:30')))
        self.assertEqual([c.level for c in changes], ['세부'])

    def test_status_is_major(self):
        changes = compare(snap(row()), snap(row(status='수술중')))
        self.assertEqual(changes[0].level, '주요')
        self.assertIn('확정 → 수술중', changes[0].message)

    def test_sort_does_not_alert(self):
        a, b = row(), row('87654321')
        self.assertEqual(compare(snap(a, b), snap(b, a)), [])

    def test_duplicate_patient_operations_are_not_overwritten(self):
        a, b = row(), row(operation='다른 가상 수술')
        self.assertEqual(len(compare(snap(a), snap(a, b))), 1)
        changes = compare(snap(a, a), snap(a, row(status='퇴실')))
        self.assertEqual(changes[0].level, '확인 필요')

    def test_operation_rename_is_ambiguous(self):
        self.assertEqual(compare(snap(row()), snap(row(operation='수정 수술')))[0].level, '확인 필요')

    def test_separate_department_baselines(self):
        tracker = Tracker()
        a, b = snap(row()), snap(row('87654321'), dept='다른과')
        self.assertEqual(tracker.stage(a, a), [])
        self.assertEqual(tracker.stage(b, b), [])
        self.assertEqual(tracker.stage(a, a), [])

    def test_unstable_result_does_not_change_baseline(self):
        tracker = Tracker()
        a, b = snap(row()), snap(row(status='퇴실'))
        tracker.stage(a, a)
        with self.assertRaises(ValueError):
            tracker.stage(a, b)
        self.assertEqual(tracker.baselines[a.scope], a)

    def test_failed_delivery_can_be_retried_until_acknowledged(self):
        tracker = Tracker()
        a, b = snap(row()), snap(row(status='퇴실'))
        tracker.stage(a, a)
        self.assertTrue(tracker.stage(b, b))
        self.assertTrue(tracker.stage(b, b))
        tracker.acknowledge(b)
        self.assertFalse(tracker.stage(b, b))

    def test_date_change_not_compared(self):
        with self.assertRaises(ValueError):
            compare(snap(row()), snap(row(), date='2026-09-27'))

    def test_minimum_interval(self):
        for value in (0, 29, 3601, 'bad'):
            with self.assertRaises(ValueError):
                validate_interval(value)
        self.assertEqual(validate_interval('30'), 30)


class RecognitionTest(unittest.TestCase):
    columns = {'등록번호': [0, 100], '수술명': [100, 250], '환자상태': [250, 350]}
    words = [Word('12345678', 5, 30, 70, 12), Word('가상수술', 110, 30, 60, 12),
             Word('수술중', 260, 30, 45, 12), Word('12:00', 370, 30, 40, 12)]

    def test_row_recognition(self):
        result = parse_table(self.words, self.columns, 20, 1, '2026-09-26', '가상과')
        self.assertEqual(result.rows[0].status, '수술중')
        self.assertEqual(result.rows[0].details, (('세부항목', '12:00'),))

    def test_hidden_rows_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_table(self.words, self.columns, 20, 2, '2026-09-26', '가상과')

    def test_bad_identifier_fails_closed(self):
        words = [Word('12O45678', 5, 30, 70, 12)] + self.words[1:]
        with self.assertRaises(ValueError):
            parse_table(words, self.columns, 20, 1, '2026-09-26', '가상과')

    def test_empty_is_valid_only_if_total_is_zero(self):
        self.assertEqual(parse_table([], self.columns, 20, 0, '2026-09-26', '가상과').rows, ())
        with self.assertRaises(ValueError):
            parse_table([], self.columns, 20, 1, '2026-09-26', '가상과')


if __name__ == '__main__':
    unittest.main()
