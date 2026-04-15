#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
密码加密存储工具

使用 Fernet 对称加密保护 .env 中的密码字段。
加密密钥存储在用户目录 ~/.campus_network_auth/ 下，与项目 .env 物理隔离。

加密后的密码以 ENC: 前缀标记，兼容明文密码读取（向后兼容）。
"""

import base64
import hashlib
import os
from pathlib import Path

_KEY_DIR = Path.home() / ".campus_network_auth"
_KEY_FILE = _KEY_DIR / ".enc_key"
_ENC_PREFIX = "ENC:"


def _get_or_create_key() -> bytes:
    """获取或创建加密密钥（Fernet 要求 32 字节 base64 编码的密钥）"""
    _KEY_DIR.mkdir(parents=True, exist_ok=True)

    if _KEY_FILE.exists():
        try:
            key = base64.urlsafe_b64decode(_KEY_FILE.read_text(encoding="utf-8").strip())
            if len(key) == 32:
                return key
        except Exception:
            pass

    # 生成新密钥
    key = os.urandom(32)
    _KEY_FILE.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")

    # 限制文件权限（仅当前用户可读写）
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass

    return key


def _derive_fernet_key() -> bytes:
    """从原始密钥派生 Fernet 兼容的密钥（32 字节 URL-safe base64 编码）"""
    raw_key = _get_or_create_key()
    # Fernet 密钥 = 32 字节 URL-safe base64 编码的字符串
    # 内部 = 16 字节 signing key + 16 字节 encryption key (共 32 字节 → base64 后 44 字符)
    signing_key = hashlib.sha256(raw_key + b":signing").digest()[:16]
    encryption_key = hashlib.sha256(raw_key + b":encryption").digest()[:16]
    return base64.urlsafe_b64encode(signing_key + encryption_key)


def encrypt_password(plaintext: str) -> str:
    """加密密码，返回 ENC: 前缀的密文字符串"""
    if not plaintext:
        return ""

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        # cryptography 未安装时回退到简单混淆（不推荐，但保证可用）
        return _simple_obfuscate(plaintext)

    key = _derive_fernet_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{encrypted.decode('ascii')}"


def decrypt_password(ciphertext: str) -> str:
    """解密密码。如果不是加密格式（无 ENC: 前缀），原样返回（向后兼容明文）"""
    if not ciphertext:
        return ""

    if not ciphertext.startswith(_ENC_PREFIX):
        # 明文密码，直接返回（向后兼容）
        return ciphertext

    encrypted_data = ciphertext[len(_ENC_PREFIX):]

    try:
        from cryptography.fernet import Fernet
        key = _derive_fernet_key()
        f = Fernet(key)
        return f.decrypt(encrypted_data.encode("ascii")).decode("utf-8")
    except ImportError:
        return _simple_deobfuscate(encrypted_data)
    except Exception:
        # 解密失败时回退：可能是密钥变更，返回原文
        return ciphertext


def is_encrypted(value: str) -> bool:
    """判断值是否已加密"""
    return bool(value and value.startswith(_ENC_PREFIX))


def mask_password(value: str) -> str:
    """密码脱敏：返回掩码用于前端显示"""
    if not value:
        return ""
    if is_encrypted(value):
        return "••••••••"  # 加密存储，不泄露长度
    # 明文密码，用等长点号掩码
    return "•" * min(len(value), 8)


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
            return base64.b64decode(ciphertext[len(_OBFUSCATE_PREFIX):]).decode("utf-8")
        except Exception:
            return ciphertext
    return ciphertext
