"""前端 E2E 全量页面回归测试。

对每个页面做回归：
- 页面能正常加载（无 JS 错误）
- 侧边栏导航能切换到该页面
- 关键元素存在且可见
- 表单能填写、按钮能点击
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


class TestDashboardPage:
    """仪表盘页面回归。"""

    def test_dashboard_default_page(self, browser_page, live_app, goto_app, navigate_to):
        """应用打开后默认显示仪表盘。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        # 仪表盘是默认页，应有状态卡片
        assert page.locator(".stats-grid").is_visible()
        # 四个统计卡片：运行时长、检测次数、登录次数、最后检测
        cards = page.locator(".stat-card")
        assert cards.count() == 4
        # 卡片标签可见
        assert page.locator(".stat-label", has_text="运行时长").is_visible()
        assert page.locator(".stat-label", has_text="检测次数").is_visible()
        assert page.locator(".stat-label", has_text="登录次数").is_visible()
        assert page.locator(".stat-label", has_text="最后检测").is_visible()

    def test_dashboard_quick_actions(self, browser_page, live_app, goto_app, navigate_to):
        """快捷操作区有手动登录和网络测试按钮。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        # 快捷操作卡片
        assert page.locator(".card", has_text="快捷操作").is_visible()
        # 手动登录按钮
        login_btn = page.locator(".action-buttons button", has_text="手动登录")
        assert login_btn.is_visible()
        # 网络测试按钮
        test_btn = page.locator(".action-buttons button", has_text="网络测试")
        assert test_btn.is_visible()

    def test_dashboard_login_history(self, browser_page, live_app, goto_app, navigate_to):
        """登录历史卡片存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        assert page.locator(".card", has_text="登录历史").is_visible()

    def test_dashboard_log_viewer(self, browser_page, live_app, goto_app, navigate_to):
        """实时日志卡片存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        assert page.locator(".card", has_text="实时日志").is_visible()
        # 日志查看器
        assert page.locator(".log-viewer").is_visible()
        # 日志工具栏（筛选/搜索）
        assert page.locator(".log-toolbar").is_visible()


class TestSettingsPage:
    """设置页面回归 — 含 5 个子标签。"""

    def test_settings_tab_navigation(self, browser_page, live_app, goto_app, navigate_to):
        """设置页面默认显示账号设置标签，并能切换到其他标签。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")

        # 5 个标签按钮
        tabs = page.locator(".settings-tab")
        assert tabs.count() == 5
        # 默认是 account 标签
        assert page.locator(".settings-tab.active", has_text="账号设置").is_visible()

    def test_settings_account_form(self, browser_page, live_app, goto_app, navigate_to):
        """账号设置表单可填写。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")

        # 账号输入框
        username_input = page.locator("#settings-username")
        assert username_input.is_visible()
        # 密码输入框
        assert page.locator("#settings-password").is_visible()
        # 认证地址输入框
        assert page.locator("#settings-auth-url").is_visible()

        # 填写账号
        username_input.fill("test_user_e2e")
        assert username_input.input_value() == "test_user_e2e"

    def test_settings_monitor_tab(self, browser_page, live_app, goto_app, navigate_to):
        """网络与监控标签可切换，关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")
        # 切到 monitor 标签
        page.locator(".settings-tab", has_text="网络与监控").click()
        page.wait_for_timeout(300)

        # 检测间隔输入框
        assert page.locator("#settings-interval").is_visible()
        # 最大重试次数
        assert page.locator("#settings-max-retries").is_visible()
        # 重试间隔
        assert page.locator("#settings-retry-interval").is_visible()

        # 修改检测间隔
        interval_input = page.locator("#settings-interval")
        interval_input.fill("60")
        assert interval_input.input_value() == "60"

    def test_settings_system_tab(self, browser_page, live_app, goto_app, navigate_to):
        """系统与日志标签可切换，关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")
        page.locator(".settings-tab", has_text="系统与日志").click()
        page.wait_for_timeout(300)

        # 日志保留天数
        assert page.locator("#settings-log-retention").is_visible()
        # 控制台端口
        assert page.locator("#settings-app-port").is_visible()

    def test_settings_browser_tab(self, browser_page, live_app, goto_app, navigate_to):
        """浏览器设置标签可切换，关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")
        page.locator(".settings-tab", has_text="浏览器设置").click()
        page.wait_for_timeout(500)

        # 浏览器设置面板应可见
        # 基本设置卡片
        assert page.locator(".card", has_text="基本设置").is_visible()
        # 页面操作超时输入框
        assert page.locator("#settings-browser-timeout").is_visible()

    def test_settings_tasks_tab(self, browser_page, live_app, goto_app, navigate_to):
        """任务设置标签可切换，关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")
        page.locator(".settings-tab", has_text="任务设置").click()
        page.wait_for_timeout(500)

        # 任务概览卡片
        assert page.locator(".card", has_text="任务概览").is_visible()
        # 任务录制器卡片
        assert page.locator(".card", has_text="任务录制器").is_visible()
        # OCR 依赖卡片
        assert page.locator(".card", has_text="OCR 依赖").is_visible()

    def test_settings_save_button(self, browser_page, live_app, goto_app, navigate_to):
        """保存按钮存在且可点击。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "settings")
        # 保存按钮
        save_btn = page.locator(".save-bar .save-btn")
        assert save_btn.is_visible()
        assert page.locator(".save-bar").is_visible()


