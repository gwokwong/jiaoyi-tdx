#!/usr/bin/env python3
"""
模拟实时交易策略
功能：
1. 指定日期，获取当日所有股票数据
2. 根据策略筛选符合条件的股票
3. 模拟买入和卖出（考虑止盈止损）
4. 生成详细的交易报告
"""

import pandas as pd
import datetime
from pytdx.hq import TdxHq_API
from pytdx.reader import TdxDailyBarReader
from core import ConfigLoader, DatabaseManager


class SimulationTrader:
    """
    模拟实时交易器
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        # 连接服务器
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if self.api.connect(ip, port):
            print(f"✅ 已连接通达信服务器 ({ip}:{port})")
        else:
            raise Exception("连接服务器失败")

        # 初始化数据库
        self.db = DatabaseManager(config)
        self.cash = config.get('account', 'initial_capital')
        self.initial_capital = self.cash
        self.positions = {}  # 当前持仓
        self.trade_history = []  # 交易记录
        self.daily_equity = []  # 每日资产记录

    def get_stock_list(self):
        """
        获取股票列表（沪深A股）
        返回: [(code, market), ...]
        """
        # 使用预设的热门股票列表（演示用）
        # 上海市场 (market=1): 60xxxx
        # 深圳市场 (market=0): 00xxxx, 30xxxx
        stocks = [
            # 上海
            ('600000', 1), ('600001', 1), ('600004', 1), ('600009', 1),
            ('600010', 1), ('600011', 1), ('600015', 1), ('600016', 1),
            ('600018', 1), ('600019', 1), ('600028', 1), ('600029', 1),
            ('600030', 1), ('600031', 1), ('600036', 1), ('600037', 1),
            ('600048', 1), ('600050', 1), ('600061', 1), ('600062', 1),
            # 深圳
            ('000001', 0), ('000002', 0), ('000063', 0), ('000066', 0),
            ('000100', 0), ('000333', 0), ('000338', 0), ('000568', 0),
            ('000625', 0), ('000651', 0), ('000725', 0), ('000768', 0),
            ('000800', 0), ('000858', 0), ('000895', 0), ('002001', 0),
            ('002007', 0), ('002024', 0), ('002027', 0), ('002142', 0),
            ('002230', 0), ('002236', 0), ('002304', 0), ('002352', 0),
            ('002415', 0), ('002460', 0), ('002475', 0), ('002594', 0),
            ('300001', 0), ('300003', 0), ('300014', 0), ('300015', 0),
            ('300033', 0), ('300059', 0), ('300122', 0), ('300124', 0),
            ('300142', 0), ('300274', 0), ('300408', 0), ('300750', 0),
        ]

        print(f"✅ 使用预设股票列表，共 {len(stocks)} 只股票")
        return stocks

    def get_day_data(self, code, market, date_str):
        """
        获取指定日期的股票数据
        """
        try:
            # 获取最近100天的数据
            data = self.api.get_security_bars(4, market, code, 0, 100)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['datetime']).dt.date
            target_date = pd.to_datetime(date_str).date()

            # 筛选目标日期
            day_data = df[df['date'] == target_date]
            if len(day_data) == 0:
                return None

            return day_data.iloc[0].to_dict()
        except Exception as e:
            return None

    def scan_stocks(self, date_str, max_stocks=50):
        """
        扫描股票，筛选出符合条件的
        策略：阳线 + 放量 + 涨幅适中
        """
        print(f"\n🔍 正在扫描 {date_str} 的股票...")

        stocks = self.get_stock_list()
        candidates = []

        for i, (code, market) in enumerate(stocks[:max_stocks]):  # 限制扫描数量
            if i % 10 == 0:
                print(f"   进度: {i}/{min(len(stocks), max_stocks)}", end='\r')

            data = self.get_day_data(code, market, date_str)
            if data is None:
                continue

            # 计算指标
            open_price = data['open']
            close_price = data['close']
            high_price = data['high']
            low_price = data['low']
            volume = data['vol']

            # 跳过无效数据
            if open_price == 0 or close_price == 0:
                continue

            change_pct = (close_price - open_price) / open_price * 100

            # 策略条件：
            # 1. 阳线（收盘 > 开盘）
            # 2. 涨幅在 0.1% - 10% 之间（放宽条件）
            # 3. 有成交量
            if (close_price > open_price and
                0.1 <= change_pct <= 10.0 and
                volume > 100000):

                candidates.append({
                    'code': code,
                    'market': market,
                    'name': f"股票{code}",
                    'open': open_price,
                    'close': close_price,
                    'high': high_price,
                    'low': low_price,
                    'change_pct': change_pct,
                    'volume': volume,
                    'buy_price': close_price,  # 以收盘价买入
                    'date': date_str
                })

        print(f"\n✅ 筛选出 {len(candidates)} 只符合条件的股票")
        return candidates

    def simulate_buy(self, stock, date_str):
        """
        模拟买入
        """
        code = stock['code']
        buy_price = stock['buy_price']

        # 计算买入数量（假设每次买入固定金额）
        position_value = self.initial_capital * self.config.get('account', 'max_position_ratio')
        vol = int(position_value / buy_price / 100) * 100  # 100股整数倍

        if vol == 0:
            return False

        cost = buy_price * vol
        fee = cost * self.config.get('fees', 'commission_rate')

        if self.cash >= cost + fee:
            self.cash -= (cost + fee)
            self.positions[code] = {
                'code': code,
                'vol': vol,
                'buy_price': buy_price,
                'buy_date': date_str,
                'cost': cost,
                'fee': fee,
                'market': stock['market']
            }

            self.trade_history.append({
                'date': date_str,
                'code': code,
                'action': 'BUY',
                'price': buy_price,
                'vol': vol,
                'amount': cost,
                'fee': fee,
                'cash_after': self.cash
            })

            print(f"   🟢 买入 {code} @ {buy_price:.2f} x {vol}股 = {cost:.2f}元")
            return True

        return False

    def check_sell(self, date_str):
        """
        检查持仓是否需要卖出（止盈止损）
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

            # 止损或止盈
            stop_loss = self.config.get('strategy', 'stop_loss_rate')
            take_profit = self.config.get('strategy', 'take_profit_rate')

            if pnl_pct <= stop_loss or pnl_pct >= take_profit:
                # 卖出
                vol = pos['vol']
                income = current_price * vol
                comm = income * self.config.get('fees', 'commission_rate')
                tax = income * self.config.get('fees', 'stamp_duty_rate')
                total_fee = comm + tax

                self.cash += (income - total_fee)

                profit = income - pos['cost'] - total_fee - pos['fee']

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
                    'cash_after': self.cash
                })

                print(f"   🔴 卖出 {code} @ {current_price:.2f} | 盈亏: {pnl_pct*100:+.2f}% | 收益: {profit:.2f}元")

                del self.positions[code]
                sold_stocks.append(code)

        return sold_stocks

    def run_simulation(self, start_date, end_date):
        """
        运行模拟交易
        """
        print(f"\n{'='*60}")
        print(f"📅 模拟交易期间: {start_date} 至 {end_date}")
        print(f"💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"{'='*60}\n")

        # 生成交易日列表
        date_range = pd.date_range(start=start_date, end=end_date, freq='B')  # B=工作日

        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"\n📊 日期: {date_str}")
            print("-" * 40)

            # 1. 检查现有持仓（止盈止损）
            if self.positions:
                print(f"   检查 {len(self.positions)} 只持仓...")
                self.check_sell(date_str)

            # 2. 扫描新机会（如果还有资金）
            if self.cash > self.initial_capital * 0.2:  # 保留20%现金
                candidates = self.scan_stocks(date_str, max_stocks=100)

                # 买入前3只符合条件的股票
                for stock in candidates[:3]:
                    if stock['code'] not in self.positions:
                        self.simulate_buy(stock, date_str)
                        if len(self.positions) >= 5:  # 最多持有5只股票
                            break
            else:
                print("   资金不足，暂停买入")

            # 3. 记录每日资产
            self.record_equity(date_str)

        # 生成报告
        self.generate_report()

    def record_equity(self, date_str):
        """
        记录每日总资产
        """
        # 计算持仓市值
        hold_value = 0
        for code, pos in self.positions.items():
            hold_value += pos['vol'] * pos['buy_price']  # 简化处理，用买入价

        total = self.cash + hold_value
        self.daily_equity.append({
            'date': date_str,
            'cash': self.cash,
            'hold_value': hold_value,
            'total': total
        })

    def generate_report(self):
        """
        生成交易报告
        """
        print(f"\n{'='*60}")
        print("📈 模拟交易报告")
        print(f"{'='*60}")

        # 1. 总体收益
        final_equity = self.daily_equity[-1]['total'] if self.daily_equity else self.cash
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final_equity:,.2f} 元")
        print(f"   总收益率: {total_return:+.2f}%")
        print(f"   现金余额: {self.cash:,.2f} 元")
        print(f"   持仓市值: {final_equity - self.cash:,.2f} 元")

        # 2. 交易统计
        print(f"\n📊 交易统计:")
        print(f"   总交易次数: {len(self.trade_history)}")

        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

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
            print(f"   平均盈利: {sum(win_trades)/len(win_trades) if win_trades else 0:,.2f} 元")
            print(f"   平均亏损: {sum(lose_trades)/len(lose_trades) if lose_trades else 0:,.2f} 元")

        # 3. 当前持仓
        print(f"\n📋 当前持仓 ({len(self.positions)} 只):")
        if self.positions:
            for code, pos in self.positions.items():
                print(f"   {code}: {pos['vol']}股 @ {pos['buy_price']:.2f}元")
        else:
            print("   无持仓")

        # 4. 交易明细
        print(f"\n📝 交易明细:")
        print("-" * 80)
        print(f"{'日期':<12} {'代码':<10} {'操作':<6} {'价格':<10} {'数量':<10} {'金额':<12} {'盈亏':<10}")
        print("-" * 80)
        for t in self.trade_history:
            profit_str = f"{t.get('profit', 0):+.2f}" if t['action'] == 'SELL' else "-"
            print(f"{t['date']:<12} {t['code']:<10} {t['action']:<6} "
                  f"{t['price']:<10.2f} {t['vol']:<10} {t['amount']:<12.2f} {profit_str:<10}")
        print("-" * 80)

        print(f"\n{'='*60}\n")

    def close(self):
        """
        关闭连接
        """
        self.api.disconnect()
        self.db.close()


if __name__ == "__main__":
    import sys

    # 获取命令行参数
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        # 默认回测最近5个交易日
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=10)
        start_date = start.strftime('%Y-%m-%d')
        end_date = end.strftime('%Y-%m-%d')
        print(f"使用默认日期范围: {start_date} 至 {end_date}")
        print(f"提示: 可指定日期范围: python3 simulation_trader.py 2026-04-01 2026-04-10")

    # 启动模拟交易
    config = ConfigLoader()
    trader = SimulationTrader(config)

    try:
        trader.run_simulation(start_date, end_date)
    finally:
        trader.close()
