#!/bin/bash
# 模拟实时交易启动脚本
# 用于启动 simulation_trader.py 进行多股票模拟交易

cd "$(dirname "$0")"

echo "🚀 启动模拟实时交易程序..."
echo "=========================="
echo "💡 使用方法:"
echo "   ./run_simulation.sh                    # 默认回测最近10天"
echo "   ./run_simulation.sh 2026-04-01 2026-04-08  # 指定日期范围"
echo "=========================="

if [ $# -eq 2 ]; then
    python3 simulation_trader.py "$1" "$2"
else
    python3 simulation_trader.py
fi

echo "=========================="
echo "✅ 模拟交易完成"
