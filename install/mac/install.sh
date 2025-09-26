#!/bin/bash
# JCU校园网自动认证工具 - macOS开机自启动安装脚本
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
PLIST_TEMPLATE="com.jcu.auto-network.plist"
LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"

# 获取当前脚本所在目录
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
    echo -e "${BLUE}===============================================${NC}"
    echo -e "${BLUE}   JCU校园网自动认证工具 - macOS自启动安装${NC}"
    echo -e "${BLUE}===============================================${NC}"
    echo
}

# 检查系统环境
check_system() {
    print_info "检查系统环境..."
    
    # 检查是否为macOS
    if [[ "$(uname)" != "Darwin" ]]; then
        print_error "此脚本仅支持macOS系统"
        exit 1
    fi
    
    # 检查项目根目录
    if [[ ! -d "$PROJECT_ROOT" ]]; then
        print_error "无法找到项目根目录: $PROJECT_ROOT"
        exit 1
    fi
    
    # 检查Python虚拟环境
    if [[ ! -f "$PROJECT_ROOT/.venv/bin/python" ]]; then
        print_warning "未找到Python虚拟环境，将使用系统Python"
        PYTHON_PATH="$(which python3)"
        if [[ -z "$PYTHON_PATH" ]]; then
            print_error "系统中未找到python3命令"
            exit 1
        fi
    else
        PYTHON_PATH="$PROJECT_ROOT/.venv/bin/python"
        print_info "使用虚拟环境Python: $PYTHON_PATH"
    fi
    
    # 检查主程序文件
    if [[ ! -f "$PROJECT_ROOT/app_cli.py" ]]; then
        print_error "无法找到主程序文件: $PROJECT_ROOT/app_cli.py"
        exit 1
    fi
    
    # 检查配置文件
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        print_warning "未找到.env配置文件，请确保稍后手动创建配置"
    fi
    
    print_success "系统环境检查完成"
}

# 创建必要的目录
create_directories() {
    print_info "创建必要的目录..."
    
    # 创建LaunchAgents目录
    if [[ ! -d "$LAUNCHAGENTS_DIR" ]]; then
        mkdir -p "$LAUNCHAGENTS_DIR"
        print_info "已创建LaunchAgents目录: $LAUNCHAGENTS_DIR"
    fi
    
    # 创建日志目录
    if [[ ! -d "$LOG_DIR" ]]; then
        mkdir -p "$LOG_DIR"
        print_info "已创建日志目录: $LOG_DIR"
    fi
    
    print_success "目录创建完成"
}

# 停止现有服务
stop_existing_service() {
    print_info "检查并停止现有服务..."
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_info "发现现有服务，正在停止..."
        launchctl unload "$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist" 2>/dev/null || true
        launchctl remove "$SERVICE_NAME" 2>/dev/null || true
        print_success "已停止现有服务"
    else
        print_info "未发现现有服务"
    fi
}

# 生成plist配置文件
generate_plist() {
    print_info "生成launchd配置文件..."
    
    local plist_source="$SCRIPT_DIR/$PLIST_TEMPLATE"
    local plist_target="$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist"
    
    # 检查模板文件
    if [[ ! -f "$plist_source" ]]; then
        print_error "无法找到plist模板文件: $plist_source"
        exit 1
    fi
    
    # 复制并替换占位符
    cp "$plist_source" "$plist_target"
    
    # 替换路径占位符
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS使用BSD sed
        sed -i '' "s|PYTHON_PATH_PLACEHOLDER|$PYTHON_PATH|g" "$plist_target"
        sed -i '' "s|APP_PATH_PLACEHOLDER|$PROJECT_ROOT/app_cli.py|g" "$plist_target"
        sed -i '' "s|WORKING_DIR_PLACEHOLDER|$PROJECT_ROOT|g" "$plist_target"
        sed -i '' "s|PYTHONPATH_PLACEHOLDER|$PROJECT_ROOT/src|g" "$plist_target"
    else
        # GNU sed
        sed -i "s|PYTHON_PATH_PLACEHOLDER|$PYTHON_PATH|g" "$plist_target"
        sed -i "s|APP_PATH_PLACEHOLDER|$PROJECT_ROOT/app_cli.py|g" "$plist_target"
        sed -i "s|WORKING_DIR_PLACEHOLDER|$PROJECT_ROOT|g" "$plist_target"
        sed -i "s|PYTHONPATH_PLACEHOLDER|$PROJECT_ROOT/src|g" "$plist_target"
    fi
    
    print_success "plist配置文件已生成: $plist_target"
}

