#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import sys

from dotenv import load_dotenv
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from .utils import BrowserContextManager, ConfigLoader, LoggerSetup, SimpleRetryHandler

# 加载环境变量
load_dotenv()


# 配置工具函数 - 已移至utils.py统一管理


class EnhancedCampusNetworkAuth:
    """增强版校园网自动认证类"""

    def __init__(self, config: dict):
        """
        初始化认证器

        Args:
            config: 配置字典
        """
        self.config = config
        self.username = config["username"]
        self.password = config["password"]
        self.auth_url = config["auth_url"]
        self.isp = config.get("isp", "")
        self.browser_settings = config.get("browser_settings", {})
        self.retry_settings = config.get("retry_settings", {})

        # 设置日志
        self._setup_logging()

    def _setup_logging(self) -> None:
        """设置日志配置（使用工具类）"""
        log_config = self.config.get("logging", {})

        # 使用工具类设置日志
        logger_name = f"{__name__}_{id(self)}"
        self.logger = LoggerSetup.setup_logger(logger_name, log_config)

    async def navigate_to_auth_page(
        self, browser_manager: BrowserContextManager
    ) -> bool:
        """导航到认证页面"""
        try:
            self.logger.info(f"正在访问认证页面: {self.auth_url}")
            return await browser_manager.navigate_to(self.auth_url)
        except PlaywrightTimeoutError as e:
            self.logger.error(f"访问认证页面超时: {e}")
            return False
        except ConnectionError as e:
            self.logger.error(f"连接认证页面失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"访问认证页面时发生错误: {type(e).__name__}: {e}")
            return False

    async def check_already_logged_in(
        self, browser_manager: BrowserContextManager
    ) -> bool:
        """✅ 重点增强：精准检测已登录状态（支持你提供的页面结构）"""
        try:
            page = browser_manager.page
            if not page:
                return False

            # 检测已登录状态的标识符
            login_indicators = [
                ('div[name="PageTips"]', ["成功登录", "already logged in"]),
                (
                    'input[name="logout"], button:has-text("注销"), button:has-text("注  销")',
                    None,
                ),
                (
                    "body",
                    [
                        "您已登录",
                        "在线用户",
                        "当前在线",
                        "logout",
                        "登出",
                        "注销",
                        "already logged in",
                        "online user",
                        "logged in",
                        "success",
                    ],
                ),
            ]

            for selector, keywords in login_indicators:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0:
                        if keywords is None:  # 按钮存在即为登录
                            if await element.is_visible(timeout=2000):
                                self.logger.info("✅ 检测到'注销'按钮，说明已登录")
                                return True
                        else:  # 检查文本内容
                            text_content = await element.text_content(timeout=2000)
                            if text_content:
                                for keyword in keywords:
                                    if keyword.lower() in text_content.lower():
                                        self.logger.info(
                                            f"✅ 检测到已登录状态: {keyword}"
                                        )
                                        return True
                except PlaywrightTimeoutError:
                    continue
                except RuntimeError:
                    continue

            return False

        except AttributeError as e:
            self.logger.warning(f"页面对象属性错误: {e}")
            return False
        except Exception as e:
            self.logger.warning(f"检测已登录状态时发生异常: {type(e).__name__}: {e}")
            return False

    async def _find_and_fill_element(
        self,
        browser_manager: BrowserContextManager,
        selectors: list,
        value: str,
        element_type: str,
    ) -> bool:
        """
        通用的元素查找和填写方法

        参数:
            browser_manager: 浏览器管理器
            selectors: 选择器列表
            value: 要填入的值
            element_type: 元素类型描述（用于日志）

        返回:
            bool: 是否成功填写
        """
        page = browser_manager.page
        if not page:
            return False

        for selector in selectors:
            try:
                element = page.locator(selector)
                if await element.count() > 0:
                    # 检查元素是否可用
                    is_visible = await element.is_visible()
                    is_enabled = await element.is_enabled()
                    element_input_type = await element.get_attribute("type")

                    if is_visible and is_enabled and element_input_type != "hidden":
                        await element.clear()
                        await element.fill(value)
                        self.logger.info(
                            f"✅ {element_type}填写成功，使用选择器: {selector}"
                        )
                        return True
                    else:
                        self.logger.debug(
                            f"选择器 {selector} 不满足条件: visible={is_visible}, enabled={is_enabled}, type={element_input_type}"
                        )
            except PlaywrightTimeoutError as e:
                self.logger.debug(f"{element_type}选择器 {selector} 超时: {e}")
                continue
            except RuntimeError as e:
                self.logger.debug(f"{element_type}选择器 {selector} 运行时错误: {e}")
                continue
            except Exception as e:
                self.logger.warning(
                    f"{element_type}选择器 {selector} 填写失败: {type(e).__name__}: {e}"
                )
                continue
        return False

    async def test_connection(self) -> tuple[bool, str]:
        """测试连接到认证页面（使用上下文管理器修复内存泄漏）"""
        try:
            async with BrowserContextManager(self.config) as browser_manager:
                if not await self.navigate_to_auth_page(browser_manager):
                    return False, "无法访问认证页面"

                # 检查是否已登录
                if await self.check_already_logged_in(browser_manager):
                    return True, "成功连接到认证页面，并检测到已登录状态"
                else:
                    return True, "成功连接到认证页面"

        except Exception as e:
            error_msg = f"连接测试失败: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    async def fill_login_form(self, browser_manager: BrowserContextManager) -> bool:
        """填写登录表单（简化版）"""
        try:
            page = browser_manager.page
            if not page:
                return False

            # 等待表单关键元素出现
            try:
                await page.wait_for_selector(
                    'input[name="DDDDD"][type="text"]:visible, input[name="upass"][type="password"]:visible',
                    state="visible",
                    timeout=3000,
                )
                self.logger.info("📝 表单元素已加载")
            except PlaywrightTimeoutError:
                self.logger.warning("等待表单元素超时")
            except Exception as e:
                self.logger.warning(f"等待表单元素异常: {type(e).__name__}: {e}")

            # 用户名选择器（优化优先级）
            username_selectors = [
                'input[name="DDDDD"][type="text"]:visible',
                'input[name="DDDDD"]:not([type="hidden"]):visible',
                'input[type="text"][placeholder*="学工号"]:visible',
                'input[type="text"][placeholder*="用户名"]:visible',
                'input[name="username"]:visible',
                'input[type="text"]:visible',
            ]

            # 密码选择器（优化优先级）
            password_selectors = [
                'input[name="upass"][type="password"]:visible',
                'input[name="upass"]:not([type="hidden"]):visible',
                'input[type="password"][placeholder*="密码"]:visible',
                'input[name="password"]:visible',
                'input[type="password"]:visible',
            ]

            # 填写用户名
            if not await self._find_and_fill_element(
                browser_manager, username_selectors, self.username, "用户名"
            ):
                self.logger.error("❌ 未找到可见的用户名输入框")
                return False

            # 填写密码
            if not await self._find_and_fill_element(
                browser_manager, password_selectors, self.password, "密码"
            ):
                self.logger.error("❌ 未找到可见的密码输入框")
                return False

            # 选择运营商（可选）
            if self.isp and self.isp.strip():
                isp_selectors = [
                    'select[name="ISP_select"]:visible',
                    'select[name="isp"]:visible',
                    "#ISP_select:visible",
                    "#isp:visible",
                ]

                for selector in isp_selectors:
                    try:
                        element = page.locator(selector)
                        if await element.count() > 0 and await element.is_visible():
                            await element.select_option(self.isp)
                            self.logger.info(f"🌐 运营商选择成功: {self.isp}")
                            break
                    except PlaywrightTimeoutError:
                        self.logger.debug(f"运营商选择器 {selector} 超时")
                        continue
                    except RuntimeError as e:
                        self.logger.debug(f"运营商选择器 {selector} 错误: {e}")
                        continue
                    except Exception as e:
                        self.logger.warning(
                            f"运营商选择器 {selector} 失败: {type(e).__name__}: {e}"
                        )
                        continue
                else:
                    self.logger.warning("⚠️ 未找到运营商选择框，跳过运营商选择")

            return True

        except RuntimeError as e:
            self.logger.error(f"填写表单时运行时错误: {e}")
            return False
        except Exception as e:
            self.logger.error(f"填写表单时发生错误: {type(e).__name__}: {e}")
            return False

    async def submit_form(self, browser_manager: BrowserContextManager) -> bool:
        """提交登录表单（简化版）"""
        try:
            page = browser_manager.page
            if not page:
                return False

            # 提交按钮选择器（优化优先级）
            submit_selectors = [
                'input[name="0MKKey"][type="button"]:visible',
                'input[name="0MKKey"]:not([type="hidden"]):visible',
                'input[onclick*="ee(1)"]:visible',
                'input[value="登录"][type="button"]:visible',
                'input[value="登录"]:visible',
                'input[type="submit"]:visible',
                'button[type="submit"]:visible',
                'button:has-text("登录"):visible',
            ]

            # 尝试点击提交按钮
            for selector in submit_selectors:
                try:
                    button = page.locator(selector)
                    if await button.count() > 0:
                        is_visible = await button.is_visible()
                        is_enabled = await button.is_enabled()

                        if is_visible and is_enabled:
                            self.logger.info(
                                f"🚀 正在提交认证表单... 使用选择器: {selector}"
                            )
                            await button.click()
                            await page.wait_for_timeout(2000)
                            self.logger.info("✅ 表单提交完成")
                            return True
                        else:
                            self.logger.debug(
                                f"提交按钮 {selector} 不可用: visible={is_visible}, enabled={is_enabled}"
                            )
                except PlaywrightTimeoutError as e:
                    self.logger.debug(f"点击提交按钮 {selector} 超时: {e}")
                    continue
                except RuntimeError as e:
                    self.logger.debug(f"点击提交按钮 {selector} 错误: {e}")
                    continue
                except Exception as e:
                    self.logger.warning(
                        f"点击提交按钮 {selector} 失败: {type(e).__name__}: {e}"
                    )
                    continue

            # Fallback: 聚焦后按回车
            self.logger.info("🔄 未找到提交按钮，尝试聚焦后按回车提交")
            try:
                await page.focus('input[name="DDDDD"]')
            except PlaywrightTimeoutError:
                try:
                    await page.focus('input[name="upass"]')
                except PlaywrightTimeoutError:
                    self.logger.warning("⚠️ 无法聚焦任何输入框")
            except Exception:
                try:
                    await page.focus('input[name="upass"]')
                except Exception:
                    self.logger.warning("⚠️ 无法聚焦任何输入框")

            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1000)
            self.logger.info("✅ 回车提交完成")
            return True

        except RuntimeError as e:
            self.logger.error(f"提交表单时运行时错误: {e}")
            return False
        except Exception as e:
            self.logger.error(f"提交表单时发生错误: {type(e).__name__}: {e}")
            return False

    async def check_auth_result(
        self, browser_manager: BrowserContextManager
    ) -> tuple[bool, str]:
        """检查认证结果

        返回:
            tuple[bool, str]: (是否成功, 提示信息)
        """
        try:
            page = browser_manager.page
            if not page:
                return False, "页面未初始化"

            # 等待页面加载完成，但使用更短的超时时间避免长时间等待
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except PlaywrightTimeoutError:
                self.logger.debug("等待页面加载超时，继续检查登录状态")
            except Exception as e:
                self.logger.debug(f"等待页面加载异常: {type(e).__name__}: {e}")

            # 直接使用check_already_logged_in函数判断登录状态
            if await self.check_already_logged_in(browser_manager):
                success_msg = "登录成功: 检测到'您已经成功登录'提示"
                self.logger.info(f"✅ {success_msg}")
                return True, success_msg

            # 如果没有检测到成功登录，检查是否有失败提示
            failure_indicators = [
                "认证失败",
                "登录失败",
                "用户名或密码错误",
                "账号或密码",
                "incorrect",
                "authentication failed",
                "login failed",
                "invalid username or password",
                "用户不存在",
                "密码错误",
                "账户被锁定",
                "网络异常",
            ]

            body_text = await page.text_content("body") or ""
            body_text_lower = body_text.lower()

            # 检查失败标识
            for indicator in failure_indicators:
                if indicator.lower() in body_text_lower:
                    failure_msg = f"登录失败: 检测到失败标识 '{indicator}'"
                    self.logger.warning(f"❌ {failure_msg}")
                    # 保存截图用于调试
                    try:
                        await browser_manager.take_screenshot("debug/auth_failed.png")
                    except (PlaywrightTimeoutError, RuntimeError, OSError):
                        pass
                    return False, failure_msg

            # 如果没有明确的成功或失败标识，默认认为失败
            failure_msg = "登录失败: 未检测到明确的成功标识"
            self.logger.warning(f"❌ {failure_msg}")
            try:
                await browser_manager.take_screenshot("debug/auth_unknown.png")
            except (PlaywrightTimeoutError, RuntimeError, OSError):
                pass
            return False, failure_msg

        except PlaywrightTimeoutError as e:
            self.logger.error(f"检查认证结果超时: {e}")
            return False, f"检查认证结果超时: {e}"
        except RuntimeError as e:
            self.logger.error(f"检查认证结果运行时错误: {e}")
            return False, f"检查认证结果运行时错误: {e}"
        except Exception as e:
            self.logger.error(f"检查认证结果时发生错误: {type(e).__name__}: {e}")
            return False, f"检查认证结果时发生错误: {e}"

    async def authenticate_once(self) -> tuple[bool, str]:
        """执行一次认证尝试（使用上下文管理器修复内存泄漏）"""
        try:
            async with BrowserContextManager(self.config) as browser_manager:
                if not await self.navigate_to_auth_page(browser_manager):
                    return False, "无法访问认证页面"

                # ✅ 核心修改：在填表单前先检查是否已登录
                if await self.check_already_logged_in(browser_manager):
                    self.logger.info("✅ 检测到已登录状态，跳过认证流程")
                    return True, "已经处于登录状态"

                if not await self.fill_login_form(browser_manager):
                    return False, "填写登录表单失败"

                if not await self.submit_form(browser_manager):
                    return False, "提交登录表单失败"

                return await self.check_auth_result(browser_manager)

        except PlaywrightTimeoutError as e:
            error_msg = f"认证超时: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except ConnectionError as e:
            error_msg = f"认证连接错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except RuntimeError as e:
            error_msg = f"认证运行时错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"认证过程中发生错误: {type(e).__name__}: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        # 无需手动清理，上下文管理器会自动处理

    async def authenticate(self) -> tuple[bool, str]:
        """执行完整的认证流程（使用简单重试机制）

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        retry_handler = SimpleRetryHandler(self.config)

        async def auth_operation():
            """重试操作封装"""
            return await self.authenticate_once()

        success, result, error_msg = await retry_handler.retry_with_simple_backoff(
            auth_operation
        )

        if success:
            success_status, message = result
            if success_status:
                success_info = f"认证成功！({message})"
                self.logger.info(f"🎉 {success_info}")
                return True, success_info
            else:
                return False, message
        else:
            failure_info = f"认证失败！{error_msg}"
            return False, failure_info

    def _analyze_failure_type(self, error_message: str) -> str:
        """分析失败类型

        参数:
            error_message: 错误消息

        返回:
            str: 失败类型
        """
        error_lower = error_message.lower()

        # 检测可能的拉黑情况
        blacklist_indicators = [
            "authentication fail",
            "认证失败",
            "被拒绝",
            "access denied",
            "forbidden",
            "blocked",
            "banned",
            "拉黑",
            "限制",
            "locked",
        ]

        # 检测频率限制
        rate_limit_indicators = [
            "too many requests",
            "rate limit",
            "频率限制",
            "请求过于频繁",
            "timeout",
            "超时",
            "connection reset",
        ]

        # 检测网络问题
        network_indicators = [
            "network error",
            "网络错误",
            "connection failed",
            "连接失败",
            "dns",
            "无法访问",
            "unreachable",
        ]

        for indicator in blacklist_indicators:
            if indicator in error_lower:
                return "blacklisted"

        for indicator in rate_limit_indicators:
            if indicator in error_lower:
                return "rate_limited"

        for indicator in network_indicators:
            if indicator in error_lower:
                return "network_error"

        return "unknown"

    async def manual_auth_fallback(self) -> tuple[bool, str]:
        """手动认证备选方案

        当自动认证失败时，提供手动认证选项

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            self.logger.info("🔄 启动手动认证备选方案...")

            # 修改配置为非无头模式
            modified_config = self.config.copy()
            modified_config["browser_settings"] = self.browser_settings.copy()
            modified_config["browser_settings"]["headless"] = False

            async with BrowserContextManager(modified_config) as browser_manager:
                if not await self.navigate_to_auth_page(browser_manager):
                    return False, "无法访问认证页面"

                # 检查是否已登录
                if await self.check_already_logged_in(browser_manager):
                    self.logger.info("✅ 检测到已登录状态")
                    return True, "已经处于登录状态"

                # 填写表单
                if not await self.fill_login_form(browser_manager):
                    return False, "填写登录表单失败"

                # 提示用户手动点击登录按钮
                self.logger.info("👆 请手动点击登录按钮完成认证...")
                self.logger.info("⏰ 等待30秒，请在此期间完成手动登录...")

                # 等待用户手动操作
                await asyncio.sleep(30)

                # 检查登录结果
                if await self.check_already_logged_in(browser_manager):
                    self.logger.info("✅ 手动认证成功")
                    return True, "手动认证成功"
                else:
                    self.logger.warning("❌ 手动认证失败或超时")
                    return False, "手动认证失败或超时"

        except PlaywrightTimeoutError as e:
            error_msg = f"手动认证超时: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except ConnectionError as e:
            error_msg = f"手动认证连接错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except RuntimeError as e:
            error_msg = f"手动认证运行时错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"手动认证过程中发生错误: {type(e).__name__}: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        # 上下文管理器会自动恢复原始设置


async def main():
    """主函数"""
    # 从环境变量加载配置
    config = ConfigLoader.load_config_from_env()

    # 检查配置
    if not config["username"] or config["username"] == "your_username_here":
        print("❌ 错误: 请在 .env 文件中配置 USERNAME")
        print("提示: 请参考 .env.example 文件进行配置")
        return

    if not config["password"] or config["password"] == "your_password_here":
        print("❌ 错误: 请在 .env 文件中配置 PASSWORD")
        print("提示: 请参考 .env.example 文件进行配置")
        return

    print("⚠️  安全提醒：密码以明文存储在 .env 文件中，请确保文件权限安全！\n")

    # 创建认证器实例
    auth = EnhancedCampusNetworkAuth(config)

    print("开始校园网自动认证...")
    print(f"👤 用户名: {config['username']}")
    print(f"🌐 认证URL: {config['auth_url']}\n")

    # 执行认证
    success, message = await auth.authenticate()

    if success:
        print("\n🎉 校园网认证成功！")
    else:
        print(f"\n❌ 校园网认证失败: {message}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 用户中断，程序退出")
        sys.exit(0)
