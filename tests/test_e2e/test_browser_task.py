"""浏览器任务真实执行 E2E 测试 — Playwright + http_portal 集成。

验证 BrowserTaskService → PlaywrightWorker → BrowserTaskRunner 完整链路：
- 创建浏览器任务定义（填表单 + 点击登录）
- 通过 scheduled-tasks API 触发浏览器任务
- Worker 启动真实 Chromium 执行步骤
- http_portal 收到登录请求并返回结果
- 执行历史正确记录

需要 Chromium 已安装（uv run playwright install chromium）。
"""

from __future__ import annotations

import time

import pytest

# ── Chromium 可用性检查（模块级，只检查一次）──


@pytest.fixture(scope="module", autouse=True)
def _ensure_chromium():
    """确保 Chromium 已安装，未安装则跳过模块内所有测试。"""
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Chromium 未安装: {e}")


# ── 辅助函数 ──


def _save_browser_task(client, task_id: str, portal_url: str):
    """创建浏览器任务定义，指向 http_portal 登录表单。"""
    payload = {
        "name": f"E2E 浏览器任务 {task_id}",
        "description": "E2E 浏览器任务测试",
        "url": "{{LOGIN_URL}}",
        "timeout": 30000,
        "variables": {
            "username": "{{USERNAME}}",
            "password": "{{PASSWORD}}",
        },
        "steps": [
            {
                "id": "fill_username",
                "type": "input",
                "description": "填写用户名",
                "selector": "#username",
                "value": "{{username}}",
                "clear": True,
            },
            {
                "id": "fill_password",
                "type": "input",
                "description": "填写密码",
                "selector": "#password",
                "value": "{{password}}",
                "clear": True,
            },
            {
                "id": "click_login",
                "type": "click",
                "description": "点击登录按钮",
                "selector": "#loginBtn",
            },
            {
                "id": "wait_result",
                "type": "sleep",
                "description": "等待页面跳转完成",
                "duration": 2000,
            },
            {
                "id": "verify_success",
                "type": "eval",
                "description": "验证登录成功",
                "script": (
                    "() => { const text = document.body.innerText || ''; "
                    "if (text.includes('登录成功')) return true; "
                    "throw new Error('未检测到登录成功标志，页面内容: ' + text.substring(0, 100)); }"
                ),
            },
        ],
        "on_success": {"message": "浏览器任务执行成功"},
        "on_failure": {"message": "浏览器任务执行失败", "screenshot": True},
    }
    resp = client.put(f"/api/tasks/{task_id}", json=payload)
    assert resp.status_code == 200, f"保存浏览器任务失败: {resp.text}"
    return resp.json()


def _create_browser_scheduled_task(
    client, task_id: str, target_id: str, timeout: int = 120
) -> str:
    """创建 type=browser 的定时任务，返回服务器生成的实际 task_id。

    API 生成 task_<uuid> 格式的 ID，不使用客户端提供的 ID。
    通过任务名称从列表中查找实际 ID。
    """
    task_name = f"E2E 浏览器定时任务 {task_id}"
    payload = {
        "name": task_name,
        "description": "E2E 浏览器任务触发",
        "type": "browser",
        "target_id": target_id,
        "enabled": True,
        "schedule": {"hour": 3, "minute": 0},
        "timeout": timeout,
    }
    resp = client.post("/api/scheduled-tasks", json=payload)
    assert resp.status_code == 200, f"创建定时任务失败: {resp.text}"
    # API 生成 task_<uuid> ID，需从列表中查找实际 ID
    tasks = client.get("/api/scheduled-tasks").json()
    task = next(t for t in tasks if t["name"] == task_name)
    return task["id"]


