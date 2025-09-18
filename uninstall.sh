#!/bin/bash
# 校园网自动认证工具 - macOS 卸载脚本
# 用于移除开机自启动服务

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目配置
SERVICE_NAME="com.campus.network.auth"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/${SERVICE_NAME}.plist"

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查系统类型
check_system() {
    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "此脚本仅支持 macOS 系统"
        exit 1
    fi
    print_info "检测到 macOS 系统"
}

# 停止并卸载服务
uninstall_service() {
    print_info "正在卸载 launchd 服务..."
    
    # 检查服务是否存在
    if [[ ! -f "$TARGET_PLIST" ]]; then
        print_warning "未找到服务文件: $TARGET_PLIST"
        print_info "服务可能已经被卸载"
        return 0
    fi
    
    # 停止服务
    print_info "停止服务..."
    if launchctl list | grep -q "$SERVICE_NAME"; then
        launchctl unload "$TARGET_PLIST" 2>/dev/null || {
            print_warning "停止服务时出现警告，继续卸载..."
        }
        print_success "服务已停止"
    else
        print_info "服务未在运行"
    fi
    
    # 删除 plist 文件
    print_info "删除服务配置文件..."
    rm -f "$TARGET_PLIST"
    print_success "服务配置文件已删除"
}

# 验证卸载结果
verify_uninstall() {
    print_info "验证卸载结果..."
    
    sleep 1  # 等待系统更新
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_warning "服务可能仍在运行，请手动检查"
        print_info "可以尝试运行: launchctl remove $SERVICE_NAME"
    else
        print_success "服务已完全卸载"
    fi
    
    if [[ -f "$TARGET_PLIST" ]]; then
        print_warning "配置文件仍然存在: $TARGET_PLIST"
    else
        print_success "配置文件已删除"
    fi
}

# 清理提示
show_cleanup_info() {
    echo
    print_info "=== 卸载完成 ==="
    echo
    print_info "如果需要完全清理，您还可以:"
    echo "  1. 删除项目目录（如果不再需要）"
    echo "  2. 删除日志文件: rm -rf $(pwd)/logs"
    echo "  3. 删除配置文件: rm -f $(pwd)/.env"
    echo
    print_info "如果需要重新安装，请运行: ./install.sh"
    echo
    print_success "校园网自动认证工具已从开机自启动中移除！"
}

# 确认卸载
confirm_uninstall() {
    echo
    print_warning "即将卸载校园网自动认证工具的开机自启动服务"
    print_info "服务名称: $SERVICE_NAME"
    print_info "配置文件: $TARGET_PLIST"
    echo
    
    read -p "确认要继续卸载吗？(y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "取消卸载"
        exit 0
    fi
}

# 主函数
main() {
    echo
    print_info "=== 校园网自动认证工具 - macOS 卸载脚本 ==="
    echo
    
    check_system
    confirm_uninstall
    uninstall_service
    verify_uninstall
    show_cleanup_info
}

# 执行主函数
main "$@"