#!/usr/bin/env python3
"""
3月份整月回测 - 30分钟K线
"""

import pandas as pd
from datetime import datetime, timedelta
from intraday_30min_demo import Intraday30MinDemo
from core import ConfigLoader


class MonthlyBacktest:
    """整月回测"""

    def __init__(self, config):
        self.config = config
        self.daily_results = []
        self.all_trades = []
        self.monthly_pnl = 0

    def get_trading_days(self, year, month):
        """获取指定月份的所有交易日（简化版：周一到周五）"""
        days = []
        start_date = datetime(year, month, 1)

        # 获取该月最后一天
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)

        current = start_date
        while current <= end_date:
            # 周一到周五为交易日（简化处理，实际应排除节假日）
            if current.weekday() < 5:  # 0-4 是周一到周五
                days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        return days

    def run_monthly_backtest(self, year=2026, month=3):
        """运行整月回测"""
        print("\n" + "="*80)
        print(f"📅 {year}年{month}月 整月回测")
        print("="*80)

        trading_days = self.get_trading_days(year, month)
        print(f"📊 共 {len(trading_days)} 个交易日")
        print(f"📅 日期列表: {', '.join(trading_days[:5])}...{', '.join(trading_days[-3:])}")

        # 累计数据
        cumulative_cash = None
        cumulative_positions = {}
        all_trade_history = []
        total_realized_pnl = 0
        total_fees = 0

        for i, date_str in enumerate(trading_days):
            print(f"\n{'='*80}")
            print(f"📅 第 {i+1}/{len(trading_days)} 个交易日: {date_str}")
            print("="*80)

            # 创建新的回测实例
            backtester = Intraday30MinDemo(self.config)

            # 如果是后续交易日，继承前一天的资金和持仓
            if cumulative_cash is not None:
                backtester.cash = cumulative_cash
                backtester.positions = cumulative_positions.copy()
                backtester.trade_history = []

            try:
                # 运行当日回测
                backtester.run_backtest(date_str)

                # 记录结果
                daily_result = {
                    'date': date_str,
                    'cash': backtester.cash,
                    'positions': backtester.positions.copy(),
                    'trades': backtester.trade_history.copy(),
                    'position_count': len(backtester.positions)
                }
                self.daily_results.append(daily_result)

                # 累计交易记录
                all_trade_history.extend(backtester.trade_history)

                # 计算当日已实现盈亏
                daily_realized = sum(t.get('profit', 0) for t in backtester.trade_history if t['action'] == 'SELL')
                total_realized_pnl += daily_realized

                # 计算当日手续费
                daily_fees = sum(t.get('fee', 0) for t in backtester.trade_history)
                total_fees += daily_fees

                # 更新累计状态
                cumulative_cash = backtester.cash
                cumulative_positions = backtester.positions.copy()

                print(f"\n📊 当日已实现盈亏: {daily_realized:+.2f} 元")
                print(f"📊 累计已实现盈亏: {total_realized_pnl:+.2f} 元")

            except Exception as e:
                print(f"❌ 日期 {date_str} 回测失败: {e}")

            finally:
                backtester.close()

        # 生成月度报告
        self.generate_monthly_report(year, month, total_realized_pnl, total_fees)

    def generate_monthly_report(self, year, month, total_realized_pnl, total_fees):
        """生成月度报告"""
        print("\n" + "="*80)
        print(f"📊 {year}年{month}月 月度交易报告")
        print("="*80)

        initial_capital = self.config.get('account', 'initial_capital')

        # 计算最终持仓市值（使用最后一天的持仓）
        if self.daily_results:
            last_day = self.daily_results[-1]
            final_cash = last_day['cash']
            final_positions = last_day['positions']

            # 简化处理：使用买入价作为最终市值估算
            position_value = sum(p['vol'] * p['buy_price'] for p in final_positions.values())
            final_value = final_cash + position_value

            # 计算未实现盈亏
            unrealized_pnl = sum(p['vol'] * (p.get('current_price', p['buy_price']) - p['buy_price'])
                                for p in final_positions.values())
        else:
            final_cash = initial_capital
            final_value = initial_capital
            unrealized_pnl = 0

        total_pnl = total_realized_pnl + unrealized_pnl
        total_return = total_pnl / initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {initial_capital:,.2f} 元")
        print(f"   最终资金: {final_value:,.2f} 元")
        print(f"   现金余额: {final_cash:,.2f} 元")
        print(f"   持仓市值: {position_value:,.2f} 元")

        print(f"\n📈 盈亏统计:")
        print(f"   月度总盈亏: {total_pnl:+.2f} 元 ({total_return:+.2f}%)")
        print(f"   已实现盈亏: {total_realized_pnl:+.2f} 元")
        print(f"   未实现盈亏: {unrealized_pnl:+.2f} 元")
        print(f"   总手续费: {total_fees:,.2f} 元")

        # 统计交易次数
        all_trades = []
        for day in self.daily_results:
            all_trades.extend(day['trades'])

        buy_count = len([t for t in all_trades if t['action'] == 'BUY'])
        sell_count = len([t for t in all_trades if t['action'] == 'SELL'])
        sell_profits = [t['profit'] for t in all_trades if t['action'] == 'SELL']

        print(f"\n📊 交易统计:")
        print(f"   总买入次数: {buy_count} 次")
        print(f"   总卖出次数: {sell_count} 次")

        if sell_count > 0:
            win_count = len([p for p in sell_profits if p > 0])
            loss_count = sell_count - win_count
            win_rate = win_count / sell_count * 100
            avg_profit = sum(sell_profits) / sell_count

            print(f"   盈利次数: {win_count} 次")
            print(f"   亏损次数: {loss_count} 次")
            print(f"   胜率: {win_rate:.1f}%")
            print(f"   平均盈亏: {avg_profit:+.2f} 元")

        # 每日盈亏明细
        print(f"\n📅 每日盈亏明细:")
        print("-"*60)
        print(f"{'日期':<15} {'买入':<8} {'卖出':<8} {'已实现盈亏':<15} {'持仓数':<8}")
        print("-"*60)

        for day in self.daily_results:
            date = day['date']
            buys = len([t for t in day['trades'] if t['action'] == 'BUY'])
            sells = len([t for t in day['trades'] if t['action'] == 'SELL'])
            realized = sum(t.get('profit', 0) for t in day['trades'] if t['action'] == 'SELL')
            pos_count = day['position_count']

            print(f"{date:<15} {buys:<8} {sells:<8} {realized:>+14.2f} {pos_count:<8}")

        print("-"*60)

        # 最终持仓
        if self.daily_results and self.daily_results[-1]['positions']:
            print(f"\n📋 月末持仓 ({len(self.daily_results[-1]['positions'])} 只):")
            for code, pos in self.daily_results[-1]['positions'].items():
                print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元")

        print("\n" + "="*80)


if __name__ == "__main__":
    config = ConfigLoader()
    backtest = MonthlyBacktest(config)

    try:
        # 回测2026年3月
        backtest.run_monthly_backtest(year=2026, month=3)
    except Exception as e:
        print(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()
