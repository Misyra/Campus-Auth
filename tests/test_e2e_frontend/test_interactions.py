"""前端 E2E 交互流程测试。

测试完整交互流程：
- 首次启动向导
- 登录配置流程
- 任务编辑流程
- 方案切换流程
- 定时任务启停
- 主题切换
- Toast 提示
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.slow


class TestWizardFlow:
    """首次启动向导流程。"""

    def test_wizard_full_flow(self, browser_page, live_app, e2e_project):
        """删除 .agree 后应显示向导，同意后进入主应用。"""
        page = browser_page
        base_url, _ = live_app

        # 删除 .agree 文件以触发首次启动向导
        agree_file = e2e_project / "config" / ".agree"
        if agree_file.exists():
            agree_file.unlink()

        # 导航到应用 — 向导应该出现（不使用 goto_app，因为主应用被向导遮挡）
        page.goto(base_url, wait_until="networkidle")
        page.wait_for_selector(".wizard-overlay", state="visible", timeout=15000)

        # 验证向导标题
        title = page.locator(".wizard-container h1")
        assert title.is_visible()
        assert "欢迎使用" in title.text_content()

        # 验证"同意并开始使用"按钮初始禁用（未勾选 checkbox）
        agree_btn = page.locator(
            ".wizard-footer button", has_text="同意并开始使用"
        )
        assert agree_btn.is_disabled()

        # 勾选同意 checkbox（用 force=True 绕过 .toggle-slider 覆盖层）
        page.locator(".terms-checkbox input[type='checkbox']").check(force=True)
        page.wait_for_timeout(300)

        # 按钮应变为可用
        assert agree_btn.is_enabled()

        # 点击同意
        agree_btn.click()

        # 向导应消失
        page.wait_for_selector(".wizard-overlay", state="hidden", timeout=10000)

        # 主应用应可见
        page.wait_for_selector("#app .sidebar", state="visible", timeout=10000)
        assert page.locator(".stats-grid").is_visible()


class TestLoginConfigFlow:
    """登录配置流程。"""

    def test_save_account_config(self, browser_page, live_app, goto_app, navigate_to):
        """填写账号配置 → 保存 → 重载验证持久化。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")

        # 填写账号
        page.locator("#settings-username").fill("e2e_test_user")
        # 填写密码
        page.locator("#settings-password").fill("e2e_test_pass")
        # 填写认证地址
        page.locator("#settings-auth-url").fill("http://10.0.0.1:8080/login")

        # 点击保存
        page.locator(".save-bar .save-btn").click()

        # 等待保存完成（按钮不再禁用）
        page.wait_for_function(
            "() => { const btn = document.querySelector('.save-bar .save-btn');"
            " return btn && !btn.disabled; }",
            timeout=10000,
        )

        # 重载页面验证持久化
        page.reload(wait_until="networkidle")
        page.wait_for_selector("#app .sidebar", state="visible", timeout=15000)
        page.wait_for_selector(".stats-grid, .empty-state", state="visible", timeout=10000)

        navigate_to(page, "settings")

        # 验证用户名已保存
        assert page.locator("#settings-username").input_value() == "e2e_test_user"
        # 验证认证地址已保存
        assert (
            page.locator("#settings-auth-url").input_value()
            == "http://10.0.0.1:8080/login"
        )


