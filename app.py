import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import datetime
import os
import sys
import asyncio
import webbrowser
import logging
from pathlib import Path
from typing import Optional

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from campus_login import EnhancedCampusNetworkAuth
from network_test import is_network_available
from utils import TimeUtils, ConfigAdapter, LoginAttemptHandler, LoggerSetup, get_runtime_stats, ConfigLoader, ConfigValidator


# 工具提示功能已移除，避免bug

class NetworkMonitorGUI:
    def __init__(self, root: tk.Tk) -> None:
        """
        初始化GUI界面
        
        参数:
            root: tkinter根窗口
        """
        self.root = root
        self.root.title("🌐 校园网络监控助手")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        # 设置窗口最小尺寸
        self.root.minsize(600, 500)
        
        # 设置窗口图标和样式
        self.setup_styles()
        
        # 监控状态变量
        self.monitoring: bool = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.start_time: Optional[float] = None
        self.network_check_count: int = 0
        self.login_attempt_count: int = 0
        self.last_check_time: Optional[datetime.datetime] = None
        
        # 设置GUI日志记录器
        self._setup_gui_logging()
        
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
    
    def setup_styles(self):
        """
        设置界面样式和主题
        """
        # 创建样式对象
        self.style = ttk.Style()
        
        # 设置主题
        self.style.theme_use('clam')
        
        # 自定义样式
        self.style.configure('Title.TLabel', font=('Arial', 12, 'bold'), foreground='#2c3e50')
        self.style.configure('Status.TLabel', font=('Arial', 10, 'bold'))
        self.style.configure('Success.TLabel', foreground='#27ae60')
        self.style.configure('Error.TLabel', foreground='#e74c3c')
        self.style.configure('Warning.TLabel', foreground='#f39c12')
        self.style.configure('Info.TLabel', foreground='#3498db')
        
        # 按钮样式
        self.style.configure('Primary.TButton', font=('Arial', 9, 'bold'))
        self.style.configure('Success.TButton', font=('Arial', 9))
        self.style.configure('Warning.TButton', font=('Arial', 9))
        self.style.configure('Info.TButton', font=('Arial', 9))
        self.style.configure('Danger.TButton', font=('Arial', 9))
        
        # 框架样式
        self.style.configure('Card.TFrame', relief='solid', borderwidth=1)
        self.style.configure('Status.TFrame', relief='solid', borderwidth=1)
    
    def create_widgets(self):
        """
        创建GUI界面组件
        """
        # 主框架
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 标题区域
        title_frame = ttk.Frame(main_frame)
        title_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))
        
        title_label = ttk.Label(title_frame, text="🌐 校园网络监控助手", style='Title.TLabel')
        title_label.pack()
        
        # 配置信息框架 - 使用卡片式设计
        config_frame = ttk.LabelFrame(main_frame, text="⚙️ 登录配置", padding="15")
        config_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # 第一行：账号和密码
        ttk.Label(config_frame, text="👤 账号:", font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=(0, 10))
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(config_frame, textvariable=self.username_var, width=20)
        self.username_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 20), pady=(0, 10))
        
        ttk.Label(config_frame, text="🔒 密码:", font=('Arial', 9, 'bold')).grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=(0, 10))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(config_frame, textvariable=self.password_var, show="•", width=20)
        self.password_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 0), pady=(0, 10))
        
        # 第二行：运营商和检测间隔
        ttk.Label(config_frame, text="🌐 运营商:", font=('Arial', 9, 'bold')).grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=(0, 10))
        self.carrier_var = tk.StringVar(value="无")
        # 运营商中文映射
        self.carrier_mapping = {
            "移动": "@cmcc",
            "联通": "@unicom", 
            "电信": "@telecom",
            "教育网": "@xyw",
            "无": ""
        }
        self.carrier_combo = ttk.Combobox(config_frame, textvariable=self.carrier_var, 
                                   values=list(self.carrier_mapping.keys()), 
                                   state="readonly", width=18)
        self.carrier_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 20), pady=(0, 10))
        
        ttk.Label(config_frame, text="⏰ 检测间隔(分钟):", font=('Arial', 9, 'bold')).grid(row=1, column=2, sticky=tk.W, padx=(20, 8), pady=(0, 10))
        self.check_interval_var = tk.StringVar(value="5")
        self.interval_entry = ttk.Entry(config_frame, textvariable=self.check_interval_var, width=18)
        self.interval_entry.grid(row=1, column=3, sticky=(tk.W, tk.E), padx=(0, 0), pady=(0, 10))
        
        # 第三行：选项配置
        options_frame = ttk.Frame(config_frame)
        options_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(10, 0))
        
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_start_check = ttk.Checkbutton(options_frame, text="🚀 启动时自动监控", variable=self.auto_start_var)
        self.auto_start_check.pack(side=tk.LEFT, padx=(0, 20))
        
        self.headless_var = tk.BooleanVar(value=False)
        self.headless_check = ttk.Checkbutton(options_frame, text="👁️ 无头模式运行", variable=self.headless_var)
        self.headless_check.pack(side=tk.LEFT, padx=(0, 20))
        
        # 第四行：暂停登录时间配置
        pause_frame = ttk.Frame(config_frame)
        pause_frame.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(10, 0))
        
        ttk.Label(pause_frame, text="⏰ 暂停登录时段:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        
        self.pause_login_var = tk.BooleanVar(value=True)
        self.pause_check = ttk.Checkbutton(pause_frame, text="启用", variable=self.pause_login_var)
        self.pause_check.pack(side=tk.LEFT, padx=(0, 15))
        
        ttk.Label(pause_frame, text="从", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 5))
        self.pause_start_var = tk.StringVar(value="0")
        self.start_spinbox = ttk.Spinbox(pause_frame, from_=0, to=23, textvariable=self.pause_start_var, width=8)
        self.start_spinbox.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Label(pause_frame, text="点到", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 5))
        self.pause_end_var = tk.StringVar(value="6")
        self.end_spinbox = ttk.Spinbox(pause_frame, from_=0, to=23, textvariable=self.pause_end_var, width=8)
        self.end_spinbox.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Label(pause_frame, text="点", font=('Arial', 9)).pack(side=tk.LEFT)
        
        # 控制按钮框架 - 使用卡片式设计
        control_frame = ttk.LabelFrame(main_frame, text="🎮 控制面板", padding="15")
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # 所有按钮放在一行
        buttons_frame = ttk.Frame(control_frame)
        buttons_frame.pack(fill=tk.X)
        
        # 设置统一的按钮宽度和样式
        button_width = 12
        button_padx = 5  # 按钮间距
        
        # 主要操作按钮
        self.monitor_button = ttk.Button(buttons_frame, text="▶️ 开始监控", command=self.toggle_monitoring, style='Primary.TButton', width=button_width)
        self.monitor_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        self.login_button = ttk.Button(buttons_frame, text="🔑 手动登录", command=self.manual_login, style='Success.TButton', width=button_width)
        self.login_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        self.manual_auth_button = ttk.Button(buttons_frame, text="🔄 手动认证", command=self.manual_auth_fallback, style='Warning.TButton', width=button_width)
        self.manual_auth_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        # 辅助操作按钮
        self.test_button = ttk.Button(buttons_frame, text="🌐 网络测试", command=self.test_network, style='Info.TButton', width=button_width)
        self.test_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        self.test_connection_button = ttk.Button(buttons_frame, text="🔗 测试连接", command=self.test_connection, style='Info.TButton', width=button_width)
        self.test_connection_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        self.save_button = ttk.Button(buttons_frame, text="💾 保存配置", command=self.save_config, style='Success.TButton', width=button_width)
        self.save_button.pack(side=tk.LEFT, padx=(0, button_padx))
        
        self.about_button = ttk.Button(buttons_frame, text="ℹ️ 关于", command=self.show_about, style='Info.TButton', width=button_width)
        self.about_button.pack(side=tk.LEFT)
        
        # 状态信息框架 - 使用卡片式设计
        status_frame = ttk.LabelFrame(main_frame, text="📊 运行状态", padding="15")
        status_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))
        
        # 状态指示器
        status_indicator_frame = ttk.Frame(status_frame)
        status_indicator_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_label = ttk.Label(status_indicator_frame, text="● 状态: 未开始监控", font=("Arial", 11, "bold"), style='Status.TLabel')
        self.status_label.pack(side=tk.LEFT)
        
        # 状态详细信息
        status_details_frame = ttk.Frame(status_frame)
        status_details_frame.pack(fill=tk.X)
        
        # 左侧状态信息
        left_status_frame = ttk.Frame(status_details_frame)
        left_status_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.time_label = ttk.Label(left_status_frame, text="⏱️ 运行时间: 00:00:00", font=('Arial', 9))
        self.time_label.pack(anchor=tk.W, pady=(2, 0))
        
        self.check_label = ttk.Label(left_status_frame, text="🔍 网络检测次数: 0", font=('Arial', 9))
        self.check_label.pack(anchor=tk.W, pady=(2, 0))
        
        # 右侧状态信息
        right_status_frame = ttk.Frame(status_details_frame)
        right_status_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        self.last_check_label = ttk.Label(right_status_frame, text="🕐 上次检测: 未检测", font=('Arial', 9))
        self.last_check_label.pack(anchor=tk.E, pady=(2, 0))
        
        # 添加进度条
        self.progress_frame = ttk.Frame(status_frame)
        self.progress_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(self.progress_frame, text="📈 监控进度:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode='indeterminate', length=300)
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))
        
        # 日志显示框架 - 使用卡片式设计
        log_frame = ttk.LabelFrame(main_frame, text="📝 运行日志", padding="15")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 日志工具栏
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(log_toolbar, text="📋 实时日志输出", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
        
        # 日志控制按钮
        log_controls = ttk.Frame(log_toolbar)
        log_controls.pack(side=tk.RIGHT)
        
        self.clear_log_button = ttk.Button(log_controls, text="🗑️ 清空", command=self.clear_log, style='Danger.TButton')
        self.clear_log_button.pack(side=tk.LEFT, padx=(5, 0))
        
        # 日志文本框
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=80, font=('Consolas', 9), 
                                                bg='#f8f9fa', fg='#2c3e50', insertbackground='#2c3e50')
        self.log_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重 - 实现自适应布局
        # 主框架权重配置
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # 主框架内部权重配置
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)  # 日志框架可扩展
        
        # 配置框架内部权重配置
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)
        
        # 状态框架内部权重配置
        status_frame.columnconfigure(0, weight=1)
        
        # 日志框架内部权重配置
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)  # 日志文本框可扩展
        
        # 日志工具栏权重配置
        log_toolbar.columnconfigure(0, weight=1)
    
    def _setup_gui_logging(self):
        """
        设置GUI日志记录器，将日志同时输出到文件和GUI
        """
        try:
            # 创建logs目录
            logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            
            # 设置日志文件路径
            log_file = os.path.join(logs_dir, 'GUI.log')
            
            # 创建日志记录器
            self.gui_logger = logging.getLogger('gui_logger')
            
            # 如果已经配置过，直接返回
            if self.gui_logger.handlers:
                return
                
            self.gui_logger.setLevel(logging.INFO)
            
            # 创建文件处理器
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            # 添加处理器
            self.gui_logger.addHandler(file_handler)
            
            # 防止传播到根logger
            self.gui_logger.propagate = False
            
        except Exception as e:
            print(f"设置GUI日志失败: {e}")
            self.gui_logger = None
    
    def log_message(self, message):
        """
        在日志区域显示消息，并同时保存到文件
        
        参数:
            message: 要显示的消息
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        # 在主线程中更新GUI
        self.root.after(0, lambda: self._update_log_text(log_entry))
        
        # 同时写入日志文件
        if hasattr(self, 'gui_logger') and self.gui_logger:
            try:
                # 移除时间戳，因为logging模块会自动添加
                clean_message = message
                self.gui_logger.info(clean_message)
            except Exception as e:
                print(f"写入日志文件失败: {e}")
    
    def _update_log_text(self, log_entry):
        """
        更新日志文本框内容
        
        参数:
            log_entry: 日志条目
        """
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
    
    def clear_log(self):
        """
        清空日志内容
        """
        self.log_text.delete(1.0, tk.END)
        self.log_message("📝 日志已清空")
    
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
            
            self.monitor_button.config(text="⏹️ 停止监控")
            self.username_entry.config(state="disabled")
            self.password_entry.config(state="disabled")
            
            # 启动进度条
            self.progress_bar.start()
            
            # 启动监控线程
            self.monitor_thread = threading.Thread(target=self.monitor_network, daemon=True)
            self.monitor_thread.start()
            
            self.log_message("🚀 开始网络监控")
        else:
            # 停止监控
            self.monitoring = False
            self.monitor_button.config(text="▶️ 开始监控")
            self.username_entry.config(state="normal")
            self.password_entry.config(state="normal")
            
            # 停止进度条
            self.progress_bar.stop()
            
            self.log_message("⏹️ 停止网络监控")
    
    def monitor_network(self) -> None:
        """
        网络监控主循环
        """
        consecutive_failures = 0
        
        while self.monitoring:
            try:
                # 检查是否在暂停登录时段
                if self._is_in_pause_period():
                    self.log_message("⏰ 当前处于暂停登录时段，暂停网络监控")
                    # 等待1分钟后重新检查
                    for i in range(60):
                        if not self.monitoring:
                            return
                        time.sleep(1)
                    continue
                
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
                    
                    # 尝试登录（不检查暂停时间，因为已经在监控循环中检查了）
                    login_success = self._attempt_login_without_pause_check()
                    
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
    
    def _is_in_pause_period(self) -> bool:
        """
        检查当前是否在暂停登录时段
        
        返回:
            bool: 是否在暂停时段
        """
        # 检查暂停登录是否启用
        if not self.pause_login_var.get():
            return False
        
        current_hour = datetime.datetime.now().hour
        start_hour = int(self.pause_start_var.get())
        end_hour = int(self.pause_end_var.get())
        
        if start_hour < end_hour:
            return start_hour <= current_hour < end_hour
        else:  # 跨天情况
            return current_hour >= start_hour or current_hour < end_hour
    
    def _attempt_login_without_pause_check(self) -> bool:
        """
        执行登录（不检查暂停时间）
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 使用 ConfigAdapter 创建认证配置
            gui_config = {
                'username': self.username_var.get(),
                'password': self.password_var.get(),
                'carrier_suffix': self.carrier_mapping.get(self.carrier_var.get(), ''),
                'headless': self.headless_var.get()
            }
            
            config = ConfigLoader.load_config_from_env()
            auth_config = ConfigAdapter.create_auth_config(gui_config, config)
            
            # 使用 LoginAttemptHandler 进行登录
            login_handler = LoginAttemptHandler(auth_config)
            
            # 执行登录（异步调用）
            try:
                success = asyncio.run(login_handler.attempt_login())
                return success
            except Exception as e:
                self.log_message(f"❌ 校园网登录失败: {str(e)}")
                return False
                
        except Exception as e:
            self.log_message(f"❌ 登录过程中发生错误: {str(e)}")
            return False
    
    def attempt_login(self) -> bool:
        """
        尝试登录校园网（手动登录，不检查暂停时间）
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 手动登录不检查暂停时间，直接执行登录
            return self._attempt_login_without_pause_check()
                
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
        def run_manual_login():
            try:
                success = self.attempt_login()
                if success:
                    self.log_message("✅ 手动登录成功！")
                else:
                    self.log_message("❌ 手动登录失败")
            except Exception as e:
                error_msg = f"手动登录发生错误: {str(e)}"
                self.log_message(f"❌ {error_msg}")
        
        threading.Thread(target=run_manual_login, daemon=True).start()
    
    def manual_auth_fallback(self):
        """
        手动认证备选方案
        当自动认证失败时使用
        """
        if not self.username_var.get() or not self.password_var.get():
            messagebox.showerror("错误", "请输入账号和密码")
            return
        
        # 确认对话框
        result = messagebox.askyesno(
            "手动认证确认", 
            "手动认证将打开浏览器窗口，您需要手动点击登录按钮。\n\n"
            "此功能适用于自动认证失败或被拉黑的情况。\n\n"
            "是否继续？"
        )
        
        if not result:
            return
        
        self.log_message("🔄 启动手动认证备选方案...")
        
        # 在新线程中执行手动认证
        def run_manual_auth():
            try:
                # 使用 ConfigAdapter 创建认证配置
                gui_config = {
                    'username': self.username_var.get(),
                    'password': self.password_var.get(),
                    'carrier_suffix': self.carrier_mapping.get(self.carrier_var.get(), ''),
                    'headless': False  # 手动认证必须使用非无头模式
                }
                
                base_config = ConfigLoader.load_config_from_env()
                auth_config = ConfigAdapter.create_auth_config(gui_config, base_config)
                
                # 创建认证器实例
                auth = EnhancedCampusNetworkAuth(auth_config)
                
                # 执行手动认证
                success, message = asyncio.run(auth.manual_auth_fallback())
                
                if success:
                    self.log_message(f"✅ 手动认证成功！{message}")
                    messagebox.showinfo("成功", f"手动认证成功！{message}")
                else:
                    self.log_message(f"❌ 手动认证失败: {message}")
                    messagebox.showerror("失败", f"手动认证失败: {message}")
                    
            except Exception as e:
                error_msg = f"手动认证发生错误: {str(e)}"
                self.log_message(f"❌ {error_msg}")
                messagebox.showerror("错误", error_msg)
        
        threading.Thread(target=run_manual_auth, daemon=True).start()
    
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
                # 使用 ConfigAdapter 创建认证配置
                gui_config = {
                    'username': self.username_var.get().strip(),
                    'password': self.password_var.get().strip(),
                    'carrier_suffix': self.carrier_mapping.get(self.carrier_var.get(), ""),
                    'headless': self.headless_var.get()
                }
                
                base_config = ConfigLoader.load_config_from_env()
                auth_config = ConfigAdapter.create_auth_config(gui_config, base_config)
                
                # 创建认证器实例
                auth = EnhancedCampusNetworkAuth(auth_config)
                
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
            # 使用 get_runtime_stats 获取运行时间
            if self.start_time:
                runtime_str, _ = get_runtime_stats(self.start_time, self.network_check_count)
                self.time_label.config(text=f"⏱️ 运行时间: {runtime_str}")
            
            self.status_label.config(text="🟢 状态: 监控中", foreground="#27ae60")
        else:
            self.status_label.config(text="🔴 状态: 未监控", foreground="#e74c3c")
        
        # 更新检测次数
        self.check_label.config(text=f"🔍 网络检测次数: {self.network_check_count}")
        
        # 更新上次检测时间
        if self.last_check_time:
            time_str = self.last_check_time.strftime("%H:%M:%S")
            self.last_check_label.config(text=f"🕐 上次检测: {time_str}")
        
        # 每秒更新一次
        self.root.after(1000, self.update_status)
    
    def initial_network_check(self):
        """
        启动时检查是否需要自动开始监控
        """
        # 使用GUI中的自动启动选项
        auto_start = self.auto_start_var.get()
        
        if not auto_start:
            self.log_message("ℹ️ 根据配置，启动时不自动开始监控")
            return
            
        # 检查是否有必要的登录信息
        if not self.username_var.get() or not self.password_var.get():
            self.log_message("⚠️ 缺少用户名或密码，跳过自动启动监控")
            return
        
        # 延迟启动监控，给界面一些时间完成初始化
        def auto_start_monitoring():
            try:
                time.sleep(1)  # 等待2秒让界面完全加载
                self.log_message("🚀 应用启动，根据配置自动开始监控")
                
                # 直接调用监控切换方法启动监控
                self.root.after(0, self.toggle_monitoring)
                    
            except Exception as e:
                self.log_message(f"❌ 自动启动监控发生错误: {str(e)}")
        
        threading.Thread(target=auto_start_monitoring, daemon=True).start()
    
    def validate_config(self) -> tuple[bool, str]:
        """
        验证当前配置是否有效
        
        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        return ConfigValidator.validate_gui_config(
            self.username_var.get(),
            self.password_var.get(),
            self.check_interval_var.get()
        )
    
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
            pause_enabled = self.pause_login_var.get()
            pause_start = self.pause_start_var.get().strip()
            pause_end = self.pause_end_var.get().strip()
            
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

# 暂停登录时间配置
PAUSE_LOGIN_ENABLED={str(pause_enabled).lower()}
PAUSE_LOGIN_START_HOUR={pause_start}
PAUSE_LOGIN_END_HOUR={pause_end}

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
            config = ConfigLoader.load_config_from_env()
            if config.get('username'):
                self.username_var.set(config['username'])
            if config.get('password'):
                self.password_var.set(config['password'])
            
            # 设置运营商
            isp_code = config.get('isp', '')  # 默认不使用运营商后缀
            for chinese_name, code in self.carrier_mapping.items():
                if code == isp_code:
                    self.carrier_var.set(chinese_name)
                    break
            else:
                # 如果没有找到匹配的运营商，默认设置为"无"
                self.carrier_var.set("无")
                    
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
            
            # 设置暂停登录时间配置
            pause_config = config.get('pause_login', {})
            pause_enabled = pause_config.get('enabled', True)
            pause_start = pause_config.get('start_hour', 0)
            pause_end = pause_config.get('end_hour', 6)
            
            self.pause_login_var.set(pause_enabled)
            self.pause_start_var.set(str(pause_start))
            self.pause_end_var.set(str(pause_end))
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