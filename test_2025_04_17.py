#!/usr/bin/env python3
"""
测试2025年4月17日盘中交易
使用实时选股策略进行单日回测
"""

import pandas as pd
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


class Test20250417:
    """测试2025年4月17日交易"""

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

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital', default=100000.0)
        self.cash = self.initial_capital
        self.positions = {}
        self.trade_history = []

        # 风控参数
        self.max_positions = config.get('risk', 'max_positions', default=5)
        self.max_buys_per_day = config.get('risk', 'max_buys_per_day', default=3)
        self.stop_loss = config.get('strategy', 'stop_loss_rate', default=-0.05)
        self.take_profit = config.get('strategy', 'take_profit_rate', default=0.10)

        self.buy_count = 0

    def get_market_type(self, code):
        """判断市场类型"""
        if code.startswith('6'):
            return 1
        return 0

    def get_stock_pool(self, limit=50):
        """获取股票池"""
        stocks = []
        try:
            # 上海市场
            for start in range(0, min(500, limit), 1000):
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk[:limit//2]:
                        code = item['code']
                        name = item.get('name', code)
                        if code.startswith('6') and len(code) == 6:
                            stocks.append((code, 1, name))

            # 深圳市场
            for start in range(0, min(500, limit), 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk[:limit//2]:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            stocks.append((code, 0, name))
        except Exception as e:
            print(f"获取股票池失败: {e}")

        return stocks[:limit]

    def get_day_data(self, code, market, date_str):
        """获取指定日期的日线数据"""
        try:
            # 获取最近60天的数据
            data = self.api.get_security_bars(4, market, code, 0, 60)
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

    def get_history_bars(self, code, market, days=20):
        """获取历史K线用于计算指标"""
        try:
            data = self.api.get_security_bars(4, market, code, 0, days)
            if not data or len(data) < 5:
                return None

            bars = []
            for item in data:
                bars.append({
                    'datetime': item['datetime'],
                    'open': item['open'],
                    'high': item['high'],
                    'low': item['low'],
                    'close': item['close'],
                    'volume': item['vol']
                })
            return bars
        except:
            return None

    def calculate_indicators(self, bars):
        """计算技术指标"""
        if not bars or len(bars) < 5:
            return None

        closes = [b['close'] for b in bars]
        volumes = [b['volume'] for b in bars]

        latest = bars[-1]
        prev = bars[-2] if len(bars) >= 2 else latest

        # 移动平均线
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else ma5
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma10

        # 成交量均线
        vol_ma5 = sum(volumes[-5:]) / 5

        # 涨跌幅
        change_pct = (latest['close'] - prev['close']) / prev['close'] * 100 if prev['close'] > 0 else 0

        # 量比
        vol_ratio = latest['volume'] / vol_ma5 if vol_ma5 > 0 else 0

        # 是否阳线
        is_yang = latest['close'] > latest['open']

        # 20日高低点
        high_20 = max(b['high'] for b in bars[-20:]) if len(bars) >= 20 else max(b['high'] for b in bars)
        low_20 = min(b['low'] for b in bars[-20:]) if len(bars) >= 20 else min(b['low'] for b in bars)

        return {
            'latest': latest,
            'prev': prev,
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'change_pct': change_pct,
            'vol_ratio': vol_ratio,
            'is_yang': is_yang,
            'high_20': high_20,
            'low_20': low_20
        }

    def check_buy_signal(self, indicators):
        """检查买入信号"""
        if not indicators:
            return None

        ind = indicators
        price = ind['latest']['close']

        # 价格过滤
        if price < 2 or price > 500:
            return None

        signals = []

        # 策略1: 放量突破
        if ind['is_yang'] and ind['change_pct'] >= 1.0 and ind['vol_ratio'] >= 1.2:
            signals.append({
                'type': '放量突破',
                'score': 3,
                'reason': f"阳线上涨{ind['change_pct']:.1f}%，放量{ind['vol_ratio']:.1f}倍"
            })

        # 策略2: 均线多头
        if ind['ma5'] > ind['ma10'] > ind['ma20'] and price > ind['ma5']:
            signals.append({
                'type': '均线多头',
                'score': 2,
                'reason': "5/10/20日均线多头排列"
            })

        # 策略3: 接近新高
        if price > ind['high_20'] * 0.98 and ind['is_yang']:
            signals.append({
                'type': '接近新高',
                'score': 2,
                'reason': f"股价接近20日新高{ind['high_20']:.2f}"
            })

        if signals:
            # 返回得分最高的
            best = max(signals, key=lambda x: x['score'])
            return best

        return None

    def can_buy(self, code, price, vol):
        """检查是否可以买入"""
        if code in self.positions:
            return False

        if len(self.positions) >= self.max_positions:
            return False

        if self.buy_count >= self.max_buys_per_day:
            return False

        cost = price * vol
        fee = cost * self.config.get('fees', 'commission_rate', default=0.00025)

        if self.cash < cost + fee:
            return False

        return True

    def execute_buy(self, code, name, price, vol, signal_info, date_str):
        """执行买入"""
        cost = price * vol
        commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
        min_commission = self.config.get('fees', 'min_commission', default=5.0)
        fee = max(cost * commission_rate, min_commission)

        if self.cash < cost + fee:
            return False

        self.cash -= (cost + fee)
        self.positions[code] = {
            'code': code,
            'name': name,
            'vol': vol,
            'buy_price': price,
            'cost': cost,
            'fee': fee
        }

        self.trade_history.append({
            'date': date_str,
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': price,
            'vol': vol,
            'amount': cost,
            'fee': fee,
            'signal_type': signal_info['type'],
            'reason': signal_info['reason']
        })

        self.buy_count += 1

        # 保存到数据库
        self.db.save_trade(code, 'BUY', price, vol, commission_rate, 0)

        print(f"\n   🟢 【买入】{code} {name}")
        print(f"      价格: {price:.2f}元 x {vol}股 = {cost:,.2f}元")
        print(f"      手续费: {fee:.2f}元")
        print(f"      策略: {signal_info['type']} - {signal_info['reason']}")

        return True

    def check_and_sell_positions(self, date_str):
        """检查持仓并执行卖出"""
        if not self.positions:
            return

        print(f"\n📊 检查 {len(self.positions)} 只持仓的卖出条件...")

        for code, pos in list(self.positions.items()):
            market = self.get_market_type(code)
            day_data = self.get_day_data(code, market, date_str)

            if not day_data:
                continue

            current_price = day_data['close']
            buy_price = pos['buy_price']
            pnl_pct = (current_price - buy_price) / buy_price

            # 检查止损止盈
            sell_reason = None
            if pnl_pct <= self.stop_loss:
                sell_reason = ('止损', f'亏损{pnl_pct*100:.1f}%')
            elif pnl_pct >= self.take_profit:
                sell_reason = ('止盈', f'盈利{pnl_pct*100:.1f}%')

            if sell_reason:
                self.execute_sell(code, pos, current_price, sell_reason[0], sell_reason[1], date_str)

    def execute_sell(self, code, pos, price, action_type, reason, date_str):
        """执行卖出"""
        vol = pos['vol']
        income = price * vol

        commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
        min_commission = self.config.get('fees', 'min_commission', default=5.0)
        stamp_duty_rate = self.config.get('fees', 'stamp_duty_rate', default=0.001)

        comm = max(income * commission_rate, min_commission)
        tax = income * stamp_duty_rate
        total_fee = comm + tax

        self.cash += (income - total_fee)

        profit = income - pos['cost'] - total_fee - pos['fee']
        pnl_pct = (price - pos['buy_price']) / pos['buy_price'] * 100

        self.trade_history.append({
            'date': date_str,
            'code': code,
            'name': pos['name'],
            'action': 'SELL',
            'price': price,
            'vol': vol,
            'amount': income,
            'fee': total_fee,
            'profit': profit,
            'pnl_pct': pnl_pct,
            'type': action_type,
            'reason': reason
        })

        # 保存到数据库
        self.db.save_trade(code, 'SELL', price, vol, commission_rate, stamp_duty_rate)

        print(f"\n   🔴 【卖出】{code} {pos['name']}")
        print(f"      价格: {price:.2f}元 (买入: {pos['buy_price']:.2f}元)")
        print(f"      盈亏: {profit:+.2f}元 ({pnl_pct:+.2f}%)")
        print(f"      原因: {action_type} - {reason}")

        del self.positions[code]

    def run_test(self, date_str='2025-04-17'):
        """运行测试"""
        print("\n" + "="*80)
        print(f"📅 测试日期: {date_str}")
        print(f"💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📋 最大持仓: {self.max_positions} 只")
        print(f"📈 每日最多买入: {self.max_buys_per_day} 次")
        print("="*80)

        # 获取股票池
        print("\n📥 正在获取股票池...")
        stock_pool = self.get_stock_pool(limit=50)
        print(f"✅ 获取到 {len(stock_pool)} 只股票")

        # 第一步：检查是否有持仓需要卖出
        self.check_and_sell_positions(date_str)

        # 第二步：扫描买入机会
        print(f"\n🔍 正在扫描买入机会...")
        candidates = []

        for i, (code, market, name) in enumerate(stock_pool):
            # 跳过已持仓
            if code in self.positions:
                continue

            # 获取历史数据
            bars = self.get_history_bars(code, market, days=20)
            if not bars:
                continue

            # 获取当日数据
            day_data = self.get_day_data(code, market, date_str)
            if not day_data:
                continue

            # 计算指标
            indicators = self.calculate_indicators(bars)
            if not indicators:
                continue

            # 检查买入信号
            signal = self.check_buy_signal(indicators)
            if signal:
                candidates.append({
                    'code': code,
                    'name': name,
                    'market': market,
                    'price': day_data['close'],
                    'signal': signal,
                    'change_pct': indicators['change_pct'],
                    'vol_ratio': indicators['vol_ratio']
                })

                print(f"   📈 发现信号: {code} {name} | {signal['type']} | {signal['reason']}")

        # 按得分排序
        if candidates:
            candidates.sort(key=lambda x: x['signal']['score'], reverse=True)

            print(f"\n🎯 共发现 {len(candidates)} 个买入信号")
            print(f"\n前5个最佳候选:")
            for i, c in enumerate(candidates[:5], 1):
                print(f"   {i}. {c['code']} {c['name']} - {c['signal']['type']} (得分:{c['signal']['score']})")

            # 执行买入（前3个）
            print(f"\n💰 开始执行买入...")
            for candidate in candidates[:3]:
                if self.buy_count >= self.max_buys_per_day:
                    print(f"   ⚠️ 已达到每日最大买入次数 {self.max_buys_per_day}")
                    break

                if len(self.positions) >= self.max_positions:
                    print(f"   ⚠️ 已达到最大持仓数 {self.max_positions}")
                    break

                code = candidate['code']
                price = candidate['price']

                # 计算买入数量（单票10%仓位）
                position_value = self.initial_capital * 0.10
                vol = int(position_value / price / 100) * 100

                if vol < 100:
                    print(f"   ⚠️ {code} 计算数量不足100股，跳过")
                    continue

                if self.can_buy(code, price, vol):
                    self.execute_buy(code, candidate['name'], price, vol, candidate['signal'], date_str)
        else:
            print(f"\n📭 未发现买入信号")

        # 生成报告
        self.generate_report(date_str)

    def generate_report(self, date_str):
        """生成测试报告"""
        print("\n" + "="*80)
        print(f"📊 {date_str} 测试报告")
        print("="*80)

        # 计算持仓市值
        position_value = 0
        unrealized_pnl = 0

        for code, pos in self.positions.items():
            market = self.get_market_type(code)
            day_data = self.get_day_data(code, market, date_str)
            if day_data:
                current_price = day_data['close']
                market_value = pos['vol'] * current_price
                cost_value = pos['vol'] * pos['buy_price']
                position_value += market_value
                unrealized_pnl += (market_value - cost_value)

        total_value = self.cash + position_value
        total_pnl = total_value - self.initial_capital
        total_return = total_pnl / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   现金余额: {self.cash:,.2f} 元")
        print(f"   持仓市值: {position_value:,.2f} 元")
        print(f"   总资产:   {total_value:,.2f} 元")
        print(f"   当日盈亏: {total_pnl:+.2f} 元 ({total_return:+.2f}%)")
        print(f"   浮动盈亏: {unrealized_pnl:+.2f} 元")

        # 交易统计
        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   买入次数: {len(buy_trades)}")
        print(f"   卖出次数: {len(sell_trades)}")

        if sell_trades:
            profits = [t['profit'] for t in sell_trades]
            win_count = len([p for p in profits if p > 0])
            loss_count = len([p for p in profits if p < 0])
            win_rate = win_count / len(profits) * 100 if profits else 0

            print(f"   盈利次数: {win_count}")
            print(f"   亏损次数: {loss_count}")
            print(f"   胜率: {win_rate:.1f}%")
            print(f"   总实现盈亏: {sum(profits):+.2f} 元")

        # 持仓明细
        if self.positions:
            print(f"\n📋 当前持仓 ({len(self.positions)} 只):")
            for code, pos in self.positions.items():
                market = self.get_market_type(code)
                day_data = self.get_day_data(code, market, date_str)
                if day_data:
                    current_price = day_data['close']
                    pnl_pct = (current_price - pos['buy_price']) / pos['buy_price'] * 100
                    print(f"   {code} {pos['name']}: {pos['vol']}股 @ {pos['buy_price']:.2f}元 (现价:{current_price:.2f}元, 盈亏:{pnl_pct:+.2f}%)")

        # 交易明细
        if self.trade_history:
            print(f"\n📝 交易明细:")
            print("-"*80)
            print(f"{'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<10} {'盈亏':<12} {'原因'}")
            print("-"*80)

            for t in self.trade_history:
                if t['action'] == 'SELL':
                    pnl_str = f"{t['profit']:+.2f}"
                    reason = f"{t['type']} - {t['reason']}"
                else:
                    pnl_str = "--"
                    reason = f"{t['signal_type']} - {t['reason']}"

                print(f"{t['action']:<6} {t['code']:<10} {t['name']:<10} {t['price']:<10.2f} {t['vol']:<10} {pnl_str:<12} {reason}")

            print("-"*80)

        print("="*80)

    def close(self):
        """关闭连接"""
        self.api.disconnect()
        self.db.close()


if __name__ == "__main__":
    import sys

    # 获取日期参数，默认2025-04-17
    date_str = sys.argv[1] if len(sys.argv) > 1 else '2025-04-17'

    config = ConfigLoader()
    tester = Test20250417(config)

    try:
        tester.run_test(date_str)
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tester.close()
