# 校园网自动认证工具 - 开机自启动配置

本文档说明如何配置校园网自动认证工具的开机自启动功能，让工具在系统启动时自动运行。

## 功能特性

- ✅ **跨平台支持**: 支持 macOS 和 Linux 系统
- ✅ **开机自启动**: 系统启动时自动运行
- ✅ **后台运行**: 守护进程模式，不占用终端
- ✅ **进程管理**: 支持启动、停止、状态查询
- ✅ **日志记录**: 完整的运行日志记录
- ✅ **单实例运行**: 防止重复启动

## 系统要求

- **macOS**: 10.10 或更高版本
- **Linux**: 支持 systemd 的发行版
- **Python**: 3.10 或更高版本
- **uv**: Python 包管理工具

## 快速开始

### 1. 安装自启动服务

```bash
# 给脚本添加执行权限（如果还没有）
chmod +x install.sh uninstall.sh

# 安装自启动服务
./install.sh
```

安装脚本会自动：
- 检测操作系统类型
- 验证依赖环境
- 创建必要的目录和文件
- 配置系统服务
- 启动服务并验证状态

### 2. 验证安装

```bash
# 查看服务状态
uv run app_cli.py --status

# 或者使用系统命令查看（macOS）
launchctl list | grep com.campus.network.auth
```

### 3. 卸载服务

```bash
# 卸载自启动服务
./uninstall.sh
```

## 详细使用说明

### 命令行选项

```bash
# 前台运行（调试模式）
uv run app_cli.py

# 后台守护进程模式运行
uv run app_cli.py --daemon

# 查看服务运行状态
uv run app_cli.py --status

# 停止后台运行的服务
uv run app_cli.py --stop

# 显示帮助信息
uv run app_cli.py --help
```

### 服务管理

#### macOS (launchd)

```bash
# 手动启动服务
launchctl load ~/Library/LaunchAgents/com.campus.network.auth.plist

# 手动停止服务
launchctl unload ~/Library/LaunchAgents/com.campus.network.auth.plist

# 查看服务状态
launchctl list com.campus.network.auth

# 查看服务日志
tail -f ~/JCU_auto_network/logs/campus_network_auth.log
```

#### Linux (systemd)

```bash
# 手动启动服务
systemctl --user start campus-network-auth

# 手动停止服务
systemctl --user stop campus-network-auth

# 查看服务状态
systemctl --user status campus-network-auth

# 查看服务日志
journalctl --user -u campus-network-auth -f
```

## 配置文件

### macOS - launchd plist

服务配置文件位置：`~/Library/LaunchAgents/com.campus.network.auth.plist`

主要配置项：
- **Label**: 服务标识符
- **Program**: 执行程序路径
- **WorkingDirectory**: 工作目录
- **RunAtLoad**: 开机自启动
- **KeepAlive**: 进程保活
- **StandardOutPath/StandardErrorPath**: 日志输出路径

### Linux - systemd service

服务配置文件位置：`~/.config/systemd/user/campus-network-auth.service`

主要配置项：
- **ExecStart**: 启动命令
- **WorkingDirectory**: 工作目录
- **Restart**: 重启策略
- **WantedBy**: 启动目标

## 日志管理

### 日志文件位置

- **应用日志**: `~/JCU_auto_network/logs/campus_network_auth.log`
- **系统日志**: 
  - macOS: 通过 `Console.app` 或 `log show` 命令查看
  - Linux: 通过 `journalctl` 命令查看

### 日志轮转

应用会自动进行日志轮转：
- 单个日志文件最大 **2MB**
- 保留最近 **5** 个日志文件
- 自动轮转，无需手动管理
- 支持 UTF-8 编码，确保中文日志正常显示

## 故障排除

### 常见问题

#### 1. 服务无法启动

**检查步骤**：
```bash
# 检查配置文件
cat .env

# 检查 Python 环境
uv run python --version

# 检查依赖
uv sync

# 手动测试运行
uv run app_cli.py
```

#### 2. 服务启动后立即退出

**可能原因**：
- 配置文件错误或缺失
- 网络环境问题
- 权限问题

**解决方法**：
```bash
# 查看详细日志
tail -f logs/campus_network_auth.log

# 前台运行查看错误
uv run app_cli.py
```

#### 3. 权限问题

```bash
# 确保脚本有执行权限
chmod +x install.sh uninstall.sh

# 确保日志目录可写
mkdir -p logs
chmod 755 logs
```

#### 4. 端口占用

如果遇到端口占用问题：
```bash
# 查看端口占用情况
lsof -i :8080  # 替换为实际端口

# 修改配置文件中的端口设置
```

### 调试模式

在前台运行程序进行调试：
```bash
# 停止后台服务
uv run app_cli.py --stop

# 前台运行查看详细输出
uv run app_cli.py
```

## 安全注意事项

1. **配置文件安全**：
   - `.env` 文件包含敏感信息，确保权限设置正确
   - 不要将包含密码的配置文件提交到版本控制系统

2. **网络安全**：
   - 定期更新密码
   - 监控异常登录活动

3. **系统安全**：
   - 定期检查服务运行状态
   - 监控系统资源使用情况

## 更新和维护

### 更新程序

```bash
# 停止服务
./uninstall.sh

# 更新代码
git pull origin main

# 更新依赖
uv sync

# 重新安装服务
./install.sh
```

### 备份配置

```bash
# 备份配置文件
cp .env .env.backup

# 备份日志（可选）
tar -czf logs_backup_$(date +%Y%m%d).tar.gz logs/
```

## 技术支持

如果遇到问题，请：

1. 查看日志文件获取详细错误信息
2. 确认系统环境和依赖是否正确安装
3. 尝试前台运行程序进行调试
4. 检查网络连接和校园网认证页面是否正常

## 版本历史

- **v2.0**: 添加开机自启动和守护进程功能
- **v1.0**: 基础校园网自动认证功能

---

**注意**: 本工具仅用于合法的网络认证自动化，请遵守学校的网络使用政策。