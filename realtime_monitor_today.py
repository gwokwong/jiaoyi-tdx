#!/usr/bin/env python3
"""
今天全天实时监控系统 - 从9:20开盘前到15:00收盘
"""

import pandas as pd
import numpy as np
import time
import os
import platform
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader


class TodayMonitor:
    """今天全天实时监控系统"""

    def __init__(self, config):
        self.config = config
        self.core = TradingCore(config)

        # 获取全市场股票池（不限制数量，获取全部5000+只）
        print("📥 正在加载全市场股票池...")
        self.stock_pool = self.core.get_all_stocks(limit=None)
        print(f"✅ 成功加载 {len(self.stock_pool)} 只股票")

        # 已提醒的股票（避免重复提醒）
        self.alerted_stocks = set()

        # 已买入的股票（模拟交易）
        self.bought_stocks = {}

        # 交易记录
        self.trade_history = []

        # 监控开始和结束时间
        self.start_time = '09:20'
        self.end_time = '15:00'

        # 扫描统计
        self.scanned_count = 0
        self.max_alerts_per_scan = 10  # 每次扫描最多提醒10只股票

    def is_monitoring_time(self):
        """检查是否在监控时间范围内"""
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        return self.start_time <= current_time <= self.end_time

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

            # 过滤无效日期数据（如2004-00-00）
            df = df[df['datetime'].str.match(r'^\d{4}-\d{2}-\d{2}')]
            if len(df) == 0:
                return None

            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 计算30分钟均线和指标
            df = self.calculate_indicators(df)

            return df

        except Exception as e:
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

        # 记录交易
        self.record_trade(code, name, current_price, suggested_vol, signals)

    def record_trade(self, code, name, price, vol, signals):
        """记录交易"""
        now = datetime.now()
        trade = {
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%H:%M:%S'),
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': price,
            'vol': vol,
            'amount': price * vol,
            'signals': [s['type'] for s in signals]
        }
        self.trade_history.append(trade)
        self.bought_stocks[code] = trade

    def system_alert(self, title, message):
        """系统级提醒"""
        system = platform.system()

        try:
            if system == 'Darwin':  # macOS
                os.system(f'''
                    osascript -e 'display notification "{message}" with title "{title}" sound name "Glass"'
                ''')
                os.system('afplay /System/Library/Sounds/Glass.aiff')

            elif system == 'Windows':
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast(title, message, duration=10)
                except:
                    pass

            else:  # Linux
                os.system(f'notify-send "{title}" "{message}"')
                print('\a')

        except Exception as e:
            print(f"⚠️ 系统提醒发送失败: {e}")
            print('\a')

    def scan_all_stocks(self):
        """扫描所有股票"""
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] 开始扫描 {len(self.stock_pool)} 只股票...")

        alerts = []
        scanned = 0
        errors = 0

        for code, market, name in self.stock_pool:
            # 跳过已提醒和已买入的股票
            if code in self.alerted_stocks or code in self.bought_stocks:
                continue

            # 如果已达到最大提醒数，停止扫描
            if len(alerts) >= self.max_alerts_per_scan:
                print(f"⏹️ 已达到最大提醒数 {self.max_alerts_per_scan}，停止扫描")
                break

            try:
                df = self.get_30min_data(code, market)
                scanned += 1

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
                    self.alerted_stocks.add(code)

                    # 打印进度
                    if len(alerts) % 5 == 0:
                        print(f"   已发现 {len(alerts)} 只信号股...")

            except Exception as e:
                errors += 1
                continue

        self.scanned_count += scanned

        print(f"✅ 扫描完成: {scanned} 只成功, {errors} 只失败")

        if alerts:
            print(f"🚨 共发现 {len(alerts)} 只股票的买入信号")
            for alert in alerts:
                self.send_alert(alert['code'], alert['name'], alert['signals'], alert['price'])
        else:
            print(f"⏳ 未发现买入信号")

        return len(alerts)

    def wait_until_start(self):
        """等待到开盘前9:20"""
        now = datetime.now()
        target = now.replace(hour=9, minute=20, second=0, microsecond=0)

        # 如果已经过了9:20，立即开始
        if now >= target:
            return

        wait_seconds = (target - now).total_seconds()
        print(f"\n⏰ 当前时间: {now.strftime('%H:%M:%S')}")
        print(f"⏰ 等待到开盘前 {self.start_time}...")
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

        print(f"\n🚀 到达开盘时间 {self.start_time}，开始监控！\n")

    def generate_daily_report(self):
        """生成今日交易报告"""
        now = datetime.now()
        print("\n" + "="*80)
        print(f"📊 今日交易报告 - {now.strftime('%Y-%m-%d')}")
        print("="*80)

        print(f"\n📈 监控统计:")
        print(f"   监控时长: {self.start_time} - {now.strftime('%H:%M:%S')}")
        print(f"   扫描次数: {self.scan_count} 次")
        print(f"   扫描股票: {self.scanned_count} 只")
        print(f"   股票池: {len(self.stock_pool)} 只")
        print(f"   提醒股票: {len(self.alerted_stocks)} 只")
        print(f"   买入股票: {len(self.bought_stocks)} 只")

        if self.trade_history:
            print(f"\n📝 今日买入记录:")
            print("-"*80)
            print(f"{'时间':<10} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<10} {'金额':<15} {'信号':<20}")
            print("-"*80)

            total_amount = 0
            for trade in self.trade_history:
                print(f"{trade['time']:<10} {trade['code']:<10} {trade['name']:<10} "
                      f"{trade['price']:<10.2f} {trade['vol']:<10} {trade['amount']:<15,.2f} "
                      f"{', '.join(trade['signals']):<20}")
                total_amount += trade['amount']

            print("-"*80)
            print(f"   总买入金额: {total_amount:,.2f} 元")
            print(f"   剩余资金: {self.config.get('account', 'initial_capital') - total_amount:,.2f} 元")

        print("\n" + "="*80)

    def run_today_monitor(self, interval=60):
        """运行今天全天监控"""
        print("\n" + "="*80)
        print("📈 今天全天实时监控系统")
        print("="*80)
        print(f"⏰ 监控时间: {self.start_time} - {self.end_time}")
        print(f"⏰ 扫描间隔: {interval} 秒")
        print(f"📊 监控股票: {len(self.stock_pool)} 只")
        print(f"🎯 提醒策略: 30分钟均线突破 + MACD金叉 + 阳线放量")
        print(f"💡 提示: 按 Ctrl+C 停止监控")
        print("="*80)

        # 检查是否是交易日
        if not self.is_trading_day():
            print(f"\n📅 今天不是交易日，监控结束")
            return

        # 等待到开盘前9:20
        self.wait_until_start()

        # 开始监控
        self.scan_count = 0

        try:
            while True:
                now = datetime.now()
                current_time = now.strftime('%H:%M')

                # 检查是否到达收盘时间
                if current_time >= self.end_time:
                    print(f"\n🏁 到达收盘时间 {self.end_time}，监控结束")
                    break

                # 执行扫描
                self.scan_count += 1
                print(f"\n{'='*80}")
                print(f"🔄 第 {self.scan_count} 次扫描 - {now.strftime('%H:%M:%S')}")
                print(f"{'='*80}")

                alert_count = self.scan_all_stocks()

                # 显示当前状态
                print(f"\n📊 当前状态:")
                print(f"   已提醒: {len(self.alerted_stocks)} 只")
                print(f"   已买入: {len(self.bought_stocks)} 只")
                if self.bought_stocks:
                    print(f"   买入列表: {', '.join(self.bought_stocks.keys())}")

                # 计算剩余时间
                end = now.replace(hour=15, minute=0, second=0, microsecond=0)
                remaining = (end - now).total_seconds()
                if remaining > 0:
                    remaining_min = int(remaining / 60)
                    print(f"\n⏰ 距离收盘还有: {remaining_min} 分钟")

                # 等待下一次扫描
                print(f"\n⏳ {interval}秒后再次扫描...")
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n" + "="*80)
            print("👋 监控已手动停止")
            print("="*80)

        finally:
            # 生成今日报告
            self.generate_daily_report()

    def close(self):
        """关闭连接"""
        self.core.close()


if __name__ == "__main__":
    import sys

    config = ConfigLoader()
    monitor = TodayMonitor(config)

    # 支持命令行参数: python realtime_monitor_today.py [interval_seconds]
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    try:
        monitor.run_today_monitor(interval=interval)
    except Exception as e:
        print(f"❌ 监控出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        monitor.close()
