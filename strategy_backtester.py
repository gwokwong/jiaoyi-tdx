#!/usr/bin/env python3
"""
基于五大策略的历史回测系统
功能：
1. 使用五大策略筛选股票
2. 严格执行买入卖出规则
3. 生成详细的回测报告
4. 支持指定日期范围回测

📌 总原则：只在"信号明确+风险可控"时介入
"""

import pandas as pd
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager
from strategy import StockSelector


class StrategyBacktester:
    """
    策略回测器
    基于五大选股策略进行历史数据回测
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()
        self.selector = StockSelector(config)

        # 连接服务器
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if not self.api.connect(ip, port):
            raise Exception("连接服务器失败")

        print(f"✅ 已连接通达信服务器 ({ip}:{port})")

        # 初始化数据库
        self.db = DatabaseManager(config)

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}  # 当前持仓 {code: {...}}
        self.trade_history = []  # 交易历史
        self.daily_records = []  # 每日资产记录

        # 预设股票池（可根据需要扩展）
        self.stock_pool = [
            # 上海
            ('600000', 1), ('600004', 1), ('600009', 1), ('600010', 1),
            ('600015', 1), ('600016', 1), ('600018', 1), ('600019', 1),
            ('600028', 1), ('600029', 1), ('600030', 1), ('600031', 1),
            ('600036', 1), ('600048', 1), ('600050', 1), ('600061', 1),
            # 深圳
            ('000001', 0), ('000002', 0), ('000063', 0), ('000066', 0),
            ('000100', 0), ('000333', 0), ('000338', 0), ('000568', 0),
            ('000625', 0), ('000651', 0), ('000725', 0), ('000768', 0),
            ('000800', 0), ('000858', 0), ('000895', 0), ('002001', 0),
            ('002007', 0), ('002230', 0), ('002304', 0), ('002415', 0),
            ('002475', 0), ('002594', 0), ('300001', 0), ('300750', 0),
        ]

    def get_day_data(self, code, market, date_str):
        """获取指定日期的股票数据"""
        try:
            data = self.api.get_security_bars(4, market, code, 0, 100)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['datetime']).dt.date
            target_date = pd.to_datetime(date_str).date()
            day_data = df[df['date'] == target_date]

            if len(day_data) == 0:
                return None

            return day_data.iloc[0].to_dict()
        except Exception as e:
            return None

    def scan_for_signals(self, date_str, max_stocks=30):
        """
        扫描股票池，寻找五大策略信号

        参数:
            date_str: 日期字符串 '2026-04-01'
            max_stocks: 最大扫描数量

        返回:
            list: 符合条件的股票列表
        """
        print(f"\n🔍 正在扫描 {date_str} 的策略信号...")

        candidates = []

        for i, (code, market) in enumerate(self.stock_pool[:max_stocks]):
            if i % 5 == 0:
                print(f"   进度: {i}/{min(len(self.stock_pool), max_stocks)}", end='\r')

            try:
                # 使用策略模块扫描
                result = self.selector.scan_stock(code, market)

                if 'error' in result:
                    continue

                # 检查是否有策略信号
                for strategy_name, signal_data in result['strategies'].items():
                    if signal_data.get('signal', False):
                        # 风控检查
                        risk = result['risk_control']
                        if risk['passed']:
                            candidates.append({
                                'code': code,
                                'market': market,
                                'strategy': strategy_name,
                                'reason': signal_data['reason'],
                                'details': signal_data['details'],
                                'buy_price': signal_data['details'].get('买入价格', result['latest_data']['close']),
                                'stop_loss': signal_data['details'].get('止损位', None)
                            })
                            break  # 一个股票只取第一个满足的策略

            except Exception as e:
                continue

        print(f"\n✅ 发现 {len(candidates)} 只符合条件的股票")
        return candidates

    def execute_buy(self, stock, date_str):
        """
        执行买入操作

        参数:
            stock: 股票信息字典
            date_str: 交易日期

        返回:
            bool: 是否买入成功
        """
        code = stock['code']
        buy_price = stock['buy_price']
        market = stock['market']

        # 计算买入数量（单票仓位≤20%）
        position_value = self.initial_capital * 0.20  # 最多20%仓位
        vol = int(position_value / buy_price / 100) * 100  # 100股整数倍

        if vol == 0:
            return False

        cost = buy_price * vol
        fee = cost * self.config.get('fees', 'commission_rate')

        # 检查资金
        if self.cash < cost + fee:
            print(f"   ⚠️ 资金不足，无法买入 {code}")
            return False

        # 执行买入
        self.cash -= (cost + fee)

        # 记录持仓
        self.positions[code] = {
            'code': code,
            'market': market,
            'vol': vol,
            'buy_price': buy_price,
            'buy_date': date_str,
            'cost': cost,
            'fee': fee,
            'strategy': stock['strategy'],
            'stop_loss': stock.get('stop_loss', buy_price * 0.95)  # 默认止损5%
        }

        # 记录交易
        self.trade_history.append({
            'date': date_str,
            'code': code,
            'action': 'BUY',
            'price': buy_price,
            'vol': vol,
            'amount': cost,
            'fee': fee,
            'strategy': stock['strategy'],
            'cash_after': self.cash
        })

        # 保存到数据库
        self.db.save_trade(code, 'BUY', buy_price, vol,
                          self.config.get('fees', 'commission_rate'), 0)

        print(f"   🟢 买入 {code} @ {buy_price:.2f} x {vol}股 = {cost:.2f}元")
        print(f"      策略: {stock['strategy']} | {stock['reason']}")

        return True

    def check_sell_signals(self, date_str):
        """
        检查持仓卖出信号（止盈止损）

        参数:
            date_str: 当前日期

        返回:
            list: 卖出的股票代码列表
        """
        sold_stocks = []

        for code, pos in list(self.positions.items()):
            # 获取当日数据
            data = self.get_day_data(code, pos['market'], date_str)
            if data is None:
                continue

            current_price = data['close']
            buy_price = pos['buy_price']
            pnl_pct = (current_price - buy_price) / buy_price

            # 获取配置
            stop_loss_rate = self.config.get('strategy', 'stop_loss_rate') or -0.05
            take_profit_rate = self.config.get('strategy', 'take_profit_rate') or 0.10

            # 检查止损/止盈
            action_type = None
            if pnl_pct <= stop_loss_rate:
                action_type = "止损"
            elif pnl_pct >= take_profit_rate:
                action_type = "止盈"

            if action_type:
                # 执行卖出
                vol = pos['vol']
                income = current_price * vol

                # 计算费用（佣金+印花税）
                comm = income * self.config.get('fees', 'commission_rate')
                tax = income * self.config.get('fees', 'stamp_duty_rate')
                total_fee = comm + tax

                # 计算盈亏
                profit = income - pos['cost'] - total_fee - pos['fee']

                # 更新资金
                self.cash += (income - total_fee)

                # 记录交易
                self.trade_history.append({
                    'date': date_str,
                    'code': code,
                    'action': 'SELL',
                    'price': current_price,
                    'vol': vol,
                    'amount': income,
                    'fee': total_fee,
                    'profit': profit,
                    'pnl_pct': pnl_pct * 100,
                    'type': action_type,
                    'cash_after': self.cash
                })

                # 保存到数据库
                self.db.save_trade(code, 'SELL', current_price, vol,
                                  self.config.get('fees', 'commission_rate'),
                                  self.config.get('fees', 'stamp_duty_rate'))

                print(f"   🔴 卖出 {code} @ {current_price:.2f} | {action_type}")
                print(f"      盈亏: {pnl_pct*100:+.2f}% | 收益: {profit:+.2f}元")

                # 移除持仓
                del self.positions[code]
                sold_stocks.append(code)

        return sold_stocks

    def record_daily_status(self, date_str):
        """记录每日资产状态"""
        # 计算持仓市值
        hold_value = 0
        for code, pos in self.positions.items():
            hold_value += pos['vol'] * pos['buy_price']

        total = self.cash + hold_value

        self.daily_records.append({
            'date': date_str,
            'cash': self.cash,
            'hold_value': hold_value,
            'total': total,
            'positions': len(self.positions)
        })

    def run_backtest(self, start_date, end_date):
        """
        执行回测

        参数:
            start_date: 开始日期 '2026-03-01'
            end_date: 结束日期 '2026-04-10'
        """
        print("\n" + "="*80)
        print("📈 策略回测系统")
        print("="*80)
        print(f"\n💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📅 回测期间: {start_date} 至 {end_date}")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"📊 策略: 五大选股策略 + 严格止盈止损")
        take_profit = self.config.get('strategy', 'take_profit_rate') or 0.10
        stop_loss = self.config.get('strategy', 'stop_loss_rate') or -0.05
        print(f"🛡️ 风控: 单票仓位≤20%, 止盈{take_profit*100:.0f}%, 止损{abs(stop_loss)*100:.0f}%")
        print("\n" + "="*80)

        # 生成交易日列表
        date_range = pd.date_range(start=start_date, end=end_date, freq='B')

        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')

            print(f"\n📅 {date_str}")
            print("-" * 60)

            # 1. 检查持仓（止盈止损）
            if self.positions:
                print(f"   检查 {len(self.positions)} 只持仓...")
                self.check_sell_signals(date_str)

            # 2. 选股买入（如果还有资金和仓位）
            if self.cash > self.initial_capital * 0.3 and len(self.positions) < 5:
                candidates = self.scan_for_signals(date_str, max_stocks=30)

                # 买入前3只（分散风险）
                for stock in candidates[:3]:
                    if stock['code'] not in self.positions and len(self.positions) < 5:
                        self.execute_buy(stock, date_str)
            elif len(self.positions) >= 5:
                print("   持仓已满(5只)，暂停买入")
            else:
                print("   资金不足，暂停买入")

            # 3. 记录每日状态
            self.record_daily_status(date_str)

        # 生成回测报告
        self.generate_report()

    def generate_report(self):
        """生成回测报告"""
        print("\n" + "="*80)
        print("📊 回测报告")
        print("="*80)

        # 1. 资金状况
        final_record = self.daily_records[-1] if self.daily_records else {'total': self.cash}
        final_equity = final_record['total']
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final_equity:,.2f} 元")
        print(f"   总收益率: {total_return:+.2f}%")
        print(f"   现金余额: {self.cash:,.2f} 元")

        # 持仓市值
        hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        print(f"   持仓市值: {hold_value:,.2f} 元")

        # 2. 交易统计
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

            if win_trades:
                print(f"   平均盈利: {sum(win_trades)/len(win_trades):,.2f} 元")
            if lose_trades:
                print(f"   平均亏损: {sum(lose_trades)/len(lose_trades):,.2f} 元")

        # 3. 策略分布
        print(f"\n📊 策略分布:")
        strategy_count = {}
        for t in buy_trades:
            strategy = t.get('strategy', '未知')
            strategy_count[strategy] = strategy_count.get(strategy, 0) + 1

        for strategy, count in sorted(strategy_count.items(), key=lambda x: x[1], reverse=True):
            print(f"   {strategy}: {count}次")

        # 4. 当前持仓
        print(f"\n📋 当前持仓 ({len(self.positions)} 只):")
        if self.positions:
            for code, pos in self.positions.items():
                print(f"   {code}: {pos['vol']}股 @ {pos['buy_price']:.2f}元 ({pos['strategy']})")
        else:
            print("   无持仓")

        # 5. 完整交易明细
        print(f"\n📝 完整交易明细:")
        print("-"*100)
        print(f"{'日期':<12} {'代码':<10} {'操作':<6} {'价格':<10} {'数量':<10} {'金额':<12} {'策略':<20} {'盈亏':<10}")
        print("-"*100)

        for t in self.trade_history:
            profit_str = f"{t.get('profit', 0):+.2f}" if t['action'] == 'SELL' else "-"
            strategy_str = t.get('strategy', t.get('type', '-'))
            print(f"{t['date']:<12} {t['code']:<10} {t['action']:<6} "
                  f"{t['price']:<10.2f} {t['vol']:<10} {t['amount']:<12.2f} "
                  f"{strategy_str:<20} {profit_str:<10}")

        print("-"*100)
        print("\n" + "="*80)

    def close(self):
        """关闭连接"""
        self.api.disconnect()
        self.selector.close()
        self.db.close()


if __name__ == "__main__":
    import sys

    # 获取命令行参数
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        # 默认回测最近一个月
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=30)
        start_date = start.strftime('%Y-%m-%d')
        end_date = end.strftime('%Y-%m-%d')
        print(f"使用默认日期范围: {start_date} 至 {end_date}")
        print(f"提示: 可指定日期: python3 strategy_backtester.py 2026-03-01 2026-04-10")

    # 启动回测
    config = ConfigLoader()
    backtester = StrategyBacktester(config)

    try:
        backtester.run_backtest(start_date, end_date)
    finally:
        backtester.close()
