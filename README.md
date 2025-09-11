# 校园网自动认证工具

基于 Playwright 的校园网自动认证工具，支持自动填写用户名密码并提交认证表单。提供GUI界面和命令行两种使用方式。

## 功能特性

### 基础认证功能
- 🚀 **自动化认证**: 使用 Playwright 自动化浏览器操作
- 🔄 **智能重试**: 支持认证失败时的自动重试机制
- 📝 **日志记录**: 详细的操作日志，便于问题排查
- ⚙️ **灵活配置**: 支持配置文件和命令行参数两种使用方式
- 🎯 **多选择器**: 智能识别各种常见的登录表单元素
- 🔍 **结果检测**: 自动检测认证成功或失败状态

### 网络监控功能
- 🔍 定期检测网络连接状态（默认4分钟间隔）
- 🌐 多目标ping测试（百度、Google DNS、114 DNS）
- 🔧 网络断开时自动执行校园网认证
- 📊 智能失败计数和认证冷却机制
- 🚀 macOS开机自启动支持
- 📋 完整的服务管理和日志记录

## 环境要求

- Python 3.10+
- uv (Python 包管理工具)
- 支持的操作系统: macOS, Linux, Windows

## 快速开始

### 1. 环境配置

```bash
# 克隆或下载项目到本地
cd network

# 项目已初始化，直接同步依赖
uv sync

# 安装 Playwright 浏览器驱动
uv run playwright install
```

### 2. 配置认证信息

复制 `.env.example` 文件为 `.env` 并修改配置：

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
vim .env  # 或使用其他编辑器
```

在 `.env` 文件中配置您的认证信息：

```bash
# 认证信息 (必填)
CAMPUS_USERNAME=your_actual_username
CAMPUS_PASSWORD=your_actual_password

# 网络配置
CAMPUS_AUTH_URL=http://172.29.0.2
CAMPUS_ISP=@cmcc  # @cmcc(移动) @unicom(联通) @telecom(电信) @xyw(测试)

# 浏览器设置
BROWSER_HEADLESS=false  # true: 后台运行, false: 显示浏览器窗口
BROWSER_TIMEOUT=10000

# 重试设置
RETRY_MAX_RETRIES=3
RETRY_INTERVAL=5

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/campus_auth.log

# 网络监控设置
MONITOR_INTERVAL=240
PING_TARGETS=8.8.8.8,114.114.114.114,baidu.com
```

### 3. 运行应用

#### 方式一：运行GUI应用程序（推荐）

```bash
# 运行GUI应用程序
uv run app.py
```

#### 方式二：使用命令行认证脚本

```bash
# 使用 .env 配置文件运行
uv run src/campus_login.py
```

**运营商选项说明：**
- `@cmcc`: 中国移动（默认）
- `@unicom`: 中国联通
- `@telecom`: 中国电信
- `@xyw`: 测试

### 4. 网络监控功能

#### 启动监控

```bash
# 在GUI中启动网络监控
# 或者使用命令行启动
uv run src/network_test.py monitor
```

#### 停止监控

```bash
# 在GUI中停止网络监控
# 或者使用命令行停止（如果以命令行方式启动）
# 按 Ctrl+C 停止
```

#### 安装开机自启动服务（macOS）
```bash
# 安装服务
./install_service.sh

# 卸载服务
./uninstall_service.sh
```

## 项目结构

```
network/
├── app.py                              # GUI应用程序主文件
├── campus_login.py                     # 校园网登录认证脚本
├── network_test.py                     # 网络连通性测试脚本
├── logs/                               # 日志文件夹
├── .env                                # 环境变量配置文件（包含敏感信息）
├── .env.example                        # 环境变量配置模板
├── pyproject.toml                      # 项目依赖配置
├── README.md                           # 项目说明文档
└── src/                                # 源代码目录
```

## 详细使用说明

### 脚本功能对比

| 功能 | campus_login.py | network_test.py |
|------|-----------------|------------------|
| 校园网登录认证 | ✅ | ❌ |
| 网络连通性测试 | ❌ | ✅ |
| .env 配置文件 | ✅ | ❌ |
| 重试机制 | ✅ | ❌ |
| 日志记录 | ✅ | ❌ |
| 推荐使用 | 校园网登录 | 网络状态检测 |

### 配置选项说明

#### 基本配置
- `username`: 校园网用户名
- `password`: 校园网密码
- `auth_url`: 认证页面URL
- `isp`: 运营商类型（可选）

#### 运营商配置说明
- `@cmcc`: 中国移动
- `@unicom`: 中国联通  
- `@telecom`: 中国电信
- `@xyw`: 测试
- 如果页面没有运营商选择框，此配置会被自动忽略

#### 浏览器设置
- `headless`: 是否无头模式运行（True: 后台运行，False: 显示浏览器）
- `timeout`: 页面加载超时时间（毫秒）
- `user_agent`: 浏览器用户代理字符串

#### 重试设置
- `max_retries`: 最大重试次数
- `retry_interval`: 重试间隔时间（秒）

#### 日志设置
- `level`: 日志级别（DEBUG, INFO, WARNING, ERROR）
- `format`: 日志格式
- `file`: 日志文件名（可选）

### 常见认证页面URL

项目支持多种常见的校园网认证页面：

- `http://172.29.0.2` （默认）
- `http://192.168.1.1`
- `http://10.0.0.1`
- `http://172.16.0.1`
- `http://auth.campus.edu.cn`
- `http://login.campus.edu.cn`

