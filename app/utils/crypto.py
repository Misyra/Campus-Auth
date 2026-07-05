"""密码加密存储工具。

使用 Fernet 对称加密保护密码字段。
加密密钥存储在用户目录 ~/.campus_network_auth/ 下，与项目配置物理隔离。
加密后的密码以 ENC: 前缀标记，兼容明文密码读取（向后兼容）。
"""

import base64
import getpass
import hashlib
import os
import threading
import time

from app.constants import AUTH_DATA_DIR

from .files import atomic_write
from .logging import get_logger
from .platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("crypto", source="backend")


class _DecryptionError(Exception):
    """密码解密失败异常（密钥变更或数据损坏）"""


_KEY_DIR = AUTH_DATA_DIR
_KEY_FILE = _KEY_DIR / ".enc_key"
_ENC_PREFIX = "ENC:"

_cached_raw_key: bytes | None = None
_cached_fernet_key: bytes | None = None
_decryption_failed = threading.Event()
_key_lock = threading.RLock()

# 一次性告警标志：cryptography 缺失时避免重复刷日志
_crypto_missing_warned = False
_crypto_missing_decrypt_warned = False


def _backup_key_file() -> None:
    """备份密钥文件（密钥损坏或长度异常时调用）"""
    backup_path = _KEY_FILE.with_suffix(f".bak.{int(time.time())}")
    try:
        _KEY_FILE.rename(backup_path)
        logger.info("备份密钥文件成功: {}", backup_path)
    except FileNotFoundError:
        pass
    except OSError as backup_err:
        logger.warning("备份密钥文件失败: {}", backup_err)


