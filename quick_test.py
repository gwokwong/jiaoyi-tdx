#!/usr/bin/env python3
"""
快速测试 - 使用小股票池测试卖出原则
"""

import pandas as pd
import numpy as np
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


class QuickBacktester:
    """快速回测器 - 小股票池测试"""

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if not self.api.connect(ip, port):
            raise Exception("连接服务器失败")

        print(f"✅ 已连接通达信服务器 ({ip}:{port})")
        self.db = DatabaseManager(config)

        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}
        self.trade_history = []
        self.daily_records = []

        # 小股票池（20只热门股）
        self.stock_pool = [
            ('000001', 0, '平安银行'), ('000002', 0, '万科A'), ('000858', 0, '五粮液'),
            ('002001', 0, '新和成'), ('002230', 0, '科大讯飞'), ('002594', 0, '比亚迪'),
            ('300750', 0, '宁德时代'), ('600000', 1, '浦发银行'), ('600036', 1, '招商银行'),
            ('600519', 1, '贵州茅台'), ('000333', 0, '美的集团'), ('000651', 0, '格力电器'),
            ('002415', 0, '海康威视'), ('002475', 0, '立讯精密'), ('600276', 1, '恒瑞医药'),
            ('600030', 1, '中信证券'), ('000725', 0, '京东方A'), ('600050', 1, '中国联通'),
            ('601318', 1, '中国平安'), ('600887', 1, '伊利股份'),
        ]
        self.stock_names = {code: name for code, market, name in self.stock_pool}

    def get_history_data(self, code, market, days=60):
        """获取历史数据"""
        try:
            data = self.api.get_security_bars(4, market, code, 0, days)
            if not data:
                return None
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['datetime'])
            df.set_index('date', inplace=True)
            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 
                              'close': 'Close', 'vol': 'Volume'}, inplace=True)
            return df
        except:
            return None

    def check_buy_signals(self, df):
        """检查买入信号（简化版）"""
        if df is None or len(df) < 20:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 计算均线
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        # 策略1: 阳线+放量
        is_yang = latest['Close'] > latest['Open']
        change_pct = (latest['Close'] - prev['Close']) / prev['Close'] * 100
        vol_ma5 = df['Volume'].iloc[-6:-1].mean()
        vol_ratio = latest['Volume'] / vol_ma5 if vol_ma5 > 0 else 0

        if is_yang and change_pct >= 1.0 and vol_ratio >= 1.2:
            return {'signal': True, 'price': latest['Close'], 'reason': f'阳线上涨{change_pct:.1f}%,放量{vol_ratio:.1f}倍'}

        # 策略2: 均线多头
        if latest['MA5'] > latest['MA10'] > latest['MA20'] and latest['Close'] > latest['MA5']:
            return {'signal': True, 'price': latest['Close'], 'reason': '均线多头排列'}

        return None

    def calculate_indicators(self, df):
        """计算卖出指标"""
        if df is None or len(df) < 30:
            return None

        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()

        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['MACD'] = (df['DIF'] - df['DEA']) * 2

        df['VOL_MA5'] = df['Volume'].rolling(window=5).mean()

        return df

    def check_sell_signals(self, code, pos, df):
        """检查卖出信号"""
        if df is None or len(df) < 2:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = latest['Close']
        buy_price = pos['buy_price']
        pnl_pct = (current_price - buy_price) / buy_price

        sell_signals = []

        # 1. 止盈止损
        if pnl_pct <= -0.05:
            sell_signals.append(("止损", f"亏损达到{pnl_pct*100:.1f}%"))
        elif pnl_pct >= 0.10:
            sell_signals.append(("止盈", f"盈利达到{pnl_pct*100:.1f}%"))

        # 2. 跌破20日均线
        if len(df) >= 2 and 'MA20' in df.columns:
            break_down = latest['Close'] < latest['MA20'] * 0.995
            was_above = prev['Close'] > prev['MA20']
            if break_down and was_above:
                sell_signals.append(("跌破支撑", "收盘价跌破20日均线"))

        # 3. MACD顶背离
        if len(df) >= 30 and 'DIF' in df.columns:
            recent = df.iloc[-30:]
            price_high = recent['High'].max()
            if latest['Close'] >= price_high * 0.98:
                high_idx = recent['High'].idxmax()
                macd_at_high = df.loc[high_idx, 'DIF']
                if latest['DIF'] < macd_at_high * 0.95:
                    sell_signals.append(("MACD顶背离", "价格新高但MACD未新高"))

        # 4. 空头排列
        if 'MA5' in df.columns and len(df) >= 5:
            bearish = (latest['MA5'] < latest['MA10'] < latest['MA20'])
            if bearish:
                recent_3 = df.iloc[-3:]
                below_ma20 = all(recent_3['Close'] < recent_3['MA20'])
                if below_ma20:
                    sell_signals.append(("空头排列", "均线空头排列且股价在20日线下方"))

        return sell_signals[0] if sell_signals else None

    def run_backtest(self, start_date, end_date):
        """执行回测"""
        print("\n" + "="*80)
        print("📈 快速测试 - 五大卖出原则")
        print("="*80)
        print(f"\n💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📅 回测期间: {start_date} 至 {end_date}")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"🛡️ 风控: 单票仓位≤5%, 止盈10%, 止损5%")
        print("\n" + "="*80)

        date_range = pd.date_range(start=start_date, end=end_date, freq='B')

        for current_date in date_range[:15]:  # 只测试前15个交易日
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"\n📅 {date_str}")
            print("-" * 60)

            # 检查持仓卖出
            if self.positions:
                print(f"   检查 {len(self.positions)} 只持仓...")
                for code, pos in list(self.positions.items()):
                    df = self.get_history_data(code, pos['market'], days=60)
                    df = self.calculate_indicators(df)
                    signal = self.check_sell_signals(code, pos, df)

                    if signal:
                        action_type, reason = signal
                        current_price = df.iloc[-1]['Close']
                        vol = pos['vol']
                        income = current_price * vol
                        fee = income * 0.0006
                        profit = income - pos['cost'] - fee - pos['fee']
                        self.cash += (income - fee)

                        print(f"   🔴 卖出 {code} {pos['name']} @ {current_price:.2f} | {action_type}")
                        print(f"      原因: {reason}")
                        print(f"      盈亏: {profit:+.2f}元")

                        self.trade_history.append({
                            'date': date_str, 'code': code, 'name': pos['name'],
                            'action': 'SELL', 'price': current_price, 'profit': profit,
                            'type': action_type, 'reason': reason
                        })
                        del self.positions[code]

            # 选股买入
            if self.cash > self.initial_capital * 0.5 and len(self.positions) < 10:
                print(f"   扫描买入机会...")
                buy_count = 0
                for code, market, name in self.stock_pool:
                    if code in self.positions or buy_count >= 3:
                        continue

                    df = self.get_history_data(code, market, days=30)
                    signal = self.check_buy_signals(df)

                    if signal:
                        buy_price = signal['price']
                        vol = int(self.initial_capital * 0.05 / buy_price / 100) * 100
                        if vol == 0:
                            continue

                        cost = buy_price * vol
                        fee = cost * 0.0001
                        if self.cash < cost + fee:
                            continue

                        self.cash -= (cost + fee)
                        self.positions[code] = {
                            'code': code, 'name': name, 'market': market,
                            'vol': vol, 'buy_price': buy_price, 'cost': cost, 'fee': fee
                        }

                        print(f"   🟢 买入 {code} {name} @ {buy_price:.2f} x {vol}股")
                        print(f"      原因: {signal['reason']}")
                        buy_count += 1

            # 记录状态
            hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
            self.daily_records.append({
                'date': date_str, 'cash': self.cash, 'hold_value': hold_value,
                'total': self.cash + hold_value, 'positions': len(self.positions)
            })

        # 生成报告
        self.generate_report()

    def generate_report(self):
        """生成报告"""
        print("\n" + "="*80)
        print("📊 测试报告")
        print("="*80)

        final = self.daily_records[-1] if self.daily_records else {'total': self.cash}
        total_return = (final['total'] - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final['total']:,.2f} 元")
        print(f"   总收益率: {total_return:+.2f}%")

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
        for code, pos in self.positions.items():
            print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元")

        print(f"\n📝 交易明细:")
        print("-"*80)
        for t in self.trade_history:
            if t['action'] == 'SELL':
                print(f"{t['date']} {t['code']} {t['name']}: {t['action']} @ {t['price']:.2f} "
                      f"| {t['type']} | {t['profit']:+.2f}元")
            else:
                print(f"{t['date']} {t['code']} {t['name']}: {t['action']} @ {t['price']:.2f}")
        print("="*80)

    def close(self):
        self.api.disconnect()
        self.db.close()


if __name__ == "__main__":
    config = ConfigLoader()
    backtester = QuickBacktester(config)
    try:
        backtester.run_backtest('2026-03-01', '2026-03-20')
    finally:
        backtester.close()