class TestTaskEditFlow:
    """任务编辑流程。"""

    def test_create_browser_task(self, browser_page, live_app, goto_app, navigate_to):
        """新建浏览器任务 → 填写 → 保存 → 验证列表更新。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "tasks")

        # 点击新建任务
        page.locator("button", has_text="新建任务").click()
        page.wait_for_timeout(500)

        # 填写任务信息
        page.locator("#task-id").fill("e2e_test_task")
        page.locator("#task-name").fill("E2E 测试任务")

        # 填写有效的 JSON 配置（无危险步骤，每个 step 必须有 id 字段）
        task_json = json.dumps(
            {
                "steps": [
                    {
                        "id": "input_username",
                        "type": "input",
                        "selector": "#username",
                        "value": "{{USERNAME}}",
                        "description": "输入用户名",
                    },
                    {
                        "id": "click_login",
                        "type": "click",
                        "selector": "#loginBtn",
                        "description": "点击登录",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        page.locator("#task-json").fill(task_json)
        page.wait_for_timeout(500)  # 等待 JSON 验证

        # 验证无 JSON 错误
        assert not page.locator(".json-error").is_visible()

        # 点击保存任务
        page.locator("button", has_text="保存任务").click()

        # 等待编辑器关闭
        page.wait_for_selector(".task-editor", state="hidden", timeout=10000)

        # 验证任务出现在列表中
        task_item = page.locator(".task-item", has_text="E2E 测试任务")
        assert task_item.is_visible()


class TestProfileSwitchFlow:
    """方案切换流程。"""

    def test_create_and_switch_profile(self, browser_page, live_app, goto_app, navigate_to):
        """新建方案 → 保存 → 切换激活 → 验证 active 变化。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")

        # 记录初始状态：default 方案应标记为当前
        initial_active = page.locator(".profile-card.active")
        assert initial_active.is_visible()

        # 点击新建方案
        page.locator("button", has_text="新建方案").click()
        page.wait_for_timeout(500)

        # 填写方案信息
        page.locator("#prof-id").fill("e2e_test_profile")
        page.locator("#prof-name").fill("E2E 测试方案")

        # 保存方案
        page.locator("button", has_text="保存方案").click()

        # 等待返回方案列表
        page.wait_for_selector(".profile-editor-topbar", state="hidden", timeout=10000)
        page.wait_for_timeout(500)

        # 验证新方案出现在列表中
        new_card = page.locator(".profile-card", has_text="E2E 测试方案")
        assert new_card.is_visible()

        # 验证 default 仍为当前激活
        default_card = page.locator(".profile-card", has_text="E2E 默认方案")
        assert default_card.locator(".profile-badge.active").is_visible()

        # 点击新方案的"切换"按钮
        new_card.locator("button", has_text="切换").click()

        # 等待 toast 出现（API 调用完成）
        page.wait_for_selector(".toast", state="visible", timeout=10000)
        page.wait_for_timeout(500)

        # 验证新方案变为激活
        assert new_card.locator(".profile-badge.active").is_visible()

        # 验证 default 不再是激活
        assert not default_card.locator(".profile-badge.active").is_visible()


