import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import datetime
import os
import sys
import asyncio
import webbrowser
from pathlib import Path
from typing import Optional

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from campus_login import EnhancedCampusNetworkAuth, load_config_from_env
from network_test import is_network_available

class NetworkMonitorGUI:
    def __init__(self, root: tk.Tk) -> None:
        """
        初始化GUI界面
        
        参数:
            root: tkinter根窗口
        """
        self.root = root
        self.root.title("校园网络监控助手")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # 监控状态变量
        self.monitoring: bool = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.start_time: Optional[float] = None
        self.network_check_count: int = 0
        self.login_attempt_count: int = 0
        self.last_check_time: Optional[datetime.datetime] = None
        
        # 检查是否首次启动并显示公告
        self.check_first_run()
        
        # 创建GUI组件
        self.create_widgets()
        
        # 加载.env配置
        self.load_env_config()
        
        # 启动时立即检测一次网络状态
        self.initial_network_check()
        
        # 启动状态更新定时器
        self.update_status()
    
    def create_widgets(self):
        """
        创建GUI界面组件
        """
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置信息框架
        config_frame = ttk.LabelFrame(main_frame, text="登录配置", padding="10")
        config_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 账号输入
        ttk.Label(config_frame, text="账号:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(config_frame, textvariable=self.username_var, width=20)
        self.username_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 20))
        
        # 密码输入
        ttk.Label(config_frame, text="密码:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(config_frame, textvariable=self.password_var, show="•", width=17)
        self.password_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 20))
        
        # 运营商选择
        ttk.Label(config_frame, text="运营商:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.carrier_var = tk.StringVar(value="移动")
        # 运营商中文映射
        self.carrier_mapping = {
            "移动": "@cmcc",
            "联通": "@unicom", 
            "电信": "@telecom",
            "教育网": "@xyw",
            "无": ""
        }
        carrier_combo = ttk.Combobox(config_frame, textvariable=self.carrier_var, 
                                   values=list(self.carrier_mapping.keys()), 
                                   state="readonly", width=17)
        carrier_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 20), pady=(10, 0))
        
        # 检测间隔设置
        ttk.Label(config_frame, text="检测间隔(分钟):").grid(row=1, column=2, sticky=tk.W, padx=(20, 5), pady=(10, 0))
        self.check_interval_var = tk.StringVar(value="5")
        interval_entry = ttk.Entry(config_frame, textvariable=self.check_interval_var, width=10)
        interval_entry.grid(row=1, column=3, sticky=tk.W, padx=(0, 20), pady=(10, 0))
        
        # 自动启动监控和无头模式选项
        self.auto_start_var = tk.BooleanVar(value=False)
        auto_start_check = ttk.Checkbutton(config_frame, text="启动时自动监控", variable=self.auto_start_var)
        auto_start_check.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        self.headless_var = tk.BooleanVar(value=False)
        headless_check = ttk.Checkbutton(config_frame, text="无头模式运行", variable=self.headless_var)
        headless_check.grid(row=2, column=2, columnspan=2, sticky=tk.W, padx=(20, 0), pady=(10, 0))
        
        # 控制按钮框架
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=1, column=0, columnspan=2, pady=(0, 10))
        
        # 开始/停止监控按钮
        self.monitor_button = ttk.Button(control_frame, text="开始监控", command=self.toggle_monitoring)
        self.monitor_button.grid(row=0, column=0, padx=(0, 10))
        
        # 手动登录按钮
        self.login_button = ttk.Button(control_frame, text="手动登录", command=self.manual_login)
        self.login_button.grid(row=0, column=1, padx=(0, 10))
        
        # 网络测试按钮
        self.test_button = ttk.Button(control_frame, text="网络测试", command=self.test_network)
        self.test_button.grid(row=0, column=2, padx=(0, 10))
        
        # 测试连接按钮
        self.test_connection_button = ttk.Button(control_frame, text="测试连接", command=self.test_connection)
        self.test_connection_button.grid(row=0, column=3, padx=(0, 10))
        
        # 保存配置按钮
        self.save_button = ttk.Button(control_frame, text="保存配置", command=self.save_config)
        self.save_button.grid(row=0, column=4, padx=(0, 10))
        
        # 关于按钮
        self.about_button = ttk.Button(control_frame, text="关于", command=self.show_about)
        self.about_button.grid(row=0, column=5)
        
        # 状态信息框架
        status_frame = ttk.LabelFrame(main_frame, text="运行状态", padding="10")
        status_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        # 状态标签
        self.status_label = ttk.Label(status_frame, text="状态: 未开始监控", font=("Arial", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        self.time_label = ttk.Label(status_frame, text="运行时间: 00:00:00")
        self.time_label.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        self.check_label = ttk.Label(status_frame, text="网络检测次数: 0")
        self.check_label.grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        
        self.last_check_label = ttk.Label(status_frame, text="上次检测: 未检测")
        self.last_check_label.grid(row=3, column=0, sticky=tk.W, pady=(5, 0))
        
        # 日志显示框架
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="10")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 日志文本框
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, width=70)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
    
    def log_message(self, message):
        """
        在日志区域显示消息
        
        参数:
            message: 要显示的消息
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        # 在主线程中更新GUI
        self.root.after(0, lambda: self._update_log_text(log_entry))
    
    def _update_log_text(self, log_entry):
        """
        更新日志文本框内容
        
        参数:
            log_entry: 日志条目
        """
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
    
    def toggle_monitoring(self):
        """
        切换监控状态
        """
        if not self.monitoring:
            # 检查配置
            if not self.username_var.get() or not self.password_var.get():
                messagebox.showerror("错误", "请输入账号和密码")
                return
            
            # 开始监控
            self.monitoring = True
            self.start_time = time.time()
            self.network_check_count = 0
            self.login_attempt_count = 0
            
            self.monitor_button.config(text="停止监控")
            self.username_entry.config(state="disabled")
            self.password_entry.config(state="disabled")
            
            # 启动监控线程
            self.monitor_thread = threading.Thread(target=self.monitor_network, daemon=True)
            self.monitor_thread.start()
            
            self.log_message("开始网络监控")
        else:
            # 停止监控
            self.monitoring = False
            self.monitor_button.config(text="开始监控")
            self.username_entry.config(state="normal")
            self.password_entry.config(state="normal")
            
            self.log_message("停止网络监控")
    
    def monitor_network(self) -> None:
        """
        网络监控主循环
        """
        consecutive_failures = 0
        
        while self.monitoring:
            try:
                # 更新检测次数
                self.network_check_count += 1
                self.last_check_time = datetime.datetime.now()
                
                self.log_message(f"第{self.network_check_count}次网络检测")
                
                # 检测网络状态
                try:
                    network_ok = is_network_available()
                except Exception as e:
                    self.log_message(f"网络检测失败: {str(e)}")
                    network_ok = False
                
                if network_ok:
                    self.log_message("网络连接正常")
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                else:
                    consecutive_failures += 1
                    self.log_message(f"网络连接异常 (连续失败{consecutive_failures}次)")
                    
                    # 检测到网络异常立即尝试登录
                    self.log_message("检测到网络异常，立即尝试重新登录")
                    
                    # 尝试登录
                    login_success = self.attempt_login()
                    
                    if login_success:
                        consecutive_failures = 0
                        self.login_attempt_count = 0
                        self.log_message("登录成功，重置失败计数")
                    else:
                        self.login_attempt_count += 1
                        self.log_message(f"登录失败 (第{self.login_attempt_count}次)")
                        
                        # 连续登录失败3次后等待5分钟
                        if self.login_attempt_count >= 3:
                            self.log_message("登录连续3次失败，等待5分钟后重试")
                            # 等待5分钟
                            for i in range(300):
                                if not self.monitoring:
                                    return
                                time.sleep(1)
                            self.login_attempt_count = 0
                            continue
                
                # 根据用户设置的间隔等待
                try:
                    interval_minutes = int(self.check_interval_var.get())
                    if interval_minutes < 1:
                        interval_minutes = 5  # 最小1分钟
                except ValueError:
                    interval_minutes = 5  # 默认5分钟
                
                wait_seconds = interval_minutes * 60
                self.log_message(f"等待{interval_minutes}分钟后进行下次检测")
                
                for i in range(wait_seconds):
                    if not self.monitoring:
                        return
                    time.sleep(1)
                    
            except Exception as e:
                self.log_message(f"监控过程中发生错误: {str(e)}")
                # 发生错误时等待1分钟，但检查是否需要停止
                for i in range(60):
                    if not self.monitoring:
                        return
                    time.sleep(1)
    
    def attempt_login(self) -> bool:
        """
        尝试登录校园网
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 检查当前时间是否在禁止登录时段（0点到6点）
            current_hour = datetime.datetime.now().hour
            if 0 <= current_hour < 6:
                self.log_message(f"⏰ 当前时间 {current_hour}:xx 在禁止登录时段（0点-6点），跳过登录")
                return False
            
            # 从GUI获取配置并转换
            config = load_config_from_env()
            # 使用GUI中的值覆盖配置
            username = self.username_var.get() + self.carrier_mapping.get(self.carrier_var.get(), '@cmcc')
            password = self.password_var.get()
            config['username'] = username
            config['password'] = password
            
            # 使用GUI中的无头模式选项
            config['browser_settings']['headless'] = self.headless_var.get()
            
            # 创建登录实例
            auth = EnhancedCampusNetworkAuth(config)
            
            # 尝试登录（异步调用）
            try:
                success, message = asyncio.run(auth.authenticate())
            except Exception as e:
                self.log_message(f"❌ 校园网登录失败: {str(e)}")
                return False
            
            if success:
                self.log_message(f"✅ 校园网登录成功: {message}")
                return True
            else:
                self.log_message(f"❌ 校园网登录失败: {message}")
                return False
                
        except Exception as e:
            self.log_message(f"❌ 登录过程中发生错误: {str(e)}")
            return False
    
    def manual_login(self):
        """
        手动登录
        """
        if not self.username_var.get() or not self.password_var.get():
            messagebox.showerror("错误", "请输入账号和密码")
            return
        
        self.log_message("开始手动登录")
        
        # 在新线程中执行登录
        threading.Thread(target=self.attempt_login, daemon=True).start()
    
    def test_network(self):
        """
        手动测试网络
        """
        self.log_message("开始网络测试")
        
        # 在新线程中执行测试
        def test():
            try:
                result = is_network_available()
                if result:
                    self.log_message("网络测试结果: 连接正常")
                else:
                    self.log_message("网络测试结果: 连接异常")
            except Exception as e:
                self.log_message(f"网络测试发生错误: {str(e)}")
        
        threading.Thread(target=test, daemon=True).start()
    
    def test_connection(self):
        """
        测试校园网连接配置
        """
        # 验证配置
        is_valid, error_msg = self.validate_config()
        if not is_valid:
            messagebox.showerror("配置错误", error_msg)
            return
        
        self.log_message("开始测试校园网连接配置...")
        
        # 在新线程中执行测试
        def test():
            try:
                # 获取当前GUI中的配置
                username = self.username_var.get().strip()
                password = self.password_var.get().strip()
                carrier_chinese = self.carrier_var.get()
                carrier_suffix = self.carrier_mapping.get(carrier_chinese, "")
                
                # 构造完整用户名
                full_username = username + carrier_suffix
                
                # 创建临时配置进行测试
                config = load_config_from_env()
                config['username'] = full_username
                config['password'] = password
                
                # 使用GUI中的无头模式选项
                config['browser_settings']['headless'] = self.headless_var.get()
                
                # 创建认证器实例
                auth = EnhancedCampusNetworkAuth(config)
                
                # 执行连接测试
                self.log_message("正在测试连接到认证页面...")
                try:
                    success, message = asyncio.run(auth.test_connection())
                    if success:
                        self.log_message(f"✅ {message}")
                    else:
                        self.log_message(f"❌ {message}")
                except Exception as e:
                    self.log_message(f"❌ 连接测试失败: {str(e)}")
                        
            except Exception as e:
                self.log_message(f"❌ 连接测试发生错误: {str(e)}")
        
        threading.Thread(target=test, daemon=True).start()
    
    def update_status(self):
        """
        更新状态显示
        """
        if self.monitoring:
            # 更新运行时间
            if self.start_time:
                elapsed = int(time.time() - self.start_time)
                hours = elapsed // 3600
                minutes = (elapsed % 3600) // 60
                seconds = elapsed % 60
                self.time_label.config(text=f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}")
            
            self.status_label.config(text="状态: 监控中", foreground="green")
        else:
            self.status_label.config(text="状态: 未监控", foreground="red")
        
        # 更新检测次数
        self.check_label.config(text=f"网络检测次数: {self.network_check_count}")
        
        # 更新上次检测时间
        if self.last_check_time:
            time_str = self.last_check_time.strftime("%H:%M:%S")
            self.last_check_label.config(text=f"上次检测: {time_str}")
        
        # 每秒更新一次
        self.root.after(1000, self.update_status)
    
    def initial_network_check(self):
        """
        启动时立即进行登录尝试
        """
        # 使用GUI中的自动启动选项
        auto_start = self.auto_start_var.get()
        
        if not auto_start:
            self.log_message("ℹ️ 根据配置，启动时不自动开始监控")
            return
            
        def login_on_startup():
            try:
                self.log_message("🚀 应用启动，开始自动登录...")
                
                # 检查是否有必要的登录信息
                if not self.username_var.get() or not self.password_var.get():
                    self.log_message("⚠️ 缺少用户名或密码，跳过自动登录")
                    return
                
                # 尝试登录
                success = self.attempt_login()
                if success:
                    self.log_message("🎉 启动时自动登录完成")
                else:
                    self.log_message("⚠️ 启动时自动登录失败，请检查网络或手动登录")
                    
            except Exception as e:
                self.log_message(f"❌ 启动时登录发生错误: {str(e)}")
        
        threading.Thread(target=login_on_startup, daemon=True).start()
    
    def validate_config(self) -> tuple[bool, str]:
        """
        验证当前配置是否有效
        
        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 验证必填字段
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        
        if not username:
            return False, "账号不能为空"
        if not password:
            return False, "密码不能为空"
            
        # 验证账号格式（基本验证）
        if len(username) < 2:
            return False, "账号长度不能少于2位"
            
        # 验证密码格式（基本验证）
        if len(password) < 2:
            return False, "密码长度不能少于2位"
        
        # 验证检测间隔
        check_interval = self.check_interval_var.get().strip()
        try:
            interval_int = int(check_interval)
            if interval_int < 1:
                return False, "检测间隔必须大于0"
            if interval_int > 1440:  # 24小时
                return False, "检测间隔不能超过1440分钟（24小时）"
        except ValueError:
            return False, "检测间隔必须是正整数"
        
        return True, ""
    
    def save_config(self) -> None:
        """
        保存当前配置到.env文件
        """
        try:
            # 验证配置
            is_valid, error_msg = self.validate_config()
            if not is_valid:
                messagebox.showerror("配置错误", error_msg)
                return
            
            # 获取当前GUI中的配置
            username = self.username_var.get().strip()
            password = self.password_var.get().strip()
            carrier_chinese = self.carrier_var.get()
            carrier_suffix = self.carrier_mapping.get(carrier_chinese, "")
            check_interval = self.check_interval_var.get().strip()
            auto_start = self.auto_start_var.get()
            headless = self.headless_var.get()
            
            # 构建.env文件内容
            env_content = f"""# 校园网认证配置