## 服务管理

### 服务状态查看
```bash
# 查看服务状态
launchctl list | grep com.campus.network.monitor

# 查看服务详细信息
launchctl print gui/$(id -u)/com.campus.network.monitor
```

### 日志文件位置
- **应用日志**: `~/Library/Logs/campus_network_monitor.log`
- **输出日志**: `~/Library/Logs/campus_network_monitor.out.log`
- **错误日志**: `~/Library/Logs/campus_network_monitor.err.log`

### 手动控制服务
```bash
# 启动服务
launchctl load ~/Library/LaunchAgents/com.campus.network.monitor.plist

# 停止服务
launchctl unload ~/Library/LaunchAgents/com.campus.network.monitor.plist

# 重启服务
launchctl unload ~/Library/LaunchAgents/com.campus.network.monitor.plist
launchctl load ~/Library/LaunchAgents/com.campus.network.monitor.plist
```

## 故障排除

### 常见问题

1. **认证失败**
   - 检查用户名和密码是否正确
   - 确认认证页面URL是否正确
   - 查看日志文件了解详细错误信息
   - 确认运营商选择正确

2. **无法填入账号和密码**
   - 脚本会自动截图保存为 `debug_page.png`，可查看页面状态
   - 检查页面是否完全加载
   - 确认表单元素是否可见
   - 运行调试脚本：`uv run test_debug.py`

3. **页面加载超时**
   - 检查网络连接
   - 增加 `timeout` 配置值
   - 确认认证页面是否可访问

4. **找不到表单元素**
   - 设置 `headless: false` 查看页面结构
   - 检查认证页面是否有特殊的表单结构
   - 可能需要自定义选择器

5. **服务无法启动**
   - 检查Python虚拟环境是否存在
   - 确认配置文件路径是否正确
   - 查看错误日志文件

6. **网络监控不工作**
   - 检查ping命令是否可用
   - 确认测试主机是否可达
   - 调整检查间隔和失败阈值

### 调试工具

- `test_debug.py`: 页面结构分析工具
- `test_form_fill.py`: 表单填写功能测试
- `debug_page.png`: 自动生成的页面截图

### 调试模式

启用调试模式查看详细信息：

```python
# 在 config.py 中设置
LOGGING_CONFIG = {
    "level": "DEBUG",
    "file": "debug.log"
}

# 设置浏览器可见
CAMPUS_NETWORK_CONFIG = {
    "browser_settings": {
        "headless": False
    }
}
```

```bash
# 前台运行监控服务（便于调试）
uv run network_monitor.py

# 查看实时日志
tail -f ~/Library/Logs/campus_network_monitor.log
```

## 安全注意事项

- 🔒 **密码安全**: 请妥善保管配置文件，避免密码泄露
- 🚫 **版本控制**: 不要将包含真实密码的配置文件提交到版本控制系统
- 🛡️ **权限控制**: 建议设置配置文件的适当访问权限

## 开发规范

本项目遵循以下开发规范：

- 使用 Python 3.10+ 语法
- 遵循 PEP 8 代码风格
- 使用 uv 进行依赖管理
- 代码包含详细的中文注释
- 函数和类使用类型注解
- 提供GUI和命令行两种使用方式



## 许可证

本项目仅供学习和个人使用，请遵守相关法律法规和校园网使用规定。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目！

---

**注意**: 使用本工具前请确保您有权限访问相应的校园网络，并遵守学校的网络使用政策。