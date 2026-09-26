import threading
import time
import unittest
from unittest.mock import patch
from or_alert.query_monitor import Monitor, shutdown_hours
from or_alert.windows import Window, GuardError
from or_alert.telegram import DeliveryError
from or_alert.outline import edges


class LifecycleTest(unittest.TestCase):
    def monitor(self,client=None):
        events=[]
        m=Monitor(Window(0,'fake','fake'),{'interval':30,'query_rect':[1,1,5,5],'query_size':[100,100],'shutdown_hours':.5},threading.Event(),lambda *e:events.append(e),client)
        return m,events

    def test_timer_interrupts_without_next_query(self):
        m,_=self.monitor()
        m.deadline=time.monotonic()-1
        m.check_lifecycle()
        self.assertTrue(m.stop.is_set())
        self.assertTrue(m.timed_out)
        self.assertIn('0.5시간',m.stop_reason)

    def test_user_input_during_interval_preserves_reason(self):
        m,_=self.monitor()
        m.desktop.expected_input=1
        with patch.object(m.desktop,'guard',side_effect=GuardError('사용자 입력 감지')):
            m.check_lifecycle()
        self.assertTrue(m.stop.is_set())
        m.request_stop('다른 사유')
        self.assertEqual(m.stop_reason,'사용자 입력 감지')

    def test_notice_sent_after_stop_event(self):
        class Client:
            def __init__(self): self.sent=[]
            def send_notice(self,text): self.sent.append(text)
        client=Client();m,_=self.monitor(client)
        m.request_stop('사용자 입력 감지')
        m.notify_stopped()
        self.assertEqual(len(client.sent),1)
        self.assertIn('사용자 입력 감지',client.sent[0])

    def test_failed_notice_visible_locally(self):
        class Client:
            def send_notice(self,text): raise DeliveryError('네트워크 오류',code='NETWORK')
        m,events=self.monitor(Client())
        m.request_stop('중지')
        m.notify_stopped()
        self.assertTrue(any(e[0]=='error' and 'NETWORK' in e[1] for e in events))

    def test_hours_and_outline_geometry(self):
        self.assertEqual(shutdown_hours('0.5'),.5)
        self.assertEqual(shutdown_hours('0'),0)
        for value in ['nan','inf',-1,169,'a']:
            with self.assertRaises(ValueError): shutdown_hours(value)
        self.assertEqual(edges((-100,20,100,120))[0],(-100,20,200,3))
