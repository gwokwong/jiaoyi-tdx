#!/bin/bash

# 多周期共振监控系统部署脚本

set -e

echo "=========================================="
echo "🚀 多周期共振监控系统部署"
echo "=========================================="

# 检查Docker和Docker Compose
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装Docker Compose"
    exit 1
fi

echo "✅ Docker 和 Docker Compose 已安装"

# 进入部署目录
cd "$(dirname "$0")"

# 检查配置文件
if [ ! -f "../config/config.json" ]; then
    echo "⚠️ 配置文件不存在，创建默认配置..."
    mkdir -p ../config
    cat > ../config/config.json << 'EOF'
{
  "tdx": {
    "server_ip": "123.125.108.14",
    "server_port": 7709
  },
  "monitor": {
    "scan_interval": 300,
    "stock_limit": 100,
    "min_score": 60,
    "trading_hours_only": true
  },
  "notification": {
    "feishu": {
      "enabled": false,
      "webhook_url": "",
      "secret": ""
    }
  }
}
EOF
    echo "⚠️ 请编辑 config/config.json 配置飞书Webhook"
fi

# 创建日志目录
mkdir -p ../logs

echo ""
echo "请选择部署模式:"
echo "1) 持续运行模式 (24小时监控)"
echo "2) 定时任务模式 (仅交易时间运行)"
echo "3) 构建镜像"
echo "4) 停止服务"
echo "5) 查看日志"
echo "6) 退出"
echo ""

read -p "请输入选项 [1-6]: " choice

case $choice in
    1)
        echo "🚀 启动持续运行模式..."
        docker-compose up -d resonance-monitor
        echo "✅ 服务已启动"
        echo "📊 查看日志: docker-compose logs -f resonance-monitor"
        ;;
    2)
        echo "🚀 启动定时任务模式..."
        docker-compose --profile scheduler up -d
        echo "✅ 服务已启动"
        echo "📊 查看日志: docker-compose logs -f resonance-scheduler"
        ;;
    3)
        echo "🔨 构建Docker镜像..."
        docker-compose build
        echo "✅ 镜像构建完成"
        ;;
    4)
        echo "🛑 停止服务..."
        docker-compose down
        echo "✅ 服务已停止"
        ;;
    5)
        echo "📊 查看日志..."
        docker-compose logs -f
        ;;
    6)
        echo "👋 退出"
        exit 0
        ;;
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
