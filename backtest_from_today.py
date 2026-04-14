#!/usr/bin/env python3
"""
从今天开始全新回测 - 使用初始资金，不继承任何持仓
"""

import pandas as pd
from datetime import datetime, timedelta
from intraday_30min_demo import Intraday30MinDemo
from core import ConfigLoader


class BacktestFromToday:
    """从今天开始全新回测"""

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

    def run_backtest_from_today(self, start_date_str, days=5):
        """从今天开始全新回测"""
        print("\n" + "="*100)
        print(f"📅 从今天开始全新回测 - {start_date_str}")
        print("="*100)
        print("💡 每天使用初始资金1000万，不继承前一天持仓")
        print("="*100)

        # 计算结束日期
        start = datetime.strptime(start_date_str, '%Y-%m-%d')
        end = start + timedelta(days=days*2)  # 预留周末
        end_date_str = end.strftime('%Y-%m-%d')

        trading_days = self.get_trading_days(start_date_str, end_date_str)[:days]
        print(f"📊 将回测 {len(trading_days)} 个交易日")
        print(f"📅 日期: {', '.join(trading_days)}")

        # 记录初始资金
        initial_capital = self.config.get('account', 'initial_capital')

        for i, date_str in enumerate(trading_days):
            print(f"\n{'='*100}")
            print(f"📅 第 {i+1}/{len(trading_days)} 个交易日: {date_str}")
            print("="*100)

            # 每天创建全新的回测实例，使用初始资金
            backtester = Intraday30MinDemo(self.config)

            try:
                # 运行当日回测
                backtester.run_backtest(date_str)

                # 记录结果
                self.daily_results[date_str] = {
                    'trades': backtester.trade_history.copy(),
                    'positions': backtester.positions.copy(),
                    'cash': backtester.cash,
                    'start_capital': backtester.initial_capital,
                    'final_value': backtester.cash + sum(
                        p['vol'] * p['buy_price'] for p in backtester.positions.values()
                    )
                }
                self.all_trades.extend(backtester.trade_history)

            except Exception as e:
                print(f"❌ 日期 {date_str} 回测失败: {e}")

            finally:
                backtester.close()

        # 生成汇总报告
        self.generate_summary_report(initial_capital, trading_days)

    def generate_summary_report(self, initial_capital, trading_days):
        """生成汇总报告"""
        print("\n" + "="*100)
        print(f"📊 全新回测汇总报告 - 从 {trading_days[0]} 开始")
        print("="*100)

        # 计算每日盈亏
        total_pnl = 0
        total_realized_pnl = 0

        print(f"\n📅 每日盈亏明细:")
        print("-"*90)
        print(f"{'日期':<15} {'起始资金':<15} {'结束资金':<15} {'当日盈亏':<15} {'买入':<8} {'卖出':<8} {'持仓':<8}")
        print("-"*90)

        for date_str in trading_days:
            if date_str not in self.daily_results:
                continue

            day_data = self.daily_results[date_str]
            start_cap = day_data['start_capital']
            end_value = day_data['final_value']
            daily_pnl = end_value - start_cap
            total_pnl += daily_pnl

            # 统计当日交易
            day_trades = day_data['trades']
            buy_count = len([t for t in day_trades if t['action'] == 'BUY'])
            sell_count = len([t for t in day_trades if t['action'] == 'SELL'])
            day_realized = sum(t.get('profit', 0) for t in day_trades if t['action'] == 'SELL')
            total_realized_pnl += day_realized

            print(f"{date_str:<15} {start_cap:<15,.2f} {end_value:<15,.2f} {daily_pnl:<+15.2f} "
                  f"{buy_count:<8} {sell_count:<8} {len(day_data['positions']):<8}")

        print("-"*90)

        # 计算平均盈亏
        valid_days = len([d for d in trading_days if d in self.daily_results])
        avg_daily_pnl = total_pnl / valid_days if valid_days > 0 else 0
        total_return = total_pnl / initial_capital * 100

        print(f"\n💰 汇总统计:")
        print(f"   回测天数: {valid_days} 天")
        print(f"   初始资金: {initial_capital:,.2f} 元")
        print(f"   累计盈亏: {total_pnl:+.2f} 元 ({total_return:+.2f}%)")
        print(f"   平均日盈亏: {avg_daily_pnl:+.2f} 元")
        print(f"   已实现盈亏: {total_realized_pnl:+.2f} 元")

        # 交易统计
        all_buys = [t for t in self.all_trades if t['action'] == 'BUY']
        all_sells = [t for t in self.all_trades if t['action'] == 'SELL']
        sell_profits = [t['profit'] for t in all_sells]

        print(f"\n📈 交易统计:")
        print(f"   总买入次数: {len(all_buys)} 次")
        print(f"   总卖出次数: {len(all_sells)} 次")

        if all_sells:
            win_count = len([p for p in sell_profits if p > 0])
            loss_count = len([p for p in sell_profits if p < 0])
            win_rate = win_count / len(sell_profits) * 100
            avg_profit = sum(sell_profits) / len(sell_profits)

            print(f"   盈利次数: {win_count} 次")
            print(f"   亏损次数: {loss_count} 次")
            print(f"   胜率: {win_rate:.1f}%")
            print(f"   平均盈亏: {avg_profit:+.2f} 元")

        # 按股票统计
        print(f"\n📋 按股票统计:")
        print("-"*80)
        print(f"{'代码':<10} {'名称':<10} {'买入':<8} {'卖出':<8} {'总盈亏':<15} {'胜率':<10}")
        print("-"*80)

        stock_stats = {}
        for t in self.all_trades:
            code = t['code']
            if code not in stock_stats:
                stock_stats[code] = {
                    'name': t['name'],
                    'buy_count': 0,
                    'sell_count': 0,
                    'profits': []
                }

            if t['action'] == 'BUY':
                stock_stats[code]['buy_count'] += 1
            else:
                stock_stats[code]['sell_count'] += 1
                stock_stats[code]['profits'].append(t.get('profit', 0))

        for code, stats in sorted(stock_stats.items()):
            total_stock_pnl = sum(stats['profits'])
            stock_win = len([p for p in stats['profits'] if p > 0])
            stock_win_rate = stock_win / len(stats['profits']) * 100 if stats['profits'] else 0
            print(f"{code:<10} {stats['name']:<10} {stats['buy_count']:<8} {stats['sell_count']:<8} "
                  f"{total_stock_pnl:<+15.2f} {stock_win_rate:<10.1f}%")

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
    backtest = BacktestFromToday(config)

    # 支持命令行参数: python backtest_from_today.py [start_date] [days]
    # 默认从今天开始（2026-04-14）
    start_date = sys.argv[1] if len(sys.argv) > 1 else '2026-04-14'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    try:
        backtest.run_backtest_from_today(start_date, days)
    except Exception as e:
        print(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()
