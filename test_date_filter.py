#!/usr/bin/env python3
"""
测试日期筛选
"""

import pandas as pd
from trading_core import TradingCore
from core import ConfigLoader


def test_date_filter():
    config = ConfigLoader()
    core = TradingCore(config)

    print("测试日期筛选...")
    print()

    code = '000001'
    market = 0
    date_str = '2026-04-07'

    # 获取30分钟数据
    data = core.api.get_security_bars(2, market, code, 0, 100)

    if data:
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)

        print(f"总数据条数: {len(df)}")
        print(f"\n日期范围:")
        print(f"  最早: {df.index[0]}")
        print(f"  最晚: {df.index[-1]}")

        # 筛选日期
        target_date = pd.to_datetime(date_str).date()
        df['date'] = df.index.date

        print(f"\n目标日期: {target_date}")
        print(f"数据中的日期示例:")
        print(df['date'].unique()[:10])

        day_data = df[df['date'] == target_date]
        print(f"\n筛选后条数: {len(day_data)}")

        if len(day_data) > 0:
            print(f"\n当天数据:")
            print(day_data[['open', 'close', 'high', 'low', 'vol']])

    core.close()


if __name__ == "__main__":
    test_date_filter()
