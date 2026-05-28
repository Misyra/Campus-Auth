"""脚本任务执行器 — 在子进程中执行 Python 脚本登录任务。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger("script_runner", side="BACKEND")

# 默认脚本超时（秒）
DEFAULT_TIMEOUT = 60


class ScriptRunner:
    """执行 Python 脚本任务。

    脚本通过环境变量接收登录参数，通过 stdout 输出 JSON 结果。

    环境变量：
        CAMPUS_USERNAME — 用户名
        CAMPUS_PASSWORD — 密码
        CAMPUS_ISP      — 运营商（可为空）
        CAMPUS_URL      — 认证地址

    输出格式：
        {"success": true, "message": "登录成功"}
        {"success": false, "message": "失败原因"}
    """

    def __init__(self, script_path: Path, timeout: int = DEFAULT_TIMEOUT):
        self.script_path = script_path
        self.timeout = timeout

    def run(self, env_vars: dict[str, str]) -> tuple[bool, str]:
        """执行脚本并返回 (success, message)。"""
        start = time.perf_counter()

        safe_env = self._build_safe_env(env_vars)

        try:
            result = subprocess.run(
                [sys.executable, str(self.script_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=safe_env,
                cwd=str(self.script_path.parent),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            logger.error("脚本执行超时 (%ds): %s", self.timeout, self.script_path)
            return False, f"脚本执行超时 ({self.timeout}s)"
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error("脚本执行异常 (%.1fs): %s", elapsed, e)
            return False, f"脚本执行异常: {e}"

        elapsed = time.perf_counter() - start

        # 记录 stderr（用于调试，不影响结果判断）
        if result.stderr.strip():
            logger.info("脚本 stderr: %s", result.stderr.strip()[:500])

        # 解析 stdout JSON 结果
        stdout = result.stdout.strip()
        if not stdout:
            logger.error("脚本无输出 (%.1fs), returncode=%d", elapsed, result.returncode)
            return False, f"脚本无输出 (exit code {result.returncode})"

        # 从 stdout 中提取 JSON 对象（从最后一行往前找）
        output = self._extract_json(stdout)
        if output is not None:
            success = bool(output.get("success", False))
            message = str(output.get("message", ""))
            if success:
                logger.info("脚本登录成功 (%.1fs): %s", elapsed, message)
            else:
                logger.warning("脚本登录失败 (%.1fs): %s", elapsed, message)
            return success, message

        # 无 JSON，从 returncode 推断
        logger.warning("脚本输出无 JSON (%.1fs): %s", elapsed, stdout[:200])
        if result.returncode == 0:
            return True, stdout[:500]
        return False, f"脚本输出解析失败: {stdout[:200]}"

    @staticmethod
    def _extract_json(stdout: str) -> dict | None:
        """从 stdout 中提取 JSON 对象（从最后一行往前找）。"""
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _build_safe_env(env_vars: dict[str, str]) -> dict[str, str]:
        """构建子进程安全环境变量。

        只传递 LOGIN_* 前缀的变量和基本系统变量，
        不泄露宿主进程的完整环境。
        """
        safe: dict[str, str] = {}
        # 基本系统变量（跨平台）
        for key in ("PATH", "SystemRoot", "TEMP", "TMP", "HOME", "USER", "ComSpec", "windir"):
            val = os.environ.get(key)
            if val:
                safe[key] = val
        # 登录相关变量 → 统一为 CAMPUS_ 前缀
        username = env_vars.get("USERNAME", "")
        password = env_vars.get("PASSWORD", "")
        isp = env_vars.get("ISP", "")
        login_url = env_vars.get("LOGIN_URL", "")
        if username:
            safe["CAMPUS_USERNAME"] = username
        if password:
            safe["CAMPUS_PASSWORD"] = password
        if isp:
            safe["CAMPUS_ISP"] = isp
        if login_url:
            safe["CAMPUS_URL"] = login_url
        # 确保 Python 输出编码正确
        safe["PYTHONIOENCODING"] = "utf-8"
        return safe
