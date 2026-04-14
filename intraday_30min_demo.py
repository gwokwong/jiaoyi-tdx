#!/usr/bin/env python3
"""
30分钟K线全天交易回测演示
简化版 - 使用固定股票池
"""

import pandas as pd
import numpy as np
from datetime import datetime
from trading_core import TradingCore
from core import ConfigLoader, DatabaseManager


class Intraday30MinDemo:
    """
    30分钟K线全天交易回测演示
    """

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)
        self.db = DatabaseManager(config)

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}
        self.trade_history = []

        # 固定股票池（20只热门股）
        self.stock_pool = [
            ('000001', 0, '平安银行'), ('000002', 0, '万科A'), ('000858', 0, '五粮液'),
            ('002001', 0, '新和成'), ('002230', 0, '科大讯飞'), ('002594', 0, '比亚迪'),
            ('300750', 0, '宁德时代'), ('600000', 1, '浦发银行'), ('600036', 1, '招商银行'),
            ('600519', 1, '贵州茅台'), ('000333', 0, '美的集团'), ('000651', 0, '格力电器'),
            ('002415', 0, '海康威视'), ('002475', 0, '立讯精密'), ('600276', 1, '恒瑞医药'),
            ('600030', 1, '中信证券'), ('000725', 0, '京东方A'), ('600050', 1, '中国联通'),
            ('601318', 1, '中国平安'), ('600887', 1, '伊利股份'),
        ]

    def get_30min_data(self, code, market, date_str):
        """获取某一天的30分钟数据"""
        try:
            data = self.core.api.get_security_bars(2, market, code, 0, 100)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 筛选日期
            target_date = pd.to_datetime(date_str).date()
            df['date'] = df.index.date
            day_data = df[df['date'] == target_date].copy()

            if len(day_data) == 0:
                return None

            day_data['time_str'] = day_data.index.strftime('%H:%M')
            return day_data

        except:
            return None

    def calculate_indicators(self, df):
        """计算30分钟指标"""
        if len(df) < 3:
            return None

        df['ma3'] = df['close'].rolling(window=3).mean()
        df['vol_ma3'] = df['vol'].rolling(window=3).mean()

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = (df['dif'] - df['dea']) * 2

        return df

    def check_buy_signal(self, df, idx):
        """检查买入信号"""
        if idx < 1:
            return None

        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]

        # 30分钟阳线突破
        is_yang = curr['close'] > curr['open']
        change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
        vol_ratio = curr['vol'] / curr['vol_ma3'] if curr['vol_ma3'] > 0 else 0

        if is_yang and change_pct >= 0.3 and vol_ratio >= 1.1:
            return {
                'type': '30分钟突破',
                'reason': f'30分钟阳线{change_pct:.2f}%,量比{vol_ratio:.2f}'
            }

        # MACD金叉
        if idx >= 1:
            macd_cross = (prev['dif'] <= prev['dea']) and (curr['dif'] > curr['dea'])
            if macd_cross and curr['macd'] > 0:
                return {
                    'type': '30分钟MACD金叉',
                    'reason': 'DIF上穿DEA'
                }

        return None

    def check_sell_signal(self, df, buy_price, idx):
        """检查卖出信号"""
        curr = df.iloc[idx]
        pnl_pct = (curr['close'] - buy_price) / buy_price

        # 止盈止损
        if pnl_pct >= 0.10:
            return ('止盈', f'盈利{pnl_pct*100:.1f}%')
        elif pnl_pct <= -0.05:
            return ('止损', f'亏损{pnl_pct*100:.1f}%')

        # MACD死叉
        if idx >= 1:
            prev = df.iloc[idx - 1]
            macd_dead = (prev['dif'] >= prev['dea']) and (curr['dif'] < curr['dea'])
            if macd_dead:
                return ('MACD死叉', '30分钟DIF下穿DEA')

        return None

    def run_backtest(self, date_str):
        """运行回测"""
        print("\n" + "="*80)
        print(f"📈 30分钟K线全天交易回测 - {date_str}")
        print("="*80)
        print(f"💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"⏰ 交易时段: 9:30-11:30, 13:00-15:00 (30分钟K线)")
        print("="*80)

        # 获取所有股票的30分钟数据
        print(f"\n📥 正在获取30分钟数据...")
        stock_data = {}

        for code, market, name in self.stock_pool:
            df = self.get_30min_data(code, market, date_str)
            if df is not None and len(df) >= 4:
                df = self.calculate_indicators(df)
                if df is not None:
                    stock_data[code] = {'df': df, 'market': market, 'name': name}

        print(f"✅ 成功获取 {len(stock_data)} 只股票数据")

        if len(stock_data) == 0:
            print("❌ 无可用数据")
            return

        # 获取时间点
        sample_df = list(stock_data.values())[0]['df']
        time_points = sample_df.index.tolist()

        print(f"\n⏰ 全天共 {len(time_points)} 个交易时段:")
        for i, t in enumerate(time_points):
            print(f"   {i+1}. {t.strftime('%H:%M')}")

        last_time_idx = 0

        # 逐时段交易
        for time_idx, current_time in enumerate(time_points):
            last_time_idx = time_idx
            time_str = current_time.strftime('%H:%M')

            print(f"\n{'='*80}")
            print(f"⏰ 时段 {time_idx+1}/{len(time_points)}: {time_str}")
            print(f"{'='*80}")

            # 检查卖出
            if self.positions:
                print(f"\n📊 检查 {len(self.positions)} 只持仓...")
                for code, pos in list(self.positions.items()):
                    if code not in stock_data:
                        continue
                    df = stock_data[code]['df']
                    if time_idx >= len(df):
                        continue

                    signal = self.check_sell_signal(df, pos['buy_price'], time_idx)
                    if signal:
                        self.execute_sell(code, pos, df.iloc[time_idx]['close'],
                                         signal[0], signal[1], date_str, time_str)

            # 检查买入
            if len(self.positions) < 10 and self.cash > self.initial_capital * 0.5:
                print(f"\n🔍 扫描买入机会...")
                candidates = []

                for code, data in stock_data.items():
                    if code in self.positions:
                        continue
                    df = data['df']
                    if time_idx >= len(df):
                        continue

                    signal = self.check_buy_signal(df, time_idx)
                    if signal:
                        candidates.append({
                            'code': code,
                            'market': data['market'],
                            'name': data['name'],
                            'signal': signal,
                            'price': df.iloc[time_idx]['close']
                        })

                # 买入前3只
                for stock in candidates[:3]:
                    if len(self.positions) >= 10:
                        break
                    self.execute_buy(stock, date_str, time_str)

        # 生成报告
        self.generate_report(date_str, stock_data, last_time_idx)

    def execute_buy(self, stock, date_str, time_str):
        """执行买入"""
        code = stock['code']
        name = stock['name']
        price = stock['price']

        # 2%仓位
        vol = int(self.initial_capital * 0.02 / price / 100) * 100
        if vol == 0:
            return False

        cost = price * vol
        fee = cost * 0.0001

        if self.cash < cost + fee:
            return False

        self.cash -= (cost + fee)
        self.positions[code] = {
            'code': code, 'name': name, 'market': stock['market'],
            'vol': vol, 'buy_price': price, 'buy_time': time_str,
            'cost': cost, 'fee': fee
        }

        self.trade_history.append({
            'date': date_str, 'time': time_str, 'code': code, 'name': name,
            'action': 'BUY', 'price': price, 'vol': vol,
            'strategy': stock['signal']['type'], 'reason': stock['signal']['reason']
        })

        print(f"\n   🟢 【买入】{code} {name}")
        print(f"      时间: {time_str}")
        print(f"      价格: {price:.2f}元 x {vol}股 = {cost:,.2f}元")
        print(f"      策略: {stock['signal']['type']} - {stock['signal']['reason']}")

        return True

    def execute_sell(self, code, pos, price, action_type, reason, date_str, time_str):
        """执行卖出"""
        vol = pos['vol']
        income = price * vol
        fee = income * 0.0006
        profit = income - pos['cost'] - fee - pos['fee']
        pnl_pct = (price - pos['buy_price']) / pos['buy_price'] * 100

        self.cash += (income - fee)

        self.trade_history.append({
            'date': date_str, 'time': time_str, 'code': code, 'name': pos['name'],
            'action': 'SELL', 'price': price, 'vol': vol,
            'profit': profit, 'pnl_pct': pnl_pct,
            'type': action_type, 'reason': reason,
            'hold_time': f"{pos['buy_time']}-{time_str}"
        })

        print(f"\n   🔴 【卖出】{code} {pos['name']}")
        print(f"      时间: {time_str}")
        print(f"      价格: {price:.2f}元 (买入: {pos['buy_price']:.2f}元 @ {pos['buy_time']})")
        print(f"      盈亏: {profit:+.2f}元 ({pnl_pct:+.2f}%)")
        print(f"      原因: {action_type} - {reason}")

        del self.positions[code]
        return True

    def generate_report(self, date_str, stock_data=None, last_time_idx=None):
        """生成报告"""
        print("\n" + "="*80)
        print(f"📊 {date_str} 日内交易报告")
        print("="*80)

        # 计算持仓市值（使用当前价格，不是买入价格）
        position_value = 0
        unrealized_pnl = 0
        for code, pos in self.positions.items():
            # 获取当前价格（如果有stock_data和time_idx）
            current_price = pos['buy_price']  # 默认使用买入价
            if stock_data and code in stock_data and last_time_idx is not None:
                df = stock_data[code]['df']
                if last_time_idx < len(df):
                    current_price = df.iloc[last_time_idx]['close']

            pos_value = pos['vol'] * current_price
            position_value += pos_value
            unrealized_pnl += pos['vol'] * (current_price - pos['buy_price'])

        final_value = self.cash + position_value

        # 计算已实现盈亏（来自卖出的交易）
        realized_pnl = sum(t.get('profit', 0) for t in self.trade_history if t['action'] == 'SELL')

        # 总盈亏 = 已实现 + 未实现
        total_pnl = realized_pnl + unrealized_pnl
        total_return = total_pnl / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final_value:,.2f} 元")
        print(f"   当日盈亏: {total_pnl:+.2f} 元 ({total_return:+.2f}%)")
        print(f"   现金余额: {self.cash:,.2f} 元")
        print(f"   持仓市值: {position_value:,.2f} 元")
        print(f"   已实现盈亏: {realized_pnl:+.2f} 元")
        print(f"   未实现盈亏: {unrealized_pnl:+.2f} 元")

        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   买入: {len(buy_trades)} 次")
        print(f"   卖出: {len(sell_trades)} 次")

        if sell_trades:
            profits = [t['profit'] for t in sell_trades]
            win = len([p for p in profits if p > 0])
            print(f"   胜率: {win}/{len(sell_trades)} = {win/len(sell_trades)*100:.1f}%")
            print(f"   总利润: {sum(profits):+.2f} 元")

        print(f"\n📝 完整交易记录:")
        print("-"*100)
        print(f"{'时间':<15} {'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'盈亏':<12} {'原因':<20}")
        print("-"*100)

        for t in self.trade_history:
            time_str = f"{t['time']}"
            if t['action'] == 'SELL':
                print(f"{time_str:<15} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {t['profit']:>+11.2f} {t['type']:<20}")
            else:
                print(f"{time_str:<15} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {'--':<12} {t['strategy']:<20}")

        print("-"*100)

        print(f"\n📋 收盘持仓 ({len(self.positions)} 只):")
        for code, pos in self.positions.items():
            print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元 (买入: {pos['buy_time']})")

        print("\n" + "="*80)

    def close(self):
        self.core.close()
        self.db.close()


if __name__ == "__main__":
    import sys

    date_str = sys.argv[1] if len(sys.argv) >= 2 else '2026-04-07'

    config = ConfigLoader()
    backtester = Intraday30MinDemo(config)

    try:
        backtester.run_backtest(date_str)
    finally:
        backtester.close()
