#!/bin/bash
# JCU校园网自动认证工具 - macOS开机自启动卸载脚本
# 作者: 开发团队
# 版本: 1.0.0

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
SERVICE_NAME="com.jcu.auto-network"
LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"

# 打印函数
print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

print_error() {
    echo -e "${RED}[错误]${NC} $1"
}

print_header() {
    echo -e "${RED}===============================================${NC}"
    echo -e "${RED}   JCU校园网自动认证工具 - macOS自启动卸载${NC}"
    echo -e "${RED}===============================================${NC}"
    echo
}

# 确认卸载
confirm_uninstall() {
    echo -e "${YELLOW}⚠️  您即将卸载JCU校园网自动认证工具的开机自启动服务${NC}"
    echo -e "${YELLOW}   这将停止并移除自动启动功能，但不会删除主程序${NC}"
    echo
    read -p "确认继续？(y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "用户取消操作"
        exit 0
    fi
}

# 停止服务
stop_service() {
    print_info "停止launchd服务..."
    
    # 检查服务是否存在
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_info "发现运行中的服务，正在停止..."
        
        # 停止服务
        if launchctl stop "$SERVICE_NAME" 2>/dev/null; then
            print_success "服务已停止"
        else
            print_warning "停止服务时出现警告（可能服务已停止）"
        fi
        
        # 卸载服务
        if launchctl unload "$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist" 2>/dev/null; then
            print_success "服务已卸载"
        else
            print_warning "卸载服务时出现警告"
        fi
        
        # 移除服务
        if launchctl remove "$SERVICE_NAME" 2>/dev/null; then
            print_success "服务已移除"
        else
            print_warning "移除服务时出现警告（可能服务不存在）"
        fi
        
    else
        print_info "未发现运行中的服务"
    fi
}

# 删除配置文件
remove_files() {
    print_info "删除配置文件..."
    
    local plist_file="$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist"
    
    # 删除plist文件
    if [[ -f "$plist_file" ]]; then
        if rm "$plist_file"; then
            print_success "已删除plist配置文件: $plist_file"
        else
            print_error "删除plist文件失败: $plist_file"
        fi
    else
        print_info "plist配置文件不存在: $plist_file"
    fi
}

# 清理日志文件
cleanup_logs() {
    print_info "清理日志文件..."
    
    if [[ -d "$LOG_DIR" ]]; then
        echo
        print_warning "发现日志目录: $LOG_DIR"
        
        # 显示具体的日志文件
        print_info "发现以下日志文件:"
        if ls "$LOG_DIR"/*.log 2>/dev/null; then
            echo
        else
            echo "  (未发现.log文件)"
        fi
        
        # 显示日志文件大小
        if command -v du &> /dev/null; then
            local log_size=$(du -sh "$LOG_DIR" 2>/dev/null | cut -f1 || echo "未知")
            print_info "日志文件总大小: $log_size"
        fi
        
        echo
        read -p "是否删除所有日志文件？(y/N): " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if rm -rf "$LOG_DIR"; then
                print_success "已删除日志目录: $LOG_DIR"
            else
                print_error "删除日志目录失败: $LOG_DIR"
            fi
        else
            print_info "保留日志文件"
        fi
    else
        print_info "未发现日志目录"
    fi
}

# 验证卸载
verify_uninstall() {
    print_info "验证卸载结果..."
    
    local errors=0
    
    # 检查服务状态
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_error "❌ 服务仍在运行中"
        errors=$((errors + 1))
    else
        print_success "✅ 服务已完全停止"
    fi
    
    # 检查plist文件
    if [[ -f "$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist" ]]; then
        print_error "❌ plist配置文件仍然存在"
        errors=$((errors + 1))
    else
        print_success "✅ plist配置文件已删除"
    fi
    
    # 总结
    echo
    if [[ $errors -eq 0 ]]; then
        print_success "✅ 卸载完成！自启动服务已完全移除"
    else
        print_warning "⚠️  卸载可能不完整，请手动检查剩余文件"
    fi
}

# 显示卸载后信息
show_post_uninstall_info() {
    echo
    print_info "==================== 卸载完成 ===================="
    echo
    echo "✅ JCU校园网自动认证工具的开机自启动服务已卸载"
    echo
    echo "📋 主程序仍然保留，您可以："
    echo "  手动运行: python3 app_cli.py"
    echo "  重新安装自启动: bash install/mac/install.sh"
    echo
    echo "📁 相关文件位置:"
    echo "  主程序目录: $PROJECT_ROOT"
    echo "  配置文件: .env"
    
    if [[ -d "$LOG_DIR" ]]; then
        echo "  日志目录: $LOG_DIR"
        echo "    - campus_auth.log (应用程序详细日志)"
        echo "    - jcu-auto-network-error.log (系统错误日志)"
    fi
    
    echo
    echo "🔄 如需重新安装，请运行:"
    echo "  bash $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh"
    echo
    print_success "卸载完成！"
}

# 主函数
main() {
    print_header
    
    # 检查系统
    if [[ "$(uname)" != "Darwin" ]]; then
        print_error "此脚本仅支持macOS系统"
        exit 1
    fi
    
    confirm_uninstall
    stop_service
    remove_files
    cleanup_logs
    verify_uninstall
    show_post_uninstall_info
}

# 错误处理
trap 'print_error "卸载过程中发生错误，请检查上述输出信息"; exit 1' ERR

# 执行主函数
main "$@"