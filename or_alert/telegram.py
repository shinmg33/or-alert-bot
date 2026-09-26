"""Only fixed Telegram HTTPS endpoints; no credentials in errors/logs."""
import io
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid


class DeliveryError(Exception):
    def __init__(self, message, code='UNKNOWN', retryable=False, retry_after=30):
        super().__init__(message)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


def api_error(code, description='', parameters=None):
    """Map server errors to fixed guidance; never echo arbitrary response text."""
    description = str(description).lower()
    parameters = parameters if isinstance(parameters, dict) else {}
    if code in (401, 404):
        return DeliveryError('토큰 인증 실패 (HTTP %s). BotFather의 API 토큰 전체를 다시 복사하세요. 봇 사용자 이름이나 앞의 bot 문자열은 넣지 않습니다.' % code, 'TOKEN')
    if code == 409:
        message = ('이 봇에 웹훅이 설정되어 그룹 찾기를 사용할 수 없습니다. 기존 연동에서 웹훅을 해제하거나 그룹 Chat ID를 직접 입력하세요.'
                   if 'webhook' in description else '다른 프로그램이 같은 봇의 메시지를 조회 중입니다. 중복 실행된 봇 프로그램을 종료하고 다시 시도하세요.')
        return DeliveryError(message, 'CONFLICT')
    if code == 429:
        delay = parameters.get('retry_after', 30)
        delay = delay if isinstance(delay, int) and 1 <= delay <= 86400 else 30
        return DeliveryError(f'Telegram 요청 제한입니다. {delay}초 후 다시 시도하세요.', 'RATE_LIMIT', True, delay)
    migration = parameters.get('migrate_to_chat_id')
    if isinstance(migration, int) and migration < 0:
        return DeliveryError(f'그룹이 업그레이드되어 ID가 변경되었습니다. Chat ID를 {migration}로 바꾸세요.', 'MIGRATED')
    if code == 400 and 'chat not found' in description:
        return DeliveryError('그룹을 찾을 수 없습니다. 봇을 해당 그룹에 추가하고 그룹 찾기로 Chat ID를 다시 선택하세요.', 'CHAT_NOT_FOUND')
    if code == 403 or 'not enough rights' in description or 'chat_write_forbidden' in description:
        return DeliveryError('봇이 이 그룹에 전송할 권한이 없습니다. 봇의 그룹 참여 여부와 메시지·파일 전송 권한을 확인하세요.', 'FORBIDDEN')
    if code >= 500:
        return DeliveryError(f'Telegram 서버 오류 (HTTP {code}). 잠시 후 다시 시도하세요.', 'SERVER', True)
    return DeliveryError(f'Telegram 요청 오류 (HTTP {code}). 토큰 확인 후 수신 그룹을 다시 선택하세요.', 'API')


def network_error(error):
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return DeliveryError('TLS 인증서 검증 실패. PC 날짜·시간과 병원 프록시 인증서 구성을 확인하세요. 인증서 검증은 해제하지 않습니다.', 'TLS_CERT')
    if isinstance(reason, ssl.SSLError):
        return DeliveryError('TLS 연결 실패. 병원 네트워크의 Telegram HTTPS 연결 정책을 확인하세요.', 'TLS', True)
    if isinstance(reason, socket.gaierror):
        return DeliveryError('DNS 조회 실패: api.telegram.org 주소를 찾지 못했습니다. 인터넷·DNS 연결을 확인하세요.', 'DNS', True)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return DeliveryError('Telegram 응답 시간 초과. api.telegram.org:443 접속 가능 여부를 확인하세요. 전송 중이었다면 그룹에 도착했는지도 확인하세요.', 'TIMEOUT', True)
    return DeliveryError('Telegram HTTPS 연결 실패. api.telegram.org:443 접속이 차단되었거나 연결이 끊겼습니다. 병원 네트워크·프록시 설정을 확인하세요.', 'NETWORK', True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Telegram:
    def __init__(self, token, chat_id=None):
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token.strip()):
            raise ValueError('BotFather에서 받은 봇 토큰 형식을 확인하세요.')
        if chat_id is not None and not re.fullmatch(r'-\d+', chat_id.strip()):
            raise ValueError('비공개 그룹의 음수 Chat ID를 입력하세요.')
        self.token, self.chat_id = token.strip(), chat_id.strip() if chat_id is not None else None
        self.opener = urllib.request.build_opener(NoRedirect())

    def _call(self, method, data, content_type):
        request = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/{method}', data=data,
            headers={'Content-Type': content_type}, method='POST')
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise DeliveryError('Telegram 응답 형식이 다릅니다. 네트워크의 로그인 페이지·프록시를 확인하세요.', 'RESPONSE')
            if not result.get('ok'):
                raise api_error(result.get('error_code', 400), result.get('description', ''), result.get('parameters'))
            return result['result']
        except urllib.error.HTTPError as error:
            code = error.code
            try:
                payload = json.loads(error.read(65536))
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, OSError, AttributeError):
                payload = {}
            finally:
                error.close()
            raise api_error(code, payload.get('description', ''), payload.get('parameters')) from None
        except (urllib.error.URLError, OSError) as error:
            raise network_error(error) from None
        except (ValueError, KeyError, TypeError):
            raise DeliveryError('Telegram의 정상 JSON 응답을 받지 못했습니다. 네트워크 로그인·프록시를 확인하세요.', 'RESPONSE') from None

    def identity(self):
        return self._call('getMe', b'', 'application/x-www-form-urlencoded')

    def diagnose(self):
        bot = self.identity()
        webhook = self._call('getWebhookInfo', b'', 'application/x-www-form-urlencoded')
        name = str(bot.get('username', ''))
        if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
            name = '(확인됨)'
        info = f'Telegram 서버 연결·토큰 인증 정상: @{name}.'
        if webhook.get('url'):
            return info + ' 웹훅 사용 중: 그룹 찾기는 불가능합니다. 기존 연동을 유지하려면 Chat ID를 직접 입력하세요.'
        return info + f' 그룹에 봇을 추가하고 /start@{name} 을 보낸 뒤 그룹 찾기를 누르세요.'

    def test(self):
        if self.chat_id is None:
            raise ValueError('먼저 수신 그룹을 선택하세요.')
        # No patient information is used by this explicitly invoked test.
        return self._call('sendMessage', urllib.parse.urlencode({
            'chat_id': self.chat_id, 'text': '수술방 알림봇 연결 테스트 — 환자정보 없는 테스트 메시지입니다.',
            'protect_content': 'true'}).encode(), 'application/x-www-form-urlencoded')

    def groups(self):
        self.identity()
        info = self._call('getWebhookInfo', b'', 'application/x-www-form-urlencoded')
        if info.get('url'):
            raise api_error(409, 'webhook')
        updates = self._call('getUpdates', b'timeout=0', 'application/x-www-form-urlencoded')
        found = {}
        for update in updates:
            for field in ('message', 'my_chat_member'):
                chat = update.get(field, {}).get('chat', {})
                if chat.get('type') in ('group', 'supergroup'):
                    found[str(chat['id'])] = chat.get('title', '그룹')
        return found

    def send_capture(self, image, caption, silent=False):
        if self.chat_id is None:
            raise ValueError('먼저 수신 그룹을 선택하세요.')
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
