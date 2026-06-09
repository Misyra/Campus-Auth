"""自定义脚本执行器 — 在子进程中执行脚本任务。"""

from __future__ import annotations

import contextlib
import ntpath
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy
from app.utils.shell_utils import detect_binaries

logger = get_logger("script_runner", source="backend")

# 默认脚本超时（秒）
DEFAULT_TIMEOUT = 60

# 解释器 → 临时文件后缀映射
_BINARY_EXT_MAP = {
    "python": ".py",
    "python3": ".py",
    "node": ".js",
    "ruby": ".rb",
    "php": ".php",
    "perl": ".pl",
    "raku": ".raku",
    "lua": ".lua",
    "r": ".R",
    "rscript": ".R",
    "cmd": ".bat",
    "powershell": ".ps1",
    "pwsh": ".ps1",
    "bash": ".sh",
    "sh": ".sh",
    "zsh": ".sh",
    "fish": ".fish",
}


def get_default_binary() -> str:
    """获取默认执行二进制（当前运行的 Python）。"""
    return sys.executable


# 向后兼容：保留旧名称供 API 路由使用
detect_available_binaries = detect_binaries


class ScriptRunner:
    """执行自定义脚本任务。

    脚本自行硬编码账号密码等参数，通过 stdout 输出信息。
    成功与否由网络检测判断，脚本只需发请求。
    支持 .py 文件和 JSON 格式（包含 content 字段）。
    """

    def __init__(
        self,
        script_path: Path,
        timeout: int = DEFAULT_TIMEOUT,
        binary_path: str = "",
    ):
        self.script_path = script_path
        self.timeout = timeout
        self.binary_path = binary_path or get_default_binary()
        self._script_content: str | None = None

    def _load_script_content(self) -> str | None:
        """从 JSON 文件加载脚本内容。

        .json 文件解析失败时抛出 ValueError，避免静默降级为 .py 执行。
        """
        if self._script_content is not None:
            return self._script_content

        if self.script_path.suffix.lower() == ".json":
            import json

            try:
                data = json.loads(self.script_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"JSON 脚本格式错误或编码不支持: {e}") from e
            self._script_content = data.get("content", "")
            return self._script_content

        # .py 文件直接返回 None，由 _build_cmd 处理
        return None

    def _build_cmd(self, script_file: str | None = None) -> list[str]:
        """构建执行命令。

        Args:
            script_file: 可选，指定要执行的脚本文件路径。
                         为 None 时使用 self.script_path（仅文件脚本）。
        """
        exe_name = ntpath.splitext(ntpath.basename(self.binary_path))[0].lower()

        # 指定了脚本文件（临时文件或普通文件）：统一按文件执行
        if script_file is not None:
            if platform.system() == "Windows":
                if exe_name in ("powershell", "pwsh"):
                    return [
                        self.binary_path,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-WindowStyle",
                        "Hidden",
                        "-File",
                        script_file,
                    ]
                elif exe_name == "cmd":
                    return [self.binary_path, "/c", f'call "{script_file}"']
            else:
                if exe_name in ("bash", "sh", "zsh", "fish"):
                    return [self.binary_path, script_file]
            return [self.binary_path, script_file]

        script = str(self.script_path)

        # JSON 格式脚本：不应该走到这里（应通过 script_file 参数传入临时文件）
        content = self._load_script_content()
        if content is not None:
            raise RuntimeError("JSON 内容脚本必须通过临时文件执行，请使用 run() 方法")

        # .py 或其他文件
        if platform.system() == "Windows":
            if exe_name in ("powershell", "pwsh"):
                return [
                    self.binary_path,
                    "-NoProfile",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    script,
                ]
            elif exe_name == "cmd":
                return [self.binary_path, "/c", f'call "{script}"']
        else:
            if exe_name in ("bash", "sh", "zsh", "fish"):
                return [self.binary_path, script]

        return [self.binary_path, script]

    def _content_temp_file(self, content: str) -> str:
        """将 JSON 内容写入临时文件，返回文件路径。"""
        exe_name = ntpath.splitext(ntpath.basename(self.binary_path))[0].lower()
        ext = _BINARY_EXT_MAP.get(exe_name, "")
        tf = tempfile.NamedTemporaryFile(
            "w",
            suffix=ext,
            delete=False,
            encoding="utf-8",
        )
        tf.write(content)
        tf.close()
        return tf.name

    def run(self) -> tuple[bool, str]:
        """执行脚本并返回 (执行是否成功, 输出信息)。

        注意：这里的 success 表示脚本是否正常执行完毕（exit code 0），
        不代表登录是否成功。登录成功与否由调用方通过网络检测判断。
        """
        if not self.binary_path:
            return False, "未指定执行二进制"

        start = time.perf_counter()
        env = _build_minimal_env()
        temp_path: str | None = None

        try:
            content = self._load_script_content()
        except ValueError as e:
            logger.error("脚本加载失败: {}", e)
            return False, str(e)

        if content is not None:
            # JSON 内容脚本：写入临时文件执行，绕过命令行引号转义问题
            temp_path = self._content_temp_file(content)
            cmd = self._build_cmd(script_file=temp_path)
        else:
            cmd = self._build_cmd()

        # 使用 ShellCommandPolicy 进行安全校验和执行
        available = [b["path"] for b in detect_available_binaries()]
        if self.binary_path not in available:
            available.append(self.binary_path)
        policy = ShellCommandPolicy(allowlist=available)

        kwargs: dict = {"env": env}
        # JSON 内容脚本（临时文件）不设 cwd，文件脚本设 cwd 为脚本所在目录
        if temp_path is None:
            kwargs["cwd"] = str(self.script_path.parent)

        try:
            returncode, stdout_str, stderr_str = policy.run_sync(
                cmd,
                timeout=self.timeout,
                **kwargs,
            )
        except PermissionError as e:
            logger.error("脚本执行被拒绝: {}", e)
            return False, str(e)
        except FileNotFoundError as e:
            logger.error("脚本或解释器不存在: {}", e)
            return False, f"脚本或解释器不存在: {e}"
        finally:
            if temp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)

        elapsed = time.perf_counter() - start

        if stderr_str:
            logger.info("脚本 stderr: {}", stderr_str[:500])

        output = (
            stdout_str[:500] or stderr_str[:500] or f"(无输出, exit code {returncode})"
        )

        if returncode == 0:
            logger.info("脚本执行完成 ({:.1f}s): {}", elapsed, output)
            return True, output
        else:
            logger.warning(
                "脚本执行失败 ({:.1f}s, exit {}): {}", elapsed, returncode, output
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
