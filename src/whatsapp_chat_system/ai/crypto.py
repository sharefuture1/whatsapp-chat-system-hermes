"""
认证加密：使用 Fernet（AES-128-CBC + HMAC）对 API 密钥进行加密存储。

主密钥来源优先级：
  1. 环境变量 AI_SECRET_ENCRYPTION_KEY（推荐，Secret Manager 注入）
  2. 环境变量 AI_SECRET_ENCRYPTION_KEY_FILE 指定的密钥文件
  3. 运行目录下的 .ai_encryption_key，不存在则自动生成并落盘（仅开发）

规则（SDD DATA-006.1）：
- 使用 Fernet.generate_key() 生成，不可自行 Base64/哈希伪造
- 密文禁止出现在日志、API 响应、Git 中
- 解密失败不抛详细错误，防止填充预言攻击
"""

from __future__ import annotations

import logging
import os
import stat
import threading
from base64 import urlsafe_b64decode
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEY_FILENAME = ".ai_encryption_key"
_KEY_BYTES = 32


class InvalidEncryptionKeyError(ValueError):
    """主密钥格式非法（不是合法的 Fernet key）。"""


def _state_dir() -> Path:
    """运行目录，与 RuntimePaths 保持一致的解析顺序。

    优先 CHAT_SYSTEM_RUNTIME_DIR（部署脚本与 systemd 使用），
    其次 STATE_DIR（历史变量），最后回落到当前目录下的 ./data。
    """

    for name in ("CHAT_SYSTEM_RUNTIME_DIR", "STATE_DIR"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw).expanduser()
    return Path("./data")


def _default_key_path() -> Path:
    override = (os.environ.get("AI_SECRET_ENCRYPTION_KEY_FILE") or "").strip()
    if override:
        return Path(override).expanduser()
    return _state_dir() / _KEY_FILENAME


def _validate_key(raw: bytes | str) -> str:
    """校验并归一化主密钥。

    合法的 Fernet key 是 32 字节、URL-safe Base64 编码后的 44 字符字符串。
    这里显式校验，避免历史上「无论是否 base64 都直接返回」的静默降级。
    """

    if isinstance(raw, str):
        candidate = raw.strip()
        if not candidate:
            raise InvalidEncryptionKeyError("encryption key is empty")
        return _validate_key(candidate.encode("ascii", errors="strict"))

    candidate = raw.strip()
    # 兼容带尾部换行的密钥文件
    decoded: bytes
    try:
        decoded = urlsafe_b64decode(candidate)
    except Exception as exc:  # noqa: BLE001 - 转为明确的领域异常
        raise InvalidEncryptionKeyError(
            "encryption key is not valid URL-safe Base64"
        ) from exc
    if len(decoded) != _KEY_BYTES:
        raise InvalidEncryptionKeyError(
            f"encryption key must decode to {_KEY_BYTES} bytes, got {len(decoded)}"
        )
    normalized = candidate.decode("ascii")
    # 交给 Fernet 做最终校验，确保两个实现判断一致
    Fernet(normalized.encode("ascii"))
    return normalized


def _restrict_permissions(path: Path) -> None:
    """尽力把密钥文件权限收紧到 0600。

    Windows 不支持 POSIX 权限位，chmod 只会切换只读标志，因此这里
    在非 POSIX 平台静默跳过，避免启动直接失败。
    """

    if os.name != "posix":
        return
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != 0o600:
            os.chmod(path, 0o600)
    except OSError as exc:  # noqa: PERF203 - 权限收紧失败不应阻断启动
        logger.warning(
            "Unable to restrict permissions on encryption key file",
            extra={"path": str(path), "error": str(exc)},
        )


def _load_or_generate_key(key_path: Path | None = None) -> str:
    """加载主密钥，不存在则自动生成并持久化。"""

    path = key_path or _default_key_path()
    if path.exists():
        return _validate_key(path.read_bytes())

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    # 先建文件再写内容，创建时即使用 0600，避免出现权限窗口
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    _restrict_permissions(path)
    logger.warning(
        "Generated a new AI encryption key. Persist it or set "
        "AI_SECRET_ENCRYPTION_KEY, otherwise previously stored API keys "
        "become undecryptable if this file is lost.",
        extra={"path": str(path)},
    )
    return key.decode("ascii")


_fernet_cache: Fernet | None = None
_fernet_lock = threading.Lock()


def _build_fernet() -> Fernet:
    raw_key = (os.environ.get("AI_SECRET_ENCRYPTION_KEY") or "").strip()
    if raw_key:
        try:
            return Fernet(_validate_key(raw_key).encode("ascii"))
        except InvalidEncryptionKeyError as exc:
            # 显式报错优于静默使用错误密钥（会导致全部密文解不开）
            raise InvalidEncryptionKeyError(
                "AI_SECRET_ENCRYPTION_KEY is not a valid Fernet key"
            ) from exc
    return Fernet(_load_or_generate_key().encode("ascii"))


def _get_fernet() -> Fernet:
    global _fernet_cache
    if _fernet_cache is None:
        with _fernet_lock:
            if _fernet_cache is None:
                _fernet_cache = _build_fernet()
    return _fernet_cache


def reset_cache() -> None:
    """清除缓存的主密钥，供测试或密钥轮换后调用。"""

    global _fernet_cache
    with _fernet_lock:
        _fernet_cache = None


def encrypt_api_key(plaintext: str) -> str:
    """对明文 API 密钥进行认证加密，返回 URL-safe Base64 密文。"""

    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    """解密密文，失败返回空字符串（不在异常中泄露原因）。"""

    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, InvalidEncryptionKeyError, ValueError):
        return ""


def mask_api_key(plaintext: str | None) -> str | None:
    """返回仅尾号提示，如 '***abc123'。"""

    if not plaintext:
        return None
    stripped = plaintext.strip()
    if len(stripped) <= 4:
        return f"***{stripped}"
    return f"***{stripped[-6:]}"
