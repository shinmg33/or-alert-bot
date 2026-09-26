import threading
import unittest
from unittest.mock import patch
from PIL import Image
from or_alert.query_monitor import Monitor
from or_alert.windows import Window,GuardError,OUTLINE_HANDLES,belongs_to_target


class RecoveryTest(unittest.TestCase):
    def monitor(self):
        class Client:
            chat_id='-123'
            def __init__(self): self.pending=[];self.sent=[]
            def identity(self):return {'username':'OurBot'}
            def updates(self,offset):return self.pending
            def send_notice(self,text,**kwargs):self.sent.append(text)
            def send_capture(self,*args,**kwargs):pass
        client=Client()
        m=Monitor(Window(0,'fake','fake'),{'interval':30,'query_rect':[160,5,190,20],'query_size':[200,140]},threading.Event(),lambda *args:None,client)
        class Desktop:
            expected_input=None
            window=Window(0,'fake','fake')
            def __init__(self):self.activations=0
            def activate(self):self.activations+=1
            def arm_user_input(self):pass
            def guard(self):pass
            def capture(self):return Image.new('RGB',(200,140),'white')
        m.desktop=Desktop()
        m.state='running'
        return m,client

    def update(self,m,uid,text,chat=-123):
        return {'update_id':uid,'message':{'chat':{'id':chat},'date':m.command_since,'text':text}}

    def test_stop_persists_and_restart_requires_idle(self):
        m,client=self.monitor()
        client.pending=[self.update(m,1,'/stop@OurBot')]
        m.poll_commands()
        self.assertEqual(m.state,'paused');self.assertFalse(m.stop.is_set())
        with patch('or_alert.query_monitor.idle_seconds',return_value=100):
            self.assertFalse(m.recover())
        client.pending=[self.update(m,2,'/restart@OurBot')];m.next_poll=0
        m.poll_commands()
        self.assertEqual(m.state,'recovering')
        with patch('or_alert.query_monitor.idle_seconds',return_value=4):self.assertFalse(m.recover())
        self.assertEqual(m.desktop.activations,0)
        m.baseline='old'
        with patch('or_alert.query_monitor.idle_seconds',return_value=6):self.assertTrue(m.recover())
        self.assertEqual(m.desktop.activations,1)
        self.assertEqual(m.state,'running');self.assertEqual(m.baseline,'old')

    def test_other_group_cannot_stop_or_restart(self):
        m,client=self.monitor()
        client.pending=[self.update(m,1,'/stop',-999),self.update(m,2,'/restart@OtherBot')]
        m.poll_commands();self.assertEqual(m.state,'running')

    def test_guard_failure_is_recoverable_but_geometry_is_not(self):
        m,_=self.monitor();m.desktop.expected_input=1
        with patch.object(m.desktop,'guard',create=True,side_effect=GuardError('가림')):m.check_lifecycle()
        self.assertEqual(m.state,'recovering');self.assertFalse(m.stop.is_set())
        m.state='running'
        with patch.object(m.desktop,'guard',create=True,side_effect=GuardError('크기 변경',False)):m.check_lifecycle()
        self.assertEqual(m.state,'paused')

    def test_only_our_outline_is_exempt(self):
        OUTLINE_HANDLES.add(555)
        try:
            with patch('or_alert.windows.u.GetAncestor',return_value=555):self.assertTrue(belongs_to_target(1,123))
            with patch('or_alert.windows.u.GetAncestor',return_value=777):self.assertFalse(belongs_to_target(1,123))
        finally:OUTLINE_HANDLES.discard(555)
