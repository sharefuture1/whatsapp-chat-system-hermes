"""ai/crypto 主密钥加载、加解密与失败降级的行为契约。"""

from __future__ import annotations

import os
import stat

import pytest
from cryptography.fernet import Fernet

from whatsapp_chat_system.ai import crypto


@pytest.fixture(autouse=True)
def _isolated_key_env(tmp_path, monkeypatch):
    """每个用例都在独立运行目录内，且不继承宿主的密钥配置。"""

    monkeypatch.setenv("CHAT_SYSTEM_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("STATE_DIR", raising=False)
    monkeypatch.delenv("AI_SECRET_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AI_SECRET_ENCRYPTION_KEY_FILE", raising=False)
    crypto.reset_cache()
    yield
    crypto.reset_cache()


def test_roundtrip_with_auto_generated_key(tmp_path):
    ciphertext = crypto.encrypt_api_key("sk-live-abcdef123456")

    assert ciphertext != "sk-live-abcdef123456"
    assert crypto.decrypt_api_key(ciphertext) == "sk-live-abcdef123456"
    assert (tmp_path / ".ai_encryption_key").exists()


def test_auto_generated_key_file_is_owner_only(tmp_path):
    crypto.encrypt_api_key("sk-live-abcdef123456")

    mode = stat.S_IMODE((tmp_path / ".ai_encryption_key").stat().st_mode)
    assert mode == 0o600


def test_generated_key_survives_cache_reset(tmp_path):
    ciphertext = crypto.encrypt_api_key("sk-live-abcdef123456")

    # 模拟进程重启：清缓存后应能从文件重新加载同一把密钥
    crypto.reset_cache()

    assert crypto.decrypt_api_key(ciphertext) == "sk-live-abcdef123456"


def test_env_key_takes_priority_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())

    ciphertext = crypto.encrypt_api_key("sk-from-env")

    assert crypto.decrypt_api_key(ciphertext) == "sk-from-env"
    # 使用显式密钥时不应再落盘生成密钥文件
    assert not (tmp_path / ".ai_encryption_key").exists()


def test_explicit_key_file_path_is_honoured(tmp_path, monkeypatch):
    custom = tmp_path / "nested" / "secret.key"
    monkeypatch.setenv("AI_SECRET_ENCRYPTION_KEY_FILE", str(custom))

    crypto.encrypt_api_key("sk-custom-path")

    assert custom.exists()


def test_invalid_env_key_raises_instead_of_silently_degrading(monkeypatch):
    """回归：历史实现无论密钥是否合法都返回明文，导致「加密」形同虚设。"""

    monkeypatch.setenv("AI_SECRET_ENCRYPTION_KEY", "not-a-valid-fernet-key")

    with pytest.raises(crypto.InvalidEncryptionKeyError):
        crypto.encrypt_api_key("sk-live-abcdef123456")


def test_decrypt_never_raises_on_corrupt_input():
    """解密失败必须静默返回空串，避免填充预言攻击。"""

    assert crypto.decrypt_api_key("not-a-token") == ""
    assert crypto.decrypt_api_key("") == ""


def test_decrypt_returns_empty_when_key_changes(tmp_path, monkeypatch):
    ciphertext = crypto.encrypt_api_key("sk-live-abcdef123456")

    # 换一把主密钥后，旧密文应解不开且不抛异常
    crypto.reset_cache()
    monkeypatch.setenv("AI_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())

    assert crypto.decrypt_api_key(ciphertext) == ""


def test_empty_plaintext_encrypts_to_empty_string():
    assert crypto.encrypt_api_key("") == ""


@pytest.mark.parametrize(
    ("plaintext", "expected"),
    [
        ("sk-abcdef123456", "***123456"),
        ("abcd", "***abcd"),
        ("", None),
        (None, None),
    ],
)
def test_mask_api_key(plaintext, expected):
    assert crypto.mask_api_key(plaintext) == expected


def test_key_file_trailing_newline_is_tolerated(tmp_path):
    """密钥文件常由编辑器写入并带尾换行，必须能正常解析。"""

    key = Fernet.generate_key().decode()
    (tmp_path / ".ai_encryption_key").write_bytes((key + "\n").encode())

    ciphertext = crypto.encrypt_api_key("sk-live-abcdef123456")

    assert crypto.decrypt_api_key(ciphertext) == "sk-live-abcdef123456"


def test_state_dir_used_when_runtime_dir_absent(tmp_path, monkeypatch):
    """CHAT_SYSTEM_RUNTIME_DIR 缺失时应回落到 STATE_DIR。"""

    monkeypatch.delenv("CHAT_SYSTEM_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))

    crypto.encrypt_api_key("sk-live-abcdef123456")

    assert (tmp_path / "state" / ".ai_encryption_key").exists()


def test_crypto_module_does_not_reference_hermes():
    """主密钥解析不得依赖任何 legacy 环境变量。"""

    source = os.path.join(os.path.dirname(crypto.__file__), "crypto.py")
    with open(source, encoding="utf-8") as handle:
        assert "hermes" not in handle.read().lower()
