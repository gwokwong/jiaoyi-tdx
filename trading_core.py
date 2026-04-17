#!/usr/bin/env python3
"""
统一交易核心模块
包含五大买入策略和五大卖出策略
回测和实盘共用此模块
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pytdx.hq import TdxHq_API
from core import ConfigLoader


class TradingCore:
    """
    交易核心类
    统一处理选股、买入、卖出策略
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        # 连接服务器
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if not self.api.connect(ip, port):
            raise Exception("连接服务器失败")

        # 风控参数
        self.max_single_position = 0.02  # 单票最大2%
        self.max_total_position = 0.50   # 总仓位最大50%
        self.max_positions = 60          # 最大持仓数
        self.stop_loss = -0.05           # 止损5%
        self.take_profit = 0.10          # 止盈10%

        print(f"✅ 交易核心初始化完成")

    def get_history_data(self, code, market, days=60):
        """获取历史K线数据"""
        try:
            data = self.api.get_security_bars(4, market, code, 0, days)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['datetime'])
            df.set_index('date', inplace=True)

            # 统一列名
            df.rename(columns={
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'vol': 'volume',
                'amount': 'amount'
            }, inplace=True)

            return df
        except Exception as e:
            return None

    def calculate_indicators(self, df):
        """计算技术指标"""
        if df is None or len(df) < 30:
            return None

        # 移动平均线
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = (df['dif'] - df['dea']) * 2

        # 成交量均线
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()

        return df

    # ==================== 五大买入策略 ====================

    def check_strategy_1_breakout(self, df):
        """
        策略1: 放量突破
        条件: 阳线 + 涨幅≥1% + 量比≥1.2
        """
        if len(df) < 5:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        is_yang = latest['close'] > latest['open']
        change_pct = (latest['close'] - prev['close']) / prev['close'] * 100
        vol_ratio = latest['volume'] / latest['vol_ma5'] if latest['vol_ma5'] > 0 else 0

        if is_yang and change_pct >= 1.0 and vol_ratio >= 1.2:
            return {
                'signal': True,
                'strategy': '策略1_放量突破',
                'reason': f'阳线上涨{change_pct:.1f}%，放量{vol_ratio:.1f}倍',
                'score': 3
            }
        return None

    def check_strategy_2_ma_bull(self, df):
        """
        策略2: 均线多头排列
        条件: MA5>MA10>MA20 且 股价在MA5上方
        """
        latest = df.iloc[-1]

        if latest['ma5'] > latest['ma10'] > latest['ma20'] and latest['close'] > latest['ma5']:
            return {
                'signal': True,
                'strategy': '策略2_均线多头',
                'reason': '5/10/20日均线多头排列，股价在MA5上方',
                'score': 2
            }
        return None

    def check_strategy_3_macd_gold(self, df):
        """
        策略3: MACD金叉
        条件: DIF上穿DEA 且 MACD柱状线为正
        """
        if len(df) < 2:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        macd_cross = (prev['dif'] <= prev['dea']) and (latest['dif'] > latest['dea'])

        if macd_cross and latest['macd'] > 0:
            return {
                'signal': True,
                'strategy': '策略3_MACD金叉',
                'reason': 'DIF上穿DEA，MACD柱状线为正',
                'score': 3
            }
        return None

    def check_strategy_4_rebound(self, df):
        """
        策略4: 超跌反弹（黄金坑简化版）
        条件: 近5日跌幅>5% 且 今日阳线反弹
        """
        if len(df) < 6:
            return None

        recent_5 = df.iloc[-6:-1]
        recent_change = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0] * 100

        latest = df.iloc[-1]
        is_yang = latest['close'] > latest['open']
        change_pct = (latest['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close'] * 100

        if recent_change < -5 and is_yang and change_pct > 0.5:
            return {
                'signal': True,
                'strategy': '策略4_超跌反弹',
                'reason': f'近5日下跌{abs(recent_change):.1f}%，今日反弹{change_pct:.1f}%',
                'score': 2
            }
        return None

    def check_strategy_5_high_break(self, df):
        """
        策略5: 创新高回踩
        条件: 股价接近20日新高 且 今日阳线
        """
        if len(df) < 20:
            return None

        high_20 = df['high'].iloc[-20:-1].max()
        latest = df.iloc[-1]

        near_high = latest['close'] > high_20 * 0.98 and latest['close'] < high_20 * 1.02
        is_yang = latest['close'] > latest['open']

        if near_high and is_yang:
            return {
                'signal': True,
                'strategy': '策略5_接近新高',
                'reason': '股价接近20日新高，今日阳线',
                'score': 2
            }
        return None

    def check_buy_signals(self, df):
        """
        检查所有买入策略
        返回得分最高的策略
        """
        if df is None or len(df) < 30:
            return None

        df = self.calculate_indicators(df)
        if df is None:
            return None

        strategies = []

        s1 = self.check_strategy_1_breakout(df)
        if s1: strategies.append(s1)

        s2 = self.check_strategy_2_ma_bull(df)
        if s2: strategies.append(s2)

        s3 = self.check_strategy_3_macd_gold(df)
        if s3: strategies.append(s3)

        s4 = self.check_strategy_4_rebound(df)
        if s4: strategies.append(s4)

        s5 = self.check_strategy_5_high_break(df)
        if s5: strategies.append(s5)

        if strategies:
            # 返回得分最高的策略
            best = max(strategies, key=lambda x: x['score'])
            best['all_strategies'] = [s['strategy'] for s in strategies]
            return best

        return None

    # ==================== 五大卖出策略 ====================

    def check_sell_stop_loss_profit(self, buy_price, current_price):
        """
        卖出原则1: 止盈止损
        """
        pnl_pct = (current_price - buy_price) / buy_price

        if pnl_pct <= self.stop_loss:
            return ('止损', f'亏损达到{pnl_pct*100:.1f}%')
        elif pnl_pct >= self.take_profit:
            return ('止盈', f'盈利达到{pnl_pct*100:.1f}%')
        return None

    def check_sell_support_break(self, df):
        """
        卖出原则6: 跌破关键支撑线（20日均线）
        """
        if len(df) < 2:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        break_down = latest['close'] < latest['ma20'] * 0.995
        was_above = prev['close'] > prev['ma20']

        if break_down and was_above:
            return ('跌破支撑', '收盘价跌破20日均线')
        return None

    def check_sell_macd_divergence(self, df):
        """
        卖出原则8: MACD顶背离
        """
        if len(df) < 30:
            return None

        recent = df.iloc[-30:]
        price_high = recent['high'].max()
        latest = df.iloc[-1]

        if latest['close'] < price_high * 0.98:
            return None

        high_idx = recent['high'].idxmax()
        macd_at_high = df.loc[high_idx, 'dif']

        if latest['dif'] < macd_at_high * 0.95:
            return ('MACD顶背离', '价格新高但MACD未新高')
        return None

    def check_sell_ma_bearish(self, df):
        """
        卖出原则9: 均线空头排列
        """
        latest = df.iloc[-1]

        bearish = latest['ma5'] < latest['ma10'] < latest['ma20']
        if not bearish:
            return None

        recent_3 = df.iloc[-3:]
        below_ma20 = all(recent_3['close'] < recent_3['ma20'])

        if below_ma20:
            return ('空头排列', '均线空头排列且股价在20日线下方')
        return None

    def check_sell_signals(self, buy_price, df):
        """
        检查所有卖出信号
        返回第一个触发的信号
        """
        if df is None or len(df) < 2:
            return None

        df = self.calculate_indicators(df)
        if df is None:
            return None

        latest = df.iloc[-1]
        current_price = latest['close']

        sell_signals = []

        # 1. 止盈止损
        s1 = self.check_sell_stop_loss_profit(buy_price, current_price)
        if s1: sell_signals.append(s1)

        # 2. 跌破支撑
        s2 = self.check_sell_support_break(df)
        if s2: sell_signals.append(s2)

        # 3. MACD顶背离
        s3 = self.check_sell_macd_divergence(df)
        if s3: sell_signals.append(s3)

        # 4. 空头排列
        s4 = self.check_sell_ma_bearish(df)
        if s4: sell_signals.append(s4)

        return sell_signals[0] if sell_signals else None

    # ==================== 股票池管理 ====================

    def get_all_stocks(self, limit=None):
        """
        获取A股所有股票
        返回: [(code, market, name), ...]
        """
        stocks = []
        print("📥 正在获取A股股票列表...")

        try:
            # 上海市场
            sh_count = self.api.get_security_count(1)
            print(f"   上海市场共 {sh_count} 只股票")
            sh_limit = min(sh_count, limit) if limit else sh_count
            for start in range(0, sh_limit, 1000):
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if code.startswith('6') and len(code) == 6:
                            stocks.append((code, 1, name))

            # 深圳市场
            sz_count = self.api.get_security_count(0)
            print(f"   深圳市场共 {sz_count} 只股票")
            sz_limit = min(sz_count, limit) if limit else sz_count
            for start in range(0, sz_limit, 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            stocks.append((code, 0, name))

        except Exception as e:
            print(f"   获取失败: {e}")

        print(f"✅ 成功获取 {len(stocks)} 只股票")
        return stocks

    def close(self):
        """关闭连接"""
        self.api.disconnect()


if __name__ == "__main__":
    # 测试核心模块
    config = ConfigLoader()
    core = TradingCore(config)

    print("\n" + "="*80)
    print("测试买入策略")
    print("="*80)

    # 测试单只股票
    df = core.get_history_data('000001', 0, days=60)
    if df is not None:
        signal = core.check_buy_signals(df)
        if signal:
            print(f"✅ 买入信号: {signal['strategy']}")
            print(f"   原因: {signal['reason']}")
        else:
            print("❌ 无买入信号")

    print("\n" + "="*80)
    print("测试卖出策略")
    print("="*80)

    # 模拟持仓
    buy_price = 10.0
    sell_signal = core.check_sell_signals(buy_price, df)
    if sell_signal:
        print(f"🔴 卖出信号: {sell_signal[0]}")
        print(f"   原因: {sell_signal[1]}")
    else:
        print("✅ 无卖出信号")

    core.close()
