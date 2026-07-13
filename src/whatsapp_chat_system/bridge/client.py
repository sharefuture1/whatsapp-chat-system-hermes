from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse

import requests


class BridgeError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {'code': self.code, 'message': self.message, 'retryable': self.retryable}


class BridgeClient:
    def __init__(
        self,
        *,
        base_url: str = 'http://127.0.0.1:3100',
        internal_token: str,
        connect_timeout: float = 2.0,
        read_timeout: float = 10.0,
        session: requests.Session | None = None,
        allow_external_host: bool = False,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('invalid bridge URL')
        if not allow_external_host and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('bridge URL must use a loopback host')
        if not internal_token:
            raise ValueError('internal token is required')
        self.base_url = base_url.rstrip('/')
        self.internal_token = internal_token
        self.timeout = (connect_timeout, read_timeout)
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f'{self.base_url}{path}',
                json=json,
                headers={'X-Internal-Token': self.internal_token},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise BridgeError('bridge_timeout', 'Bridge request timed out', retryable=True) from exc
        except requests.ConnectionError as exc:
            raise BridgeError('bridge_unavailable', 'Bridge is unavailable', retryable=True) from exc
        except requests.RequestException as exc:
            raise BridgeError('bridge_request_failed', 'Bridge request failed', retryable=True) from exc

        payload: dict[str, Any]
        try:
            decoded = response.json()
            payload = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            payload = {}

        if expected is None:
            expected = {200}
        if response.status_code in expected:
            return payload

        error = payload.get('error') if isinstance(payload.get('error'), dict) else {}
        remote_code = str(error.get('code') or '')
        message = str(error.get('message') or payload.get('detail') or 'Bridge request failed')
        if response.status_code == 410 and remote_code == 'qr_expired':
            raise BridgeError('qr_expired', message or 'QR code expired', retryable=True, status_code=410)
        if response.status_code == 401:
            raise BridgeError('bridge_unauthorized', message, retryable=False, status_code=502)
        if response.status_code == 503:
            raise BridgeError('bridge_unavailable', message, retryable=True, status_code=503)
        raise BridgeError(remote_code or 'bridge_error', message, retryable=response.status_code >= 500)

    @staticmethod
    def _account_path(account_id: str) -> str:
        return quote(account_id, safe='')

    def create_account(self, account_id: str, session_ref: str) -> dict[str, Any]:
        return self._request('POST', '/accounts', json={'account_id': account_id, 'session_ref': session_ref})

    def list_accounts(self) -> dict[str, Any]:
        return self._request('GET', '/accounts')

    def connect(self, account_id: str) -> dict[str, Any]:
        return self._request('POST', f'/accounts/{self._account_path(account_id)}/connect', expected={200, 202})

    def status(self, account_id: str) -> dict[str, Any]:
        return self._request('GET', f'/accounts/{self._account_path(account_id)}/status')

    def qr(self, account_id: str) -> dict[str, Any]:
        return self._request('GET', f'/accounts/{self._account_path(account_id)}/qr')

    def logout(self, account_id: str) -> dict[str, Any]:
        return self._request('POST', f'/accounts/{self._account_path(account_id)}/logout')

    def stop(self, account_id: str) -> dict[str, Any]:
        return self._request('POST', f'/accounts/{self._account_path(account_id)}/stop', expected={200, 202})

    def delete(self, account_id: str, *, delete_session: bool = False) -> dict[str, Any]:
        suffix = '?delete_session=true' if delete_session else '?delete_session=false'
        return self._request('DELETE', f'/accounts/{self._account_path(account_id)}{suffix}')

    def send(
        self,
        account_id: str,
        *,
        chat_id: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body = {'chat_id': chat_id, 'text': text}
        if idempotency_key:
            body['idempotency_key'] = idempotency_key
        payload = self._request(
            'POST',
            f'/accounts/{self._account_path(account_id)}/send',
            json=body,
        )
        message_id = payload.get('message_id')
        if payload.get('success') is not True or not isinstance(message_id, str) or not message_id.strip():
            raise BridgeError(
                'missing_message_id',
                'Bridge response did not include a real WhatsApp message ID',
                retryable=True,
            )
        return payload
