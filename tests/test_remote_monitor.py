import threading
import unittest
from datetime import date
from unittest.mock import Mock, patch
from PIL import Image
from or_alert.query_monitor import Monitor
from or_alert.windows import Window


class RemoteMonitorTest(unittest.TestCase):
    def monitor(self):
        client = Mock(); client.chat_id = '-123'
        m = Monitor(Window(1, 'fake', 'fake'), {
            'interval': 30, 'query_rect': [250, 20, 290, 40], 'query_size': [300, 200]},
            threading.Event(), Mock(), client)
        m.state = 'running'; m.bot_username = 'OurBot'
        m.desktop = Mock(); m.desktop.critical_regions = []
        m.region = (0, 60, 300, 200)
        return m, client

    def update(self, m, text, chat=-123, uid=1):
        return {'update_id': uid, 'message': {'chat': {'id': chat}, 'date': m.command_since, 'text': text}}

    def test_new_commands_reject_wrong_group_bot_or_stale_message(self):
        m, _ = self.monitor()
        self.assertEqual(m.command(self.update(m, '/date@OurBot 2026-09-29')), '/date')
        for item in [self.update(m, '/dept 외과', -999), self.update(m, '/date@OtherBot 오늘')]:
            self.assertIsNone(m.command(item))
        item = self.update(m, '/date 오늘'); item['message']['date'] -= 1
        self.assertIsNone(m.command(item))

    def test_stop_cancels_pending_filter(self):
        m, client = self.monitor()
        client.updates.return_value = [self.update(m, '/date 2026-09-29'), self.update(m, '/stop', uid=2)]
        m.poll_commands()
        self.assertIsNone(m.pending_filter)
        self.assertEqual(m.state, 'paused')
        m.desktop.click.assert_not_called()

    def test_invalid_date_does_not_pause_or_click(self):
        m, client = self.monitor()
        client.updates.return_value = [self.update(m, '/date 2026-02-30')]
        m.poll_commands()
        self.assertIsNone(m.pending_filter)
        self.assertEqual(m.state, 'running')

    def test_capture_includes_filter_header_and_lower_margin(self):
        m, _ = self.monitor()
        image = Image.new('RGB', (300, 200))
        with patch.object(m, 'visible_region', return_value=(0, 60, 300, 120)):
            self.assertEqual(m.notification_region(image), (0, 0, 300, 168))
            m.update_regions(image)
            self.assertIn((0, 0, 300, 168), m.desktop.critical_regions)

    def test_success_starts_new_baseline_and_sends_capture(self):
        m, _ = self.monitor(); m.baseline = 'old'
        m.pending_filter = ('/date', date(2026, 9, 29))
        image = Image.new('RGB', (300, 200), 'white')
        with patch('or_alert.query_monitor.FilterControls') as controls, patch.object(m, 'wait_interval', return_value=False), patch.object(m, 'capture', return_value=image), patch.object(m, 'send_current') as send:
            controls.return_value.set_date.return_value = '2026-09-29'
            m.apply_filter()
        self.assertNotEqual(m.baseline, 'old')
        m.desktop.click.assert_called_once_with('query', m.config['query_rect'])
        send.assert_called_once()
        self.assertFalse(m.filter_active)

    def test_failed_selection_never_queries_and_pauses(self):
        m, _ = self.monitor(); m.baseline = 'old'
        m.pending_filter = ('/dept', '외과')
        with patch('or_alert.query_monitor.FilterControls') as controls:
            controls.return_value.set_department.side_effect = ValueError('not found')
            with self.assertRaises(ValueError): m.apply_filter()
        m.desktop.click.assert_not_called()
        self.assertEqual(m.state, 'paused')
        self.assertEqual(m.baseline, 'old')
        self.assertFalse(m.filter_active)

    def test_calibration_and_busy_requests_cannot_queue(self):
        m, _ = self.monitor(); m.calibrating = True
        m.queue_filter('/date', '오늘')
        self.assertIsNone(m.pending_filter)
        m.calibrating = False; m.filter_active = True
        m.queue_filter('/dept', '외과')
        self.assertIsNone(m.pending_filter)
