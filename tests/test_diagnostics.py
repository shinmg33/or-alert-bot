import io
import json
import socket
import ssl
import unittest
from unittest.mock import patch
import urllib.error
from or_alert.telegram import Telegram, DeliveryError


class DiagnosticTest(unittest.TestCase):
    def client(self):
        return Telegram('12345:'+'TEST_ONLY_'*4)

    def fail(self, code, description, parameters=None):
        client = self.client()
        payload = json.dumps({'description': description, 'parameters': parameters or {}}).encode()
        error = urllib.error.HTTPError('https://api.telegram.org/bot'+client.token, code,
                                      description, {}, io.BytesIO(payload))
        with patch.object(client.opener, 'open', side_effect=error):
            with self.assertRaises(DeliveryError) as caught:
                client.identity()
        self.assertNotIn(client.token, str(caught.exception))
        return caught.exception

    def test_invalid_token_is_not_generic_network_error(self):
        self.assertEqual(self.fail(401, 'Unauthorized').code, 'TOKEN')

    def test_missing_chat_and_forbidden_have_different_guidance(self):
        self.assertEqual(self.fail(400, 'Bad Request: chat not found').code, 'CHAT_NOT_FOUND')
        self.assertEqual(self.fail(403, 'Forbidden').code, 'FORBIDDEN')

    def test_webhook_and_conflicting_reader(self):
        self.assertIn('웹훅', str(self.fail(409, 'webhook active')))
        self.assertIn('중복', str(self.fail(409, 'terminated by other getUpdates request')))

    def test_rate_limit_and_migration(self):
        error = self.fail(429, 'Too Many Requests', {'retry_after': 55})
        self.assertTrue(error.retryable)
        self.assertEqual(error.retry_after, 55)
        error = self.fail(400, 'migrated', {'migrate_to_chat_id': -1001234})
        self.assertEqual(error.code, 'MIGRATED')
        self.assertIn('-1001234', str(error))

    def test_never_echo_server_token(self):
        self.assertNotIn('secret-raw-body', str(self.fail(400, 'secret-raw-body')))

    def test_network_error_categories(self):
        for reason, code in [(socket.gaierror(11001, 'dns'), 'DNS'),
                             (TimeoutError('time'), 'TIMEOUT'),
                             (ssl.SSLCertVerificationError('certificate'), 'TLS_CERT')]:
            client = self.client()
            with patch.object(client.opener, 'open', side_effect=urllib.error.URLError(reason)):
                with self.assertRaises(DeliveryError) as caught:
                    client.identity()
            self.assertEqual(caught.exception.code, code)

    def test_diagnostic_does_not_send_or_change_webhooks(self):
        client = self.client()
        with patch.object(client, '_call', side_effect=[{'username':'sample_bot'}, {'url':''}]) as call:
            self.assertIn('인증 정상', client.diagnose())
            self.assertEqual([c.args[0] for c in call.call_args_list], ['getMe','getWebhookInfo'])

    def test_groups_stop_at_webhook_without_mutating(self):
        client = self.client()
        with patch.object(client, '_call', side_effect=[{}, {'url':'https://private.example'}]) as call:
            with self.assertRaises(DeliveryError):
                client.groups()
            self.assertEqual(call.call_count, 2)
