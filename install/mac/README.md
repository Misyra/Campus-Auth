# JCU校园网自动认证工具 - macOS开机自启动说明

## 📋 功能介绍

本目录包含macOS系统的开机自启动脚本，可以让校园网自动认证工具在系统启动时自动运行，确保网络连接的持续可用性。

## 📁 文件说明

- `com.jcu.auto-network.plist` - launchd服务配置文件模板
- `install.sh` - 自启动服务安装脚本
- `uninstall.sh` - 自启动服务卸载脚本
- `README.md` - 本说明文件

## 🚀 快速安装

### 1. 安装自启动服务

```bash
cd /Users/misyra/JCU_auto_network/install/mac
bash install.sh
```

### 2. 验证安装

```bash
# 查看服务状态
launchctl list | grep com.jcu.auto-network

# 查看运行日志
tail -f /Users/misyra/JCU_auto_network/logs/jcu-auto-network.log
```

## 🔧 服务管理

### 启动服务
```bash
launchctl start com.jcu.auto-network
```

### 停止服务
```bash
launchctl stop com.jcu.auto-network
```

### 重启服务
```bash
launchctl kickstart -k gui/$(id -u)/com.jcu.auto-network
```

### 查看服务状态
```bash
launchctl list | grep com.jcu.auto-network
```

## 📝 日志文件

日志文件位于项目目录下的 `logs/` 文件夹：

- `logs/jcu-auto-network.log` - 标准输出日志
- `logs/jcu-auto-network-error.log` - 错误输出日志

### 查看实时日志
```bash
# 查看标准日志
tail -f /Users/misyra/JCU_auto_network/logs/jcu-auto-network.log

# 查看错误日志
tail -f /Users/misyra/JCU_auto_network/logs/jcu-auto-network-error.log
```

## ⚙️ 配置说明

### 服务配置特性

- **自动启动**: 系统启动时自动运行
- **网络依赖**: 仅在网络可用时启动
- **自动重启**: 程序意外退出时自动重启
- **资源限制**: 限制内存使用（256MB）
- **启动延迟**: 等待系统完全启动（30秒）
- **重启保护**: 避免频繁重启（10秒间隔）

### 环境要求

- macOS 10.10+ (Yosemite及以上版本)
- Python 3.7+
- 已配置的项目环境（.env文件）

## 🛠️ 故障排查

### 1. 服务无法启动

检查配置文件是否正确：
```bash
plutil -lint ~/Library/LaunchAgents/com.jcu.auto-network.plist
```

检查Python路径是否正确：
```bash
# 查看plist文件中的Python路径
grep -A1 ProgramArguments ~/Library/LaunchAgents/com.jcu.auto-network.plist
```

### 2. 网络认证失败

检查主程序配置：
```bash
# 查看.env配置文件
cat /Users/misyra/JCU_auto_network/.env

# 手动测试程序
cd /Users/misyra/JCU_auto_network
python3 app_cli.py
```

### 3. 日志文件过大

清理旧日志：
```bash
# 清空日志文件
> /Users/misyra/JCU_auto_network/logs/jcu-auto-network.log
> /Users/misyra/JCU_auto_network/logs/jcu-auto-network-error.log

# 或删除日志目录（下次启动会自动创建）
rm -rf /Users/misyra/JCU_auto_network/logs/
```

### 4. 服务状态异常

完全重装服务：
```bash
# 卸载现有服务
bash uninstall.sh

# 重新安装
bash install.sh
```

## 🗑️ 卸载服务

```bash
cd /Users/misyra/JCU_auto_network/install/mac
bash uninstall.sh
```

卸载脚本会：
- 停止并移除launchd服务
- 删除plist配置文件
- 可选择清理日志文件
- 保留主程序和配置

## 🔒 安全说明

- 服务以当前用户权限运行，无需管理员权限
- 所有文件存储在用户目录下
- 不会修改系统级配置
- 可以随时完全卸载

## 📞 技术支持

如遇到问题，请检查：

1. **系统要求**: 确保macOS版本兼容
2. **权限问题**: 确保对相关目录有读写权限
3. **网络环境**: 确保校园网环境正常
4. **配置文件**: 确保.env配置正确
5. **日志信息**: 查看详细错误日志

---

**注意**: 本脚本专为JCU校园网环境设计，在其他网络环境中可能需要调整配置。