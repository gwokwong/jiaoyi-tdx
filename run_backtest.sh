#!/bin/bash
# 回测启动脚本
# 用于启动 backtester.py 进行历史数据回测

cd "$(dirname "$0")"

echo "🚀 启动回测程序..."
echo "=========================="
python3 backtester.py
echo "=========================="
echo "✅ 回测完成"
