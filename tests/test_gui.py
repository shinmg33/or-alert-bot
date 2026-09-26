import unittest
import subprocess
import sys


class GuiTest(unittest.TestCase):
    def test_first_launch_is_stopped_and_local_only(self):
        # Isolate Tcl's thread-affine teardown from subsequent worker-thread OCR.
        code = r'''
from unittest.mock import patch
from or_alert.app import App
with patch('or_alert.app.list_windows', return_value=[]), patch('or_alert.app.load_settings', return_value={}):
    app = App()
    app.withdraw()
    app.update_idletasks()
    assert app.preview.get()
    assert not hasattr(app, 'checked')
    assert not hasattr(app, 'pick_column')
    assert not app.active()
    assert app.interval.get() == '60'
    app.depts.insert('1.0', '산부인과\n외과')
    assert app.collect()['departments'] == [{'name':'산부인과'}, {'name':'외과'}]
    app.destroy()
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
