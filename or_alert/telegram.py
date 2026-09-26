"""Only fixed Telegram HTTPS endpoints; no credentials in errors/logs."""
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid


class DeliveryError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Telegram:
    def __init__(self, token, chat_id):
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token.strip()):
            raise ValueError('BotFather에서 받은 봇 토큰 형식을 확인하세요.')
        if not re.fullmatch(r'-\d+', chat_id.strip()):
            raise ValueError('비공개 그룹의 음수 Chat ID를 입력하세요.')
        self.token, self.chat_id = token.strip(), chat_id.strip()
        self.opener = urllib.request.build_opener(NoRedirect())

    def _call(self, method, data, content_type):
        request = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/{method}', data=data,
            headers={'Content-Type': content_type}, method='POST')
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise DeliveryError('Telegram이 전송을 거절했습니다. 토큰·그룹 권한을 확인하세요.')
            return result['result']
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise DeliveryError(f'Telegram 전송 실패 (HTTP {code}). 그룹·권한·전송 제한을 확인하세요.') from None
        except (OSError, ValueError):
            raise DeliveryError('Telegram 연결 실패. 전송 여부가 불확실하므로 그룹을 확인하세요.') from None

    def test(self):
        # No patient information is used by this explicitly invoked test.
        return self._call('sendMessage', urllib.parse.urlencode({
            'chat_id': self.chat_id, 'text': '수술방 알림봇 연결 테스트 — 환자정보 없는 테스트 메시지입니다.',
            'protect_content': 'true'}).encode(), 'application/x-www-form-urlencoded')

    def groups(self):
        updates = self._call('getUpdates', b'timeout=0', 'application/x-www-form-urlencoded')
        found = {}
        for update in updates:
            for field in ('message', 'my_chat_member'):
                chat = update.get(field, {}).get('chat', {})
                if chat.get('type') in ('group', 'supergroup'):
                    found[str(chat['id'])] = chat.get('title', '그룹')
        return found

    def send_capture(self, image, caption, silent=False):
        stream = io.BytesIO()
        image.save(stream, 'PNG')
        boundary = 'ORAlert' + uuid.uuid4().hex
        chunks = []
        fields = {'chat_id': self.chat_id, 'caption': caption[:1000],
                  'protect_content': 'true', 'disable_notification': str(silent).lower()}
        for key, value in fields.items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        # sendDocument preserves the small Korean table text at original resolution.
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="surgery-list.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
        chunks.extend([stream.getvalue(), f'\r\n--{boundary}--\r\n'.encode()])
        return self._call('sendDocument', b''.join(chunks), f'multipart/form-data; boundary={boundary}')