def _get_or_create_key() -> bytes:
    """获取或创建加密密钥（Fernet 要求 32 字节 base64 编码的密钥）"""
    global _cached_raw_key
    if _cached_raw_key is not None:
        return _cached_raw_key

    with _key_lock:
        if _cached_raw_key is not None:
            return _cached_raw_key

        _KEY_DIR.mkdir(parents=True, exist_ok=True)

        if _KEY_FILE.exists():
            try:
                key = base64.urlsafe_b64decode(
                    _KEY_FILE.read_text(encoding="utf-8").strip()
                )
                if len(key) == 32:
                    _cached_raw_key = key
                    return key
                else:
                    logger.warning(
                        "密钥文件长度异常: 期望 32 字节，实际 {} 字节", len(key)
                    )
                    _backup_key_file()
            except Exception as exc:
                logger.warning("读取加密密钥失败: {}", exc)
                _backup_key_file()
                logger.warning(
                    "将生成新密钥，此前保存的密码将无法自动恢复，请重新输入密码"
                )

        # 生成新密钥
        key = os.urandom(32)
        encoded_key = base64.urlsafe_b64encode(key).decode("ascii")
        atomic_write(str(_KEY_FILE), encoded_key, encoding="utf-8")

        try:
            _KEY_FILE.chmod(0o600)  # POSIX: 仅所有者可读写
        except OSError:
            logger.warning("设置密钥文件权限失败 (chmod): {}", _KEY_FILE, exc_info=True)

        # Windows: 用 icacls 限制文件访问
        if is_windows():
            try:
                import subprocess

                username = os.environ.get("USERNAME") or getpass.getuser()
                # 域环境用户名格式为 DOMAIN\user，icacls 只需用户名部分
                username = username.split("\\")[-1]
                subprocess.run(
                    [
                        "icacls",
                        str(_KEY_FILE),
                        "/inheritance:r",
                        "/grant",
                        f"{username}:F",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=CREATE_NO_WINDOW_FLAG,
                    check=True,
                )
            except subprocess.TimeoutExpired:
                logger.warning("设置密钥文件权限超时 (icacls)")
            except Exception as exc:
                logger.warning("设置密钥文件权限失败 (icacls): {}", exc)

        _cached_raw_key = key
        return key


def _derive_fernet_key() -> bytes:
    """从原始密钥派生 Fernet 兼容的密钥（32 字节 URL-safe base64 编码）"""
    global _cached_fernet_key
    if _cached_fernet_key is not None:
        return _cached_fernet_key

    with _key_lock:
        if _cached_fernet_key is not None:
            return _cached_fernet_key

        raw_key = _get_or_create_key()
        # Fernet 密钥格式：32 字节原始数据（16 签名 + 16 加密）→ URL-safe base64 编码 → 44 字符字符串
        signing_key = hashlib.sha256(raw_key + b":signing").digest()[:16]
        encryption_key = hashlib.sha256(raw_key + b":encryption").digest()[:16]
        _cached_fernet_key = base64.urlsafe_b64encode(signing_key + encryption_key)
        return _cached_fernet_key


def encrypt_password(plaintext: str) -> str:
    """加密密码，返回 ENC: 前缀的密文字符串"""
    global _crypto_missing_warned, _crypto_missing_decrypt_warned
    if not plaintext:
        return ""

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        # cryptography 是 pyproject.toml 中的必需依赖（uv sync 会自动安装），
        # 正常部署下不可能缺失。此分支仅作为极端防御（如手动删除 .venv 中的包）。
        # 密码以明文写入 settings.json，已有 warning 日志提示用户。
        with _key_lock:
            if not _crypto_missing_warned:
                logger.warning(
                    "cryptography 库未安装，密码将以明文存储，"
                    "建议通过 uv add cryptography 安装依赖以启用加密保护"
                )
                _crypto_missing_warned = True
        return plaintext

    # cryptography 可用，重置告警标志（依赖恢复后重新启用告警机制）
    with _key_lock:
        _crypto_missing_warned = False
        _crypto_missing_decrypt_warned = False

    key = _derive_fernet_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{encrypted.decode('ascii')}"


def decrypt_password(ciphertext: str) -> str:
    """解密密码。如果不是加密格式（无 ENC: 前缀），原样返回（向后兼容明文）"""
    global _crypto_missing_warned, _crypto_missing_decrypt_warned
    if not ciphertext:
        return ""

    if not ciphertext.startswith(_ENC_PREFIX):
        # 明文密码，直接返回（向后兼容）
        return ciphertext

    encrypted_data = ciphertext[len(_ENC_PREFIX) :]

    try:
        from cryptography.fernet import Fernet, InvalidToken

        # cryptography 可用，重置告警标志（依赖恢复后重新启用告警机制）
        with _key_lock:
            _crypto_missing_warned = False
            _crypto_missing_decrypt_warned = False

        key = _derive_fernet_key()
        f = Fernet(key)
        result = f.decrypt(encrypted_data.encode("ascii")).decode("utf-8")
        # 解密成功，清除之前的解密失败标记（按活跃方案粒度，避免误清其他方案）
        _clear_decryption_error()
        return result
    except ImportError:
        _decryption_failed.set()
        with _key_lock:
            if not _crypto_missing_decrypt_warned:
                logger.warning("cryptography 库未安装，无法解密密码，请安装依赖后重试")
                _crypto_missing_decrypt_warned = True
        raise _DecryptionError("cryptography 库未安装，无法解密密码") from None
    except (InvalidToken, ValueError, OSError) as e:
        # 解密失败：可能是密钥变更，记录错误并抛出异常
        _decryption_failed.set()
        logger.warning("密码解密失败: 可能是密钥变更或数据损坏，请重新输入密码")
        raise _DecryptionError("密码解密失败，请重新输入密码") from e


def has_decryption_error() -> bool:
    """检查是否有解密失败记录"""
    return _decryption_failed.is_set()


def _clear_decryption_error() -> None:
    """清除解密失败标记（重新输入密码后调用）"""
    _decryption_failed.clear()


def save_password_field(raw: str | None, existing_encrypted: str) -> str:
    """处理前端提交的密码。

    语义：
    - raw is None 或 "" → 不修改，返回 existing_encrypted
    - raw startswith "ENC:" → 已是加密值，原样返回
    - 其他（明文密码） → 加密后返回
    """
    if raw is None or raw == "":
        return existing_encrypted
    if raw.startswith("ENC:"):
        return raw
    return encrypt_password(raw)


def decrypt_password_field(
    raw_pwd: str,
    fallback_pwd: str = "",
    label: str = "",
) -> tuple[str, bool]:
    """解密密码字段，支持 ENC: 前缀和掩码回退。

    与 save_password_field 对称：save 处理写入加密，decrypt 处理读取解密。

    Args:
        raw_pwd: 存储的密码值（可能是 ENC:密文、掩码、明文或空）
        fallback_pwd: 回退密码（当 raw_pwd 为掩码或空时使用）
        label: 日志标签（如方案名称）

    Returns:
        (解密结果, 是否有错误)
    """
    if raw_pwd.startswith("ENC:"):
        try:
            return (decrypt_password(raw_pwd), False)
        except _DecryptionError as e:
            if label:
                logger.warning("{} 密码解密失败: {}", label, e)
            else:
                logger.warning("密码解密失败: {}", e)
            return ("", True)
    elif raw_pwd.startswith("•"):
        if fallback_pwd:
            try:
                return (decrypt_password(fallback_pwd), False)
            except _DecryptionError as e:
                if label:
                    logger.warning("{} 回退密码解密失败: {}", label, e)
                else:
                    logger.warning("回退密码解密失败: {}", e)
                return ("", True)
        else:
            if label:
                logger.warning("{} 密码为掩码但回退密码为空", label)
            return ("", False)
    elif raw_pwd:
        return (raw_pwd, False)
    else:
        if fallback_pwd:
            if label:
                logger.debug("{} 密码为空，使用回退密码", label)
            try:
                return (decrypt_password(fallback_pwd), False)
            except _DecryptionError as e:
                logger.warning("回退密码解密失败，使用空密码: {}", e)
                return ("", True)
        else:
            return ("", False)
