#!/usr/bin/env python3
"""
简化版30分钟回测测试
"""

import pandas as pd
from datetime import datetime
from trading_core import TradingCore
from core import ConfigLoader


def test_30min_data():
    """测试30分钟数据获取"""
    config = ConfigLoader()
    core = TradingCore(config)

    print("测试获取30分钟数据...")

    # 测试平安银行
    code = '000001'
    market = 0

    try:
        # 获取30分钟数据 (category=2)
        data = core.api.get_security_bars(2, market, code, 0, 50)

        if data:
            print(f"✅ 成功获取 {len(data)} 条30分钟数据")

            # 查看数据结构
            print("\n数据示例:")
            for i, item in enumerate(data[:5]):
                print(f"  {i+1}. {item}")

            # 创建DataFrame
            df = pd.DataFrame(data)
            print(f"\nDataFrame列: {df.columns.tolist()}")
            print(f"\n前5行:")
            print(df.head())

        else:
            print("❌ 未获取到数据")

    except Exception as e:
        print(f"❌ 错误: {e}")

    core.close()


if __name__ == "__main__":
    test_30min_data()