class TestTasksPage:
    """任务管理页面回归。"""

    def test_tasks_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """任务管理页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "tasks")

        # 任务列表卡片
        assert page.locator(".card", has_text="任务列表").is_visible()
        # 新建任务按钮
        assert page.locator("button", has_text="新建任务").is_visible()
        # 导入按钮（用 title 精确定位，避免与"远程仓库导入"冲突）
        assert page.locator("button[title='从文件导入任务']").is_visible()
        # 远程仓库导入按钮
        assert page.locator("button[title='从任务仓库导入']").is_visible()

    def test_tasks_new_editor(self, browser_page, live_app, goto_app, navigate_to):
        """点击新建任务后显示编辑器。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "tasks")
        # 点击新建任务
        page.locator("button", has_text="新建任务").click()
        page.wait_for_timeout(500)

        # 编辑器卡片
        editor = page.locator(".task-editor")
        assert editor.is_visible()
        # 任务 ID 输入框
        assert page.locator("#task-id").is_visible()
        # 任务名称输入框
        assert page.locator("#task-name").is_visible()
        # JSON 配置文本框
        assert page.locator("#task-json").is_visible()
        # 保存任务按钮
        assert page.locator("button", has_text="保存任务").is_visible()
        # 取消按钮
        assert page.locator("button", has_text="取消").is_visible()

    def test_tasks_help_content(self, browser_page, live_app, goto_app, navigate_to):
        """未编辑任务时显示 JSON 配置说明。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "tasks")

        # 当未在编辑态时显示说明卡片
        assert page.locator(".card", has_text="JSON 配置说明").is_visible()
        # 支持的步骤类型说明
        assert page.locator(".help-content h4", has_text="支持的步骤类型").is_visible()


class TestProfilesPage:
    """配置方案页面回归。"""

    def test_profiles_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """配置方案页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")

        # 顶部状态栏
        assert page.locator(".profiles-topbar").is_visible()
        # 新建方案按钮
        assert page.locator("button", has_text="新建方案").is_visible()
        # 自动切换开关
        assert page.locator(".profiles-topbar .toggle").is_visible()
        # 方案列表或空状态
        assert page.locator(".profiles-list").is_visible() or page.locator(
            ".profiles-empty"
        ).is_visible()

    def test_profiles_default_exists(self, browser_page, live_app, goto_app, navigate_to):
        """默认方案存在并显示在列表中。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")

        # e2e_project 写入了 default 方案，应至少有一个方案卡片
        cards = page.locator(".profile-card")
        assert cards.count() >= 1
        # default 方案应标记为当前
        active_card = page.locator(".profile-card.active")
        assert active_card.is_visible()

    def test_profiles_new_editor(self, browser_page, live_app, goto_app, navigate_to):
        """点击新建方案后进入编辑页面。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "profiles")
        page.locator("button", has_text="新建方案").click()
        page.wait_for_timeout(500)

        # 编辑器顶部
        assert page.locator(".profile-editor-topbar").is_visible()
        # 方案 ID 输入框
        assert page.locator("#prof-id").is_visible()
        # 方案名称输入框
        assert page.locator("#prof-name").is_visible()
        # 保存方案按钮
        assert page.locator("button", has_text="保存方案").is_visible()


class TestScheduledTasksPage:
    """定时任务页面回归。"""

    def test_scheduled_tasks_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """定时任务页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "scheduled_tasks")

        # 任务列表卡片
        assert page.locator(".card", has_text="定时任务").is_visible()
        # 新建定时任务按钮
        assert page.locator("button", has_text="新建定时任务").is_visible()

    def test_scheduled_tasks_new_modal(self, browser_page, live_app, goto_app, navigate_to):
        """点击新建定时任务后显示弹窗。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "scheduled_tasks")
        page.locator("button", has_text="新建定时任务").click()
        page.wait_for_timeout(500)

        # 弹窗容器
        modal = page.locator(".modal-container")
        assert modal.is_visible()
        # 任务名称输入框
        assert page.locator("#scheduled-task-name").is_visible()
        # 执行时间输入框
        assert page.locator("#scheduled-task-time").is_visible()
        # 保存按钮
        assert page.locator("button", has_text="保存").is_visible()


