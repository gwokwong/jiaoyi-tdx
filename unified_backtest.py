#!/usr/bin/env python3
"""
统一回测系统
调用trading_core模块进行历史数据回测
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader, DatabaseManager


class UnifiedBacktester:
    """
    统一回测器
    使用TradingCore的策略进行回测
    """

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)
        self.db = DatabaseManager(config)

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}  # {code: {...}}
        self.trade_history = []
        self.daily_records = []

        # 动态获取股票池
        self.stock_pool = self.core.get_all_stocks(limit=2000)
        self.stock_names = {code: name for code, market, name in self.stock_pool}

    def scan_for_signals(self, date_str, max_scan=500):
        """
        扫描股票池寻找买入信号
        """
        print(f"\n🔍 正在扫描 {date_str} 的买入信号...")

        candidates = []

        for i, (code, market, name) in enumerate(self.stock_pool[:max_scan]):
            if i % 50 == 0:
                print(f"   进度: {i}/{min(len(self.stock_pool), max_scan)}", end='\r')

            # 获取数据
            df = self.core.get_history_data(code, market, days=60)
            if df is None:
                continue

            # 检查买入信号
            signal = self.core.check_buy_signals(df)
            if signal:
                candidates.append({
                    'code': code,
                    'market': market,
                    'name': name,
                    'strategy': signal['strategy'],
                    'reason': signal['reason'],
                    'all_strategies': signal.get('all_strategies', []),
                    'buy_price': df.iloc[-1]['close'],
                    'score': signal['score']
                })

        # 按得分排序
        candidates.sort(key=lambda x: x['score'], reverse=True)

        print(f"\n✅ 发现 {len(candidates)} 只符合条件的股票")
        return candidates

    def check_sell_for_position(self, code, pos, date_str):
        """
        检查持仓的卖出信号
        """
        df = self.core.get_history_data(code, pos['market'], days=60)
        if df is None:
            return None

        signal = self.core.check_sell_signals(pos['buy_price'], df)
        if signal:
            return {
                'action_type': signal[0],
                'reason': signal[1],
                'current_price': df.iloc[-1]['close']
            }
        return None

    def execute_buy(self, stock, date_str):
        """执行买入"""
        code = stock['code']
        name = stock['name']
        buy_price = stock['buy_price']
        market = stock['market']

        # 计算买入数量（单票最多2%仓位）
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
            'cost': cost,
            'fee': fee,
            'strategy': stock['strategy']
        }

        self.trade_history.append({
            'date': date_str,
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': buy_price,
            'vol': vol,
            'amount': cost,
            'fee': fee,
            'strategy': stock['strategy'],
            'reason': stock['reason'],
            'cash_after': self.cash
        })

        self.db.save_trade(code, 'BUY', buy_price, vol,
                          self.config.get('fees', 'commission_rate'), 0)

        print(f"   🟢 买入 {code} {name} @ {buy_price:.2f} x {vol}股 = {cost:.2f}元")
        print(f"      策略: {stock['strategy']}")
        print(f"      说明: {stock['reason']}")

        return True

    def execute_sell(self, code, pos, sell_info, date_str):
        """执行卖出"""
        current_price = sell_info['current_price']
        action_type = sell_info['action_type']
        reason = sell_info['reason']

        vol = pos['vol']
        income = current_price * vol
        comm = income * self.config.get('fees', 'commission_rate')
        tax = income * self.config.get('fees', 'stamp_duty_rate')
        total_fee = comm + tax

        profit = income - pos['cost'] - total_fee - pos['fee']
        self.cash += (income - total_fee)

        self.trade_history.append({
            'date': date_str,
            'code': code,
            'name': pos['name'],
            'action': 'SELL',
            'price': current_price,
            'vol': vol,
            'amount': income,
            'fee': total_fee,
            'profit': profit,
            'pnl_pct': (current_price - pos['buy_price']) / pos['buy_price'] * 100,
            'type': action_type,
            'reason': reason,
            'cash_after': self.cash
        })

        self.db.save_trade(code, 'SELL', current_price, vol,
                          self.config.get('fees', 'commission_rate'),
                          self.config.get('fees', 'stamp_duty_rate'))

        print(f"   🔴 卖出 {code} {pos['name']} @ {current_price:.2f} | {action_type}")
        print(f"      原因: {reason}")
        print(f"      盈亏: {profit:+.2f}元")

        del self.positions[code]
        return True

    def run_backtest(self, start_date, end_date):
        """执行回测"""
        print("\n" + "="*80)
        print("📈 统一回测系统")
        print("="*80)
        print(f"\n💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📅 回测期间: {start_date} 至 {end_date}")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"🛡️ 风控参数:")
        print(f"   - 单票仓位 ≤ {self.core.max_single_position*100:.0f}%")
        print(f"   - 最大持仓 {self.core.max_positions} 只")
        print(f"   - 总仓位 ≤ {self.core.max_total_position*100:.0f}%")
        print(f"   - 止盈 {self.core.take_profit*100:.0f}% / 止损 {abs(self.core.stop_loss)*100:.0f}%")
        print("\n" + "="*80)

        date_range = pd.date_range(start=start_date, end=end_date, freq='B')

        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"\n📅 {date_str}")
            print("-" * 60)

            # 1. 检查持仓卖出
            if self.positions:
                print(f"   检查 {len(self.positions)} 只持仓...")
                for code, pos in list(self.positions.items()):
                    sell_info = self.check_sell_for_position(code, pos, date_str)
                    if sell_info:
                        self.execute_sell(code, pos, sell_info, date_str)

            # 2. 选股买入
            # 检查仓位限制
            current_position_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
            current_position_ratio = current_position_value / self.initial_capital

            if current_position_ratio >= self.core.max_total_position:
                print(f"   总仓位已达{current_position_ratio*100:.1f}%，暂停买入")
            elif len(self.positions) >= self.core.max_positions:
                print(f"   持仓已满({self.core.max_positions}只)，暂停买入")
            elif self.cash < self.initial_capital * (1 - self.core.max_total_position):
                print(f"   现金不足，暂停买入")
            else:
                candidates = self.scan_for_signals(date_str, max_scan=500)

                # 买入前10只
                for stock in candidates[:10]:
                    if stock['code'] not in self.positions and len(self.positions) < self.core.max_positions:
                        # 再次检查总仓位
                        current_position_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
                        if current_position_value / self.initial_capital >= self.core.max_total_position:
                            break
                        self.execute_buy(stock, date_str)

            # 3. 记录每日状态
            self.record_daily_status(date_str)

        # 生成报告
        self.generate_report()

    def record_daily_status(self, date_str):
        """记录每日状态"""
        hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        total = self.cash + hold_value

        self.daily_records.append({
            'date': date_str,
            'cash': self.cash,
            'hold_value': hold_value,
            'total': total,
            'positions': len(self.positions)
        })

    def generate_report(self):
        """生成回测报告"""
        print("\n" + "="*80)
        print("📊 回测报告")
        print("="*80)

        final_record = self.daily_records[-1] if self.daily_records else {'total': self.cash}
        final_equity = final_record['total']
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final_equity:,.2f} 元")
        print(f"   总收益率: {total_return:+.2f}%")
        print(f"   现金余额: {self.cash:,.2f} 元")

        hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        print(f"   持仓市值: {hold_value:,.2f} 元")

        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   买入次数: {len(buy_trades)}")
        print(f"   卖出次数: {len(sell_trades)}")

        if sell_trades:
            profits = [t['profit'] for t in sell_trades]
            win_trades = [p for p in profits if p > 0]
            lose_trades = [p for p in profits if p <= 0]

            print(f"   盈利次数: {len(win_trades)}")
            print(f"   亏损次数: {len(lose_trades)}")
            print(f"   胜率: {len(win_trades)/len(sell_trades)*100:.1f}%")
            print(f"   总利润: {sum(profits):,.2f} 元")

        # 卖出原因统计
        print(f"\n🔴 卖出原因统计:")
        reason_count = {}
        for t in sell_trades:
            r = t.get('type', '未知')
            reason_count[r] = reason_count.get(r, 0) + 1
        for reason, count in sorted(reason_count.items(), key=lambda x: x[1], reverse=True):
            print(f"   {reason}: {count}次")

        print(f"\n📋 当前持仓 ({len(self.positions)} 只):")
        if self.positions:
            for code, pos in self.positions.items():
                print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元")
        else:
            print("   无持仓")

        print("\n" + "="*80)

    def close(self):
        """关闭连接"""
        self.core.close()
        self.db.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        end = datetime.now()
        start = end - timedelta(days=15)
        start_date = start.strftime('%Y-%m-%d')
        end_date = end.strftime('%Y-%m-%d')
        print(f"使用默认日期范围: {start_date} 至 {end_date}")

    config = ConfigLoader()
    backtester = UnifiedBacktester(config)

    try:
        backtester.run_backtest(start_date, end_date)
    finally:
        backtester.close()
