#!/bin/bash

# LOF 项目一键启动脚本
# 同时启动后端（FastAPI）和前端（Vite），并自动切换 Node 版本

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACK_DIR="$PROJECT_ROOT/back"
FRONT_DIR="$PROJECT_ROOT/front/vite-project"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 清理子进程
cleanup() {
    log_info "正在停止所有服务..."
    if [ ! -z "$BACK_PID" ]; then
        kill "$BACK_PID" 2>/dev/null || true
    fi
    if [ ! -z "$FRONT_PID" ]; then
        kill "$FRONT_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null
    log_info "所有服务已停止"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ========== 后端启动 ==========
start_backend() {
    log_info "启动后端服务..."

    cd "$BACK_DIR"

    # 检查虚拟环境
    if [ ! -d "venv" ]; then
        log_error "后端虚拟环境不存在，请先创建：cd back && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi

    # 激活虚拟环境并启动
    source venv/bin/activate
    uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
    BACK_PID=$!
    log_info "后端服务已启动 (PID: $BACK_PID, http://localhost:8000)"
}

# ========== 前端启动 ==========
start_frontend() {
    log_info "启动前端服务..."

    cd "$FRONT_DIR"

    # 切换 Node 版本（通过 nvm）
    if command -v nvm &> /dev/null || [ -s "$HOME/.nvm/nvm.sh" ]; then
        [ -s "$HOME/.nvm/nvm.sh" ] && source "$HOME/.nvm/nvm.sh"
        log_info "切换 Node 版本至 .nvmrc 指定版本..."
        nvm use
        log_info "当前 Node 版本: $(node -v)"
    else
        log_warn "未检测到 nvm，跳过自动切换 Node 版本，当前版本: $(node -v)"
        log_warn "项目要求 Node v22.21.1，如版本不匹配请先安装 nvm"
    fi

    # 检查依赖
    if [ ! -d "node_modules" ]; then
        log_warn "前端依赖未安装，正在安装..."
        npm install
    fi

    # 启动前端
    npm run dev &
    FRONT_PID=$!
    log_info "前端服务已启动 (PID: $FRONT_PID)"
}

# ========== 主流程 ==========
echo ""
echo "========================================"
echo "   LOF 基金监控系统 - 一键启动"
echo "========================================"
echo ""

start_backend
start_frontend

echo ""
log_info "所有服务已启动！按 Ctrl+C 停止所有服务"
echo ""

# 等待任意子进程退出
wait -n 2>/dev/null || wait
