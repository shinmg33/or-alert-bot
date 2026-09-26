import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from PIL import ImageDraw
from or_alert.query_monitor import Monitor
from or_alert.windows import Desktop,Window,GuardError
from or_alert.telegram import Telegram
from test_visual_layout import VisualRowsTest


class FocusedMonitoringTest(unittest.TestCase):
    def monitor(self, client=None):
        return Monitor(Window(1,'fake','fake'),{'interval':30,'query_rect':[160,5,190,20],'query_size':[330,180]},threading.Event(),lambda *args:None,client)

    def test_blank_area_changes_ignored_but_new_rows_detected(self):
        m=self.monitor();fixture=VisualRowsTest()
        m.region=(0,0,330,180);m.columns=fixture.columns;m.header_height=24
        a=fixture.image([('12345678','A','12:00')])
        b=a.copy();ImageDraw.Draw(b).rectangle((5,120,300,170),fill='red')
        self.assertEqual(m.sample(a)[0],m.sample(b)[0])
        c=fixture.image([('12345678','A','12:00'),('87654321','B','13:00')])
        self.assertNotEqual(m.sample(a)[0],m.sample(c)[0])
        self.assertEqual(m.visible_region(a)[3],49)

    def test_only_critical_rectangles_checked(self):
        d=Desktop(Window(1,'fake','fake'),size=[200,200])
        d.critical_regions=[[10,10,40,30],[10,60,150,100]]
        points=[]
        def hit(point): points.append((point.x,point.y)); return 1
        with patch('or_alert.windows.title',return_value='fake'),patch('or_alert.windows.executable',return_value='fake'),patch('or_alert.windows.client_box',return_value=(0,0,200,200)),patch('or_alert.windows.stop_pressed',return_value=False),patch('or_alert.windows.u.GetAsyncKeyState',return_value=0),patch('or_alert.windows.u.IsWindow',return_value=True),patch('or_alert.windows.u.IsIconic',return_value=False),patch('or_alert.windows.u.GetForegroundWindow',return_value=99),patch('or_alert.windows.u.WindowFromPoint',side_effect=hit),patch('or_alert.windows.belongs_to_target',side_effect=lambda h,t:h==t):
            d.guard()
        self.assertTrue(points)
        self.assertTrue(all(any(l<=x<r and t<=y<b for l,t,r,b in d.critical_regions) for x,y in points))

    def test_short_recovery_sends_no_system_notice(self):
        m=self.monitor();m.state='running'
        m.pause('일시적 입력',automatic=True)
        self.assertTrue(m.notices.empty())
        m.flush_notices()
        self.assertTrue(m.notices.empty())

    def test_system_message_is_silent_by_default(self):
        client=Telegram('123:'+('x'*25),'-123')
        with patch.object(client,'_call',return_value=True) as call:
            client.send_notice('system')
            self.assertEqual(parse_qs(call.call_args.args[1].decode())['disable_notification'],['true'])

    def test_system_off_suppresses_notices(self):
        class Client:
            def send_notice(self,*a,**kw): raise AssertionError('must not send')
        m=self.monitor(Client());m.config['system_notifications']='off'
        m.notices.put('system');m.flush_notices();m.notify_stopped()
