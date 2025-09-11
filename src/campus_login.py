#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

# 加载环境变量
load_dotenv()


def load_config_from_env() -> dict:
    """从环境变量加载配置"""
    
    def str_to_bool(value: str) -> bool:
        """将字符串转换为布尔值"""
        return value.lower() in ('true', '1', 'yes', 'on')
    
    def get_int_env(key: str, default: int) -> int:
        """获取整数环境变量"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default
    
    return {
        "username": os.getenv("CAMPUS_USERNAME", ""),
        "password": os.getenv("CAMPUS_PASSWORD", ""),
        "auth_url": os.getenv("CAMPUS_AUTH_URL", "http://172.29.0.2"),
        "isp": os.getenv("CAMPUS_ISP", "@cmcc"),
        "auto_start_monitoring": str_to_bool(os.getenv("AUTO_START_MONITORING", "false")),
        
        "browser_settings": {
            "headless": str_to_bool(os.getenv("BROWSER_HEADLESS", "false")),
            "timeout": get_int_env("BROWSER_TIMEOUT", 10000),
            "user_agent": os.getenv(
                "BROWSER_USER_AGENT",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
        
        "retry_settings": {
            "max_retries": get_int_env("RETRY_MAX_RETRIES", 3),
            "retry_interval": get_int_env("RETRY_INTERVAL", 5)
        },
        
        "logging": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "format": os.getenv("LOG_FORMAT", "%(asctime)s - %(levelname)s - %(message)s"),
            "file": os.getenv("LOG_FILE", "logs/campus_auth.log") or None  # 空字符串转为None
        },
        
        "monitor": {
            "interval": get_int_env("MONITOR_INTERVAL", 240),
            "ping_targets": [target.strip() for target in os.getenv("PING_TARGETS", "8.8.8.8,114.114.114.114,baidu.com").split(",") if target.strip()]
        }
    }


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
        """设置日志配置（带容错）"""
        log_config = self.config.get('logging', {})
        
        # 创建唯一的logger名称，避免重复
        logger_name = f"{__name__}_{id(self)}"
        self.logger = logging.getLogger(logger_name)
        
        # 如果logger已经有处理器，说明已经配置过，直接返回
        if self.logger.handlers:
            return
            
        # 设置日志级别
        self.logger.setLevel(getattr(logging, log_config.get("level", "INFO")))
        
        # 创建格式器
        formatter = logging.Formatter(
            log_config.get("format", "%(asctime)s - %(levelname)s - %(message)s")
        )
        
        # 添加文件处理器
        if log_config.get("file"):
            import os
            log_file = log_config["file"]
            # 确保日志目录存在
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # 防止日志传播到根logger，避免重复输出
        self.logger.propagate = False

    async def start_browser(self) -> None:
        """启动浏览器"""
        self.playwright = await async_playwright().start()

        headless = self.browser_settings.get("headless", False)
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.page = await self.browser.new_page()

        user_agent = self.browser_settings.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        await self.page.set_extra_http_headers({"User-Agent": user_agent})

        self.logger.info(f"浏览器已启动，无头模式: {headless}")

    async def navigate_to_auth_page(self) -> bool:
        """导航到认证页面"""
        try:
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
            await self.page.wait_for_load_state("networkidle", timeout=5000)

            # 🎯 方案1：检测 <div name="PageTips">您已经成功登录。</div>
            page_tips_locator = self.page.locator('div[name="PageTips"]')
            if await page_tips_locator.count() > 0:
                tip_text = await page_tips_locator.text_content()
                if tip_text and ("成功登录" in tip_text or "already logged in" in tip_text.lower()):
                    self.logger.info(f"✅ 检测到已登录提示: {tip_text.strip()}")
                    return True

            # 🎯 方案2：检测注销按钮 <input name="logout" value="注  销">
            logout_button_locator = self.page.locator('input[name="logout"], button:has-text("注销"), button:has-text("注  销")')
            if await logout_button_locator.count() > 0 and await logout_button_locator.is_visible():
                self.logger.info("✅ 检测到“注销”按钮，说明已登录")
                return True

            # 🎯 方案3：通用文本兜底检测
            body_text = await self.page.text_content("body")
            if body_text:
                indicators = [
                    "您已登录", "在线用户", "当前在线", "logout", "登出", "注销",
                    "already logged in", "online user", "logged in", "success"
                ]
                for indicator in indicators:
                    if indicator.lower() in body_text.lower():
                        self.logger.info(f"✅ 通过通用文本检测到已登录状态: {indicator}")
                        return True

            return False

        except Exception as e:
            self.logger.warning(f"检测已登录状态时发生异常: {e}")
            return False
    
    async def test_connection(self) -> tuple[bool, str]:
        """测试连接到认证页面
        
        返回:
            tuple[bool, str]: (是否成功, 提示信息)
        """
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
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

    async def fill_login_form(self) -> bool:
        """填写登录表单"""
        try:
            # 👇 等待表单关键元素出现（优化选择器，避免隐藏元素）
            try:
                await self.page.wait_for_selector(
                    'input[name="DDDDD"][type="text"]:visible, input[name="upass"][type="password"]:visible',
                    state="visible", 
                    timeout=10000
                )
                self.logger.info("📝 表单元素已加载")
            except Exception as e:
                self.logger.warning(f"等待表单元素超时: {e}")
                # 尝试备用选择器
                try:
                    await self.page.wait_for_selector(
                        'input[type="text"]:visible, input[type="password"]:visible',
                        state="visible",
                        timeout=5000
                    )
                    self.logger.info("📝 通过备用选择器找到表单元素")
                except Exception as e2:
                    self.logger.warning(f"备用选择器也失败: {e2}")

            # 用户名选择器（优化优先级，更精确匹配）
            username_selectors = [
                'input[name="DDDDD"][type="text"]:visible',  # 最高优先级：明确指定类型和可见性
                'input[name="DDDDD"]:not([type="hidden"]):visible',  # 排除隐藏字段
                'input[type="text"][placeholder*="学工号"]:visible',
                'input[type="text"][placeholder*="用户名"]:visible', 
                'input[name="username"]:visible',
                'input[name="user"]:visible',
                'input[type="text"]:visible'
            ]

            # 密码选择器（优化优先级，更精确匹配）
            password_selectors = [
                'input[name="upass"][type="password"]:visible',  # 最高优先级：明确指定类型和可见性
                'input[name="upass"]:not([type="hidden"]):visible',  # 排除隐藏字段
                'input[type="password"][placeholder*="密码"]:visible',
                'input[type="password"][placeholder*="云陶"]:visible',
                'input[name="password"]:visible',
                'input[type="password"]:visible'
            ]

            # 填写用户名（增加更严格的可见性检查）
            username_filled = False
            for selector in username_selectors:
                try:
                    element = self.page.locator(selector)
                    if await element.count() > 0:
                        # 更严格的可见性检查
                        is_visible = await element.is_visible()
                        is_enabled = await element.is_enabled()
                        element_type = await element.get_attribute('type')
                        
                        if is_visible and is_enabled and element_type != 'hidden':
                            await element.clear()  # 使用 clear() 替代 fill('')
                            await element.fill(self.username)
                            username_filled = True
                            self.logger.info(f"👤 用户名填写成功，使用选择器: {selector}")
                            break
                        else:
                            self.logger.debug(f"选择器 {selector} 不满足条件: visible={is_visible}, enabled={is_enabled}, type={element_type}")
                except Exception as e:
                    self.logger.warning(f"用户名选择器 {selector} 填写失败: {e}")
                    continue

            if not username_filled:
                self.logger.error("❌ 未找到可见的用户名输入框")
                # 调试：打印所有 input 元素
                all_inputs = await self.page.query_selector_all('input')
                for i, inp in enumerate(all_inputs):
                    inp_type = await inp.get_attribute('type')
                    inp_name = await inp.get_attribute('name')
                    inp_visible = await inp.is_visible()
                    self.logger.debug(f"Input {i}: type={inp_type}, name={inp_name}, visible={inp_visible}")
                return False

            # 填写密码（增加更严格的可见性检查）
            password_filled = False
            for selector in password_selectors:
                try:
                    element = self.page.locator(selector)
                    if await element.count() > 0:
                        # 更严格的可见性检查
                        is_visible = await element.is_visible()
                        is_enabled = await element.is_enabled()
                        element_type = await element.get_attribute('type')
                        
                        if is_visible and is_enabled and element_type != 'hidden':
                            await element.clear()  # 使用 clear() 替代 fill('')
                            await element.fill(self.password)
                            password_filled = True
                            self.logger.info(f"🔑 密码填写成功，使用选择器: {selector}")
                            break
                        else:
                            self.logger.debug(f"选择器 {selector} 不满足条件: visible={is_visible}, enabled={is_enabled}, type={element_type}")
                except Exception as e:
                    self.logger.warning(f"密码选择器 {selector} 填写失败: {e}")
                    continue

            if not password_filled:
                self.logger.error("❌ 未找到可见的密码输入框")
                return False

            # 选择运营商（优化选择器优先级）
            if self.isp and self.isp.strip():
                isp_selectors = [
                    'select[name="ISP_select"]:visible',  # 最高优先级
                    'select[name="isp"]:visible',
                    'select[name="operator"]:visible',
                    '#ISP_select:visible',
                    '#isp:visible',
                    '#operator:visible'
                ]
                isp_selected = False
                for selector in isp_selectors:
                    try:
                        element = self.page.locator(selector)
                        if await element.count() > 0 and await element.is_visible():
                            await element.select_option(self.isp)
                            isp_selected = True
                            self.logger.info(f"🌐 运营商选择成功: {self.isp}，使用选择器: {selector}")
                            break
                    except Exception as e:
                        self.logger.warning(f"运营商选择器 {selector} 失败: {e}")
                        continue
                if not isp_selected:
                    self.logger.warning("⚠️ 未找到运营商选择框，跳过运营商选择")

            return True

        except Exception as e:
            self.logger.error(f"填写表单时发生错误: {e}")
            return False

    async def submit_form(self) -> bool:
        """提交登录表单（优化选择器优先级）"""
        try:
            # 提交按钮选择器（优化优先级，更精确匹配）
            submit_selectors = [
                'input[name="0MKKey"][type="button"]:visible',  # 最高优先级：明确指定类型和可见性
                'input[name="0MKKey"]:not([type="hidden"]):visible',  # 排除隐藏字段
                'input[onclick*="ee(1)"]:visible',
                'input[value="登录"][type="button"]:visible',
                'input[value="登录"]:visible',
                'input[type="submit"]:visible',
                'button[type="submit"]:visible',
                'button:has-text("登录"):visible'
            ]

            # 遍历提交按钮选择器（增加更严格的可用性检查）
            for selector in submit_selectors:
                try:
                    button = self.page.locator(selector)
                    if await button.count() > 0:
                        is_visible = await button.is_visible()
                        is_enabled = await button.is_enabled()
                        
                        if is_visible and is_enabled:
                            self.logger.info(f"🚀 正在提交认证表单... 使用选择器: {selector}")
                            await button.click()
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
            await self.page.wait_for_load_state("networkidle", timeout=8000)

            success_indicators = [
                "认证成功", "登录成功", "连接成功", "welcome", "success",
                "authentication successful", "login successful", "connected",
                "您已经成功登录"  # 特别加入你页面的提示
            ]

            failure_indicators = [
                "认证失败", "登录失败", "用户名或密码错误", "账号或密码", "incorrect",
                "authentication failed", "login failed", "invalid username or password",
                "用户不存在", "密码错误", "账户被锁定", "网络异常"
            ]

            body_text = (await self.page.text_content("body") or "")
            body_text_lower = body_text.lower()

            # 检查特定的提示框内容
            try:
                # 查找包含提示信息的div元素
                tip_elements = await self.page.query_selector_all('div[name="PageTips"], .edit_lobo_cell, .message, .alert, .tip')
                for element in tip_elements:
                    element_text = await element.text_content()
                    if element_text and element_text.strip():
                        self.logger.info(f"📋 检测到提示信息: {element_text.strip()}")
                        
                        # 检查是否为成功提示
                        for indicator in success_indicators:
                            if indicator.lower() in element_text.lower():
                                success_msg = f"登录成功: {element_text.strip()}"
                                self.logger.info(f"✅ {success_msg}")
                                return True, success_msg
                        
                        # 检查是否为失败提示
                        for indicator in failure_indicators:
                            if indicator.lower() in element_text.lower():
                                failure_msg = f"登录失败: {element_text.strip()}"
                                self.logger.warning(f"❌ {failure_msg}")
                                await self.page.screenshot(path="auth_failed.png")
                                return False, failure_msg
            except Exception as e:
                self.logger.debug(f"检查提示元素时出错: {e}")

            # 先检查失败
            for indicator in failure_indicators:
                if indicator.lower() in body_text_lower:
                    failure_msg = f"登录失败: 检测到失败标识 '{indicator}'"
                    self.logger.warning(f"❌ {failure_msg}")
                    await self.page.screenshot(path="auth_failed.png")
                    self.logger.info("📸 已保存失败截图: auth_failed.png")
                    return False, failure_msg

            # 再检查成功
            for indicator in success_indicators:
                if indicator.lower() in body_text_lower:
                    success_msg = f"登录成功: 检测到成功标识 '{indicator}'"
                    self.logger.info(f"✅ {success_msg}")
                    return True, success_msg

            # 检查URL变化
            if self.page.url != self.auth_url:
                success_msg = f"登录成功: 页面URL已变化到 {self.page.url}"
                self.logger.info(f"✅ {success_msg}")
                return True, success_msg

            # 无法确定结果
            ambiguous_msg = "无法确定登录结果，可能网络异常或页面加载问题"
            self.logger.warning(f"⚠️ {ambiguous_msg}")
            await self.page.screenshot(path="auth_ambiguous.png")
            return False, ambiguous_msg

        except Exception as e:
            self.logger.error(f"检查认证结果时发生错误: {e}")
            return False

    async def authenticate_once(self) -> tuple[bool, str]:
        """执行一次认证尝试
        
        返回:
            tuple[bool, str]: (是否成功, 提示信息)
        """
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
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()  # 防止内存泄漏

    async def authenticate(self) -> tuple[bool, str]:
        """执行完整的认证流程（包含重试机制）
        
        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        max_retries = self.retry_settings.get("max_retries", 3)
        retry_interval = self.retry_settings.get("retry_interval", 5)
        last_message = ""

        for attempt in range(max_retries):
            self.logger.info(f"🔁 开始第 {attempt + 1} 次认证尝试")

            success, message = await self.authenticate_once()
            last_message = message

            if success:
                success_info = f"认证成功！({message})"
                self.logger.info(f"🎉 {success_info}")
                return True, success_info

            self.logger.warning(f"❌ 第 {attempt + 1} 次尝试失败: {message}")

            if attempt < max_retries - 1:
                self.logger.info(f"⏳ 认证失败，{retry_interval}秒后进行第 {attempt + 2} 次尝试")
                await asyncio.sleep(retry_interval)
            else:
                self.logger.error(f"💥 所有 {max_retries} 次认证尝试均失败")

        failure_info = f"认证失败！已尝试 {max_retries} 次，最后错误: {last_message}"
        return False, failure_info


async def main():
    """主函数"""
    # 从环境变量加载配置
    config = load_config_from_env()
    
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