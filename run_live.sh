#!/bin/bash
# 实盘交易启动脚本
# 用于启动 live_trader.py 进行实盘交易
# ⚠️ 注意：实盘交易有风险，请谨慎使用

cd "$(dirname "$0")"

echo "🚀 启动实盘交易程序..."
echo "=========================="
echo "⚠️  警告：这是实盘交易程序！"
echo "    请确保您已了解相关风险"
echo "    按 Ctrl+C 可停止程序"
echo "=========================="
python3 live_trader.py