class TestScriptsPage:
    """脚本管理页面回归。"""

    def test_scripts_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """脚本管理页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "scripts")

        # 脚本列表卡片
        assert page.locator(".card", has_text="自定义脚本").is_visible()
        # 新建脚本按钮
        assert page.locator("button", has_text="新建脚本").is_visible()
        # 导入按钮（用 title 精确定位）
        assert page.locator("button[title='从文件导入脚本']").is_visible()

    def test_scripts_new_editor(self, browser_page, live_app, goto_app, navigate_to):
        """点击新建脚本后显示编辑器。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "scripts")
        page.locator("button", has_text="新建脚本").click()
        page.wait_for_timeout(500)

        # 编辑器卡片
        editor = page.locator(".task-editor")
        assert editor.is_visible()
        # 脚本 ID 输入框
        assert page.locator("#script-id").is_visible()
        # 脚本名称输入框
        assert page.locator("#script-name").is_visible()
        # 保存脚本按钮
        assert page.locator("button", has_text="保存脚本").is_visible()


class TestAboutPage:
    """关于页面回归。"""

    def test_about_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """关于页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "about")

        # 标题
        assert page.locator("h1", has_text="校园网自动认证").is_visible()
        # 版本信息
        assert page.locator(".version").is_visible()
        # 检查更新按钮
        assert page.locator("button", has_text="检查更新").is_visible()
        # GitHub 链接
        assert page.locator("a", has_text="GitHub").is_visible()

    def test_about_tech_stack(self, browser_page, live_app, goto_app, navigate_to):
        """技术栈卡片存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "about")

        # 技术栈卡片
        assert page.locator(".card", has_text="技术栈与工具链").is_visible()
        # 技术徽章
        badges = page.locator(".tech-badge")
        assert badges.count() >= 4

    def test_about_system_info(self, browser_page, live_app, goto_app, navigate_to):
        """系统信息卡片存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "about")

        # 系统信息卡片
        assert page.locator(".card", has_text="系统信息").is_visible()
        # Python 版本信息项
        assert page.locator(".info-label", has_text="Python").is_visible()


class TestAppearancePage:
    """外观设置页面回归。"""

    def test_appearance_page_elements(self, browser_page, live_app, goto_app, navigate_to):
        """外观页面关键元素存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "appearance")

        # 4 个设置卡片
        assert page.locator(".card", has_text="背景与氛围").is_visible()
        assert page.locator(".card", has_text="主题与配色").is_visible()
        assert page.locator(".card", has_text="卡片样式").is_visible()
        assert page.locator(".card", has_text="侧边栏").is_visible()

    def test_appearance_theme_buttons(self, browser_page, live_app, goto_app, navigate_to):
        """主题切换按钮存在（浅色/深色/跟随系统）。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "appearance")

        # 主题切换分段按钮（.appearance-segmented 是唯一的，直接定位）
        theme_section = page.locator(".appearance-segmented").first
        assert theme_section.is_visible()
        # 三个主题选项
        assert theme_section.locator("button", has_text="浅色").is_visible()
        assert theme_section.locator("button", has_text="深色").is_visible()
        assert theme_section.locator("button", has_text="跟随系统").is_visible()

    def test_appearance_sliders(self, browser_page, live_app, goto_app, navigate_to):
        """滑块控件存在。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        navigate_to(page, "appearance")

        # 背景模糊滑块
        assert page.locator("#bg-blur").is_visible()
        # 背景可见度滑块
        assert page.locator("#bg-opacity").is_visible()
        # 玻璃模糊度滑块
        assert page.locator("#card-blur").is_visible()


class TestSidebarNavigation:
    """侧边栏导航完整性测试。"""

    def test_all_pages_navigable(self, browser_page, live_app, goto_app, navigate_to):
        """所有页面都能通过侧边栏导航到达。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        # 依次导航到每个页面，验证页面切换
        pages_to_test = [
            ("dashboard", ".stats-grid"),
            ("settings", ".settings-tab"),
            ("tasks", ".tasks-grid"),
            ("about", ".about-container"),
            ("profiles", ".profiles-topbar"),
            ("scripts", ".tasks-grid"),
            ("scheduled_tasks", ".scheduled-tasks-page"),
            ("appearance", ".appearance-page"),
        ]

        for page_name, selector in pages_to_test:
            navigate_to(page, page_name)
            # 验证目标页面的关键元素可见
            assert page.locator(selector).first.is_visible(), (
                f"导航到 {page_name} 后未找到元素 {selector}"
            )

    def test_sidebar_active_state(self, browser_page, live_app, goto_app, navigate_to):
        """导航后侧边栏对应项应标记为 active。"""
        page = browser_page
        base_url, _ = live_app
        goto_app(page, base_url)

        # 导航到 tasks
        navigate_to(page, "tasks")
        # tasks 导航项应有 active 类
        active_nav = page.locator(".nav-links > .nav-item.active", has_text="任务管理")
        assert active_nav.is_visible()

        # 导航到 about
        navigate_to(page, "about")
        active_nav = page.locator(".nav-links > .nav-item.active", has_text="关于")
        assert active_nav.is_visible()
