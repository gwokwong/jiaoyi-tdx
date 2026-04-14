#!/usr/bin/env python3
"""
从指定日期开始回测 - 继承之前的资金和持仓
"""

import pandas as pd
from datetime import datetime, timedelta
from intraday_30min_demo import Intraday30MinDemo
from core import ConfigLoader


class BacktestFromDate:
    """从指定日期开始回测"""

    def __init__(self, config):
        self.config = config
        self.all_trades = []
        self.daily_results = {}

    def get_trading_days(self, start_date_str, end_date_str=None):
        """获取交易日列表"""
        days = []
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # 默认回测7天
            end_date = start_date + timedelta(days=7)

        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # 周一到周五
                days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        return days

    def run_backtest_from(self, start_date_str, days=5):
        """从指定日期开始回测"""
        print("\n" + "="*100)
        print(f"📅 从 {start_date_str} 开始回测")
        print("="*100)

        # 计算结束日期
        start = datetime.strptime(start_date_str, '%Y-%m-%d')
        end = start + timedelta(days=days*2)  # 预留周末
        end_date_str = end.strftime('%Y-%m-%d')

        trading_days = self.get_trading_days(start_date_str, end_date_str)[:days]
        print(f"📊 将回测 {len(trading_days)} 个交易日")
        print(f"📅 日期: {', '.join(trading_days)}")

        # 第一天使用配置中的初始资金
        first_day = True
        cumulative_cash = None
        cumulative_positions = {}
        initial_capital_for_calc = None

        for i, date_str in enumerate(trading_days):
            print(f"\n{'='*100}")
            print(f"📅 第 {i+1}/{len(trading_days)} 个交易日: {date_str}")
            print("="*100)

            backtester = Intraday30MinDemo(self.config)

            if first_day:
                # 第一天：使用配置的初始资金作为起点
                initial_capital_for_calc = backtester.initial_capital
                first_day = False
            else:
                # 后续日期：继承前一天的资金和持仓
                backtester.cash = cumulative_cash
                backtester.positions = cumulative_positions.copy()
                backtester.trade_history = []
                # 更新初始资金为当天的起始资金
                backtester.initial_capital = cumulative_cash + sum(
                    p['vol'] * p['buy_price'] for p in cumulative_positions.values()
                )

            try:
                # 运行当日回测
                backtester.run_backtest(date_str)

                # 记录结果
                self.daily_results[date_str] = {
                    'trades': backtester.trade_history.copy(),
                    'positions': backtester.positions.copy(),
                    'cash': backtester.cash,
                    'start_capital': backtester.initial_capital
                }
                self.all_trades.extend(backtester.trade_history)

                # 更新累计状态
                cumulative_cash = backtester.cash
                cumulative_positions = backtester.positions.copy()

            except Exception as e:
                print(f"❌ 日期 {date_str} 回测失败: {e}")

            finally:
                backtester.close()

        # 生成汇总报告
        self.generate_summary_report(initial_capital_for_calc, trading_days)

    def generate_summary_report(self, initial_capital, trading_days):
        """生成汇总报告"""
        print("\n" + "="*100)
        print(f"📊 回测汇总报告 - 从 {trading_days[0]} 开始")
        print("="*100)

        # 计算最终资金
        last_day = self.daily_results[trading_days[-1]]
        final_cash = last_day['cash']
        final_positions = last_day['positions']
        position_value = sum(p['vol'] * p['buy_price'] for p in final_positions.values())
        final_value = final_cash + position_value

        # 计算盈亏
        total_pnl = final_value - initial_capital
        total_return = total_pnl / initial_capital * 100

        # 计算已实现盈亏
        realized_pnl = sum(t.get('profit', 0) for t in self.all_trades if t['action'] == 'SELL')

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {initial_capital:,.2f} 元")
        print(f"   最终资金: {final_value:,.2f} 元")
        print(f"   总盈亏: {total_pnl:+.2f} 元 ({total_return:+.2f}%)")
        print(f"   已实现盈亏: {realized_pnl:+.2f} 元")
        print(f"   现金余额: {final_cash:,.2f} 元")
        print(f"   持仓市值: {position_value:,.2f} 元")

        # 交易统计
        all_buys = [t for t in self.all_trades if t['action'] == 'BUY']
        all_sells = [t for t in self.all_trades if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   总买入次数: {len(all_buys)} 次")
        print(f"   总卖出次数: {len(all_sells)} 次")

        if all_sells:
            profits = [t['profit'] for t in all_sells]
            win_count = len([p for p in profits if p > 0])
            loss_count = len([p for p in profits if p < 0])
            win_rate = win_count / len(profits) * 100

            print(f"   盈利次数: {win_count} 次")
            print(f"   亏损次数: {loss_count} 次")
            print(f"   胜率: {win_rate:.1f}%")

        # 每日明细
        print(f"\n📅 每日明细:")
        print("-"*80)
        print(f"{'日期':<15} {'起始资金':<15} {'结束资金':<15} {'当日盈亏':<15} {'持仓数':<8}")
        print("-"*80)

        for date_str in trading_days:
            if date_str not in self.daily_results:
                continue

            day_data = self.daily_results[date_str]
            start_cap = day_data['start_capital']
            end_cash = day_data['cash']
            end_positions = day_data['positions']
            end_value = end_cash + sum(p['vol'] * p['buy_price'] for p in end_positions.values())
            daily_pnl = end_value - start_cap

            print(f"{date_str:<15} {start_cap:<15,.2f} {end_value:<15,.2f} {daily_pnl:<+15.2f} {len(end_positions):<8}")

        print("-"*80)

        # 完整交易流水
        print(f"\n📝 完整交易流水:")
        print("="*100)
        print(f"{'日期':<12} {'时间':<10} {'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<10} {'盈亏':<12} {'原因':<20}")
        print("="*100)

        for t in self.all_trades:
            if t['action'] == 'SELL':
                print(f"{t['date']:<12} {t['time']:<10} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {t['vol']:<10} {t['profit']:<+12.2f} {t.get('type', ''):<20}")
            else:
                print(f"{t['date']:<12} {t['time']:<10} {t['action']:<6} {t['code']:<10} {t['name']:<10} "
                      f"{t['price']:<10.2f} {t['vol']:<10} {'--':<12} {t.get('strategy', ''):<20}")

        print("="*100)


if __name__ == "__main__":
    import sys

    config = ConfigLoader()
    backtest = BacktestFromDate(config)

    # 支持命令行参数: python backtest_from_date.py [start_date] [days]
    start_date = sys.argv[1] if len(sys.argv) > 1 else '2026-04-14'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    try:
        backtest.run_backtest_from(start_date, days)
    except Exception as e:
        print(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()