def _run_scheduled_task_and_wait(client, task_id: str, max_wait: int = 90):
    """触发定时任务并等待执行完成（轮询历史）。

    POST /api/scheduled-tasks/{task_id}/run 是异步后台执行，
    TestClient 会等待 background task 完成后才返回响应。
    但仍需短暂轮询确保历史记录已写入。
    """
    resp = client.post(f"/api/scheduled-tasks/{task_id}/run")
    assert resp.status_code == 200, f"触发定时任务失败: {resp.text}"

    # 轮询历史记录，等待执行结果
    deadline = time.time() + max_wait
    while time.time() < deadline:
        resp = client.get(f"/api/scheduled-tasks/{task_id}/history")
        assert resp.status_code == 200, f"获取历史失败: {resp.text}"
        history = resp.json()
        if len(history) > 0:
            return history
        time.sleep(0.5)

    pytest.fail(f"定时任务 {task_id} 在 {max_wait}s 内未产生执行历史")


# ── 测试类 ──


@pytest.mark.slow
class TestBrowserTaskExecution:
    """浏览器任务真实执行 — Playwright + http_portal 集成。"""

    def test_browser_task_fills_form_and_logs_in(self, real_app, http_portal):
        """浏览器任务填写表单、点击登录、验证成功页面。"""
        client, _ = real_app
        _, _, portal_base_url = http_portal

        # 1. 更新配置：auth_url 指向 http_portal，browser_channel 改为 playwright
        resp = client.patch(
            "/api/config",
            json={
                "auth_url": portal_base_url + "/",
                "browser": {"browser_channel": "playwright", "pure_mode": True},
            },
        )
        assert resp.status_code == 200, f"更新配置失败: {resp.text}"

        # 2. 创建浏览器任务定义
        _save_browser_task(client, "e2e_browser_task", portal_base_url)

        # 3. 创建定时任务并触发
        actual_task_id = _create_browser_scheduled_task(
            client, "e2e_browser_sched", "e2e_browser_task"
        )
        history = _run_scheduled_task_and_wait(client, actual_task_id)

        # 4. 验证执行结果
        assert len(history) >= 1
        record = history[0]
        assert record["status"] == "success", (
            f"浏览器任务执行失败: {record.get('message', '')}"
        )

    def test_browser_task_with_wrong_credentials_fails(self, real_app, http_portal):
        """错误凭据时 eval 步骤检测到登录失败，任务返回 failure。"""
        client, _ = real_app
        _, _, portal_base_url = http_portal

        # 更新配置：auth_url 指向 portal，但密码错误
        resp = client.patch(
            "/api/config",
            json={
                "auth_url": portal_base_url + "/",
                "password": "wrong_password",
                "browser": {"browser_channel": "playwright", "pure_mode": True},
            },
        )
        assert resp.status_code == 200

        _save_browser_task(client, "e2e_browser_fail", portal_base_url)
        actual_task_id = _create_browser_scheduled_task(
            client, "e2e_browser_fail_sched", "e2e_browser_fail"
        )
        history = _run_scheduled_task_and_wait(client, actual_task_id)

        assert len(history) >= 1
        record = history[0]
        # 错误密码时 portal 返回失败页面，eval 步骤抛异常 → 任务 failure
        assert record["status"] == "failure", (
            f"错误凭据应导致任务失败，但实际状态: {record['status']}, "
            f"消息: {record.get('message', '')}"
        )

    def test_browser_task_nonexistent_target_fails(self, real_app, http_portal):
        """定时任务指向不存在的浏览器任务时返回失败。"""
        client, _ = real_app
        _, _, portal_base_url = http_portal

        # 更新配置确保 browser_channel 正确
        client.patch(
            "/api/config",
            json={
                "auth_url": portal_base_url + "/",
                "browser": {"browser_channel": "playwright"},
            },
        )

        # 创建指向不存在目标的定时任务
        actual_task_id = _create_browser_scheduled_task(
            client, "e2e_browser_nonexist_sched", "nonexistent_task"
        )
        history = _run_scheduled_task_and_wait(client, actual_task_id)

        assert len(history) >= 1
        record = history[0]
        assert record["status"] == "failure"
        assert "不存在" in record.get("message", "") or "失败" in record.get("message", "")