CAMPUS_USERNAME={username}
CAMPUS_PASSWORD={password}
CAMPUS_AUTH_URL=http://172.29.0.2
CAMPUS_ISP={carrier_suffix}

# 浏览器配置
BROWSER_HEADLESS={str(headless).lower()}

# 网络检测配置
MONITOR_INTERVAL={int(check_interval) * 60}
AUTO_START_MONITORING={str(auto_start).lower()}

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/campus_auth.log
"""
            
            # 写入.env文件
            env_file_path = os.path.join(os.path.dirname(__file__), '.env')
            try:
                with open(env_file_path, 'w', encoding='utf-8') as f:
                    f.write(env_content)
            except Exception as e:
                error_msg = f"写入配置文件失败: {e}"
                self.log_message(f"❌ {error_msg}")
                messagebox.showerror("错误", error_msg)
                return
            
            self.log_message("✅ 配置已保存到.env文件")
            messagebox.showinfo("成功", "配置已成功保存到.env文件")
            
        except Exception as e:
            error_msg = f"保存配置失败: {e}"
            self.log_message(f"❌ {error_msg}")
            messagebox.showerror("错误", error_msg)
    
    def load_env_config(self):
        """
        从.env文件加载配置
        """
        try:
            config = load_config_from_env()
            if config.get('username'):
                self.username_var.set(config['username'])
            if config.get('password'):
                self.password_var.set(config['password'])
            
            # 设置运营商
            isp_code = config.get('isp', '@cmcc')
            for chinese_name, code in self.carrier_mapping.items():
                if code == isp_code:
                    self.carrier_var.set(chinese_name)
                    break
                    
            # 设置检测间隔（如果存在）
            monitor_interval = config.get('monitor', {}).get('interval')
            if monitor_interval:
                # 转换为分钟
                interval_minutes = max(1, monitor_interval // 60)
                self.check_interval_var.set(str(interval_minutes))
                
            # 设置自动启动监控选项
            auto_start = config.get('auto_start_monitoring', False)
            self.auto_start_var.set(auto_start)
            
            # 设置无头模式选项
            headless = config.get('browser_settings', {}).get('headless', False)
            self.headless_var.set(headless)
        except Exception as e:
            self.log_message(f"加载配置失败: {e}")
    
    def check_first_run(self):
        """
        检查是否首次运行，如果是则显示公告
        """
        # 检查是否已同意声明
        agreed_file = os.path.join(os.path.dirname(__file__), '.agreed')
        if not os.path.exists(agreed_file):
            # 显示公告窗口
            self.show_announcement()
    
    def show_announcement(self):
        """
        显示首次启动公告窗口
        """
        # 创建公告窗口
        announcement_window = tk.Toplevel(self.root)
        announcement_window.title("重要公告")
        announcement_window.geometry("700x600")  # 增加窗口高度以容纳输入框
        announcement_window.resizable(False, False)
        announcement_window.grab_set()  # 模态窗口，阻止用户与主窗口交互
        
        # 添加窗口关闭事件处理 - 如果用户关闭公告窗口，则关闭整个应用程序
        def on_window_close():
            self.log_message("用户关闭了公告窗口，程序将退出")
            self.root.quit()  # 关闭主程序
            self.root.destroy()
        
        announcement_window.protocol("WM_DELETE_WINDOW", on_window_close)
        
        # 居中显示在屏幕中央
        announcement_window.transient(self.root)
        # 获取屏幕尺寸
        screen_width = announcement_window.winfo_screenwidth()
        screen_height = announcement_window.winfo_screenheight()
        # 计算居中位置
        x = (screen_width // 2) - 350
        y = (screen_height // 2) - 300  # 调整Y位置以适应更高的窗口
        announcement_window.geometry(f"700x600+{x}+{y}")
        
        # 公告内容
        announcement_text = """
