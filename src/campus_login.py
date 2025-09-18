#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import random
import sys
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)
from utils import ConfigLoader, LoggerSetup

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
        self.isp = config.get("isp", "@cmcc")  # 默认使用移动
        self.browser_settings = config.get("browser_settings", {})
        self.retry_settings = config.get("retry_settings", {})

        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None  # 用于正确关闭 Playwright

        # 设置日志
        self._setup_logging()

    def _setup_logging(self) -> None:
        """设置日志配置（使用工具类）"""
        log_config = self.config.get('logging', {})
        
        # 使用工具类设置日志
        logger_name = f"{__name__}_{id(self)}"
        self.logger = LoggerSetup.setup_logger(logger_name, log_config)

    async def start_browser(self) -> None:
        """启动浏览器"""
        self.playwright = await async_playwright().start()

        headless = self.browser_settings.get("headless", False)
        
        # 启动浏览器时添加更多反检测参数
        browser_args = [
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=VizDisplayCompositor',
            '--disable-web-security',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-default-apps',
            '--disable-popup-blocking',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images',
            '--disable-javascript',
            '--disable-plugins-discovery',
            '--disable-preconnect',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding'
        ]
        
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=browser_args
        )
        
        # 创建页面时添加反检测上下文
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=self._get_random_user_agent(),
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        )
        
        self.page = await context.new_page()
        
        # 注入反检测脚本
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en'],
            });
            
            window.chrome = {
                runtime: {},
            };
        """)

        self.logger.info(f"浏览器已启动，无头模式: {headless}")
    
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        import random
        user_agents = self.browser_settings.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ])
        return random.choice(user_agents)

    async def navigate_to_auth_page(self) -> bool:
        """导航到认证页面"""
        try:
            if not self.page:
                self.logger.error("页面未初始化")
                return False
                
            timeout = self.browser_settings.get("timeout", 10000)
            self.logger.info(f"正在访问认证页面: {self.auth_url}")

            await self.page.goto(self.auth_url, timeout=timeout)
            await self.page.wait_for_load_state("networkidle", timeout=timeout)

            self.logger.info("成功访问认证页面")
            return True

        except PlaywrightTimeoutError:
            self.logger.error("访问认证页面超时，请检查网络连接或认证地址是否正确")
            return False
        except Exception as e:
            self.logger.error(f"访问认证页面时发生错误: {e}")
            return False

    async def check_already_logged_in(self) -> bool:
        """✅ 重点增强：精准检测已登录状态（支持你提供的页面结构）"""
        try:
            if not self.page:
                return False
                
            # 检测已登录状态的标识符
            login_indicators = [
                ('div[name="PageTips"]', ['成功登录', 'already logged in']),
                ('input[name="logout"], button:has-text("注销"), button:has-text("注  销")', None),
                ('body', ['您已登录', '在线用户', '当前在线', 'logout', '登出', '注销',
                          'already logged in', 'online user', 'logged in', 'success'])
            ]
            
            for selector, keywords in login_indicators:
                try:
                    element = self.page.locator(selector)
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
                                        self.logger.info(f"✅ 检测到已登录状态: {keyword}")
                                        return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            self.logger.warning(f"检测已登录状态时发生异常: {e}")
            return False
    
    async def _find_and_fill_element(self, selectors: list, value: str, element_type: str) -> bool:
        """
        通用的元素查找和填写方法
        
        参数:
            selectors: 选择器列表
            value: 要填入的值
            element_type: 元素类型描述（用于日志）
            
        返回:
            bool: 是否成功填写
        """
        if not self.page:
            return False
            
        for selector in selectors:
            try:
                element = self.page.locator(selector)
                if await element.count() > 0:
                    # 检查元素是否可用
                    is_visible = await element.is_visible()
                    is_enabled = await element.is_enabled()
                    element_input_type = await element.get_attribute('type')
                    
                    if is_visible and is_enabled and element_input_type != 'hidden':
                        await element.clear()
                        await element.fill(value)
                        self.logger.info(f"✅ {element_type}填写成功，使用选择器: {selector}")
                        return True
                    else:
                        self.logger.debug(f"选择器 {selector} 不满足条件: visible={is_visible}, enabled={is_enabled}, type={element_input_type}")
            except Exception as e:
                self.logger.warning(f"{element_type}选择器 {selector} 填写失败: {e}")
                continue
        return False
    
    async def test_connection(self) -> tuple[bool, str]:
        """测试连接到认证页面（修复内存泄漏）"""
        try:
            await self.start_browser()
            
            if not await self.navigate_to_auth_page():
                return False, "无法访问认证页面"
            
            # 检查是否已登录
            if await self.check_already_logged_in():
                return True, "成功连接到认证页面，并检测到已登录状态"
            else:
                return True, "成功连接到认证页面"
                
        except Exception as e:
            error_msg = f"连接测试失败: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        finally:
            # 确保总是清理资源
            await self.cleanup()

    async def fill_login_form(self) -> bool:
        """填写登录表单（简化版）"""
        try:
            if not self.page:
                return False
                
            # 等待表单关键元素出现
            try:
                await self.page.wait_for_selector(
                    'input[name="DDDDD"][type="text"]:visible, input[name="upass"][type="password"]:visible',
                    state="visible", 
                    timeout=3000
                )
                self.logger.info("📝 表单元素已加载")
            except Exception as e:
                self.logger.warning(f"等待表单元素超时: {e}")

            # 用户名选择器（优化优先级）
            username_selectors = [
                'input[name="DDDDD"][type="text"]:visible',
                'input[name="DDDDD"]:not([type="hidden"]):visible',
                'input[type="text"][placeholder*="学工号"]:visible',
                'input[type="text"][placeholder*="用户名"]:visible', 
                'input[name="username"]:visible',
                'input[type="text"]:visible'
            ]

            # 密码选择器（优化优先级）
            password_selectors = [
                'input[name="upass"][type="password"]:visible',
                'input[name="upass"]:not([type="hidden"]):visible',
                'input[type="password"][placeholder*="密码"]:visible',
                'input[name="password"]:visible',
                'input[type="password"]:visible'
            ]

            # 填写用户名
            if not await self._find_and_fill_element(username_selectors, self.username, "用户名"):
                self.logger.error("❌ 未找到可见的用户名输入框")
                return False

            # 填写密码
            if not await self._find_and_fill_element(password_selectors, self.password, "密码"):
                self.logger.error("❌ 未找到可见的密码输入框")
                return False

            # 选择运营商（可选）
            if self.isp and self.isp.strip():
                isp_selectors = [
                    'select[name="ISP_select"]:visible',
                    'select[name="isp"]:visible',
                    '#ISP_select:visible',
                    '#isp:visible'
                ]
                
                for selector in isp_selectors:
                    try:
                        element = self.page.locator(selector)
                        if await element.count() > 0 and await element.is_visible():
                            await element.select_option(self.isp)
                            self.logger.info(f"🌐 运营商选择成功: {self.isp}")
                            break
                    except Exception as e:
                        self.logger.warning(f"运营商选择器 {selector} 失败: {e}")
                        continue
                else:
                    self.logger.warning("⚠️ 未找到运营商选择框，跳过运营商选择")

            return True

        except Exception as e:
            self.logger.error(f"填写表单时发生错误: {e}")
            return False

    async def submit_form(self) -> bool:
        """提交登录表单（简化版）"""
        try:
            if not self.page:
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
                'button:has-text("登录"):visible'
            ]

            # 尝试点击提交按钮
            for selector in submit_selectors:
                try:
                    button = self.page.locator(selector)
                    if await button.count() > 0:
                        is_visible = await button.is_visible()
                        is_enabled = await button.is_enabled()
                        
                        if is_visible and is_enabled:
                            self.logger.info(f"🚀 正在提交认证表单... 使用选择器: {selector}")
                            await button.click()
                            await self.page.wait_for_timeout(2000)
                            self.logger.info("✅ 表单提交完成")
                            return True
                        else:
                            self.logger.debug(f"提交按钮 {selector} 不可用: visible={is_visible}, enabled={is_enabled}")
                except Exception as e:
                    self.logger.warning(f"点击提交按钮 {selector} 失败: {e}")
                    continue

            # Fallback: 聚焦后按回车
            self.logger.info("🔄 未找到提交按钮，尝试聚焦后按回车提交")
            try:
                await self.page.focus('input[name="DDDDD"]')
            except:
                try:
                    await self.page.focus('input[name="upass"]')
                except:
                    self.logger.warning("⚠️ 无法聚焦任何输入框")
            
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_timeout(1000)
            self.logger.info("✅ 回车提交完成")
            return True

        except Exception as e:
            self.logger.error(f"提交表单时发生错误: {e}")
            return False

    async def check_auth_result(self) -> tuple[bool, str]:
        """检查认证结果
        
        返回:
            tuple[bool, str]: (是否成功, 提示信息)
        """
        try:
            if not self.page:
                return False, "页面未初始化"
                
            # 等待页面加载完成，但使用更短的超时时间避免长时间等待
            try:
                await self.page.wait_for_load_state("networkidle", timeout=2000)
            except Exception as e:
                self.logger.debug(f"等待页面加载超时，继续检查登录状态: {e}")
            
            # 直接使用check_already_logged_in函数判断登录状态
            if await self.check_already_logged_in():
                success_msg = "登录成功: 检测到'您已经成功登录'提示"
                self.logger.info(f"✅ {success_msg}")
                return True, success_msg
            
            # 如果没有检测到成功登录，检查是否有失败提示
            failure_indicators = [
                "认证失败", "登录失败", "用户名或密码错误", "账号或密码", "incorrect",
                "authentication failed", "login failed", "invalid username or password",
                "用户不存在", "密码错误", "账户被锁定", "网络异常"
            ]
            
            body_text = (await self.page.text_content("body") or "")
            body_text_lower = body_text.lower()
            
            # 检查失败标识
            for indicator in failure_indicators:
                if indicator.lower() in body_text_lower:
                    failure_msg = f"登录失败: 检测到失败标识 '{indicator}'"
                    self.logger.warning(f"❌ {failure_msg}")
                    if self.page:
                        await self.page.screenshot(path="auth_failed.png")
                        self.logger.info("📸 已保存失败截图: auth_failed.png")
                    return False, failure_msg
            
            # 如果没有明确的成功或失败标识，默认认为失败
            failure_msg = "登录失败: 未检测到明确的成功标识"
            self.logger.warning(f"❌ {failure_msg}")
            if self.page:
                await self.page.screenshot(path="auth_unknown.png")
                self.logger.info("📸 已保存未知状态截图: auth_unknown.png")
            return False, failure_msg
            
        except Exception as e:
            self.logger.error(f"检查认证结果时发生错误: {e}")
            return False, f"检查认证结果时发生错误: {e}"

    async def cleanup(self) -> None:
        """清理资源，防止内存泄漏"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self.page = None
        except Exception as e:
            self.logger.warning(f"清理资源时发生错误: {e}")

    async def authenticate_once(self) -> tuple[bool, str]:
        """执行一次认证尝试（修复内存泄漏）"""
        try:
            await self.start_browser()

            if not await self.navigate_to_auth_page():
                return False, "无法访问认证页面"

            # ✅ 核心修改：在填表单前先检查是否已登录
            if await self.check_already_logged_in():
                self.logger.info("✅ 检测到已登录状态，跳过认证流程")
                return True, "已经处于登录状态"

            if not await self.fill_login_form():
                return False, "填写登录表单失败"

            if not await self.submit_form():
                return False, "提交登录表单失败"

            return await self.check_auth_result()

        except Exception as e:
            error_msg = f"认证过程中发生错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        finally:
            # 确保总是清理资源
            await self.cleanup()

    async def authenticate(self) -> tuple[bool, str]:
        """执行完整的认证流程（包含智能重试机制）
        
        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        max_retries = self.retry_settings.get("max_retries", 3)
        base_retry_interval = self.retry_settings.get("retry_interval", 5)
        last_message = ""
        consecutive_failures = 0

        for attempt in range(max_retries):
            self.logger.info(f"🔁 开始第 {attempt + 1} 次认证尝试")

            # 在重试前添加随机延迟，避免被识别为机器人
            if attempt > 0:
                # 指数退避 + 随机延迟
                delay = base_retry_interval * (2 ** (attempt - 1)) + random.randint(1, 5)
                self.logger.info(f"⏳ 智能延迟 {delay} 秒后重试...")
                await asyncio.sleep(delay)

            success, message = await self.authenticate_once()
            last_message = message

            if success:
                success_info = f"认证成功！({message})"
                self.logger.info(f"🎉 {success_info}")
                return True, success_info

            # 分析失败原因
            failure_type = self._analyze_failure_type(message)
            consecutive_failures += 1
            
            self.logger.warning(f"❌ 第 {attempt + 1} 次尝试失败: {message} (失败类型: {failure_type})")

            # 根据失败类型调整策略
            if failure_type == "blacklisted":
                self.logger.error("🚫 检测到可能被拉黑，建议等待更长时间或手动认证")
                if attempt < max_retries - 1:
                    # 被拉黑时等待更长时间
                    long_delay = 300 + random.randint(0, 120)  # 5-7分钟
                    self.logger.info(f"⏳ 检测到拉黑风险，等待 {long_delay} 秒后重试")
                    await asyncio.sleep(long_delay)
            elif failure_type == "rate_limited":
                self.logger.warning("⏰ 检测到频率限制，增加延迟时间")
                if attempt < max_retries - 1:
                    rate_limit_delay = 60 + random.randint(0, 30)  # 1-1.5分钟
                    self.logger.info(f"⏳ 频率限制延迟 {rate_limit_delay} 秒")
                    await asyncio.sleep(rate_limit_delay)

            if attempt < max_retries - 1:
                continue
            else:
                self.logger.error(f"💥 所有 {max_retries} 次认证尝试均失败")

        failure_info = f"认证失败！已尝试 {max_retries} 次，最后错误: {last_message}"
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
            "authentication fail", "认证失败", "被拒绝", "access denied",
            "forbidden", "blocked", "banned", "拉黑", "限制", "locked"
        ]
        
        # 检测频率限制
        rate_limit_indicators = [
            "too many requests", "rate limit", "频率限制", "请求过于频繁",
            "timeout", "超时", "connection reset"
        ]
        
        # 检测网络问题
        network_indicators = [
            "network error", "网络错误", "connection failed", "连接失败",
            "dns", "无法访问", "unreachable"
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
            
            # 启动非无头模式浏览器
            original_headless = self.browser_settings.get("headless", False)
            self.browser_settings["headless"] = False
            
            await self.start_browser()
            
            if not await self.navigate_to_auth_page():
                return False, "无法访问认证页面"
            
            # 检查是否已登录
            if await self.check_already_logged_in():
                self.logger.info("✅ 检测到已登录状态")
                return True, "已经处于登录状态"
            
            # 填写表单
            if not await self.fill_login_form():
                return False, "填写登录表单失败"
            
            # 提示用户手动点击登录按钮
            self.logger.info("👆 请手动点击登录按钮完成认证...")
            self.logger.info("⏰ 等待30秒，请在此期间完成手动登录...")
            
            # 等待用户手动操作
            await asyncio.sleep(30)
            
            # 检查登录结果
            if await self.check_already_logged_in():
                self.logger.info("✅ 手动认证成功")
                return True, "手动认证成功"
            else:
                self.logger.warning("❌ 手动认证失败或超时")
                return False, "手动认证失败或超时"
                
        except Exception as e:
            error_msg = f"手动认证过程中发生错误: {e}"
            self.logger.error(error_msg)
            return False, error_msg
        finally:
            # 恢复原始设置
            self.browser_settings["headless"] = original_headless
            await self.cleanup()


async def main():
    """主函数"""
    # 从环境变量加载配置
    config = ConfigLoader.load_config_from_env()
    
    # 检查配置
    if not config["username"] or config["username"] == "your_username_here":
        print("❌ 错误: 请在 .env 文件中配置 CAMPUS_USERNAME")
        print("提示: 请参考 .env.example 文件进行配置")
        return

    if not config["password"] or config["password"] == "your_password_here":
        print("❌ 错误: 请在 .env 文件中配置 CAMPUS_PASSWORD")
        print("提示: 请参考 .env.example 文件进行配置")
        return

    print("⚠️  安全提醒：密码以明文存储在 .env 文件中，请确保文件权限安全！\n")

    # 创建认证器实例
    auth = EnhancedCampusNetworkAuth(config)

    print("开始校园网自动认证...")
    print(f"👤 用户名: {config['username']}")
    print(f"🌐 认证URL: {config['auth_url']}\n")

    # 执行认证
    success = await auth.authenticate()

    if success:
        print("\n🎉 校园网认证成功！")
    else:
        print("\n❌ 校园网认证失败，请检查配置、网络连接或查看日志")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 用户中断，程序退出")
        sys.exit(0)