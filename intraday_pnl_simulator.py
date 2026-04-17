#!/usr/bin/env python3
"""
盘中当日盈利模拟器 - 实时跟踪买入股票的盈亏情况
"""

import pandas as pd
import time
import os
import platform
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader


class IntradayPnLSimulator:
    """盘中当日盈利模拟器"""

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)

        # 获取全市场股票池（不限制数量，获取全部5000+只）
        print("📥 正在加载全市场股票池...")
        self.stock_pool = self.core.get_all_stocks(limit=None)
        print(f"✅ 成功加载 {len(self.stock_pool)} 只股票")

        # 持仓记录 {code: {'name': str, 'buy_price': float, 'vol': int, 'buy_time': str, 'signals': list}}
        self.positions = {}

        # 交易记录
        self.trade_history = []

        # 已提醒的股票
        self.alerted_stocks = set()

        # 初始资金
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital

        # 监控时间
        self.start_time = '09:20'
        self.end_time = '15:00'

        # 统计
        self.scan_count = 0
        self.max_alerts_per_scan = 10

    def is_monitoring_time(self):
        """检查是否在监控时间"""
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        return self.start_time <= current_time <= self.end_time

    def is_trading_day(self):
        """检查是否是交易日"""
        now = datetime.now()
        return now.weekday() < 5

    def get_30min_data(self, code, market):
        """获取30分钟K线数据"""
        try:
            data = self.core.api.get_security_bars(2, market, code, 0, 100)
            if not data:
                return None

            df = pd.DataFrame(data)
            df = df[df['datetime'].str.match(r'^\d{4}-\d{2}-\d{2}')]
            if len(df) == 0:
                return None

            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            df = self.calculate_indicators(df)

            return df

        except Exception as e:
            return None

    def calculate_indicators(self, df):
        """计算技术指标"""
        if len(df) < 3:
            return None

        df['ma3'] = df['close'].rolling(window=3).mean()
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['vol_ma3'] = df['vol'].rolling(window=3).mean()

        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = (df['dif'] - df['dea']) * 2

        return df

    def check_buy_signals(self, df, code, name):
        """检查买入信号"""
        if df is None or len(df) < 3:
            return None

        signals = []
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None

        current_price = latest['close']

        # 信号1: 30分钟MACD金叉
        if prev is not None:
            macd_cross = (prev['dif'] <= prev['dea']) and (latest['dif'] > latest['dea'])
            if macd_cross and latest['macd'] > 0:
                signals.append({
                    'type': 'MACD金叉',
                    'price': current_price,
                    'strength': '强' if latest['macd'] > 0.5 else '中',
                    'desc': f'DIF上穿DEA，MACD={latest["macd"]:.2f}'
                })

        # 信号2: 价格突破30分钟均线
        if latest['close'] > latest['ma3'] and (prev is None or prev['close'] <= prev['ma3']):
            change_pct = (latest['close'] - latest['open']) / latest['open'] * 100
            vol_ratio = latest['vol'] / latest['vol_ma3'] if latest['vol_ma3'] > 0 else 0

            if change_pct >= 0.3 and vol_ratio >= 1.1:
                signals.append({
                    'type': '均线突破',
                    'price': current_price,
                    'strength': '强' if vol_ratio > 1.5 else '中',
                    'desc': f'突破MA3，涨幅{change_pct:.2f}%，量比{vol_ratio:.2f}'
                })

        # 信号3: 30分钟阳线放量
        if latest['close'] > latest['open']:
            change_pct = (latest['close'] - latest['open']) / latest['open'] * 100
            vol_ratio = latest['vol'] / latest['vol_ma3'] if latest['vol_ma3'] > 0 else 0

            if change_pct >= 0.5 and vol_ratio >= 1.2:
                signals.append({
                    'type': '阳线放量',
                    'price': current_price,
                    'strength': '强' if change_pct > 1.0 else '中',
                    'desc': f'阳线{change_pct:.2f}%，量比{vol_ratio:.2f}'
                })

        return signals if signals else None

    def execute_buy(self, code, name, price, signals):
        """执行买入"""
        # 计算买入数量（2%仓位）
        position_value = self.initial_capital * 0.02
        vol = int(position_value / price / 100) * 100

        if vol < 100:
            return False

        amount = price * vol
        fee = amount * 0.0003  # 手续费0.03%
        total_cost = amount + fee

        if total_cost > self.cash:
            return False

        # 记录持仓
        now = datetime.now()
        self.positions[code] = {
            'name': name,
            'buy_price': price,
            'vol': vol,
            'buy_time': now.strftime('%H:%M:%S'),
            'signals': [s['type'] for s in signals],
            'buy_amount': amount,
            'fee': fee
        }

        self.cash -= total_cost

        # 记录交易
        trade = {
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%H:%M:%S'),
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': price,
            'vol': vol,
            'amount': amount,
            'fee': fee,
            'signals': [s['type'] for s in signals]
        }
        self.trade_history.append(trade)

        print(f"\n🟢 【买入成交】{code} {name}")
        print(f"   价格: {price:.2f}元, 数量: {vol}股, 金额: {amount:,.2f}元")
        print(f"   手续费: {fee:.2f}元, 剩余现金: {self.cash:,.2f}元")

        return True

    def update_positions_pnl(self):
        """更新持仓盈亏"""
        if not self.positions:
            return None

        total_pnl = 0
        total_cost = 0
        position_details = []

        for code, pos in self.positions.items():
            # 查找当前价格
            current_price = None
            for stock_code, market, name in self.stock_pool:
                if stock_code == code:
                    df = self.get_30min_data(code, market)
                    if df is not None and len(df) > 0:
                        current_price = df.iloc[-1]['close']
                    break

            if current_price is None:
                continue

            # 计算盈亏
            cost = pos['buy_price'] * pos['vol']
            market_value = current_price * pos['vol']
            pnl = market_value - cost - pos['fee']
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0

            total_pnl += pnl
            total_cost += cost

            position_details.append({
                'code': code,
                'name': pos['name'],
                'buy_price': pos['buy_price'],
                'current_price': current_price,
                'vol': pos['vol'],
                'pnl': pnl,
                'pnl_pct': pnl_pct
            })

        total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0

        return {
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'total_cost': total_cost,
            'positions': position_details
        }

    def display_pnl_report(self):
        """显示盈亏报告"""
        pnl_data = self.update_positions_pnl()

        if not pnl_data:
            print("\n📊 当前无持仓")
            return

        now = datetime.now().strftime('%H:%M:%S')

        print("\n" + "="*100)
        print(f"📊 盘中盈亏报告 - {now}")
        print("="*100)

        print(f"\n💰 总体盈亏:")
        print(f"   持仓成本: {pnl_data['total_cost']:,.2f} 元")
        print(f"   总盈亏: {pnl_data['total_pnl']:+.2f} 元 ({pnl_data['total_pnl_pct']:+.2f}%)")
        print(f"   现金余额: {self.cash:,.2f} 元")
        print(f"   总资产: {self.cash + pnl_data['total_cost'] + pnl_data['total_pnl']:,.2f} 元")

        print(f"\n📋 持仓明细:")
        print("-"*100)
        print(f"{'代码':<10} {'名称':<10} {'买入价':<10} {'当前价':<10} {'数量':<10} {'盈亏':<12} {'盈亏%':<10}")
        print("-"*100)

        for pos in pnl_data['positions']:
            print(f"{pos['code']:<10} {pos['name']:<10} {pos['buy_price']:<10.2f} "
                  f"{pos['current_price']:<10.2f} {pos['vol']:<10} {pos['pnl']:<+12.2f} {pos['pnl_pct']:<+10.2f}%")

        print("-"*100)

    def scan_and_buy(self):
        """扫描并买入"""
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] 开始扫描 {len(self.stock_pool)} 只股票...")

        alerts = 0
        bought = 0

        for code, market, name in self.stock_pool:
            # 跳过已持仓和已提醒的股票
            if code in self.positions or code in self.alerted_stocks:
                continue

            # 限制买入数量
            if len(self.positions) >= self.max_alerts_per_scan:
                print(f"⏹️ 已达到最大持仓数 {self.max_alerts_per_scan}")
                break

            df = self.get_30min_data(code, market)
            if df is None:
                continue

            signals = self.check_buy_signals(df, code, name)
            if signals:
                current_price = df.iloc[-1]['close']
                alerts += 1

                # 执行买入
                if self.execute_buy(code, name, current_price, signals):
                    bought += 1
                    self.alerted_stocks.add(code)

                    if bought % 3 == 0:
                        print(f"   已买入 {bought} 只股票...")

        print(f"✅ 扫描完成: 发现 {alerts} 只信号股, 买入 {bought} 只")
        return bought

    def wait_until_start(self):
        """等待到开盘前"""
        now = datetime.now()
        target = now.replace(hour=9, minute=20, second=0, microsecond=0)

        if now >= target:
            return

        wait_seconds = (target - now).total_seconds()
        print(f"\n⏰ 等待到开盘前 {self.start_time}...")
        print(f"⏰ 还需等待 {int(wait_seconds)} 秒\n")

        while datetime.now() < target:
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 60:
                print(f"⏳ 还有 {int(remaining/60)} 分钟...")
                time.sleep(60)
            elif remaining > 10:
                print(f"⏳ 还有 {int(remaining)} 秒...")
                time.sleep(10)
            else:
                time.sleep(1)

        print(f"\n🚀 到达开盘时间，开始监控！\n")

    def run_simulation(self, interval=60):
        """运行盘中模拟"""
        print("\n" + "="*100)
        print("📈 盘中当日盈利模拟器")
        print("="*100)
        print(f"⏰ 监控时间: {self.start_time} - {self.end_time}")
        print(f"⏰ 扫描间隔: {interval} 秒")
        print(f"📊 股票池: {len(self.stock_pool)} 只")
        print(f"💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"🎯 策略: 30分钟均线买入，实时跟踪盈亏")
        print(f"💡 提示: 按 Ctrl+C 停止")
        print("="*100)

        if not self.is_trading_day():
            print(f"\n📅 今天不是交易日")
            return

        self.wait_until_start()

        try:
            while True:
                now = datetime.now()
                current_time = now.strftime('%H:%M')

                # 检查是否收盘
                if current_time >= self.end_time:
                    print(f"\n🏁 到达收盘时间 {self.end_time}")
                    break

                self.scan_count += 1

                print(f"\n{'='*100}")
                print(f"🔄 第 {self.scan_count} 次扫描 - {now.strftime('%H:%M:%S')}")
                print(f"{'='*100}")

                # 扫描并买入
                bought = self.scan_and_buy()

                # 显示盈亏报告
                self.display_pnl_report()

                # 显示状态
                print(f"\n📊 当前状态:")
                print(f"   持仓: {len(self.positions)} 只")
                print(f"   现金: {self.cash:,.2f} 元")

                # 距离收盘时间
                end = now.replace(hour=15, minute=0, second=0, microsecond=0)
                remaining = (end - now).total_seconds()
                if remaining > 0:
                    print(f"\n⏰ 距离收盘: {int(remaining/60)} 分钟")

                print(f"\n⏳ {interval}秒后再次扫描...")
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n" + "="*100)
            print("👋 模拟已停止")
            print("="*100)

        finally:
            self.generate_final_report()

    def generate_final_report(self):
        """生成最终报告"""
        print("\n" + "="*100)
        print(f"📊 当日交易总结 - {datetime.now().strftime('%Y-%m-%d')}")
        print("="*100)

        # 最终盈亏
        pnl_data = self.update_positions_pnl()

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")

        if pnl_data:
            final_value = self.cash + pnl_data['total_cost'] + pnl_data['total_pnl']
            print(f"   最终资产: {final_value:,.2f} 元")
            print(f"   当日盈亏: {final_value - self.initial_capital:+.2f} 元")
            print(f"   盈亏比例: {((final_value - self.initial_capital) / self.initial_capital * 100):+.2f}%")
            print(f"   现金余额: {self.cash:,.2f} 元")
            print(f"   持仓市值: {pnl_data['total_cost'] + pnl_data['total_pnl']:,.2f} 元")

        print(f"\n📈 交易统计:")
        print(f"   扫描次数: {self.scan_count} 次")
        print(f"   买入股票: {len(self.positions)} 只")

        if self.trade_history:
            print(f"\n📝 买入明细:")
            print("-"*100)
            print(f"{'时间':<10} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<10} {'金额':<15}")
            print("-"*100)

            total_amount = 0
            for trade in self.trade_history:
                print(f"{trade['time']:<10} {trade['code']:<10} {trade['name']:<10} "
                      f"{trade['price']:<10.2f} {trade['vol']:<10} {trade['amount']:<15,.2f}")
                total_amount += trade['amount']

            print("-"*100)
            print(f"   总买入金额: {total_amount:,.2f} 元")

        print("\n" + "="*100)

    def close(self):
        """关闭连接"""
        self.core.close()


if __name__ == "__main__":
    import sys

    config = ConfigLoader()
    simulator = IntradayPnLSimulator(config)

    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    try:
        simulator.run_simulation(interval=interval)
    except Exception as e:
        print(f"❌ 模拟出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        simulator.close()
