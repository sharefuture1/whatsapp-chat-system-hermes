from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep as default_sleep
from typing import Any, Callable, Protocol

import requests

from ..settings import AISettings


@dataclass(frozen=True, slots=True)
class AIResult:
    content: str
    model: str
    request_id: str | None
    usage: dict[str, Any]
    latency_ms: int


class AIProviderError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = request_id

    def as_dict(self) -> dict[str, Any]:
        return {
            'error': {
                'code': self.code,
                'message': str(self),
                'retryable': self.retryable,
                'request_id': self.request_id,
                'details': {'status_code': self.status_code} if self.status_code else {},
            }
        }


class AIProvider(Protocol):
    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> AIResult: ...


class WendingAIProvider:
    def __init__(
        self,
        settings: AISettings,
        *,
        session: Any | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self.settings = settings
        self._injected_session = session
        self.sleep = sleep

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> AIResult:
        if not self.settings.api_key.strip():
            raise AIProviderError(
                code='configuration_error',
                message='Wending AI API key is not configured',
                retryable=False,
            )
        if self.settings.timeout_seconds <= 0 or self.settings.max_retries < 0:
            raise AIProviderError(
                code='configuration_error',
                message='Wending AI settings are invalid',
                retryable=False,
            )

        payload: dict[str, Any] = {'model': model, 'messages': messages}
        if response_format is not None:
            payload['response_format'] = response_format
        if temperature is not None:
            payload['temperature'] = temperature

        started = monotonic()
        session = self._injected_session or requests.Session()
        owns_session = self._injected_session is None
        try:
            return self._chat_with_session(
                session,
                payload=payload,
                model=model,
                started=started,
            )
        finally:
            if owns_session:
                session.close()

    def _chat_with_session(
        self,
        session: Any,
        *,
        payload: dict[str, Any],
        model: str,
        started: float,
    ) -> AIResult:
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = session.post(
                    f"{self.settings.base_url.rstrip('/')}/chat/completions",
                    headers={
                        'Authorization': f'Bearer {self.settings.api_key}',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
            except requests.Timeout as exc:
                error = AIProviderError(
                    code='timeout',
                    message='Wending AI request timed out',
                    retryable=True,
                )
                if attempt < self.settings.max_retries:
                    self.sleep(_retry_delay(attempt))
                    continue
                raise error from exc
            except requests.RequestException as exc:
                raise AIProviderError(
                    code='connection_error',
                    message='Wending AI request failed',
                    retryable=False,
                ) from exc

            request_id = _request_id(response)
            if 200 <= response.status_code < 300:
                try:
                    data = response.json()
                    content = str(data['choices'][0]['message']['content'])
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise AIProviderError(
                        code='invalid_response',
                        message='Wending AI returned an invalid response',
                        retryable=False,
                        status_code=response.status_code,
                        request_id=request_id,
                    ) from exc
                return AIResult(
                    content=content,
                    model=str(data.get('model') or model),
                    request_id=str(data.get('id') or request_id or '') or None,
                    usage=data.get('usage') if isinstance(data.get('usage'), dict) else {},
                    latency_ms=max(0, int((monotonic() - started) * 1000)),
                )

            error = _http_error(response.status_code, request_id)
            if error.retryable and attempt < self.settings.max_retries:
                self.sleep(_retry_delay(attempt))
                continue
            raise error

        raise AssertionError('unreachable')


def _http_error(status_code: int, request_id: str | None) -> AIProviderError:
    if status_code == 401:
        return AIProviderError(
            code='authentication_error', message='Wending AI authentication failed',
            retryable=False, status_code=status_code, request_id=request_id,
        )
    if status_code == 429:
        return AIProviderError(
            code='rate_limited', message='Wending AI rate limit exceeded',
            retryable=True, status_code=status_code, request_id=request_id,
        )
    if status_code >= 500:
        return AIProviderError(
            code='upstream_error', message='Wending AI upstream service failed',
            retryable=True, status_code=status_code, request_id=request_id,
        )
    return AIProviderError(
        code='request_error', message=f'Wending AI request failed with HTTP {status_code}',
        retryable=False, status_code=status_code, request_id=request_id,
    )


def _request_id(response: Any) -> str | None:
    headers = getattr(response, 'headers', {}) or {}
    return headers.get('X-Request-ID') or headers.get('x-request-id')


def _retry_delay(attempt: int) -> float:
    return min(2.0, 0.25 * (2**attempt))