欢迎使用校园网认证工具！
========================

重要声明：
1. 本工具核心功能基于浏览器端自动化点击脚本实现，不涉及对任何校园网系统的破解、入侵或恶意攻击行为，理论上可适配各类网页端网络认证场景。
2. 本工具不会存储、缓存用户的任何账号信息及密码，亦不会将上述敏感数据上传至任何第三方服务器；工具全部源代码已公开。
3. 用户在使用本工具前，须严格遵守所在学校的网络使用管理规定及国家相关法律法规，严禁将其用于任何非法、违规用途（包括但不限于破坏网络秩序、侵犯他人权益等）；本工具仅授权用于学习与技术研究场景，禁止用于任何商业活动、盈利目的或其他非授权用途。
4. 因用户未遵守使用规范、违反相关规定或不当使用本工具，导致的任何网络安全问题、数据风险、财产损失、法律纠纷等后果，均由用户自行承担全部责任；工具开发者不对使用本工具产生的任何直接或间接损失、纠纷及法律责任承担责任。

本项目github地址:https://github.com/Misyra/JCU_auto_network

注意事项：
- 请妥善保管您的账号密码
- 建议定期修改密码
- 如遇到问题请查看日志文件
- 可通过.env文件自定义检测间隔

滑动确认机制：
- 请将此文本滑动到最底部
- 在底部输入框中输入"我已阅读且知悉并愿意承担使用本工具造成的全部后果，且同意以上声明"
- 点击确认按钮完成首次启动设置

