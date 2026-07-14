"""Task 模型单元测试。"""

from __future__ import annotations

from app.tasks.models import TASK_ID_PATTERN, JsCheck, StepConfig, TaskConfig

# ── TASK_ID_PATTERN 长度限制 ──


class TestTaskIdPattern:
    """TASK_ID_PATTERN 正则验证测试。"""

    def test_valid_short_id(self):
        """短 ID 通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("my_task")

    def test_valid_max_length_64(self):
        """恰好 64 字符的 ID 通过验证。"""
        valid_id = "a" * 64
        assert TASK_ID_PATTERN.fullmatch(valid_id)

    def test_exceeds_max_length_65(self):
        """65 字符的 ID 不通过验证。"""
        invalid_id = "a" * 65
        assert TASK_ID_PATTERN.fullmatch(invalid_id) is None

    def test_empty_id_rejected(self):
        """空 ID 不通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("") is None

    def test_single_char_id(self):
        """单字符 ID 通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("a")
        assert TASK_ID_PATTERN.fullmatch("1")
        assert TASK_ID_PATTERN.fullmatch("_")
        assert TASK_ID_PATTERN.fullmatch("-")

    def test_allowed_characters(self):
        """允许字母、数字、下划线、连字符。"""
        assert TASK_ID_PATTERN.fullmatch("test-123_id")

    def test_disallowed_special_chars(self):
        """不允许特殊字符。"""
        assert TASK_ID_PATTERN.fullmatch("test@id") is None
        assert TASK_ID_PATTERN.fullmatch("test id") is None
        assert TASK_ID_PATTERN.fullmatch("test/id") is None
        assert TASK_ID_PATTERN.fullmatch("test.id") is None

    def test_starts_with_digit_allowed(self):
        """允许以数字开头。"""
        assert TASK_ID_PATTERN.fullmatch("123task")

    def test_starts_with_hyphen_allowed(self):
        """允许以连字符开头。"""
        assert TASK_ID_PATTERN.fullmatch("-task")

    def test_only_underscores(self):
        """纯下划线 ID 通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("___")

    def test_only_hyphens(self):
        """纯连字符 ID 通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("---")

    def test_chinese_characters_rejected(self):
        """中文字符不通过验证。"""
        assert TASK_ID_PATTERN.fullmatch("任务") is None

    def test_63_chars_valid(self):
        """63 字符的 ID 通过验证（边界内）。"""
        valid_id = "b" * 63
        assert TASK_ID_PATTERN.fullmatch(valid_id)


# ── StepConfig 基础测试 ──


class TestStepConfig:
    """StepConfig 基础测试。"""

    def test_from_dict_minimal(self):
        """最小字段创建 StepConfig。"""
        step = StepConfig.from_dict({"id": "s1", "type": "click"})
        assert step.id == "s1"
        assert step.type == "click"

    def test_code_to_script_normalization(self):
        """code 字段自动规范化为 script。"""
        step = StepConfig.from_dict({"id": "s1", "type": "eval", "code": "1+1"})
        assert step.script == "1+1"

    def test_to_dict_skips_defaults(self):
        """to_dict 跳过默认值字段。"""
        step = StepConfig(id="s1", type="click")
        d = step.to_dict()
        assert d == {"id": "s1", "type": "click"}
        assert "description" not in d
        assert "timeout" not in d


# ── JsCheck 测试 ──


class TestJsCheck:
    """JsCheck dataclass 测试。"""

    def test_from_dict_full(self):
        """JsCheck.from_dict 解析完整字段。"""
        check = JsCheck.from_dict({
            "expr": "document.body.innerText.includes('密码错误')",
            "message": "凭证错误",
            "timeout": 3000,
        })
        assert check.expr == "document.body.innerText.includes('密码错误')"
        assert check.message == "凭证错误"
        assert check.timeout == 3000

    def test_from_dict_defaults(self):
        """JsCheck.from_dict 缺省字段使用默认值。"""
        check = JsCheck.from_dict({"expr": "true"})
        assert check.expr == "true"
        assert check.message == ""
        assert check.timeout == 2000

    def test_to_dict_full(self):
        """JsCheck.to_dict 序列化完整字段。"""
        check = JsCheck(
            expr="document.title === 'ok'",
            message="已登录",
            timeout=5000,
        )
        d = check.to_dict()
        assert d == {
            "expr": "document.title === 'ok'",
            "message": "已登录",
            "timeout": 5000,
        }

    def test_to_dict_skips_defaults(self):
        """JsCheck.to_dict 跳过默认 message 和 timeout。"""
        check = JsCheck(expr="true")
        d = check.to_dict()
        assert d == {"expr": "true"}


# ── TaskConfig success_checks / failure_checks 测试 ──


class TestTaskConfigChecks:
    """TaskConfig.success_checks / failure_checks 字段测试。"""

    def test_defaults_no_checks(self):
        """TaskConfig 默认 success_checks 和 failure_checks 为空列表。"""
        cfg = TaskConfig()
        assert cfg.success_checks == []
        assert cfg.failure_checks == []

    def test_from_dict_with_checks(self):
        """TaskConfig.from_dict 解析 success_checks / failure_checks。"""
        cfg = TaskConfig.from_dict({
            "name": "登录任务",
            "success_checks": [
                {"expr": "document.querySelector('.welcome') !== null", "message": "已登录"}
            ],
            "failure_checks": [
                {"expr": "document.body.innerText.includes('密码错误')", "timeout": 1000}
            ],
        })
        assert len(cfg.success_checks) == 1
        assert cfg.success_checks[0].expr == "document.querySelector('.welcome') !== null"
        assert cfg.success_checks[0].message == "已登录"
        assert cfg.success_checks[0].timeout == 2000  # 未指定，用默认
        assert len(cfg.failure_checks) == 1
        assert cfg.failure_checks[0].timeout == 1000

    def test_from_dict_skips_invalid_checks(self):
        """TaskConfig.from_dict 跳过非 dict 或无 expr 的 check。"""
        cfg = TaskConfig.from_dict({
            "success_checks": [
                "not a dict",
                {"expr": ""},  # 空 expr 被跳过
                {"message": "no expr"},  # 无 expr 被跳过
                {"expr": "true"},  # 有效
            ],
        })
        assert len(cfg.success_checks) == 1
        assert cfg.success_checks[0].expr == "true"

    def test_to_dict_with_checks(self):
        """TaskConfig.to_dict 序列化 success_checks / failure_checks。"""
        cfg = TaskConfig(name="t")
        cfg.success_checks.append(JsCheck(expr="true", message="ok"))
        d = cfg.to_dict()
        assert "success_checks" in d
        assert d["success_checks"] == [{"expr": "true", "message": "ok"}]

    def test_to_dict_without_checks(self):
        """TaskConfig.to_dict 空 checks 不序列化。"""
        cfg = TaskConfig(name="t")
        d = cfg.to_dict()
        assert "success_checks" not in d
        assert "failure_checks" not in d
