import threading
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from or_alert.query_monitor import Monitor
from or_alert.windows import Window
from or_alert.telegram import DeliveryError


class QueryOnlyTest(unittest.TestCase):
    def monitor(self,telegram=None):
        events=[]
        m=Monitor(Window(0,'fake','fake'),{'interval':30,'query_rect':[160,5,190,20],
                  'query_size':[200,140]},threading.Event(),lambda *e:events.append(e),telegram)
        m.setup(Image.new('RGB',(200,140),'white'))
        return m,events

    def image(self,text):
        im=Image.new('RGB',(200,140),'white')
        ImageDraw.Draw(im).text((10,60),text,fill='black')
        return im

    def test_without_ocr_or_department_config(self):
        m,events=self.monitor()
        a,b=self.image('A'),self.image('B')
        m.process(a,a)
        m.process(a,b)
        self.assertFalse(any(e[0]=='change' for e in events))
        m.process(b,b)
        self.assertEqual(sum(e[0]=='change' for e in events),1)
        m.process(b,b)
        self.assertEqual(sum(e[0]=='change' for e in events),1)

    def test_failed_delivery_retains_baseline(self):
        class Client:
            def send_capture(self,*args,**kw): raise DeliveryError('failed',code='FORBIDDEN')
        m,_=self.monitor(Client())
        a,b=self.image('A'),self.image('B')
        m.process(a,a)
        baseline=m.baseline
        with self.assertRaises(DeliveryError): m.process(b,b)
        self.assertEqual(m.baseline,baseline)

    def test_run_only_clicks_query(self):
        m,_=self.monitor()
        class Desktop:
            def __init__(self): self.actions=[]
            def activate(self): pass
            def arm_user_input(self): pass
            def capture(self): return Image.new('RGB',(200,140),'white')
            def click(self,kind,rect): self.actions.append(kind)
        class Stop:
            def __init__(self): self.calls=0
            def is_set(self): return False
            def wait(self,_):
                self.calls+=1
                return self.calls>=5
        m.desktop=Desktop()
        m.stop=Stop()
        with patch('or_alert.query_monitor.idle_seconds',return_value=5): m.run()
        self.assertEqual(m.desktop.actions,['query'])

class CommandsTest(QueryOnlyTest):
    def client(self):
        class Client:
            chat_id='-123'
            def __init__(self): self.sent=[]; self.pending=[]; self.offsets=[]
            def identity(self): return {'username':'OurBot'}
            def updates(self,offset): self.offsets.append(offset); return self.pending
            def send_capture(self,image,caption,**kw): self.sent.append((image,caption))
        return Client()

    def update(self,m,uid=1,chat=-123,text='/capture',date=None):
        return {'update_id':uid,'message':{'chat':{'id':chat},'date':m.command_since if date is None else date,'text':text}}

    def test_commands_restricted_to_configured_group_and_bot(self):
        client=self.client(); m,_=self.monitor(client); m.bot_username='OurBot'
        self.assertTrue(m.accepts_command(self.update(m)))
        self.assertTrue(m.accepts_command(self.update(m,text='/capture@OurBot')))
        for update in [self.update(m,chat=-999),self.update(m,text='/capture@OtherBot'),self.update(m,date=m.command_since-1),self.update(m,text='/captureevil')]:
            self.assertFalse(m.accepts_command(update))

    def test_manual_capture_is_fresh_and_preserves_baseline(self):
        client=self.client(); m,_=self.monitor(client)
        image=self.image('fresh')
        class Desktop:
            def capture(self): return image
        m.desktop=Desktop(); m.baseline='unchanged'
        client.pending=[self.update(m)]
        m.poll_commands()
        self.assertIs(client.sent[0][0],image)
        self.assertEqual(m.baseline,'unchanged')
        m.next_poll=0; m.poll_commands()
        self.assertEqual(len(client.sent),1)
        self.assertEqual(client.offsets,[None,2])

    def test_initial_send_even_without_changes(self):
        client=self.client(); m,events=self.monitor(client)
        m.send_current(self.image('initial'),'감시 시작')
        self.assertEqual(len(client.sent),1)
        self.assertIn('Alert Bot',client.sent[0][1])
        self.assertTrue(any(e[0]=='change' for e in events))