class TestScheduledTaskFlow:
    """定时任务启停流程。"""

    def test_create_and_toggle_scheduled_task(self, browser_page, live_app, e2e_project, goto_app, navigate_to):
        """新建定时任务 → 启用 → 验证状态 → 禁用 → 重新启用。"""
        page = browser_page
        base_url, _ = live_app

        # 预创建脚本文件供定时任务引用
        script_dir = e2e_project / "tasks" / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "e2e_test_script.json").write_text(
            json.dumps(
                {
                    "name": "E2E 测试脚本",
                    "description": "供定时任务引用",
                    "type": "py",
                    "content": "#!/usr/bin/env python3\nprint('hello')\n",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        goto_app(page, base_url)
        navigate_to(page, "scheduled_tasks")

        # 验证初始为空
        assert page.locator(".empty-state", has_text="暂无定时任务").is_visible()

        # 点击新建定时任务
        page.locator("button", has_text="新建定时任务").click()
        page.wait_for_timeout(500)

        # 验证弹窗显示
        assert page.locator(".modal-container").is_visible()

        # 填写任务名称
        page.locator("#scheduled-task-name").fill("E2E 定时任务")

        # 选择目标任务（custom-select 交互）
        # 目标选择是模态框中第二个 custom-select（第一个是任务类型）
        target_select = page.locator(".modal-container .custom-select").nth(1)
        target_select.locator(".custom-select-trigger").click()
        page.wait_for_timeout(300)
        # 点击"E2E 测试脚本"选项
        page.locator(".custom-select-option", has_text="E2E 测试脚本").click()
        page.wait_for_timeout(300)

        # 设置执行时间
        page.locator("#scheduled-task-time").fill("08:30")

        # 点击保存
        page.locator(".modal-footer button", has_text="保存").click()

        # 等待弹窗关闭
        page.wait_for_selector(".modal-container", state="hidden", timeout=10000)
        page.wait_for_timeout(500)

        # 验证任务出现在列表中
        task_item = page.locator(".scheduled-task-item", has_text="E2E 定时任务")
        assert task_item.is_visible()

        # 验证任务初始为启用状态（toggle-switch 有 active 类）
        toggle = task_item.locator(".task-toggle .toggle-switch")
        toggle_class = toggle.get_attribute("class") or ""
        assert "active" in toggle_class

        # 点击 toggle 禁用任务
        toggle.click()

        # 等待 toast 出现（API 调用完成）
        page.wait_for_selector(".toast", state="visible", timeout=10000)
        page.wait_for_timeout(1000)  # 等待列表刷新

        # 验证任务已禁用（task-item 有 disabled 类）
        disabled_item = page.locator(
            ".scheduled-task-item.disabled", has_text="E2E 定时任务"
        )
        assert disabled_item.is_visible()

        # 再次点击 toggle 启用
        disabled_item.locator(".task-toggle .toggle-switch").click()
        page.wait_for_selector(".toast", state="visible", timeout=10000)
        page.wait_for_timeout(1000)

        # 验证任务已重新启用（无 disabled 类）
        enabled_item = page.locator(
            ".scheduled-task-item:not(.disabled)", has_text="E2E 定时任务"
        )
        assert enabled_item.is_visible()


class TestThemeSwitch:
    """主题切换流程。"""

    def test_switch_theme(self, browser_page, live_app, goto_app, navigate_to):
        """切换主题 → 验证 data-theme 属性变化。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "appearance")

        # 点击"深色"主题
        page.locator(".appearance-segmented button", has_text="深色").click()
        page.wait_for_timeout(500)

        # 验证 data-theme 变为 dark
        dark_theme = page.get_attribute("html", "data-theme")
        assert dark_theme == "dark"

        # 点击"浅色"主题
        page.locator(".appearance-segmented button", has_text="浅色").click()
        page.wait_for_timeout(500)

        # 验证 data-theme 变为 light
        light_theme = page.get_attribute("html", "data-theme")
        assert light_theme == "light"

        # 点击"跟随系统"主题
        page.locator(".appearance-segmented button", has_text="跟随系统").click()
        page.wait_for_timeout(500)

        # 验证 data-theme 为 light 或 dark（取决于系统偏好）
        auto_theme = page.get_attribute("html", "data-theme")
        assert auto_theme in ("light", "dark")


class TestToastNotification:
    """Toast 提示测试。"""

    def test_toast_appears_on_toggle_autoswitch(self, browser_page, live_app, goto_app, navigate_to):
        """切换自动开关后 toast 提示应出现。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")

        # 点击自动切换开关（点击 label.toggle 绕过 toggle-slider 覆盖层）
        page.locator(".profiles-topbar label.toggle").click()
        page.wait_for_timeout(300)

        # 等待 toast 出现
        page.wait_for_selector(".toast", state="visible", timeout=10000)

        # 验证 toast 有消息内容
        toast = page.locator(".toast")
        assert toast.is_visible()
        message = toast.locator("span").text_content()
        assert message  # 消息非空

    def test_toast_appears_on_save_profile(self, browser_page, live_app, goto_app, navigate_to):
        """保存方案后 toast 提示应出现。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")

        # 新建方案
        page.locator("button", has_text="新建方案").click()
        page.wait_for_timeout(500)

        page.locator("#prof-id").fill("e2e_toast_test")
        page.locator("#prof-name").fill("Toast 测试方案")

        # 保存方案，等待 toast
        page.locator("button", has_text="保存方案").click()

        # 等待 toast 出现
        page.wait_for_selector(".toast", state="visible", timeout=10000)

        toast = page.locator(".toast")
        assert toast.is_visible()
        message = toast.locator("span").text_content()
        assert message
