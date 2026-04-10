#!/usr/bin/env python3
from pytdx.hq import TdxHq_API
import pandas as pd

api = TdxHq_API()
api.connect('123.125.108.14', 7709)

# 获取最近30天的数据
data = api.get_security_bars(4, 0, '000001', 0, 30)
df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['datetime'])
df['is_yang'] = df['close'] > df['open']  # 阳线

# 找出最近的阳线日期
yang_days = df[df['is_yang'] == True].tail(5)

print('📈 最近阳线（会买入）的交易日：')
print('=' * 50)
for _, row in yang_days.iterrows():
    date_str = row['date'].strftime('%Y-%m-%d')
    change = (row['close'] - row['open']) / row['open'] * 100
    print(f"{date_str} | 开盘: {row['open']:.2f} | 收盘: {row['close']:.2f} | 涨幅: {change:+.2f}% | ✅ 阳线")

print('=' * 50)
last_yang = yang_days.iloc[-1]['date'].strftime('%Y-%m-%d')
print(f"\n💡 建议选择: {last_yang} 进行回测")

api.disconnect()
