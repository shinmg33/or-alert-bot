import threading
import unittest
from unittest.mock import Mock
from or_alert.commands import validate_value, HELP
from or_alert.query_monitor import Monitor
from or_alert.windows import Window, GuardError


class ConditionsTest(unittest.TestCase):
    def monitor(self):
        client = Mock(chat_id='-123')
        client.identity.return_value = {'username': 'OurBot'}
        m = Monitor(Window(1, 'fake', 'fake'), {
            'interval': 30, 'query_rect': [160, 5, 190, 20], 'query_size': [200, 140],
            'condition_fields': {f: {'rect': [5, 5, 90, 20], 'size': [200, 140]}
                                 for f in ('date', 'department', 'doctor')},
            'system_notifications': 'off'}, threading.Event(), Mock(), client)
        m.state = 'running'
        return m

    def update(self, m, text, uid=1, chat=-123):
        return {'update_id': uid, 'message': {'chat': {'id': chat},
                'date': m.command_since, 'text': text}}

    def test_date_and_exact_name_validation(self):
        self.assertEqual(validate_value('date', '20260929'), '20260929')
        self.assertEqual(validate_value('doctor', '김 교수'), '김 교수')
        for value in ('20260230', '2026092', '2026-09-29', '２０２６０９２９'):
            with self.assertRaises(ValueError): validate_value('date', value)
        for value in ('', '홍\n길동', 'a'*81):
            with self.assertRaises(ValueError): validate_value('doctor', value)

    def test_unconfigured_and_calibrating_do_not_write(self):
        m = self.monitor(); m.config.pop('condition_fields')
        m.request_condition('date', '20260929')
        self.assertFalse(m.pending_conditions)
        m = self.monitor(); m.calibrating = True
        m.request_condition('doctor', '홍길동')
        self.assertFalse(m.pending_conditions)

    def test_commands_and_help_with_system_notices_off(self):
        m = self.monitor()
        m.telegram.updates.return_value = [self.update(m, '/date@OurBot 20260929'),
            self.update(m, '/doctor@OtherBot 홍길동', 2),
            self.update(m, '/department 산부인과', 3, -999), self.update(m, '/help', 4)]
        m.poll_commands(); m.flush_notices()
        self.assertEqual(m.pending_conditions, {'date': '20260929'})
        self.assertTrue(any(c.args[0] == HELP for c in m.telegram.send_notice.call_args_list))
        m.next_poll = 0; m.poll_commands()
        self.assertEqual(m.command_offset, 5)

    def test_apply_once_resets_baseline_and_schedules_query(self):
        m = self.monitor()
        m.request_condition('doctor', '홍길동'); m.request_condition('department', '산부인과')
        m.request_condition('date', '20260929')
        m.state = 'running'; m.baseline = 'old'; m.next_query = 999
        m.desktop = Mock(critical_regions=[[160, 5, 190, 20]])
        m.apply_conditions(); m.apply_conditions()
        self.assertEqual([c.args[0] for c in m.desktop.replace_text.call_args_list], ['date','department','doctor'])
        self.assertIsNone(m.baseline); self.assertTrue(m.condition_capture)
        self.assertEqual(m.next_query, 0); self.assertFalse(m.pending_conditions)

    def test_stop_cancels_and_interrupted_input_is_not_retried(self):
        m = self.monitor(); m.request_condition('date', '20260929')
        m.pause('stop'); self.assertFalse(m.pending_conditions)
        m.request_condition('date', '20260929'); m.state = 'running'
        m.desktop = Mock(critical_regions=[])
        m.desktop.replace_text.side_effect = GuardError('blocked')
        with self.assertRaises(GuardError): m.apply_conditions()
        self.assertEqual(m.state, 'paused'); self.assertFalse(m.pending_conditions)

    def test_new_geometry_invalidates_fields(self):
        m = self.monitor()
        m.end_calibration(Window(1,'fake','fake'), [1,1,10,10], [300,200])
        self.assertNotIn('condition_fields', m.config)
