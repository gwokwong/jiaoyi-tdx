#!/usr/bin/env python3
"""
尾盘选股系统 - 基于全网最流行的量价关系指标
每天2:30后用来尾盘选股买入
支持指定日期回测历史数据
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_core import TradingCore
from core import ConfigLoader


class AfternoonStockPicker:
    """尾盘选股系统 - 基于量价关系"""

    def __init__(self, config, target_date=None):
        self.config = config
        self.core = TradingCore(config)

        # 设置目标日期（用于回测）
        self.target_date = target_date
        if target_date:
            self.target_datetime = pd.to_datetime(target_date)
            print(f"📅 回测模式：选股日期 {target_date}")
        else:
            self.target_datetime = None
            print(f"📅 实时模式：选股日期 {datetime.now().strftime('%Y-%m-%d')}")

        # 获取全市场股票池（不限制数量，获取全部5000+只）
        print("📥 正在加载全市场股票池...")
        self.stock_pool = self.core.get_all_stocks(limit=None)
        print(f"✅ 成功加载 {len(self.stock_pool)} 只股票")

    def get_day_data(self, code, market, days=20):
        """获取日线数据，支持指定日期回测"""
        try:
            # 获取更多天数的数据以便筛选
            data = self.core.api.get_security_bars(9, market, code, 0, days)
            if not data:
                return None

            df = pd.DataFrame(data)
            df = df[df['datetime'].str.match(r'^\d{4}-\d{2}-\d{2}')]
            if len(df) == 0:
                return None

            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 如果指定了目标日期，筛选到该日期的数据
            if self.target_datetime:
                df = df[df.index <= self.target_datetime]
                if len(df) < 5:
                    return None

            return df

        except Exception as e:
            return None

    def get_30min_data(self, code, market):
        """获取30分钟K线数据，支持指定日期回测"""
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

            # 如果指定了目标日期，筛选到该日期的数据
            if self.target_datetime:
                df = df[df.index <= self.target_datetime + pd.Timedelta(days=1)]
                # 只保留目标日期的数据
                df = df[df.index.date == self.target_datetime.date()]
                if len(df) < 4:
                    return None

            return df

        except Exception as e:
            return None

    def calculate_volume_price_indicators(self, df_day, df_30min):
        """计算量价关系指标"""
        if df_day is None or len(df_day) < 3:
            return None

        indicators = {}

        # 最新日线数据
        latest_day = df_day.iloc[-1]
        prev_day = df_day.iloc[-2] if len(df_day) >= 2 else None

        # 1. 量价齐升（最经典的多头信号）
        price_change = (latest_day['close'] - latest_day['open']) / latest_day['open'] * 100
        vol_ratio = latest_day['vol'] / df_day['vol'].mean()

        indicators['量价齐升'] = {
            'trigger': price_change > 2 and vol_ratio > 1.5,
            'score': min(price_change * vol_ratio, 100),
            'desc': f'涨幅{price_change:.2f}%，量比{vol_ratio:.2f}',
            'strength': '强' if price_change > 4 and vol_ratio > 2 else '中'
        }

        # 2. 缩量回调（洗盘结束信号）
        if prev_day is not None:
            price_drop = (latest_day['close'] - prev_day['close']) / prev_day['close'] * 100
            vol_shrink = latest_day['vol'] / prev_day['vol']

            indicators['缩量回调'] = {
                'trigger': -3 < price_drop < 0 and vol_shrink < 0.7,
                'score': 80 if vol_shrink < 0.5 else 60,
                'desc': f'跌幅{price_drop:.2f}%，缩量至{vol_shrink*100:.0f}%',
                'strength': '强' if vol_shrink < 0.5 else '中'
            }

        # 3. 放量突破（关键位置突破）
        if len(df_day) >= 5:
            high_5day = df_day['high'].iloc[-5:-1].max()
            breakout = latest_day['close'] > high_5day
            vol_increase = latest_day['vol'] > df_day['vol'].iloc[-5:-1].mean() * 1.3

            indicators['放量突破'] = {
                'trigger': breakout and vol_increase,
                'score': 90 if breakout and latest_day['vol'] > df_day['vol'].mean() * 2 else 70,
                'desc': f'突破5日高点，量比{latest_day["vol"] / df_day["vol"].mean():.2f}',
                'strength': '强' if latest_day['vol'] > df_day['vol'].mean() * 2 else '中'
            }

        # 4. 尾盘放量（资金抢筹）
        if df_30min is not None and len(df_30min) >= 4:
            # 取最后4个30分钟（下午2小时）
            afternoon = df_30min.iloc[-4:]
            afternoon_vol = afternoon['vol'].sum()
            morning_vol = df_30min.iloc[:-4]['vol'].sum() if len(df_30min) > 4 else afternoon_vol

            if morning_vol > 0:
                afternoon_ratio = afternoon_vol / morning_vol
                price_trend = (afternoon['close'].iloc[-1] - afternoon['open'].iloc[0]) / afternoon['open'].iloc[0] * 100

                indicators['尾盘放量'] = {
                    'trigger': afternoon_ratio > 0.6 and price_trend > 0.5,
                    'score': min(afternoon_ratio * 100, 100),
                    'desc': f'下午成交量占比{afternoon_ratio*100:.0f}%，涨幅{price_trend:.2f}%',
                    'strength': '强' if afternoon_ratio > 0.8 else '中'
                }

        # 5. 量价背离（底部反转）
        if len(df_day) >= 3:
            price_trend = (latest_day['close'] - df_day['close'].iloc[-3]) / df_day['close'].iloc[-3] * 100
            vol_trend = (latest_day['vol'] - df_day['vol'].iloc[-3]) / df_day['vol'].iloc[-3] * 100

            indicators['底部量价背离'] = {
                'trigger': price_trend < -2 and vol_trend > 20,
                'score': 75,
                'desc': f'价格下跌{price_trend:.2f}%但放量{vol_trend:.0f}%',
                'strength': '中'
            }

        # 6. 涨停回调（强势股二次上车）
        if prev_day is not None:
            prev_limit_up = prev_day['close'] >= prev_day['open'] * 1.095  # 接近涨停
            today_pullback = (latest_day['close'] - prev_day['close']) / prev_day['close'] * 100

            indicators['涨停回调'] = {
                'trigger': prev_limit_up and -2 < today_pullback < 2,
                'score': 85,
                'desc': f'昨日涨停，今日回调{today_pullback:.2f}%',
                'strength': '强'
            }

        # 7. 均量线金叉（量能持续）
        if len(df_day) >= 5:
            vol_ma5 = df_day['vol'].iloc[-5:].mean()
            vol_ma10 = df_day['vol'].iloc[-10:].mean() if len(df_day) >= 10 else vol_ma5

            indicators['均量线金叉'] = {
                'trigger': vol_ma5 > vol_ma10 * 1.1 and latest_day['vol'] > vol_ma5,
                'score': 70,
                'desc': f'5日均量{vol_ma5/10000:.0f}万 > 10日均量{vol_ma10/10000:.0f}万',
                'strength': '中'
            }

        return indicators

    def calculate_technical_indicators(self, df_day):
        """计算技术指标"""
        if df_day is None or len(df_day) < 5:
            return None

        indicators = {}

        # 计算均线
        df_day['ma5'] = df_day['close'].rolling(window=5).mean()
        df_day['ma10'] = df_day['close'].rolling(window=10).mean()
        df_day['ma20'] = df_day['close'].rolling(window=20).mean()

        latest = df_day.iloc[-1]

        # 均线多头排列
        indicators['均线多头排列'] = {
            'trigger': latest['close'] > latest['ma5'] > latest['ma10'],
            'score': 80,
            'desc': f'收盘价{latest["close"]:.2f} > MA5{latest["ma5"]:.2f} > MA10{latest["ma10"]:.2f}',
            'strength': '强'
        }

        # MACD
        ema12 = df_day['close'].ewm(span=12, adjust=False).mean()
        ema26 = df_day['close'].ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2

        macd_cross = dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]

        indicators['MACD金叉'] = {
            'trigger': macd_cross,
            'score': 85,
            'desc': f'DIF上穿DEA，MACD={macd.iloc[-1]:.2f}',
            'strength': '强' if macd.iloc[-1] > 0 else '中'
        }

        return indicators

    def analyze_stock(self, code, market, name):
        """分析单只股票"""
        # 获取数据
        df_day = self.get_day_data(code, market, days=20)
        df_30min = self.get_30min_data(code, market)

        if df_day is None or len(df_day) < 5:
            return None

        # 计算指标
        vp_indicators = self.calculate_volume_price_indicators(df_day, df_30min)
        tech_indicators = self.calculate_technical_indicators(df_day)

        if not vp_indicators:
            return None

        # 综合评分
        total_score = 0
        triggered_signals = []

        for name_ind, ind in vp_indicators.items():
            if ind['trigger']:
                total_score += ind['score']
                triggered_signals.append({
                    'name': name_ind,
                    'score': ind['score'],
                    'desc': ind['desc'],
                    'strength': ind['strength']
                })

        if tech_indicators:
            for name_ind, ind in tech_indicators.items():
                if ind['trigger']:
                    total_score += ind['score']
                    triggered_signals.append({
                        'name': name_ind,
                        'score': ind['score'],
                        'desc': ind['desc'],
                        'strength': ind['strength']
                    })

        if not triggered_signals:
            return None

        # 获取当前价格
        current_price = df_day.iloc[-1]['close']

        # 计算买入点位建议
        buy_point = self.calculate_buy_point(df_day, current_price)

        return {
            'code': code,
            'name': name,
            'price': current_price,
            'score': total_score,
            'signals': triggered_signals,
            'buy_point': buy_point,
            'day_data': df_day
        }

    def calculate_buy_point(self, df_day, current_price):
        """计算买入点位建议"""
        latest = df_day.iloc[-1]

        # 计算支撑位和压力位
        support = df_day['low'].iloc[-5:].min()
        resistance = df_day['high'].iloc[-5:].max()

        # 计算建议买入价
        if current_price < support * 1.02:
            # 接近支撑位，可以买入
            suggested_price = current_price
            reason = f"价格接近5日支撑位{support:.2f}元，风险较低"
        elif current_price > resistance * 0.98:
            # 接近压力位，谨慎
            suggested_price = current_price * 0.995
            reason = f"价格接近5日压力位{resistance:.2f}元，建议回调至{suggested_price:.2f}元买入"
        else:
            # 中间位置
            suggested_price = current_price
            reason = f"当前价格{current_price:.2f}元处于合理区间"

        return {
            'current': current_price,
            'suggested': suggested_price,
            'support': support,
            'resistance': resistance,
            'reason': reason
        }

    def pick_stocks(self, top_n=20):
        """选股主函数"""
        print("\n" + "="*100)
        if self.target_date:
            print(f"📊 尾盘选股系统 - 回测模式 - {self.target_date}")
        else:
            print(f"📊 尾盘选股系统 - 实时模式 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("="*100)
        print("🎯 选股策略：全网最流行的量价关系指标")
        if self.target_date:
            print(f"📅 回测日期：{self.target_date}（模拟当天14:30后选股）")
        else:
            print("⏰ 选股时间：14:30后尾盘选股")
        print("="*100)

        candidates = []
        scanned = 0

        print(f"\n🔍 开始扫描 {len(self.stock_pool)} 只股票...")

        for code, market, name in self.stock_pool:
            try:
                result = self.analyze_stock(code, market, name)
                scanned += 1

                if result and result['score'] >= 100:  # 至少触发2个信号
                    candidates.append(result)

                if scanned % 500 == 0:
                    print(f"   已扫描 {scanned} 只，发现 {len(candidates)} 只候选股...")

            except Exception as e:
                continue

        print(f"\n✅ 扫描完成: {scanned} 只")
        print(f"🎯 发现 {len(candidates)} 只符合条件的股票")

        # 按评分排序
        candidates.sort(key=lambda x: x['score'], reverse=True)

        # 显示结果
        self.display_results(candidates[:top_n])

        return candidates[:top_n]

    def display_results(self, candidates):
        """显示选股结果"""
        if not candidates:
            print("\n❌ 未发现符合条件的股票")
            return

        print("\n" + "="*100)
        print(f"🎯 精选股票列表（按综合评分排序）")
        print("="*100)

        for i, stock in enumerate(candidates, 1):
            print(f"\n{'─'*100}")
            print(f"【{i}】{stock['code']} {stock['name']} - 综合评分: {stock['score']:.0f}")
            print(f"{'─'*100}")

            print(f"\n💰 买入建议:")
            print(f"   当前价格: {stock['buy_point']['current']:.2f} 元")
            print(f"   建议买入价: {stock['buy_point']['suggested']:.2f} 元")
            print(f"   支撑位: {stock['buy_point']['support']:.2f} 元")
            print(f"   压力位: {stock['buy_point']['resistance']:.2f} 元")
            print(f"   💡 {stock['buy_point']['reason']}")

            print(f"\n📊 触发信号 ({len(stock['signals'])}个):")
            for signal in stock['signals']:
                print(f"   ✅ 【{signal['name']}】强度:{signal['strength']} 评分:{signal['score']:.0f}")
                print(f"      {signal['desc']}")

            # 计算建议仓位
            position_value = self.config.get('account', 'initial_capital') * 0.02
            vol = int(position_value / stock['buy_point']['suggested'] / 100) * 100
            amount = vol * stock['buy_point']['suggested']

            print(f"\n📈 交易计划:")
            print(f"   建议买入: {vol} 股")
            print(f"   预计金额: {amount:,.2f} 元")
            print(f"   仓位占比: 约2%")

        print("\n" + "="*100)
        print(f"💡 共选出 {len(candidates)} 只股票，建议精选前10只分散买入")
        print("="*100)

    def close(self):
        """关闭连接"""
        self.core.close()


if __name__ == "__main__":
    import sys

    config = ConfigLoader()

    # 解析命令行参数
    # 用法: python afternoon_stock_picker.py [选股数量] [日期]
    # 例如: python afternoon_stock_picker.py 20 2026-04-14
    top_n = 20
    target_date = None

    if len(sys.argv) > 1:
        # 第一个参数可能是数字（选股数量）或日期
        arg1 = sys.argv[1]
        if arg1.isdigit():
            top_n = int(arg1)
        elif '-' in arg1 and len(arg1) == 10:
            target_date = arg1

    if len(sys.argv) > 2:
        # 第二个参数
        arg2 = sys.argv[2]
        if arg2.isdigit():
            top_n = int(arg2)
        elif '-' in arg2 and len(arg2) == 10:
            target_date = arg2

    try:
        picker = AfternoonStockPicker(config, target_date=target_date)
        picker.pick_stocks(top_n=top_n)
    except Exception as e:
        print(f"❌ 选股失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'picker' in locals():
            picker.close()
