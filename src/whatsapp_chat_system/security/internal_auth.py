"""内部事件接口（WhatsApp Bridge → API）的鉴权。

原有实现只有静态共享 token，一旦泄露即可注入任意事件，且没有时效性，
抓包得到的请求可以无限期重放。这里在保留静态 token 的前提下，
增加可选（推荐开启）的 HMAC-SHA256 请求签名：

    X-Internal-Token:     <shared token>          # 保持向后兼容
    X-Internal-Timestamp: <unix seconds>          # 签名时效
    X-Internal-Signature: <hex hmac-sha256>       # 签名
    X-Internal-Nonce:     <任意随机串，可选>       # 重放去重

签名口径：hmac_sha256(secret, f"{timestamp}.{raw_body}") 的十六进制摘要。
把 timestamp 纳入签名范围，避免签名本身被长期复用。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# 允许的时钟偏移；Bridge 与 API 不同机部署时应确保 NTP 同步
DEFAULT_MAX_SKEW_SECONDS = 300

# 时间戳不得比签名有效窗口更超前，防止构造未来时间戳延长重放窗口


class InternalAuthError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class InternalAuthHeaders:
    """从请求头提取出的鉴权字段。"""

    token: str | None = None
    timestamp: str | None = None
    signature: str | None = None
    nonce: str | None = None


@dataclass
class ReplayGuard:
    """单进程内的 nonce 去重窗口。

    多进程/多实例部署下各进程各有一份，因此这只是纵深防御的一层：
    真正的幂等由 event_id 唯一约束保证。nonce 的价值在于拦截
    「请求体校验失败、未被记账」的那些被捕获请求的重放。
    """

    ttl_seconds: float = DEFAULT_MAX_SKEW_SECONDS
    max_entries: int = 10_000
    _seen: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _clock: Callable[[], float] = time.monotonic

    def check_and_record(self, nonce: str) -> bool:
        """返回 True 表示首次出现；False 表示在窗口内重复。"""

        if not nonce:
            return True
        now = self._clock()
        with self._lock:
            self._evict(now)
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            return True

    def _evict(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        expired = [key for key, seen_at in self._seen.items() if seen_at < cutoff]
        for key in expired:
            self._seen.pop(key, None)
        # 兜底：异常流量导致窗口内条目过多时，丢弃最早的一半
        if len(self._seen) > self.max_entries:
            ordered = sorted(self._seen.items(), key=lambda item: item[1])
            for key, _ in ordered[: len(ordered) // 2]:
                self._seen.pop(key, None)


def verify_internal_token(configured_token: str, presented_token: str | None) -> None:
    if not configured_token:
        raise InternalAuthError(
            'internal_events_not_configured',
            'WhatsApp internal event token is not configured',
            status_code=503,
        )
    if not presented_token or not secrets.compare_digest(configured_token, presented_token):
        raise InternalAuthError('invalid_internal_token', 'Invalid internal token', status_code=401)


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """计算请求签名，供 API 校验与 Bridge 生成时共用。"""

    mac = hmac.new(
        secret.encode('utf-8'),
        f'{timestamp}.'.encode('utf-8') + body,
        hashlib.sha256,
    )
    return mac.hexdigest()


def verify_request_signature(
    *,
    secret: str,
    headers: InternalAuthHeaders,
    body: bytes,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    replay_guard: ReplayGuard | None = None,
    now: float | None = None,
) -> None:
    """校验 HMAC 签名、时间戳窗口与 nonce 唯一性。"""

    if not secret:
        raise InternalAuthError(
            'internal_signature_not_configured',
            'WhatsApp internal event signature secret is not configured',
            status_code=503,
        )
    if not headers.timestamp or not headers.signature:
        raise InternalAuthError(
            'missing_signature',
            'Missing internal request signature',
            status_code=401,
        )

    try:
        presented_at = float(headers.timestamp)
    except (TypeError, ValueError) as exc:
        raise InternalAuthError(
            'invalid_timestamp', 'Invalid internal request timestamp', status_code=401
        ) from exc

    current = time.time() if now is None else now
    skew = current - presented_at
    # 同时拒绝过于超前与过于滞后的时间戳
    if abs(skew) > max_skew_seconds:
        raise InternalAuthError(
            'stale_signature',
            'Internal request timestamp is outside the allowed window',
            status_code=401,
        )

    expected = compute_signature(secret, headers.timestamp, body)
    if not secrets.compare_digest(expected, headers.signature):
        raise InternalAuthError(
            'invalid_signature', 'Invalid internal request signature', status_code=401
        )

    if replay_guard is not None and headers.nonce:
        if not replay_guard.check_and_record(headers.nonce):
            raise InternalAuthError(
                'replayed_request', 'Internal request nonce was already used',
                status_code=401,
            )


def verify_internal_request(
    *,
    configured_token: str,
    headers: InternalAuthHeaders,
    body: bytes = b'',
    hmac_secret: str | None = None,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    replay_guard: ReplayGuard | None = None,
    now: float | None = None,
) -> None:
    """统一入口：始终校验静态 token；配置了密钥时叠加签名校验。"""

    verify_internal_token(configured_token, headers.token)
    secret = (hmac_secret or '').strip()
    if not secret:
        # 未配置签名密钥时保持旧行为，但显式告警以便运维启用
        logger.warning(
            'Internal event endpoint is running without HMAC signature verification; '
            'set WHATSAPP_BRIDGE_HMAC_SECRET to enable replay-resistant auth'
        )
        return
    verify_request_signature(
        secret=secret,
        headers=headers,
        body=body,
        max_skew_seconds=max_skew_seconds,
        replay_guard=replay_guard,
        now=now,
    )
