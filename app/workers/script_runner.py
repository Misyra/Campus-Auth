"""自定义脚本执行器 — 在子进程中执行脚本任务。"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy

logger = get_logger("script_runner", source="backend")

# 默认脚本超时（秒）
DEFAULT_TIMEOUT = 60

# script_type → 临时文件后缀
_TEMP_EXT: dict[str, str] = {
    "py": ".py",
    "bat": ".bat",
    "ps1": ".ps1",
    "sh": ".sh",
}

# 文本脚本类型
_TEXT_TYPES = frozenset({"py", "bat", "ps1", "sh"})

# ShellCommandPolicy 允许的二进制列表
_ALLOWED_BINARIES: list[str] = [
    sys.executable,  # py
    "cmd.exe",  # bat (Windows)
    "powershell.exe",  # ps1 (Windows)
    "sh",  # sh (Unix)
]


class ScriptRunner:
    """执行自定义脚本任务。

    脚本自行硬编码账号密码等参数，通过 stdout 输出信息。
    成功与否由网络检测判断，脚本只需发请求。
    支持 .py 文件和 JSON 格式（包含 content 字段）。

    Args:
        script_path: 脚本文件路径（.json 或 .py）
        timeout: 脚本执行超时秒数
        script_type: 脚本类型，如 "py", "bat", "ps1", "sh", "exe"
        cancel_event: 可选的取消事件，设置后终止正在执行的子进程
    """

    def __init__(
        self,
        script_path: Path,
        timeout: int = DEFAULT_TIMEOUT,
        script_type: str = "py",
        cancel_event: threading.Event | None = None,
    ):
        self.script_path = script_path
        self.timeout = timeout
        self.script_type = script_type
        self._script_content: str | None = None
        self._cancel_event = cancel_event

    def _load_script_content(self) -> str | None:
        """从 JSON 文件加载脚本内容。

        .json 文件解析失败时抛出 ValueError，避免静默降级。
        非 JSON 文件返回 None。
        """
        if self._script_content is not None:
            return self._script_content

        if self.script_path.suffix.lower() == ".json":
            try:
                data = json.loads(self.script_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"JSON 脚本格式错误或编码不支持: {e}") from e
            self._script_content = data.get("content", "")
            return self._script_content

        return None

    def _load_exe_path(self) -> str:
        """从 JSON 文件读取 exe 的 path 字段。

        Raises:
            ValueError: JSON 格式错误或缺少 path 字段
        """
        try:
            data = json.loads(self.script_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"JSON 脚本格式错误或编码不支持: {e}") from e
        exe_path = data.get("path", "")
        if not exe_path:
            raise ValueError("JSON 中缺少 'path' 字段")
        return exe_path

    # 脚本类型 → 命令模板（{file} 为脚本路径占位符）
    _CMD_TEMPLATES: dict[str, list[str]] = {
        "py": [sys.executable, "{file}"],
        "bat": ["cmd.exe", "/c", "{file}"],
        "ps1": [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "{file}",
        ],
        "sh": ["sh", "{file}"],
    }

    def _build_cmd(self, script_file: str) -> list[str]:
        """根据 script_type 构建固定命令模板。"""
        tpl = self._CMD_TEMPLATES.get(self.script_type)
        if tpl is None:
            raise ValueError(f"不支持的 script_type: {self.script_type}")
        return [s.replace("{file}", script_file) for s in tpl]

    def _content_temp_file(self, content: str) -> str:
        """将脚本内容写入临时文件，返回文件路径。"""
        ext = _TEMP_EXT.get(self.script_type, "")
        tf = tempfile.NamedTemporaryFile(
            "w",
            suffix=ext,
            delete=False,
            encoding="utf-8",
        )
        tf.write(content)
        tf.close()
        return tf.name

    def _run_exe(self, path: str) -> tuple[bool, str]:
        """直接启动 exe 程序（fire-and-forget）。"""
        try:
            subprocess.Popen([path], close_fds=True)
            return True, f"已启动: {path}"
        except FileNotFoundError:
            return False, f"文件不存在: {path}"
        except PermissionError as e:
            return False, f"权限不足: {e}"
        except Exception as e:
            return False, f"启动失败: {e}"

    def run(self) -> tuple[bool, str]:
        """执行脚本并返回 (执行是否成功, 输出信息)。

        注意：这里的 success 表示脚本是否正常执行完毕（exit code 0），
        不代表登录是否成功。登录成功与否由调用方通过网络检测判断。
        """
        # exe 类型：直接启动进程，不走 ShellCommandPolicy
        if self.script_type == "exe":
            if self._cancel_event is not None and self._cancel_event.is_set():
                return False, "任务已被取消"
            try:
                exe_path = self._load_exe_path()
            except ValueError as e:
                logger.warning("exe 脚本加载失败 (script={}): {}", self.script_path, e)
                return False, str(e)
            return self._run_exe(exe_path)

        # 文本脚本类型
        if self.script_type not in _TEXT_TYPES:
            return False, f"不支持的脚本类型: {self.script_type}"

        start = time.perf_counter()
        env = _build_minimal_env()
        temp_path: str | None = None

        try:
            content = self._load_script_content()
        except ValueError as e:
            logger.warning("脚本加载失败 (script={}): {}", self.script_path, e)
            return False, str(e)

        if content is not None:
            # JSON 内容脚本：写入临时文件执行
            temp_path = self._content_temp_file(content)
            cmd = self._build_cmd(script_file=temp_path)
        else:
            # 文件脚本：直接使用文件路径
            cmd = self._build_cmd(script_file=str(self.script_path))

        # 使用 ShellCommandPolicy 进行安全校验和执行
        policy = ShellCommandPolicy(allowlist=list(_ALLOWED_BINARIES))

        kwargs: dict = {"env": env}
        # JSON 内容脚本（临时文件）不设 cwd，文件脚本设 cwd 为脚本所在目录
        if temp_path is None:
            kwargs["cwd"] = str(self.script_path.parent)

        try:
            returncode, stdout_str, stderr_str = policy.run_sync(
                cmd,
                timeout=self.timeout,
                cancel_event=self._cancel_event,
                **kwargs,
            )
        except PermissionError as e:
            logger.warning("脚本执行被拒绝 (script={}): {}", self.script_path, e)
            return False, str(e)
        except FileNotFoundError as e:
            logger.warning("脚本或解释器不存在 (script={}): {}", self.script_path, e)
            return False, f"脚本或解释器不存在: {e}"
        except Exception as e:
            logger.exception("脚本执行异常: {}", e)
            return False, f"执行异常: {e}"
        finally:
            if temp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)

        elapsed = time.perf_counter() - start

        if stderr_str:
            logger.debug("脚本 stderr: {}", stderr_str[:500])

        if returncode == 0:
            output = stdout_str[:500] or "(无输出, exit code 0)"
            logger.info("脚本执行成功 (耗时 {:.1f}s)", elapsed)
            return True, output
        else:
            # 失败时优先使用 stderr
            output = (
                stderr_str[:500]
                or stdout_str[:500]
                or f"(无输出, exit code {returncode})"
            )
            logger.warning(
                "脚本执行失败: {} (耗时 {:.1f}s, exit {})", output, elapsed, returncode
            )
            return False, output


def _build_minimal_env() -> dict[str, str]:
    """构建子进程最小环境变量（仅系统基础变量）。"""
    safe: dict[str, str] = {}
    base_keys = {"PATH", "HOME", "USER", "TEMP", "TMP"}
    if platform.system() == "Windows":
        base_keys.update(
            {
                "SystemRoot",
                "SystemDrive",
                "ComSpec",
                "windir",
                "USERPROFILE",
                "APPDATA",
                "LOCALAPPDATA",
            }
        )
    else:
        base_keys.update({"LANG", "LC_ALL", "SHELL", "XDG_RUNTIME_DIR"})
    for key in base_keys:
        val = os.environ.get(key)
        if val:
            safe[key] = val
    safe["PYTHONIOENCODING"] = "utf-8"
    return safe
