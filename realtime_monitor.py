#!/usr/bin/env python3
"""
盘中实时监控系统 - 30分钟均线买入提醒
"""

import pandas as pd
import numpy as np
import time
import os
import platform
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader


class RealtimeMonitor:
    """盘中实时监控系统"""

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)

        # 监控的股票池
        self.stock_pool = [
            ('000001', 0, '平安银行'), ('000002', 0, '万科A'), ('000858', 0, '五粮液'),
            ('002001', 0, '新和成'), ('002230', 0, '科大讯飞'), ('002594', 0, '比亚迪'),
            ('300750', 0, '宁德时代'), ('600000', 1, '浦发银行'), ('600036', 1, '招商银行'),
            ('600519', 1, '贵州茅台'), ('000333', 0, '美的集团'), ('000651', 0, '格力电器'),
            ('002415', 0, '海康威视'), ('002475', 0, '立讯精密'), ('600276', 1, '恒瑞医药'),
            ('600030', 1, '中信证券'), ('000725', 0, '京东方A'), ('600050', 1, '中国联通'),
            ('601318', 1, '中国平安'), ('600887', 1, '伊利股份'),
        ]

        # 已提醒的股票（避免重复提醒）
        self.alerted_stocks = set()

        # 交易时间
        self.trading_hours = [
            ('09:30', '11:30'),  # 上午
            ('13:00', '15:00'),  # 下午
        ]

    def is_trading_time(self):
        """检查是否在交易时间"""
        now = datetime.now()
        current_time = now.strftime('%H:%M')

        for start, end in self.trading_hours:
            if start <= current_time <= end:
                return True
        return False

    def is_trading_day(self):
        """检查是否是交易日（简化版：周一到周五）"""
        now = datetime.now()
        return now.weekday() < 5  # 0-4 是周一到周五

    def get_30min_data(self, code, market):
        """获取30分钟K线数据"""
        try:
            # 获取最近100条30分钟数据
            data = self.core.api.get_security_bars(2, market, code, 0, 100)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 计算30分钟均线和指标
            df = self.calculate_indicators(df)

            return df

        except Exception as e:
            print(f"❌ 获取 {code} 数据失败: {e}")
            return None

    def calculate_indicators(self, df):
        """计算技术指标"""
        if len(df) < 3:
            return None

        # 30分钟均线
        df['ma3'] = df['close'].rolling(window=3).mean()
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['vol_ma3'] = df['vol'].rolling(window=3).mean()

        # MACD
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

    def send_alert(self, code, name, signals, current_price):
        """发送提醒"""
        now = datetime.now().strftime('%H:%M:%S')

        # 构建提醒消息
        message = f"\n{'='*80}\n"
        message += f"🚨 【买入提醒】{now}\n"
        message += f"{'='*80}\n"
        message += f"股票: {code} {name}\n"
        message += f"当前价格: {current_price:.2f} 元\n"
        message += f"\n📊 买入信号:\n"

        for i, signal in enumerate(signals, 1):
            message += f"   {i}. 【{signal['type']}】强度:{signal['strength']}\n"
            message += f"      {signal['desc']}\n"

        # 计算建议仓位（2%）
        initial_capital = self.config.get('account', 'initial_capital')
        suggested_vol = int(initial_capital * 0.02 / current_price / 100) * 100
        suggested_amount = suggested_vol * current_price

        message += f"\n💰 交易建议:\n"
        message += f"   建议买入: {suggested_vol} 股\n"
        message += f"   预计金额: {suggested_amount:,.2f} 元\n"
        message += f"   仓位占比: 约2%\n"
        message += f"{'='*80}\n"

        print(message)

        # 系统提醒
        self.system_alert(f"买入提醒: {code} {name}", f"价格: {current_price:.2f}元，信号: {len(signals)}个")

    def system_alert(self, title, message):
        """系统级提醒"""
        system = platform.system()

        try:
            if system == 'Darwin':  # macOS
                # 使用osascript发送通知
                os.system(f'''
                    osascript -e 'display notification "{message}" with title "{title}" sound name "Glass"'
                ''')
                # 同时播放提示音
                os.system('afplay /System/Library/Sounds/Glass.aiff')

            elif system == 'Windows':
                # Windows使用winsound
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                # 使用toast通知
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast(title, message, duration=10)
                except:
                    pass

            else:  # Linux
                # 使用notify-send
                os.system(f'notify-send "{title}" "{message}"')
                # 播放提示音
                print('\a')  # 蜂鸣声

        except Exception as e:
            print(f"⚠️ 系统提醒发送失败: {e}")
            print('\a')  # 备用蜂鸣声

    def scan_all_stocks(self):
        """扫描所有股票"""
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] 开始扫描 {len(self.stock_pool)} 只股票...")

        alerts = []

        for code, market, name in self.stock_pool:
            # 跳过已提醒的股票
            if code in self.alerted_stocks:
                continue

            df = self.get_30min_data(code, market)
            if df is None:
                continue

            signals = self.check_buy_signals(df, code, name)
            if signals:
                current_price = df.iloc[-1]['close']
                alerts.append({
                    'code': code,
                    'name': name,
                    'price': current_price,
                    'signals': signals
                })
                # 添加到已提醒集合
                self.alerted_stocks.add(code)

        if alerts:
            print(f"✅ 发现 {len(alerts)} 只股票的买入信号")
            for alert in alerts:
                self.send_alert(alert['code'], alert['name'], alert['signals'], alert['price'])
        else:
            print(f"⏳ 未发现买入信号")

        return len(alerts)

    def run_monitor(self, interval=60):
        """运行监控"""
        print("\n" + "="*80)
        print("📈 盘中实时监控系统启动")
        print("="*80)
        print(f"⏰ 监控间隔: {interval} 秒")
        print(f"📊 监控股票: {len(self.stock_pool)} 只")
        print(f"🎯 提醒策略: 30分钟均线突破 + MACD金叉 + 阳线放量")
        print(f"💡 提示: 按 Ctrl+C 停止监控")
        print("="*80)

        scan_count = 0

        try:
            while True:
                now = datetime.now()

                # 检查是否是交易日
                if not self.is_trading_day():
                    print(f"\n📅 {now.strftime('%Y-%m-%d')} 非交易日，监控暂停")
                    time.sleep(60)
                    continue

                # 检查是否在交易时间
                if not self.is_trading_time():
                    current_time = now.strftime('%H:%M')
                    print(f"\n⏰ 当前时间 {current_time} 非交易时间，监控暂停")
                    time.sleep(60)
                    continue

                # 执行扫描
                scan_count += 1
                print(f"\n{'='*80}")
                print(f"🔄 第 {scan_count} 次扫描 - {now.strftime('%H:%M:%S')}")
                print(f"{'='*80}")

                alert_count = self.scan_all_stocks()

                # 显示当前状态
                print(f"\n📊 当前状态:")
                print(f"   已提醒股票: {len(self.alerted_stocks)} 只")
                if self.alerted_stocks:
                    print(f"   列表: {', '.join(sorted(self.alerted_stocks))}")

                # 等待下一次扫描
                print(f"\n⏳ {interval}秒后再次扫描...")
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n" + "="*80)
            print("👋 监控已停止")
            print("="*80)
            print(f"📊 共扫描 {scan_count} 次")
            print(f"🚨 共提醒 {len(self.alerted_stocks)} 只股票")
            if self.alerted_stocks:
                print(f"   列表: {', '.join(sorted(self.alerted_stocks))}")
            print("="*80)

    def close(self):
        """关闭连接"""
        self.core.close()


if __name__ == "__main__":
    import sys

    config = ConfigLoader()
    monitor = RealtimeMonitor(config)

    # 支持命令行参数: python realtime_monitor.py [interval_seconds]
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    try:
        monitor.run_monitor(interval=interval)
    except Exception as e:
        print(f"❌ 监控出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        monitor.close()
