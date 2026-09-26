import subprocess
import sys
import threading
import unittest
from or_alert.query_monitor import Monitor
from or_alert.windows import Window


class CalibrationTest(unittest.TestCase):
    def test_restart_blocked_during_picker_and_new_geometry_applied(self):
        m=Monitor(Window(1,'fake','fake'),{'interval':30,'query_rect':[1,1,10,10],'query_size':[100,100]},threading.Event(),lambda *args:None)
        m.state='running';m.baseline='old';m.initial_sent=True
        m.begin_calibration();m.restart()
        self.assertEqual(m.state,'paused');self.assertTrue(m.calibrating)
        m.end_calibration(Window(2,'new','fake'),[20,10,40,30],[200,150])
        self.assertEqual(m.desktop.window.handle,2)
        self.assertEqual(m.desktop.size,[200,150])
        self.assertEqual(m.config['query_rect'],[20,10,40,30])
        self.assertIsNone(m.baseline);self.assertFalse(m.initial_sent)
        m.restart();self.assertEqual(m.state,'recovering')

    def test_cancel_keeps_previous_position(self):
        m=Monitor(Window(1,'fake','fake'),{'interval':30,'query_rect':[1,1,10,10],'query_size':[100,100]},threading.Event(),lambda *args:None)
        m.begin_calibration();m.end_calibration()
        self.assertEqual(m.config['query_rect'],[1,1,10,10])
        self.assertFalse(m.calibrating);self.assertEqual(m.state,'paused')

    def test_button_opens_picker_with_live_paused_listener(self):
        code=r'''
import threading
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PIL import Image
from or_alert.app import App
from or_alert.query_monitor import Monitor
from or_alert.windows import Window
window=Window(1,'fake','fake')
with patch('or_alert.app.list_windows',return_value=[window]),patch('or_alert.app.load_settings',return_value={}):
    app=App();app.withdraw()
    app.monitor=Monitor(window,{'interval':30,'query_rect':[1,1,10,10],'query_size':[100,100]},threading.Event(),lambda *a:None)
    app.monitor.state='paused'
    app.worker=SimpleNamespace(is_alive=lambda:True)
    desktop=Mock();desktop.capture_preview.return_value=Image.new('RGB',(200,150),'white')
    def picker(parent,image,prompt,selected,on_close):
        assert app.capture_busy
        assert app.monitor.calibrating
        selected([120,10,160,30]);on_close()
    with patch('or_alert.app.Desktop',return_value=desktop),patch('or_alert.app.Picker',side_effect=picker) as picked,patch('or_alert.app.save_settings') as saved,patch.object(app,'after',side_effect=lambda delay,fn:fn()):
        app.capture_setup()
        assert picked.call_count==1
        desktop.capture_preview.assert_called_once()
        saved.assert_called_once()
        assert app.monitor.config['query_rect']==[120,10,160,30]
        assert app.monitor.desktop.size==[200,150]
        assert not app.capture_busy
        assert not app.monitor.calibrating
    app.worker=None
    app.destroy()
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
