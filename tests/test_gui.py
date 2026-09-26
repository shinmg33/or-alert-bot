import unittest
import subprocess
import sys


class GuiTest(unittest.TestCase):
    def test_first_launch_is_stopped_and_ready_to_send(self):
        # Isolate Tcl's thread-affine teardown from subsequent worker-thread OCR.
        code = r'''
from unittest.mock import patch
from or_alert.app import App
with patch('or_alert.app.list_windows', return_value=[]), patch('or_alert.app.load_settings', return_value={}):
    app = App()
    app.withdraw()
    app.update_idletasks()
    assert not app.preview.get()
    assert not hasattr(app, 'checked')
    assert not hasattr(app, 'pick_column')
    assert not app.active()
    assert app.interval.get() == '60'
    assert not hasattr(app, 'depts')
    assert 'departments' not in app.collect()
    app.destroy()
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
