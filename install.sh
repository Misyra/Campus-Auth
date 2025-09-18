#!/bin/bash
# 校园网自动认证工具 - macOS 安装脚本
# 用于设置开机自启动服务

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目配置
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="com.campus.network.auth"
PLIST_FILE="${PROJECT_DIR}/${SERVICE_NAME}.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/${SERVICE_NAME}.plist"
LOG_DIR="${PROJECT_DIR}/logs"

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

# 检查必要文件
check_files() {
    print_info "检查必要文件..."
    
    if [[ ! -f "${PROJECT_DIR}/app_cli.py" ]]; then
        print_error "未找到 app_cli.py 文件"
        exit 1
    fi
    
    if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
        print_warning "未找到 .env 配置文件，请确保已正确配置"
    fi
    
    if [[ ! -f "$PLIST_FILE" ]]; then
        print_error "未找到 plist 服务文件: $PLIST_FILE"
        exit 1
    fi
    
    print_success "文件检查完成"
}

# 检查并安装 uv
check_uv() {
    print_info "检查 uv 工具..."
    
    if ! command -v uv &> /dev/null; then
        print_warning "未找到 uv 工具，正在安装..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        
        # 重新加载 shell 环境
        export PATH="$HOME/.cargo/bin:$PATH"
        
        if ! command -v uv &> /dev/null; then
            print_error "uv 安装失败，请手动安装后重试"
            exit 1
        fi
    fi
    
    print_success "uv 工具检查完成"
}

# 创建日志目录
create_log_dir() {
    print_info "创建日志目录..."
    mkdir -p "$LOG_DIR"
    print_success "日志目录创建完成: $LOG_DIR"
}

# 更新 plist 文件中的路径
update_plist_paths() {
    print_info "更新 plist 文件路径..."
    
    # 创建临时 plist 文件
    local temp_plist="${PROJECT_DIR}/temp_${SERVICE_NAME}.plist"
    
    # 替换路径变量
    sed "s|/Users/misyra/JCU_auto_network|${PROJECT_DIR}|g" "$PLIST_FILE" > "$temp_plist"
    sed -i '' "s|<string>misyra</string>|<string>$(whoami)</string>|g" "$temp_plist"
    
    # 检查 uv 路径
    local uv_path=$(which uv)
    if [[ -n "$uv_path" ]]; then
        sed -i '' "s|/usr/local/bin/uv|${uv_path}|g" "$temp_plist"
    fi
    
    mv "$temp_plist" "$PLIST_FILE"
    print_success "plist 文件路径更新完成"
}

# 安装 launchd 服务
install_service() {
    print_info "安装 launchd 服务..."
    
    # 创建 LaunchAgents 目录
    mkdir -p "$LAUNCH_AGENTS_DIR"
    
    # 如果服务已存在，先卸载
    if [[ -f "$TARGET_PLIST" ]]; then
        print_warning "发现已存在的服务，正在卸载..."
        launchctl unload "$TARGET_PLIST" 2>/dev/null || true
        rm -f "$TARGET_PLIST"
    fi
    
    # 复制 plist 文件
    cp "$PLIST_FILE" "$TARGET_PLIST"
    
    # 加载服务
    launchctl load "$TARGET_PLIST"
    
    print_success "launchd 服务安装完成"
}

# 验证服务状态
verify_service() {
    print_info "验证服务状态..."
    
    sleep 2  # 等待服务启动
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_success "服务已成功启动"
        
        # 显示服务状态
        print_info "服务状态:"
        launchctl list | grep "$SERVICE_NAME" || true
    else
        print_warning "服务可能未正常启动，请检查日志文件"
    fi
}

# 显示使用说明
show_usage() {
    echo
    print_info "=== 安装完成 ==="
    echo
    print_info "服务名称: $SERVICE_NAME"
    print_info "配置文件: $TARGET_PLIST"
    print_info "日志目录: $LOG_DIR"
    echo
    print_info "常用命令:"
    echo "  查看服务状态: launchctl list | grep $SERVICE_NAME"
    echo "  查看日志: tail -f $LOG_DIR/campus_auth.log"
    echo "  手动启动: launchctl load $TARGET_PLIST"
    echo "  手动停止: launchctl unload $TARGET_PLIST"
    echo "  卸载服务: ./uninstall.sh"
    echo
    print_success "校园网自动认证工具已设置为开机自启动！"
}

# 主函数
main() {
    echo
    print_info "=== 校园网自动认证工具 - macOS 安装脚本 ==="
    echo
    
    check_system
    check_files
    check_uv
    create_log_dir
    update_plist_paths
    install_service
    verify_service
    show_usage
}

# 执行主函数
main "$@"