# 安装并启动服务
install_service() {
    print_info "安装并启动launchd服务..."
    
    local plist_file="$LAUNCHAGENTS_DIR/$SERVICE_NAME.plist"
    
    # 加载服务
    if launchctl load "$plist_file"; then
        print_success "服务已成功加载"
    else
        print_error "服务加载失败"
        exit 1
    fi
    
    # 启动服务
    if launchctl start "$SERVICE_NAME"; then
        print_success "服务已成功启动"
    else
        print_warning "服务启动可能失败，请检查日志"
    fi
}

# 验证安装
verify_installation() {
    print_info "验证安装结果..."
    
    sleep 3  # 等待服务启动
    
    # 检查服务状态
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_success "✅ 服务已成功安装并运行"
        
        # 显示服务状态
        echo
        print_info "服务状态信息:"
        launchctl list | grep "$SERVICE_NAME" || true
        
    else
        print_warning "⚠️  服务可能未正常启动"
    fi
    
    # 检查日志文件
    echo
    print_info "日志文件位置:"
    echo "  - 应用程序日志: $LOG_DIR/campus_auth.log"
    echo "  - 系统错误日志: $LOG_DIR/jcu-auto-network-error.log"
    
    # 显示最近的日志
    if [[ -f "$LOG_DIR/campus_auth.log" ]]; then
        echo
        print_info "最近的日志输出:"
        tail -n 5 "$LOG_DIR/campus_auth.log" 2>/dev/null || print_info "暂无日志输出"
    fi
}

# 显示使用说明
show_usage_info() {
    echo
    print_info "==================== 使用说明 ===================="
    echo
    echo "✅ 安装完成！校园网自动认证工具将在每次开机时自动启动。"
    echo
    echo "📋 常用命令:"
    echo "  启动服务: launchctl start $SERVICE_NAME"
    echo "  停止服务: launchctl stop $SERVICE_NAME"
    echo "  重启服务: launchctl kickstart -k gui/\$(id -u)/$SERVICE_NAME"
    echo "  查看状态: launchctl list | grep $SERVICE_NAME"
    echo "  卸载服务: bash $SCRIPT_DIR/uninstall.sh"
    echo
    echo "📝 日志文件:"
    echo "  应用程序日志: $LOG_DIR/campus_auth.log"
    echo "  系统错误日志: $LOG_DIR/jcu-auto-network-error.log"
    echo
    echo "⚙️  配置文件:"
    echo "  主配置: $PROJECT_ROOT/.env"
    echo "  服务配置: $LAUNCHAGENTS_DIR/$SERVICE_NAME.plist"
    echo
    echo "🔧 故障排查:"
    echo "  1. 检查日志文件是否有错误信息"
    echo "  2. 确保.env配置文件存在且配置正确"
    echo "  3. 确保网络连接正常"
    echo "  4. 运行 'launchctl list | grep $SERVICE_NAME' 检查服务状态"
    echo
    print_success "安装完成！"
}

# 主函数
main() {
    print_header
    
    # 检查是否有管理员权限（可选）
    if [[ $EUID -eq 0 ]]; then
        print_warning "检测到以root权限运行，建议使用普通用户权限"
    fi
    
    check_system
    create_directories
    stop_existing_service
    generate_plist
    install_service
    verify_installation
    show_usage_info
}

# 错误处理
trap 'print_error "安装过程中发生错误，请检查上述输出信息"; exit 1' ERR

# 执行主函数
main "$@"