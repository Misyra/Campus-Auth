from __future__ import annotations


from backend.task_service import TaskService, _check_dangerous_steps


class TestCheckDangerousSteps:

    def test_no_dangerous_steps(self):
        task = {"steps": [{"type": "click", "selector": "#btn"}]}
        warnings = _check_dangerous_steps(task)
        assert warnings == []

    def test_eval_step_detected(self):
        task = {"steps": [{"type": "eval", "script": "alert(1)"}]}
        warnings = _check_dangerous_steps(task)
        assert len(warnings) == 1
        assert warnings[0]["step_type"] == "eval"

    def test_custom_js_step_detected(self):
        task = {"steps": [{"type": "custom_js", "script": "console.log('hi')"}]}
        warnings = _check_dangerous_steps(task)
        assert len(warnings) == 1
        assert warnings[0]["step_type"] == "custom_js"

    def test_code_truncated(self):
        long_code = "x" * 5000
        task = {"steps": [{"type": "eval", "script": long_code}]}
        warnings = _check_dangerous_steps(task)
        assert len(warnings[0]["code"]) <= 2000

    def test_legacy_code_field_detected(self):
        """Legacy 'code' field (pre-normalization) should also trigger warnings."""
        task = {"steps": [{"type": "eval", "code": "alert(1)"}]}
        warnings = _check_dangerous_steps(task)
        assert len(warnings) == 1
        assert warnings[0]["step_type"] == "eval"
        assert "alert(1)" in warnings[0]["code"]

    def test_legacy_code_field_in_extra(self):
        """Legacy 'code' field inside 'extra' should also trigger warnings."""
        task = {"steps": [{"type": "eval", "extra": {"code": "alert(2)"}}]}
        warnings = _check_dangerous_steps(task)
        assert len(warnings) == 1
        assert "alert(2)" in warnings[0]["code"]


class TestTaskService:

    def _make_service(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        return TaskService(tmp_path)

    def test_list_tasks_empty(self, tmp_path):
        svc = self._make_service(tmp_path)
        tasks = svc.list_tasks()
        assert isinstance(tasks, list)

    def test_get_task_not_found(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.get_task("nonexistent")
        assert result is None

    def test_save_task_invalid_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.save_task("123invalid", {"name": "Test", "steps": []})
        assert ok is False

    def test_save_task_empty_name(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.save_task("test", {"name": "", "steps": [{"type": "click"}]})
        assert ok is False
        assert "名称" in msg

    def test_save_task_no_steps(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.save_task("test", {"name": "Test", "steps": []})
        assert ok is False
        assert "至少" in msg

    def test_save_and_get_task(self, tmp_path):
        svc = self._make_service(tmp_path)
        task_data = {
            "name": "Test Task",
            "steps": [{"id": "step1", "type": "click", "selector": "#btn", "description": "Click button"}],
        }
        ok, msg = svc.save_task("testtask", task_data)
        assert ok is True
        result = svc.get_task("testtask")
        assert result is not None
        assert result["name"] == "Test Task"

    def test_delete_default_task(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.delete_task("default")
        assert ok is False
        assert "不能删除" in msg

    def test_delete_nonexistent_task(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.delete_task("nonexistent")
        assert ok is True

    def test_get_active_task_default(self, tmp_path):
        svc = self._make_service(tmp_path)
        active = svc.get_active_task()
        assert isinstance(active, str)

    def test_set_active_task_not_found(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.set_active_task("nonexistent")
        assert ok is False
        assert "不存在" in msg

    def test_set_active_task_success(self, tmp_path):
        svc = self._make_service(tmp_path)
        task_data = {
            "name": "Test",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        svc.save_task("mytask", task_data)
        ok, msg = svc.set_active_task("mytask")
        assert ok is True
        assert svc.get_active_task() == "mytask"
