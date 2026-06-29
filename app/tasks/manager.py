"""任务管理器 — 任务文件的 CRUD 操作。"""

from __future__ import annotations

import functools
import json
import threading
from pathlib import Path
from typing import Any

from app.utils.files import atomic_write
from app.utils.logging import get_logger

from .models import TASK_ID_PATTERN, ScriptTaskInfo, TaskConfig
from .validator import TaskValidator

logger = get_logger("task_manager", source="backend")

_DANGEROUS_STEP_TYPES = {"eval", "custom_js"}

_INVALID_ID_MSG = "任务ID必须以字母开头，且只能包含字母、数字和下划线"


def _with_task_id_validation(func):
    """装饰器：规范化 task_id 并校验有效性，无效时返回 (False, 错误消息)。"""
    @functools.wraps(func)
    def wrapper(self, task_id: str, *args, **kwargs):
        task_id = normalize_task_id(task_id)
        if not is_valid_task_id(task_id):
            return False, _INVALID_ID_MSG
        return func(self, task_id, *args, **kwargs)
    return wrapper


def _check_dangerous_steps(task_data: dict[str, Any]) -> list[dict[str, Any]]:
    """检查任务中的危险步骤，返回详细信息列表（含代码内容）。"""
    warnings = []
    steps = task_data.get("steps", [])
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_type = step.get("type", "")
        if step_type in _DANGEROUS_STEP_TYPES:
            desc = step.get("description", step.get("id", f"步骤{i + 1}"))
            extra = step.get("extra", {})
            code = (
                step.get("script")
                or step.get("code")
                or extra.get("script")
                or extra.get("code")
                or ""
            )
            warnings.append(
                {
                    "step_index": i + 1,
                    "step_type": step_type,
                    "description": desc,
                    "code": str(code)[:2000],
                }
            )
    return warnings


def normalize_task_id(task_id: str | None) -> str:
    if not isinstance(task_id, str):
        return ""
    return task_id.strip()


def is_valid_task_id(task_id: str | None) -> bool:
    normalized = normalize_task_id(task_id)
    return bool(normalized and TASK_ID_PATTERN.fullmatch(normalized))


