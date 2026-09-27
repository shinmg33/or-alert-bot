import unittest
from datetime import date
from unittest.mock import Mock, patch
from or_alert.remote_controls import FilterControls, parse_date, read_date, read_month, day_rect, validate_rect


class RemoteControlsTest(unittest.TestCase):
    def controller(self):
        desktop = Mock()
        stop = Mock(); stop.wait.return_value = False
        r = {'size': [800, 600], 'date': [10, 10, 90, 30],
             'calendar_button': [90, 10, 110, 30],
             'calendar_title': [10, 40, 110, 60],
             'calendar_prev': [0, 40, 10, 60], 'calendar_next': [110, 40, 120, 60],
             'calendar_grid': [0, 80, 210, 260],
             'department': [300, 10, 400, 30], 'department_button': [400, 10, 420, 30]}
        with patch('or_alert.ocr.Reader'):
            controls = FilterControls(desktop, {'query_size': [800, 600], 'remote_controls': r}, stop)
        controls.text = Mock()
        return controls, desktop, r

    def test_date_validation_and_relative_dates(self):
        self.assertEqual(parse_date('내일', date(2026, 12, 31)), date(2027, 1, 1))
        self.assertEqual(parse_date('어제', date(2024, 3, 1)), date(2024, 2, 29))
        for value in ['2026-02-29', '2026-9-1', '', 'tomorrow junk']:
            with self.assertRaises(ValueError): parse_date(value)
        self.assertEqual(read_date('2026-09-28'), date(2026, 9, 28))
        self.assertEqual(read_month('2026.09'), (2026, 9))

    def test_calendar_sunday_first_and_sixth_row(self):
        self.assertEqual(day_rect([0, 0, 700, 600], date(2026, 9, 28)), [148, 448, 153, 453])
        self.assertEqual(day_rect([0, 0, 700, 600], date(2026, 8, 31)), [148, 548, 153, 553])

    def test_calendar_icon_clicked_before_day(self):
        c, d, r = self.controller()
        c.text.side_effect = ['2026-09-28', '2026.09', '2026-09-29']
        self.assertEqual(c.set_date(date(2026, 9, 29)), '2026-09-29')
        self.assertEqual(d.click.call_args_list[0].args, ('calendar', r['calendar_button']))
        self.assertEqual(d.click.call_args_list[1].args, ('calendar', day_rect(r['calendar_grid'], date(2026, 9, 29))))
        self.assertFalse(d.allow_owned_popup)

    def test_month_navigation_across_year(self):
        c, d, r = self.controller()
        c.text.side_effect = ['2026-12-28', '2026.12', '2027.01', '2027-01-02']
        c.set_date(date(2027, 1, 2))
        self.assertEqual(d.click.call_args_list[1].args, ('calendar', r['calendar_next']))

    def test_wrong_month_does_not_click_day(self):
        c, d, r = self.controller()
        c.text.side_effect = ['2026-09-28', '2026.09', '2026.09']
        with self.assertRaises(ValueError): c.set_date(date(2026, 10, 1))
        self.assertEqual(d.click.call_count, 2)
        self.assertFalse(d.allow_owned_popup)

    def test_wrong_selected_date_fails(self):
        c, d, r = self.controller()
        c.text.side_effect = ['2026-09-28', '2026.09', '2026-09-28']
        with self.assertRaises(ValueError): c.set_date(date(2026, 9, 29))

    def test_department_uses_arrow_separate_from_label(self):
        c, d, r = self.controller()
        c.text.side_effect = ['외과', '전체', '내과', '산부인과']
        self.assertEqual(c.set_department('산부인과'), '산부인과')
        d.select.assert_called_once_with('department', r['department_button'], 0)
        self.assertEqual(d.select_next.call_count, 2)
        self.assertTrue(all(call.args[1] == r['department_button'] for call in d.select_next.call_args_list))

    def test_missing_department_stops_at_list_end(self):
        c, d, r = self.controller()
        c.text.side_effect = ['외과', '전체', '내과', '내과']
        with self.assertRaises(ValueError): c.set_department('없는과')
        d.click.assert_not_called()

    def test_wrong_size_prevents_input(self):
        c, d, r = self.controller(); r['size'] = [900, 600]
        with self.assertRaises(ValueError): c.set_date(date(2026, 9, 29))
        d.click.assert_not_called()

    def test_stop_checkpoint_aborts_calendar_before_day(self):
        c, d, r = self.controller()
        c.text.return_value = '2026-09-28'
        c.checkpoint = Mock(side_effect=ValueError('stopped'))
        with self.assertRaises(ValueError): c.set_date(date(2026, 9, 29))
        self.assertEqual(d.click.call_count, 1)

    def test_invalid_region_rejected(self):
        for rect in [[0, 0, 900, 5], [1, 1, 0, 0], None]:
            with self.assertRaises(ValueError): validate_rect(rect, [800, 600])


if __name__ == '__main__':
    unittest.main()
