import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error
from PIL import Image
from or_alert.storage import save_settings, load_settings
from or_alert.telegram import Telegram, DeliveryError


class LocalStorageTest(unittest.TestCase):
    def test_secret_encrypted_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.bin'
            data = {'token': 'FAKE_TEST_SECRET', 'departments': [{'name': '가상과', 'index': 1}]}
            save_settings(data, path)
            self.assertNotIn(b'FAKE_TEST_SECRET', path.read_bytes())
            self.assertEqual(load_settings(path), data)


class TelegramTest(unittest.TestCase):
    def client(self):
        return Telegram('12345:' + 'TEST_ONLY_TOKEN_' * 3, '-10012345')

    def test_original_png_and_silent_detail_flag(self):
        client = self.client()
        with patch.object(client, '_call', return_value={}) as call:
            client.send_capture(Image.new('RGB', (10, 10)), '가상 알림', silent=True)
            method, payload, _ = call.call_args.args
            self.assertEqual(method, 'sendDocument')
            self.assertIn(b'\x89PNG', payload)
            self.assertIn(b'name="disable_notification"\r\n\r\ntrue', payload)
            self.assertNotIn(client.token.encode(), payload)

    def test_http_errors_do_not_leak_token(self):
        client = self.client()
        error = urllib.error.HTTPError('https://api.telegram.org/bot' + client.token, 401, 'Unauthorized', {}, None)
        with patch.object(client.opener, 'open', side_effect=error):
            with self.assertRaises(DeliveryError) as caught:
                client.test()
        self.assertNotIn(client.token, str(caught.exception))

    def test_requires_group_id(self):
        with self.assertRaises(ValueError):
            Telegram('12345:' + 'a'*30, '12345')


if __name__ == '__main__':
    unittest.main()