class TaskManager:
    """任务管理器（浏览器任务、脚本任务分目录存储）"""

    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.browser_dir = tasks_dir / "browser"
        self.scripts_dir = tasks_dir / "scripts"
        self.browser_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        # BUG-048 修复：添加锁保护文件操作
        self._lock = threading.Lock()

    # ── 路径工具 ──

    def _validate_id(self, task_id: str) -> str | None:
        """规范化并校验 task_id，无效返回 None。"""
        normalized = normalize_task_id(task_id)
        if not is_valid_task_id(normalized):
            return None
        return normalized

    def _safe_subdir_path(self, subdir: Path, task_id: str, suffix: str) -> Path | None:
        """返回子目录下的安全文件路径（不检查存在性）。"""
        normalized = self._validate_id(task_id)
        if normalized is None:
            return None
        base = self.tasks_dir.absolute()
        candidate = (subdir / f"{normalized}{suffix}").absolute()
        try:
            candidate.relative_to(base)
        except ValueError:
            return None
        return candidate

    def _safe_task_path(self, task_id: str, task_type: str = "") -> Path | None:
        """返回任务文件路径（跨 browser/scripts 子目录搜索）。

        Args:
            task_id: 任务 ID
            task_type: 可选，限定搜索目录 ("browser" 或 "scripts")，为空则搜索全部
        """
        normalized = self._validate_id(task_id)
        if normalized is None:
            return None
        base = self.tasks_dir.absolute()
        if task_type == "browser":
            search_dirs = [(self.browser_dir, ".json")]
        elif task_type == "scripts":
            search_dirs = [(self.scripts_dir, ".json"), (self.scripts_dir, ".py")]
        else:
            # 搜索顺序：browser/*.json → scripts/*.json → scripts/*.py
            search_dirs = [
                (self.browser_dir, ".json"),
                (self.scripts_dir, ".json"),
                (self.scripts_dir, ".py"),
            ]
        for subdir, ext in search_dirs:
            candidate = (subdir / f"{normalized}{ext}").absolute()
            try:
                candidate.relative_to(base)
            except ValueError:
                return None
            if candidate.exists():
                return candidate
        # 都不存在时返回对应目录的 .json 路径
        first_dir = search_dirs[0][0]
        return (first_dir / f"{normalized}.json").absolute()

    def _safe_json_path(self, task_id: str, task_type: str = "browser") -> Path | None:
        """返回 .json 路径（根据任务类型选择子目录）。"""
        subdir = self.scripts_dir if task_type == "scripts" else self.browser_dir
        return self._safe_subdir_path(subdir, task_id, ".json")

    def _safe_meta_path(self, task_id: str) -> Path | None:
        """返回 scripts/ 下的 .meta.json 路径。"""
        return self._safe_subdir_path(self.scripts_dir, task_id, ".meta.json")

    def _read_meta(self, task_id: str) -> dict[str, str]:
        """读取脚本元数据文件。"""
        meta_path = self._safe_meta_path(task_id)
        if meta_path and meta_path.exists():
            try:
                return json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                logger.debug("读取脚本元数据失败: {}", meta_path, exc_info=True)
        return {}

    def _write_meta(self, task_id: str, meta: dict[str, str]) -> bool:
        """写入脚本元数据文件。"""
        meta_path = self._safe_meta_path(task_id)
        if meta_path is None:
            return False
        try:
            atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
            return True
        except Exception as e:
            logger.error("无法保存脚本元数据 {}: {}", task_id, e)
            return False

    @staticmethod
    def _extract_script_metadata(file: Path) -> dict[str, str]:
        """从 Python 脚本的注释和 docstring 中提取 name 和 description。

        支持格式：
            # name: 任务名称
            # description: 任务描述
        或者使用模块级 docstring 的第一行作为 name。
        """
        name = file.stem
        description = ""
        try:
            content = file.read_text(encoding="utf-8")
            lines = content.splitlines()[:10]
            for line in lines:
                stripped = line.strip()
                if stripped.lower().startswith("# name:"):
                    name = stripped.split(":", 1)[1].strip()
                elif stripped.lower().startswith("# description:"):
                    description = stripped.split(":", 1)[1].strip()
            # 如果没找到 name 注释，尝试 docstring
            if name == file.stem:
                import ast
                tree = ast.parse(content)
                docstring = ast.get_docstring(tree)
                if docstring:
                    name = docstring.split("\n")[0][:80]
        except Exception:
            logger.debug("解析脚本 docstring 失败: {}", file, exc_info=True)
        return {"name": name, "description": description}

    # ── CRUD ──

    def _order_file(self) -> Path:
        return self.tasks_dir / ".order.json"

    def load_order(self) -> dict[str, list[str]]:
        """读取排序配置。"""
        path = self._order_file()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.debug("读取排序配置失败: {}", path, exc_info=True)
        return {}

    def save_order(self, order: dict[str, list[str]]) -> bool:
        """保存排序配置。"""
        try:
            atomic_write(
                str(self._order_file()),
                json.dumps(order, ensure_ascii=False, indent=2),
            )
            return True
        except Exception as e:
            logger.error("保存排序配置失败: {}", e)
            return False

    def _sort_by_order(self, tasks: list[dict], order_key: str) -> list[dict]:
        """按排序配置对任务列表排序，未在排序中的排到末尾。"""
        order = self.load_order()
        id_order = order.get(order_key, [])
        if not id_order:
            return tasks
        order_map = {tid: i for i, tid in enumerate(id_order)}
        return sorted(tasks, key=lambda t: order_map.get(t["id"], len(id_order)))

    def list_tasks(self) -> list[dict[str, str]]:
        """列出浏览器任务（browser/ 目录下的 .json 文件）。"""
        tasks: list[dict[str, str]] = []
        for file in self.browser_dir.glob("*.json"):
            if not is_valid_task_id(file.stem):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                tasks.append(
                    {
                        "id": file.stem,
                        "name": data.get("name", file.stem),
                        "description": data.get("description", ""),
                        "type": "browser",
                    }
                )
            except Exception as e:
                logger.warning("无法读取任务文件 {}: {}", file, e)
        return self._sort_by_order(tasks, "all")

    def list_script_tasks(self) -> list[dict[str, str]]:
        """列出所有自定义脚本任务（scripts/ 目录）。"""
        tasks: list[dict[str, str]] = []
        seen_ids: set[str] = set()

        # 1. 扫描 scripts/ 下的 JSON 文件（排除 .meta.json）
        for file in self.scripts_dir.glob("*.json"):
            if file.name.lower().endswith(".meta.json"):
                continue
            if not is_valid_task_id(file.stem):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                tasks.append(
                    {
                        "id": file.stem,
                        "name": data.get("name", file.stem),
                        "description": data.get("description", ""),
                        "binary_path": data.get("binary_path", ""),
                    }
                )
                seen_ids.add(file.stem)
            except Exception as e:
                logger.warning("无法读取脚本 JSON {}: {}", file, e)

        # 2. 扫描 scripts/ 下的 .py 文件（兼容旧格式）
        for file in self.scripts_dir.glob("*.py"):
            if not is_valid_task_id(file.stem) or file.stem in seen_ids:
                continue
            try:
                file_meta = self._read_meta(file.stem)
                if file_meta:
                    name = file_meta.get("name", file.stem)
                    description = file_meta.get("description", "")
                    binary_path = file_meta.get("binary_path", "")
                else:
                    comment_meta = self._extract_script_metadata(file)
                    name = comment_meta["name"]
                    description = comment_meta["description"]
                    binary_path = ""
                tasks.append(
                    {
                        "id": file.stem,
                        "name": name,
                        "description": description,
                        "binary_path": binary_path,
                    }
                )
            except Exception as e:
                logger.warning("无法读取脚本文件 {}: {}", file, e)

        return self._sort_by_order(tasks, "scripts")

    def load_task(
        self, task_id: str, task_type: str = ""
    ) -> TaskConfig | ScriptTaskInfo | None:
        file = self._safe_task_path(task_id, task_type=task_type)
        if file is None or not file.exists():
            return None
        try:
            # 根据文件位置判断类型：scripts/ 下的是脚本任务
            is_script = (
                self.scripts_dir in file.parents or file.parent == self.scripts_dir
            )

            if is_script:
                # 脚本任务
                if file.suffix.lower() == ".json":
                    data = json.loads(file.read_text(encoding="utf-8"))
                    return ScriptTaskInfo(
                        task_id=task_id,
                        name=data.get("name", task_id),
                        description=data.get("description", ""),
                        script_path=file,
                        binary_path=data.get("binary_path", ""),
                    )
                # .py 文件（兼容旧格式）
                if file.suffix.lower() == ".py":
                    file_meta = self._read_meta(task_id)
                    if file_meta:
                        name = file_meta.get("name", file.stem)
                        description = file_meta.get("description", "")
                        binary_path = file_meta.get("binary_path", "")
                    else:
                        comment_meta = self._extract_script_metadata(file)
                        name = comment_meta["name"]
                        description = comment_meta["description"]
                        binary_path = ""
                    return ScriptTaskInfo(
                        task_id=task_id,
                        name=name,
                        description=description,
                        script_path=file,
                        binary_path=binary_path,
                    )
            else:
                # 浏览器任务
                data = json.loads(file.read_text(encoding="utf-8"))
                config = TaskConfig.from_dict(data)
                config.task_id = task_id
                return config

            return None
        except Exception as e:
            logger.error("无法加载任务 {}: {}", task_id, e)
            return None

    def save_task(
        self, task_id: str, config: dict[str, Any], task_type: str = "browser"
    ) -> bool:
        """保存任务（支持 browser 和 script 两种类型）。"""
        with self._lock:
            if task_type == "scripts":
                return self._save_script_task(task_id, config)

            # 浏览器任务：带验证
            is_valid, errors = TaskValidator.validate(config)
            if not is_valid:
                logger.error("任务验证失败: {}", errors)
                return False

            file = self._safe_json_path(task_id, task_type="browser")
            if file is None:
                return False

            try:
                atomic_write(
                    str(file),
                    json.dumps(config, ensure_ascii=False, indent=2),
                )
                return True
            except Exception as e:
                logger.error("无法保存任务 {}: {}", task_id, e)
                return False

    def _save_script_task(self, task_id: str, config: dict[str, Any]) -> bool:
        """保存自定义脚本任务（JSON 格式，存入 scripts/ 目录）。"""
        script_content = config.get("content", "")
        if not script_content.strip():
            logger.error("脚本内容不能为空")
            return False

        file = self._safe_json_path(task_id, task_type="scripts")
        if file is None:
            return False

        save_data = {
            "type": "script",
            "name": config.get("name", task_id),
            "description": config.get("description", ""),
            "binary_path": config.get("binary_path", ""),
            "content": script_content,
        }

        try:
            atomic_write(str(file), json.dumps(save_data, ensure_ascii=False, indent=2))
            return True
        except Exception as e:
            logger.error("无法保存脚本任务 {}: {}", task_id, e)
            return False

    def delete_task(self, task_id: str) -> bool:
        normalized = normalize_task_id(task_id)
        if normalized == "default":
            return False
        if not is_valid_task_id(normalized):
            return False
        with self._lock:
            deleted = False
            # 从两个子目录中删除
            for subdir in (self.browser_dir, self.scripts_dir):
                for ext in (".json", ".py", ".meta.json"):
                    file = subdir / f"{normalized}{ext}"
                    if file.exists():
                        try:
                            file.unlink()
                            deleted = True
                        except Exception as e:
                            logger.error("无法删除任务文件 {}: {}", file, e)
            # 删除活动任务后回退到默认任务
            if deleted:
                active = self.get_active_task()
                if active == normalized:
                    try:
                        atomic_write(
                            str(self.tasks_dir / "active.txt"), "browser:default"
                        )
                        logger.info("活动任务已删除，已回退到默认任务")
                    except Exception as e:
                        logger.error("回退活动任务失败: {}", e)
            return deleted

    def _find_task_type(self, task_id: str) -> str | None:
        """查找任务所在的子目录类型，返回 'browser' 或 'scripts'，未找到返回 None。"""
        normalized = normalize_task_id(task_id)
        if not is_valid_task_id(normalized):
            return None
        if (self.browser_dir / f"{normalized}.json").exists():
            return "browser"
        for ext in (".json", ".py"):
            if (self.scripts_dir / f"{normalized}{ext}").exists():
                return "scripts"
        return None

    def get_active_task(self) -> str:
        """返回活动任务 ID（不含类型前缀）。"""
        config_file = self.tasks_dir / "active.txt"
        if config_file.exists():
            raw = config_file.read_text(encoding="utf-8").strip()
            # 解析 type:id 格式，返回纯 ID
            if ":" in raw:
                return raw.split(":", 1)[1]
            return raw
        return "default"

    def load_active_task(self) -> TaskConfig | ScriptTaskInfo | None:
        """加载活动任务（自动解析 type:id 格式）。"""
        config_file = self.tasks_dir / "active.txt"
        if not config_file.exists():
            return self.load_task("default")
        raw = config_file.read_text(encoding="utf-8").strip()
        if ":" in raw:
            task_type, task_id = raw.split(":", 1)
            if task_type in ("browser", "scripts"):
                return self.load_task(task_id, task_type=task_type)
            return self.load_task(task_id)
        return self.load_task(raw) if raw else self.load_task("default")

    def set_active_task(self, task_id: str) -> bool:
        normalized = normalize_task_id(task_id)
        if not is_valid_task_id(normalized):
            return False
        task_type = self._find_task_type(normalized)
        if not task_type:
            return False
        config_file = self.tasks_dir / "active.txt"
        try:
            atomic_write(str(config_file), f"{task_type}:{normalized}")
            return True
        except Exception as e:
            logger.error("无法设置活动任务: {}", e)
            return False

    # ── 验证包装方法（原 TaskService 逻辑）──

    def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        """加载任务详情（含脚本内容读取），统一浏览器/脚本任务返回格式。"""
        task_id = normalize_task_id(task_id)
        if not is_valid_task_id(task_id):
            return None
        task = self.load_task(task_id)
        if task is None:
            return None

        if isinstance(task, ScriptTaskInfo):
            content = ""
            if task.script_path.suffix.lower() == ".json":
                try:
                    data = json.loads(task.script_path.read_text(encoding="utf-8"))
                    content = data.get("content", "")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    logger.error("读取脚本 JSON 失败 {}: {}", task.script_path, exc)
                    return None
            else:
                try:
                    content = task.script_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.error("读取脚本文件失败 {}: {}", task.script_path, exc)
                    return None
            return {
                "id": task_id,
                "name": task.name,
                "description": task.description,
                "type": "script",
                "content": content,
                "binary_path": task.binary_path,
            }

        result = task.to_dict()
        result["id"] = task_id
        result["type"] = "browser"
        try:
            json_path = self._safe_json_path(task_id, task_type="browser")
            if json_path and json_path.exists():
                result["raw_json"] = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "读取任务原始 JSON 失败 (task_id={})", task_id, exc_info=True
            )
        return result

    @_with_task_id_validation
    def save_task_with_validation(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存任务（含危险步骤检查和 ID 校验）。"""
        task_type = config.get("type", "browser")
        if task_type == "script":
            return self._save_script_task_validated(task_id, config)

        if not config.get("name"):
            return False, "任务名称不能为空"
        if not config.get("steps"):
            return False, "至少需要一个执行步骤"

        warnings = _check_dangerous_steps(config)
        for w in warnings:
            logger.warning("任务 {}: {}", task_id, w)

        success = self.save_task(task_id, config)
        if success:
            logger.info("任务已保存: {}", task_id)
            return True, "任务保存成功"
        return False, "任务保存失败"

    def _save_script_task_validated(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存自定义脚本任务（含验证）。"""
        content = config.get("content", "")
        if not content.strip():
            return False, "脚本内容不能为空"

        max_size = 100 * 1024
        if len(content.encode("utf-8")) > max_size:
            return False, f"脚本内容超过大小限制（最大 {max_size // 1024}KB）"

        save_data = {
            "content": content,
            "name": config.get("name", ""),
            "description": config.get("description", ""),
            "binary_path": config.get("binary_path", ""),
        }
        success = self.save_task(task_id, save_data, task_type="scripts")
        if success:
            logger.info("脚本任务已保存: {}", task_id)
            return True, "脚本任务保存成功"
        return False, "脚本任务保存失败"

    @_with_task_id_validation
    def delete_task_with_validation(self, task_id: str) -> tuple[bool, str]:
        """删除任务（含 ID 校验）。"""
        if task_id == "default":
            return False, "不能删除默认任务"

        success = self.delete_task(task_id)
        if success:
            logger.info("任务已删除: {}", task_id)
            return True, "任务删除成功"
        return False, "任务不存在或删除失败"

    @_with_task_id_validation
    def set_active_task_with_validation(self, task_id: str) -> tuple[bool, str]:
        """设置活动任务（含 ID 校验）。"""
        if not self.load_task(task_id):
            return False, "任务不存在"

        success = self.set_active_task(task_id)
        if success:
            logger.info("活动任务已设置: {}", task_id)
            return True, "活动任务已设置"
        logger.error("设置活动任务失败: {}", task_id)
        return False, "设置活动任务失败"

    def save_order_with_validation(self, order: dict[str, list[str]]) -> tuple[bool, str]:
        """保存任务排序配置。"""
        if not isinstance(order, dict):
            return False, "排序数据格式无效"
        success = self.save_order(order)
        if success:
            logger.info("任务排序已保存")
            return True, "排序保存成功"
        return False, "排序保存失败"
