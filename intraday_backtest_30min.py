#!/usr/bin/env python3
"""
30分钟K线全天交易回测系统
功能：
1. 获取某一天的30分钟K线数据
2. 模拟全天的交易过程（买入/卖出时间点）
3. 记录每笔交易的具体时间和价格
4. 生成详细的交易日志

交易日时间：
- 上午：9:30-11:30（4根30分钟K线：9:30, 10:00, 10:30, 11:00）
- 下午：13:00-15:00（4根30分钟K线：13:00, 13:30, 14:00, 14:30）
- 全天共8根30分钟K线
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader, DatabaseManager


class IntradayBacktest30Min:
    """
    30分钟K线全天交易回测器
    """

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)
        self.db = DatabaseManager(config)

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}  # 当前持仓
        self.trade_history = []  # 交易历史
        self.daily_records = []  # 每日记录

        # 股票池
        self.stock_pool = self.core.get_all_stocks(limit=500)  # 限制500只加快测试
        self.stock_names = {code: name for code, market, name in self.stock_pool}

    def get_30min_data(self, code, market, date_str):
        """
        获取某一天的30分钟K线数据
        """
        try:
            # 获取最近几天的30分钟数据 (category=2)
            data = self.core.api.get_security_bars(2, market, code, 0, 100)
            if not data:
                return None

            # 转换为DataFrame
            df = pd.DataFrame(data)

            # 使用datetime字段
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 筛选指定日期的数据
            target_date = pd.to_datetime(date_str).date()
            df['date'] = df.index.date
            day_data = df[df['date'] == target_date].copy()

            if len(day_data) == 0:
                return None

            # 重命名列（统一命名）
            day_data = day_data.rename(columns={
                'vol': 'volume'
            })

            # 添加时间标签
            day_data['time_str'] = day_data.index.strftime('%H:%M')

            return day_data

        except Exception as e:
            return None

    def calculate_30min_indicators(self, df):
        """
        计算30分钟级别的技术指标
        """
        if df is None or len(df) < 5:
            return None

        # 移动平均线
        df['ma3'] = df['close'].rolling(window=3).mean()  # 3根30分钟均线（1.5小时）
        df['ma5'] = df['close'].rolling(window=5).mean()  # 5根30分钟均线（2.5小时）
        df['ma8'] = df['close'].rolling(window=8).mean()  # 8根30分钟均线（全天）

        # MACD（30分钟级别）
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = (df['dif'] - df['dea']) * 2

        # 成交量均线
        df['vol_ma3'] = df['volume'].rolling(window=3).mean()

        return df

    def check_intraday_buy_signal(self, df, current_idx):
        """
        检查30分钟级别的买入信号
        
        策略：
        1. 30分钟阳线突破
        2. 30分钟MACD金叉
        3. 放量上涨
        """
        if df is None or current_idx < 1:
            return None

        current = df.iloc[current_idx]
        prev = df.iloc[current_idx - 1]

        signals = []

        # 策略1: 30分钟阳线 + 突破前高
        is_yang = current['close'] > current['open']
        change_pct = (current['close'] - prev['close']) / prev['close'] * 100

        if is_yang and change_pct >= 0.5:
            vol_ratio = current['volume'] / current['vol_ma3'] if current['vol_ma3'] > 0 else 0
            if vol_ratio >= 1.2:
                signals.append({
                    'type': '30分钟放量突破',
                    'reason': f'30分钟阳线上涨{change_pct:.2f}%，量比{vol_ratio:.2f}',
                    'score': 3
                })

        # 策略2: 30分钟MACD金叉
        if current_idx >= 1:
            macd_cross = (prev['dif'] <= prev['dea']) and (current['dif'] > current['dea'])
            if macd_cross and current['macd'] > 0:
                signals.append({
                    'type': '30分钟MACD金叉',
                    'reason': '30分钟DIF上穿DEA',
                    'score': 3
                })

        # 策略3: 突破MA3均线
        if current['close'] > current['ma3'] and prev['close'] <= prev['ma3']:
            signals.append({
                'type': '突破MA3',
                'reason': '价格突破3周期均线',
                'score': 2
            })

        if signals:
            best = max(signals, key=lambda x: x['score'])
            return best

        return None

    def check_intraday_sell_signal(self, df, buy_price, current_idx):
        """
        检查30分钟级别的卖出信号
        """
        if df is None or current_idx < 0:
            return None

        current = df.iloc[current_idx]
        current_price = current['close']
        pnl_pct = (current_price - buy_price) / buy_price

        signals = []

        # 止盈止损
        if pnl_pct >= 0.10:
            signals.append(('止盈', f'盈利达到{pnl_pct*100:.1f}%'))
        elif pnl_pct <= -0.05:
            signals.append(('止损', f'亏损达到{pnl_pct*100:.1f}%'))

        # 30分钟MACD死叉
        if current_idx >= 1:
            prev = df.iloc[current_idx - 1]
            macd_dead = (prev['dif'] >= prev['dea']) and (current['dif'] < current['dea'])
            if macd_dead:
                signals.append(('MACD死叉', '30分钟DIF下穿DEA'))

        # 跌破MA3
        if current_idx >= 1:
            prev = df.iloc[current_idx - 1]
            if current['close'] < current['ma3'] and prev['close'] >= prev['ma3']:
                signals.append(('跌破MA3', '价格跌破3周期均线'))

        return signals[0] if signals else None

    def run_intraday_backtest(self, date_str):
        """
        运行某一天的30分钟级别回测
        """
        print("\n" + "="*80)
        print(f"📈 30分钟K线全天交易回测 - {date_str}")
        print("="*80)
        print(f"\n💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"⏰ 交易时间: 9:30-11:30, 13:00-15:00")
        print(f"📊 K线周期: 30分钟")
        print("\n" + "="*80)

        # 获取所有股票的30分钟数据
        print(f"\n📥 正在获取 {date_str} 的30分钟数据...")
        stock_data = {}

        for i, (code, market, name) in enumerate(self.stock_pool[:100]):  # 限制100只加快测试
            if i % 20 == 0:
                print(f"   进度: {i}/100", end='\r')

            df = self.get_30min_data(code, market, date_str)
            if df is not None and len(df) >= 4:  # 至少要有4根K线
                df = self.calculate_30min_indicators(df)
                if df is not None:
                    stock_data[code] = {
                        'df': df,
                        'market': market,
                        'name': name
                    }

        print(f"\n✅ 成功获取 {len(stock_data)} 只股票的30分钟数据")

        if len(stock_data) == 0:
            print("❌ 没有可用的30分钟数据")
            return

        # 获取所有时间点
        sample_df = list(stock_data.values())[0]['df']
        time_points = sample_df.index.tolist()

        print(f"\n⏰ 全天共 {len(time_points)} 个30分钟交易时段:")
        for i, t in enumerate(time_points):
            print(f"   {i+1}. {t.strftime('%H:%M')}")

        # 逐时段模拟交易
        for time_idx, current_time in enumerate(time_points):
            time_str = current_time.strftime('%H:%M')
            print(f"\n{'='*80}")
            print(f"⏰ 交易时段 {time_idx + 1}/{len(time_points)}: {time_str}")
            print(f"{'='*80}")

            # 1. 检查持仓卖出
            if self.positions:
                print(f"\n📊 检查 {len(self.positions)} 只持仓...")
                for code, pos in list(self.positions.items()):
                    if code not in stock_data:
                        continue

                    df = stock_data[code]['df']
                    if time_idx >= len(df):
                        continue

                    sell_signal = self.check_intraday_sell_signal(df, pos['buy_price'], time_idx)

                    if sell_signal:
                        current_price = df.iloc[time_idx]['close']
                        self.execute_sell(code, pos, current_price, sell_signal[0], sell_signal[1], date_str, time_str)

            # 2. 选股买入
            # 检查仓位限制
            current_position_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
            current_position_ratio = current_position_value / self.initial_capital

            if current_position_ratio >= self.core.max_total_position:
                print(f"\n⚠️  总仓位已达{current_position_ratio*100:.1f}%，暂停买入")
            elif len(self.positions) >= self.core.max_positions:
                print(f"\n⚠️  持仓已满({self.core.max_positions}只)，暂停买入")
            else:
                print(f"\n🔍 扫描买入机会...")
                candidates = []

                for code, data in stock_data.items():
                    if code in self.positions:
                        continue

                    df = data['df']
                    if time_idx >= len(df):
                        continue

                    signal = self.check_intraday_buy_signal(df, time_idx)
                    if signal:
                        candidates.append({
                            'code': code,
                            'market': data['market'],
                            'name': data['name'],
                            'signal': signal,
                            'price': df.iloc[time_idx]['close']
                        })

                # 买入前5只
                for stock in candidates[:5]:
                    if len(self.positions) >= self.core.max_positions:
                        break
                    self.execute_buy(stock, date_str, time_str)

            # 记录当前状态
            self.record_status(date_str, time_str)

        # 生成报告
        self.generate_intraday_report(date_str)

    def execute_buy(self, stock, date_str, time_str):
        """执行买入"""
        code = stock['code']
        name = stock['name']
        buy_price = stock['price']
        market = stock['market']

        # 计算买入数量（单票2%仓位）
        position_value = self.initial_capital * self.core.max_single_position
        vol = int(position_value / buy_price / 100) * 100

        if vol == 0:
            return False

        cost = buy_price * vol
        fee = cost * self.config.get('fees', 'commission_rate')

        if self.cash < cost + fee:
            return False

        self.cash -= (cost + fee)

        self.positions[code] = {
            'code': code,
            'name': name,
            'market': market,
            'vol': vol,
            'buy_price': buy_price,
            'buy_date': date_str,
            'buy_time': time_str,
            'cost': cost,
            'fee': fee
        }

        self.trade_history.append({
            'date': date_str,
            'time': time_str,
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': buy_price,
            'vol': vol,
            'amount': cost,
            'strategy': stock['signal']['type'],
            'reason': stock['signal']['reason']
        })

        print(f"\n   🟢 【买入】{code} {name}")
        print(f"      时间: {date_str} {time_str}")
        print(f"      价格: {buy_price:.2f}元")
        print(f"      数量: {vol}股")
        print(f"      金额: {cost:,.2f}元")
        print(f"      策略: {stock['signal']['type']}")
        print(f"      信号: {stock['signal']['reason']}")

        return True

    def execute_sell(self, code, pos, sell_price, action_type, reason, date_str, time_str):
        """执行卖出"""
        vol = pos['vol']
        income = sell_price * vol
        comm = income * self.config.get('fees', 'commission_rate')
        tax = income * self.config.get('fees', 'stamp_duty_rate')
        total_fee = comm + tax

        profit = income - pos['cost'] - total_fee - pos['fee']
        pnl_pct = (sell_price - pos['buy_price']) / pos['buy_price'] * 100

        self.cash += (income - total_fee)

        self.trade_history.append({
            'date': date_str,
            'time': time_str,
            'code': code,
            'name': pos['name'],
            'action': 'SELL',
            'price': sell_price,
            'vol': vol,
            'amount': income,
            'profit': profit,
            'pnl_pct': pnl_pct,
            'type': action_type,
            'reason': reason,
            'hold_time': f"{pos['buy_time']}-{time_str}"
        })

        print(f"\n   🔴 【卖出】{code} {pos['name']}")
        print(f"      时间: {date_str} {time_str}")
        print(f"      价格: {sell_price:.2f}元")
        print(f"      买入: {pos['buy_price']:.2f}元 ({pos['buy_time']})")
        print(f"      盈亏: {profit:+.2f}元 ({pnl_pct:+.2f}%)")
        print(f"      原因: {action_type} - {reason}")

        del self.positions[code]
        return True

    def record_status(self, date_str, time_str):
        """记录当前状态"""
        hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        total = self.cash + hold_value

        self.daily_records.append({
            'datetime': f"{date_str} {time_str}",
            'cash': self.cash,
            'hold_value': hold_value,
            'total': total,
            'positions': len(self.positions)
        })

    def generate_intraday_report(self, date_str):
        """生成日内交易报告"""
        print("\n" + "="*80)
        print(f"📊 {date_str} 日内交易报告")
        print("="*80)

        final = self.daily_records[-1] if self.daily_records else {'total': self.cash}
        total_return = (final['total'] - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final['total']:,.2f} 元")
        print(f"   当日盈亏: {final['total'] - self.initial_capital:+.2f} 元")
        print(f"   收益率: {total_return:+.2f}%")
        print(f"   现金余额: {self.cash:,.2f} 元")
        print(f"   持仓市值: {final['hold_value']:,.2f} 元")

        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   买入次数: {len(buy_trades)}")
        print(f"   卖出次数: {len(sell_trades)}")

        if sell_trades:
            profits = [t['profit'] for t in sell_trades]
            win = len([p for p in profits if p > 0])
            lose = len([p for p in profits if p <= 0])
            print(f"   盈利次数: {win}")
            print(f"   亏损次数: {lose}")
            print(f"   胜率: {win/len(sell_trades)*100:.1f}%")
            print(f"   总利润: {sum(profits):+.2f} 元")

        # 详细交易记录
        print(f"\n📝 详细交易记录:")
        print("-"*100)
        print(f"{'时间':<20} {'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'盈亏':<12} {'原因':<20}")
        print("-"*100)

        for t in self.trade_history:
            time_str = f"{t['date']} {t['time']}"
            if t['action'] == 'SELL':
                profit_str = f"{t['profit']:+.2f}"
                print(f"{time_str:<20} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {profit_str:<12} {t['type']:<20}")
            else:
                print(f"{time_str:<20} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {'--':<12} {t['strategy']:<20}")

        print("-"*100)

        # 当前持仓
        print(f"\n📋 收盘持仓 ({len(self.positions)} 只):")
        if self.positions:
            for code, pos in self.positions.items():
                print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元 "
                      f"(买入时间: {pos['buy_time']})")
        else:
            print("   无持仓")

        print("\n" + "="*80)

    def close(self):
        """关闭连接"""
        self.core.close()
        self.db.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2:
        date_str = sys.argv[1]
    else:
        # 默认回测最近一个交易日
        date_str = '2026-04-08'
        print(f"使用默认日期: {date_str}")
        print(f"提示: 可指定日期 python3 intraday_backtest_30min.py 2026-04-08")

    config = ConfigLoader()
    backtester = IntradayBacktest30Min(config)

    try:
        backtester.run_intraday_backtest(date_str)
    finally:
        backtester.close()
