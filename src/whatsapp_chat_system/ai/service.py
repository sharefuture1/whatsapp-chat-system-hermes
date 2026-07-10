from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from ..settings import AISettings
from .provider import AIProvider, AIProviderError, AIResult


@dataclass(frozen=True, slots=True)
class ModelResolution:
    model: str
    source: str


@dataclass(frozen=True, slots=True)
class AIServiceResult:
    result: AIResult
    model_resolution: ModelResolution


class AIService:
    """解析有效模型、调用统一 Provider，并记录不含消息/密钥的安全审计。"""

    def __init__(
        self,
        provider: AIProvider,
        settings: AISettings,
        *,
        audit_logger: Callable[..., None] | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.audit_logger = audit_logger

    def resolve_model(
        self,
        *,
        contact_model: str | None = None,
        account_model: str | None = None,
    ) -> ModelResolution:
        contact = (contact_model or '').strip()
        if contact:
            return ModelResolution(contact, 'contact_override')
        account = (account_model or '').strip()
        if account:
            return ModelResolution(account, 'account_profile')
        return ModelResolution(self.settings.default_model, 'global_default')

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        contact_model: str | None = None,
        account_model: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> AIServiceResult:
        resolution = self.resolve_model(contact_model=contact_model, account_model=account_model)
        started = monotonic()
        try:
            result = self.provider.chat(
                model=resolution.model,
                messages=messages,
                response_format=response_format,
                temperature=temperature,
            )
        except AIProviderError as exc:
            self._audit(
                request_id=exc.request_id,
                resolution=resolution,
                latency_ms=max(0, int((monotonic() - started) * 1000)),
                status='failed',
                usage={},
                error_code=exc.code,
                retryable=exc.retryable,
            )
            raise
        self._audit(
            request_id=result.request_id,
            resolution=resolution,
            latency_ms=result.latency_ms,
            status='success',
            usage=result.usage,
            error_code=None,
            retryable=None,
        )
        return AIServiceResult(result=result, model_resolution=resolution)

    def _audit(
        self,
        *,
        request_id: str | None,
        resolution: ModelResolution,
        latency_ms: int,
        status: str,
        usage: dict[str, Any],
        error_code: str | None,
        retryable: bool | None,
    ) -> None:
        if self.audit_logger is None:
            return
        self.audit_logger(
            'ai_request_audit',
            provider='wendingai',
            request_id=request_id,
            effective_model=resolution.model,
            model_source=resolution.source,
            latency_ms=latency_ms,
            status=status,
            usage=usage,
            error_code=error_code,
            retryable=retryable,
        )
