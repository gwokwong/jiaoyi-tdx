#!/usr/bin/env python3
"""
详细交易记录报告 - 包含完整的买入卖出时间、点位等信息
"""

import pandas as pd
from datetime import datetime, timedelta
from intraday_30min_demo import Intraday30MinDemo
from core import ConfigLoader


class DetailedTradeReport:
    """详细交易记录报告"""

    def __init__(self, config):
        self.config = config
        self.all_trades = []  # 所有交易记录
        self.daily_details = {}  # 每日详细数据

    def get_trading_days(self, year, month):
        """获取指定月份的所有交易日"""
        days = []
        start_date = datetime(year, month, 1)

        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)

        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        return days

    def run_detailed_backtest(self, year=2026, month=3):
        """运行详细回测"""
        print("\n" + "="*100)
        print(f"📅 {year}年{month}月 详细交易记录报告")
        print("="*100)

        trading_days = self.get_trading_days(year, month)
        print(f"📊 共 {len(trading_days)} 个交易日")

        # 累计数据
        cumulative_cash = None
        cumulative_positions = {}

        for i, date_str in enumerate(trading_days):
            backtester = Intraday30MinDemo(self.config)

            if cumulative_cash is not None:
                backtester.cash = cumulative_cash
                backtester.positions = cumulative_positions.copy()
                backtester.trade_history = []

            try:
                # 运行当日回测（简化输出）
                self.run_daily_backtest_quiet(backtester, date_str)

                # 保存详细交易记录
                if backtester.trade_history:
                    self.daily_details[date_str] = {
                        'trades': backtester.trade_history.copy(),
                        'positions': backtester.positions.copy(),
                        'cash': backtester.cash
                    }
                    self.all_trades.extend(backtester.trade_history)

                # 更新累计状态
                cumulative_cash = backtester.cash
                cumulative_positions = backtester.positions.copy()

            except Exception as e:
                print(f"❌ 日期 {date_str} 回测失败: {e}")

            finally:
                backtester.close()

        # 生成详细报告
        self.generate_detailed_report(year, month)

    def run_daily_backtest_quiet(self, backtester, date_str):
        """静默运行单日回测（减少输出）"""
        # 获取所有股票的30分钟数据
        stock_data = {}
        for code, market, name in backtester.stock_pool:
            df = backtester.get_30min_data(code, market, date_str)
            if df is not None and len(df) >= 4:
                df = backtester.calculate_indicators(df)
                if df is not None:
                    stock_data[code] = {'df': df, 'market': market, 'name': name}

        if len(stock_data) == 0:
            return

        # 获取时间点
        sample_df = list(stock_data.values())[0]['df']
        time_points = sample_df.index.tolist()
        last_time_idx = 0

        # 逐时段交易
        for time_idx, current_time in enumerate(time_points):
            last_time_idx = time_idx
            time_str = current_time.strftime('%H:%M')

            # 检查卖出
            if backtester.positions:
                for code, pos in list(backtester.positions.items()):
                    if code not in stock_data:
                        continue
                    df = stock_data[code]['df']
                    if time_idx >= len(df):
                        continue

                    signal = backtester.check_sell_signal(df, pos['buy_price'], time_idx)
                    if signal:
                        backtester.execute_sell(code, pos, df.iloc[time_idx]['close'],
                                         signal[0], signal[1], date_str, time_str)

            # 检查买入
            if len(backtester.positions) < 10 and backtester.cash > backtester.initial_capital * 0.5:
                candidates = []
                for code, data in stock_data.items():
                    if code in backtester.positions:
                        continue
                    df = data['df']
                    if time_idx >= len(df):
                        continue

                    signal = backtester.check_buy_signal(df, time_idx)
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
                    if len(backtester.positions) >= 10:
                        break
                    backtester.execute_buy(stock, date_str, time_str)

    def generate_detailed_report(self, year, month):
        """生成详细交易报告"""
        print("\n" + "="*100)
        print(f"📋 详细交易记录 - {year}年{month}月")
        print("="*100)

        initial_capital = self.config.get('account', 'initial_capital')

        # 按日期分组显示交易
        for date_str in sorted(self.daily_details.keys()):
            day_data = self.daily_details[date_str]
            trades = day_data['trades']

            if not trades:
                continue

            print(f"\n{'='*100}")
            print(f"📅 交易日: {date_str}")
            print("="*100)

            # 买入记录
            buy_trades = [t for t in trades if t['action'] == 'BUY']
            if buy_trades:
                print(f"\n🟢 买入记录 ({len(buy_trades)}笔):")
                print("-"*100)
                print(f"{'时间':<10} {'代码':<10} {'名称':<10} {'买入价格':<12} {'数量':<10} {'金额':<15} {'策略':<20}")
                print("-"*100)

                for t in buy_trades:
                    amount = t['price'] * t['vol']
                    print(f"{t['time']:<10} {t['code']:<10} {t['name']:<10} "
                          f"{t['price']:<12.2f} {t['vol']:<10} {amount:<15,.2f} {t['strategy']:<20}")

            # 卖出记录
            sell_trades = [t for t in trades if t['action'] == 'SELL']
            if sell_trades:
                print(f"\n🔴 卖出记录 ({len(sell_trades)}笔):")
                print("-"*100)
                print(f"{'时间':<10} {'代码':<10} {'名称':<10} {'卖出价格':<12} {'买入价格':<12} {'数量':<10} "
                      f"{'盈亏':<12} {'盈亏%':<10} {'原因':<15}")
                print("-"*100)

                for t in sell_trades:
                    # 查找对应的买入记录
                    buy_price = 0
                    for bt in self.all_trades:
                        if bt['action'] == 'BUY' and bt['code'] == t['code'] and bt['date'] <= t['date']:
                            buy_price = bt['price']

                    print(f"{t['time']:<10} {t['code']:<10} {t['name']:<10} "
                          f"{t['price']:<12.2f} {buy_price:<12.2f} {t['vol']:<10} "
                          f"{t['profit']:<+12.2f} {t['pnl_pct']:<+10.2f} {t['type']:<15}")

            # 当日持仓
            positions = day_data['positions']
            if positions:
                print(f"\n📦 收盘持仓 ({len(positions)}只):")
                print("-"*80)
                print(f"{'代码':<10} {'名称':<10} {'持仓数量':<12} {'买入价格':<12} {'当前市值':<15}")
                print("-"*80)

                for code, pos in positions.items():
                    market_value = pos['vol'] * pos['buy_price']
                    print(f"{code:<10} {pos['name']:<10} {pos['vol']:<12} {pos['buy_price']:<12.2f} {market_value:<15,.2f}")

            # 当日盈亏统计
            realized_pnl = sum(t.get('profit', 0) for t in sell_trades)
            print(f"\n💰 当日盈亏统计:")
            print(f"   已实现盈亏: {realized_pnl:+.2f} 元")
            print(f"   现金余额: {day_data['cash']:,.2f} 元")
            print(f"   持仓数量: {len(positions)} 只")

        # 月度汇总
        self.generate_monthly_summary(year, month, initial_capital)

    def generate_monthly_summary(self, year, month, initial_capital):
        """生成月度汇总"""
        print("\n" + "="*100)
        print(f"📊 月度交易汇总 - {year}年{month}月")
        print("="*100)

        # 所有交易统计
        all_buys = [t for t in self.all_trades if t['action'] == 'BUY']
        all_sells = [t for t in self.all_trades if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   总买入次数: {len(all_buys)} 次")
        print(f"   总卖出次数: {len(all_sells)} 次")

        if all_sells:
            profits = [t['profit'] for t in all_sells]
            win_count = len([p for p in profits if p > 0])
            loss_count = len([p for p in profits if p < 0])
            win_rate = win_count / len(profits) * 100 if profits else 0
            total_profit = sum(profits)
            avg_profit = total_profit / len(profits) if profits else 0

            print(f"   盈利次数: {win_count} 次")
            print(f"   亏损次数: {loss_count} 次")
            print(f"   胜率: {win_rate:.1f}%")
            print(f"   总盈亏: {total_profit:+.2f} 元")
            print(f"   平均盈亏: {avg_profit:+.2f} 元")

        # 按股票统计
        print(f"\n📋 按股票统计:")
        print("-"*100)
        print(f"{'代码':<10} {'名称':<10} {'买入次数':<10} {'卖出次数':<10} {'总盈亏':<15} {'平均盈亏':<15}")
        print("-"*100)

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
            total_pnl = sum(stats['profits'])
            avg_pnl = total_pnl / len(stats['profits']) if stats['profits'] else 0
            print(f"{code:<10} {stats['name']:<10} {stats['buy_count']:<10} {stats['sell_count']:<10} "
                  f"{total_pnl:<+15.2f} {avg_pnl:<+15.2f}")

        # 完整交易流水
        print(f"\n📝 完整交易流水:")
        print("="*100)
        print(f"{'日期':<12} {'时间':<10} {'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<10} {'盈亏':<12} {'备注':<20}")
        print("="*100)

        for t in self.all_trades:
            date = t['date']
            time = t['time']
            action = t['action']
            code = t['code']
            name = t['name']
            price = t['price']
            vol = t['vol']

            if action == 'SELL':
                profit = t.get('profit', 0)
                pnl_pct = t.get('pnl_pct', 0)
                remark = f"{t.get('type', '')}"
                print(f"{date:<12} {time:<10} {action:<6} {code:<10} {name:<10} "
                      f"{price:<10.2f} {vol:<10} {profit:<+12.2f} {remark:<20}")
            else:
                remark = t.get('strategy', '')
                print(f"{date:<12} {time:<10} {action:<6} {code:<10} {name:<10} "
                      f"{price:<10.2f} {vol:<10} {'--':<12} {remark:<20}")

        print("="*100)


if __name__ == "__main__":
    import sys

    config = ConfigLoader()
    report = DetailedTradeReport(config)

    # 支持命令行参数: python detailed_trade_report.py [year] [month]
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    month = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    try:
        # 生成指定月份详细报告
        report.run_detailed_backtest(year=year, month=month)
    except Exception as e:
        print(f"❌ 生成报告失败: {e}")
        import traceback
        traceback.print_exc()
