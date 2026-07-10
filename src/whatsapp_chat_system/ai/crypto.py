"""
认证加密：使用 Fernet（AES-128-CBC + HMAC）对 API 密钥进行加密存储。

主密钥来源优先级：
  1. 环境变量 AI_SECRET_ENCRYPTION_KEY（推荐，Secret Manager 注入）
  2. 首次启动自动生成写入本地文件（仅用于本地开发）

规则（SDD DATA-006.1）：
- 使用 Fernet.generate_key() 生成，不可自行 Base64/哈希伪造
- 密文禁止出现在日志、API 响应、Git 中
- 解密失败不抛详细错误，防止填充预言攻击
"""

from __future__ import annotations

import os
import secrets
from base64 import b64encode, b64decode
from pathlib import Path

from cryptography.fernet import Fernet


def _default_key_path() -> Path:
    state_dir = Path(os.environ.get('STATE_DIR', './data'))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / '.ai_encryption_key'


def _load_or_generate_key(key_path: Path | None = None) -> FernetKey:
    """加载主密钥，不存在则自动生成并持久化（仅开发模式）。"""
    path = key_path or _default_key_path()
    if path.exists():
        raw = path.read_bytes()
        # 支持直接存储原始 key 或 b64encode 后的
        try:
            b64decode(raw)
            return raw.decode()
        except Exception:
            return raw.decode()
    # 生成新密钥
    key = Fernet.generate_key()
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key.decode()


_fernet_cache: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_cache
    if _fernet_cache is None:
        raw_key = os.environ.get('AI_SECRET_ENCRYPTION_KEY', '').strip()
        if raw_key:
            # 用户提供的主密钥（来自 Secret Manager）
            _fernet_cache = Fernet(raw_key.encode())
        else:
            # 本地开发模式：从文件加载或自动生成
            _fernet_cache = Fernet(_load_or_generate_key().encode())
    return _fernet_cache


def encrypt_api_key(plaintext: str) -> str:
    """对明文 API 密钥进行认证加密，返回 URL-safe Base64 密文。"""
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """解密密文，失败返回空字符串（不在异常中泄露原因）。"""
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ''


def mask_api_key(plaintext: str | None) -> str | None:
    """返回仅尾号提示，如 '***abc123'。"""
    if not plaintext:
        return None
    stripped = plaintext.strip()
    if len(stripped) <= 4:
        return f'***{stripped}'
    return f'***{stripped[-6:]}'