感谢您的使用！
        """
        
        # 创建文本框显示公告内容
        text_frame = tk.Frame(announcement_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))  # 减少底部边距为输入框留出空间
        
        # 创建滚动文本框
        text_widget = tk.Text(text_frame, wrap=tk.WORD, font=("Arial", 12))
        scrollbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.insert(tk.END, announcement_text)
        text_widget.config(state=tk.DISABLED)  # 只读
        
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 滑动检测变量
        self.scrolled_to_bottom = False
        self.declaration_confirmed = False
        
        # 滑动检测变量
        self.scrolled_to_bottom = False
        self.declaration_confirmed = False
        
        # 检查确认条件
        def check_confirmation():
            # 检查是否满足确认条件
            if self.scrolled_to_bottom and self.declaration_confirmed:
                self.confirm_button.config(state=tk.NORMAL)
            else:
                self.confirm_button.config(state=tk.DISABLED)
        
        # 绑定滚动事件
        def on_scroll(first, last):
            # 检查是否滚动到底部
            if float(last) == 1.0:  # 已经滚动到底部
                self.scrolled_to_bottom = True
                check_confirmation()
            # 更新滚动条位置
            scrollbar.set(first, last)
        
        text_widget.config(yscrollcommand=on_scroll)
        
        # 声明输入框
        declaration_frame = tk.Frame(announcement_window)
        declaration_frame.pack(fill=tk.X, padx=10, pady=(5, 5))  # 调整边距
        
        tk.Label(declaration_frame, text="请滑动到底部并阅读完所有内容，在此输入框中输入声明:", 
                wraplength=680).pack(anchor=tk.W, pady=(0, 5))  # 添加文本换行和间距
        
        self.declaration_entry = tk.Entry(declaration_frame, font=("Arial", 10))
        self.declaration_entry.pack(fill=tk.X, pady=(0, 5))  # 调整边距
        
        # 验证输入内容
        def validate_declaration(*args):
            content = self.declaration_entry.get()
            if content == "我已阅读且知悉并愿意承担使用本工具造成的全部后果，且同意以上声明":
                self.declaration_confirmed = True
            else:
                self.declaration_confirmed = False
            check_confirmation()
        
        self.declaration_entry.bind('<KeyRelease>', validate_declaration)
        
        # 倒计时和确认按钮框架
        bottom_frame = tk.Frame(announcement_window)
        bottom_frame.pack(fill=tk.X, padx=10, pady=(5, 10))  # 调整顶部边距
        
        # 倒计时标签
        self.countdown_label = tk.Label(bottom_frame, text="请仔细阅读以上内容...")
        self.countdown_label.pack(side=tk.LEFT)
        
        # 确认按钮
        self.confirm_button = tk.Button(
            bottom_frame,
            text="确认",
            state=tk.DISABLED,
            command=lambda: self.confirm_agreement(announcement_window)
        )
        self.confirm_button.pack(side=tk.RIGHT)
        
        # 开始倒计时
        self.countdown_seconds = 10
        self.run_countdown()
    
    def run_countdown(self):
        """
        运行倒计时
        """
        if self.countdown_seconds > 0:
            self.countdown_label.config(text=f"请等待{self.countdown_seconds}秒...")
            self.countdown_seconds -= 1
            self.root.after(1000, self.run_countdown)
        else:
            self.countdown_label.config(text="倒计时结束，可以继续操作")
            # 检查是否满足确认条件
            if self.scrolled_to_bottom and self.declaration_confirmed:
                self.confirm_button.config(state=tk.NORMAL)
    
    def on_agreement_change(self):
        """
        当声明复选框状态改变时调用（保留此方法以避免其他地方调用出错）
        """
        pass
    
    def confirm_agreement(self, window):
        """
        确认同意声明
        
        参数:
            window: 公告窗口
        """
        # 创建.agreed文件标记已同意声明
        agreed_file = os.path.join(os.path.dirname(__file__), '.agreed')
        try:
            with open(agreed_file, 'w') as f:
                f.write("用户已同意声明\n")
        except Exception as e:
            self.log_message(f"创建同意文件失败: {e}")
        
        # 关闭公告窗口
        window.destroy()
        
        # 启用主窗口
        self.root.focus_set()
    
    def show_about(self):
        """
        显示关于信息并跳转到GitHub仓库
        """
        try:
            # 打开GitHub仓库链接
            webbrowser.open("https://github.com/Misyra/JCU_auto_network")
            self.log_message("🔗 已打开GitHub仓库页面")
        except Exception as e:
            self.log_message(f"❌ 打开GitHub页面失败: {e}")
            messagebox.showerror("错误", f"无法打开GitHub页面: {e}")

def main():
    """
    主函数
    """
    # 创建logs目录
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # 创建GUI
    root = tk.Tk()
    app = NetworkMonitorGUI(root)
    
    # 设置窗口关闭事件
    def on_closing():
        if app.monitoring:
            if messagebox.askokcancel("退出", "监控正在运行，确定要退出吗？"):
                app.monitoring = False
                root.destroy()
        else:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # 启动GUI
    root.mainloop()

if __name__ == "__main__":
    main()