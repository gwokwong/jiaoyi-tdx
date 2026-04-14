#!/usr/bin/env python3
"""
检查30分钟数据的可用范围
"""

import pandas as pd
from trading_core import TradingCore
from core import ConfigLoader


def check_30min_data():
    config = ConfigLoader()
    core = TradingCore(config)

    print("检查30分钟数据的可用范围...")
    print()

    # 测试几只股票
    test_stocks = [
        ('000001', 0, '平安银行'),
        ('600000', 1, '浦发银行'),
        ('000002', 0, '万科A'),
    ]

    for code, market, name in test_stocks:
        try:
            # 获取30分钟数据
            data = core.api.get_security_bars(2, market, code, 0, 100)

            if data:
                df = pd.DataFrame(data)
                print(f"{code} {name}:")
                print(f"  总条数: {len(data)}")

                # 找出日期范围
                dates = [item['datetime'] for item in data]
                dates.sort()
                print(f"  最早: {dates[0]}")
                print(f"  最晚: {dates[-1]}")
                print()
            else:
                print(f"{code} {name}: 无数据")
                print()

        except Exception as e:
            print(f"{code} {name}: 错误 - {e}")
            print()

    core.close()


if __name__ == "__main__":
    check_30min_data()
