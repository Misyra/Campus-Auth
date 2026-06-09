"""密码加密存储工具。

使用 Fernet 对称加密保护密码字段。
加密密钥存储在用户目录 ~/.campus_network_auth/ 下，与项目配置物理隔离。
加密后的密码以 ENC: 前缀标记，兼容明文密码读取（向后兼容）。
"""

import base64
import hashlib
import os
import threading
import time

from app.constants import AUTH_DATA_DIR

from .exceptions import DecryptionError
from .file_helpers import atomic_write
from .logging import get_logger
from .platform_utils import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("crypto", source="backend")

_KEY_DIR = AUTH_DATA_DIR
_KEY_FILE = _KEY_DIR / ".enc_key"
_ENC_PREFIX = "ENC:"

_cached_raw_key: bytes | None = None
_cached_fernet_key: bytes | None = None
_decryption_failed = threading.Event()
_key_lock = threading.RLock()


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
            except Exception as exc:
                logger.error("读取加密密钥失败: {}", exc)
                # 备份损坏的密钥文件
                if _KEY_FILE.exists():
                    backup_path = _KEY_FILE.with_suffix(f".bak.{int(time.time())}")
                    try:
                        _KEY_FILE.rename(backup_path)
                        logger.info("已备份损坏的密钥文件到: {}", backup_path)
                    except OSError as backup_err:
                        logger.warning("备份密钥文件失败: {}", backup_err)
                logger.warning("将生成新密钥，此前加密的密码将无法解密")

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

                username = os.environ.get("USERNAME", "Users")
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
    if not plaintext:
        return ""

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        # cryptography 未安装时回退到简单混淆（不推荐，但保证可用）
        logger.warning(
            "cryptography 库未安装，密码将使用 Base64 编码存储（非真正加密），"
            "建议安装 cryptography: pip install cryptography"
        )
        return _simple_obfuscate(plaintext)

    key = _derive_fernet_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    # 新密码加密成功，清除之前的解密失败标记
    clear_decryption_error()
    return f"{_ENC_PREFIX}{encrypted.decode('ascii')}"


def decrypt_password(ciphertext: str) -> str:
    """解密密码。如果不是加密格式（无 ENC: 前缀），原样返回（向后兼容明文）"""
    if not ciphertext:
        return ""

    if not ciphertext.startswith(_ENC_PREFIX):
        # 明文密码，直接返回（向后兼容）
        return ciphertext

    encrypted_data = ciphertext[len(_ENC_PREFIX) :]

    # B64: 前缀表示无 cryptography 时的简单混淆，优先路由避免 Fernet 错误
    if encrypted_data.startswith(_OBFUSCATE_PREFIX):
        return _simple_deobfuscate(encrypted_data)

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.fernet import Fernet, InvalidToken

        key = _derive_fernet_key()
        f = Fernet(key)
        return f.decrypt(encrypted_data.encode("ascii")).decode("utf-8")
    except ImportError:
        logger.warning("cryptography 库未安装，尝试 Base64 反混淆")
        return _simple_deobfuscate(encrypted_data)
    except (InvalidToken, InvalidSignature, ValueError, OSError) as e:
        # 解密失败：可能是密钥变更，记录错误并抛出异常
        _decryption_failed.set()
        logger.error(
            "密码解密失败（可能是密钥变更或数据损坏），请在设置页面重新输入密码"
        )
        raise DecryptionError("密码解密失败，请重新输入密码") from e


def is_encrypted(value: str) -> bool:
    """判断值是否已加密"""
    return bool(value and value.startswith(_ENC_PREFIX))


def has_decryption_error() -> bool:
    """检查是否有解密失败记录"""
    return _decryption_failed.is_set()


def clear_decryption_error() -> None:
    """清除解密失败标记（重新输入密码后调用）"""
    _decryption_failed.clear()


def mask_password(value: str) -> str:
    """密码脱敏：返回掩码用于前端显示"""
    if not value:
        return ""
    return "••••••••"  # 统一长度掩码，不泄露密码长度


def save_password_field(raw: str | None, existing_encrypted: str) -> str:
    """处理前端提交的密码：掩码保留原值，ENC 原样返回，明文加密存储。

    分支行为：
    - raw is None （字段未传）→ 静默返回 existing_encrypted（无日志）
    - raw == ""    （显式传空）→ 返回 existing_encrypted
      + existing_encrypted 为空 → 警告 + 返回 ""
      + existing_encrypted 有值 → 保留（无日志）
    - raw startswith "•" （掩码）→ 同 raw=="" 行为
    - raw startswith "ENC:" （已是加密值）→ 原样返回，不二次加密
    - 其他（明文密码） → encrypt_password(raw) 加密后返回

    Args:
        raw: 前端传来的原始值。None = 未传（静默），"" = 显式置空
        existing_encrypted: 数据库中已有的加密密码（ENC:xxx 或 ""）

    Returns:
        加密后的密码字符串（ENC: 前缀）或空字符串
    """
    if raw is None:
        # 未传密码 → 无操作，保留原值。不发警告（合法场景）
        return existing_encrypted or ""
    if raw == "" or raw.startswith("•"):
        # 显式置空或掩码 → 尝试保留已有密码
        if not existing_encrypted:
            logger.warning(
                "密码为空或掩码但无已有加密密码，密码将保持为空！",
            )
        return existing_encrypted or ""
    if raw.startswith("ENC:"):
        # 已是加密值（来自已保存的方案）→ 原样返回
        return raw
    # 明文密码 → 加密存储
    return encrypt_password(raw)


# ==================== 简单回退方案 ====================
# 当 cryptography 不可用时，使用 base64 混淆（非加密，仅防肉眼）

_OBFUSCATE_PREFIX = "B64:"


def _simple_obfuscate(plaintext: str) -> str:
    """简单 base64 混淆（非加密）"""
    encoded = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{_OBFUSCATE_PREFIX}{encoded}"


def _simple_deobfuscate(ciphertext: str) -> str:
    """简单 base64 反混淆"""
    if ciphertext.startswith(_OBFUSCATE_PREFIX):
        try:
            return base64.b64decode(ciphertext[len(_OBFUSCATE_PREFIX) :]).decode(
                "utf-8"
            )
        except Exception as e:
            _decryption_failed.set()
            logger.error("Base64 反混淆失败（数据损坏），请在设置页面重新输入密码")
            raise DecryptionError("密码解混淆失败，请重新输入密码") from e
    return ciphertext
