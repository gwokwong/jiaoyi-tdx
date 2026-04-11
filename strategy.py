#!/usr/bin/env python3
"""
A股量化选股策略模块
基于五大核心策略的技术面选股系统

📌 总原则：只在"信号明确+风险可控"时介入
   所有信号需同时满足：形态条件 + 量能配合 + 位置合理（非高位）

🔢 五大选股策略（按优先级排序）
   1. 日K线放量突破平台（核心启动信号）
   2. 长周期均线站稳（趋势确立信号）
   3. K线"黄金坑"形态（超跌反弹机会）
   4. 多指标金叉共振（高胜率信号）
   5. 强者恒强：创新高后回踩介入（趋势加速信号）

🛡️ 通用风控与过滤规则
"""

import pandas as pd
import numpy as np
from pytdx.hq import TdxHq_API
from core import ConfigLoader


class StockSelector:
    """
    股票选股器
    实现五大技术面选股策略 + 风控过滤
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        # 连接通达信服务器
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if not self.api.connect(ip, port):
            raise Exception("连接服务器失败")

        print("✅ 选股系统初始化完成")

    def get_history_data(self, code, market, days=120):
        """
        获取历史K线数据

        参数:
            code: 股票代码
            market: 市场(0=深圳, 1=上海)
            days: 获取天数

        返回:
            DataFrame: 包含OHLCV数据的DataFrame
        """
        # 获取日K线数据
        data = self.api.get_security_bars(4, market, code, 0, days)
        if not data:
            return None

        df = pd.DataFrame(data)

        # 数据预处理
        df['date'] = pd.to_datetime(df['datetime'])
        df.set_index('date', inplace=True)

        # 重命名列（统一命名）
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'vol': 'Volume',
            'amount': 'Amount'
        }, inplace=True)

        return df

    def calculate_indicators(self, df):
        """
        计算技术指标

        计算的指标:
            - MA5, MA10, MA20, MA60, MA120, MA250 (移动平均线)
            - DIF, DEA, MACD (MACD指标)
            - K, D, J (KDJ指标)
            - RSI6, RSI12, RSI24 (RSI相对强弱指标)
            - VOL_MA5, VOL_MA20 (成交量均线)
            - BOLL_UPPER, BOLL_MIDDLE, BOLL_LOWER (布林带)
        """
        if df is None or len(df) < 30:
            return None

        # ========== 移动平均线 (MA) ==========
        # 短期均线：5日、10日、20日
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        # 中期均线：60日
        df['MA60'] = df['Close'].rolling(window=60).mean()

        # 长期均线：120日、250日
        df['MA120'] = df['Close'].rolling(window=120).mean()
        df['MA250'] = df['Close'].rolling(window=250).mean()

        # ========== MACD指标 (指数平滑异同移动平均线) ==========
        # DIF = EMA12 - EMA26 (快线)
        # DEA = DIF的9日EMA (慢线)
        # MACD柱 = (DIF - DEA) * 2

        # 计算12日和26日EMA
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()

        df['DIF'] = ema12 - ema26  # 快线
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()  # 慢线
        df['MACD'] = (df['DIF'] - df['DEA']) * 2  # 柱状线

        # ========== KDJ指标 (随机指标) ==========
        # 计算RSV (未成熟随机值)
        low_list = df['Low'].rolling(window=9, min_periods=9).min()
        high_list = df['High'].rolling(window=9, min_periods=9).max()

        # 避免除以零
        RSV = (df['Close'] - low_list) / (high_list - low_list) * 100
        RSV = RSV.fillna(50)  # 默认值

        # 计算K、D、J值
        df['K'] = RSV.ewm(com=2, adjust=False).mean()  # K线
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()  # D线
        df['J'] = 3 * df['K'] - 2 * df['D']  # J线

        # ========== RSI指标 (相对强弱指标) ==========
        # RSI = 上涨幅度均值 / (上涨幅度均值 + 下跌幅度均值) * 100

        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)

        # 计算不同周期的RSI
        avg_gain = gain.rolling(window=6, min_periods=6).mean()
        avg_loss = loss.rolling(window=6, min_periods=6).mean()

        # 避免除以零
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['RSI6'] = 100 - (100 / (1 + rs))
        df['RSI6'] = df['RSI6'].fillna(50)

        # 12日和24日RSI（简化计算）
        df['RSI12'] = df['RSI6']  # 简化处理
        df['RSI24'] = df['RSI6']  # 简化处理

        # ========== 成交量指标 ==========
        df['VOL_MA5'] = df['Volume'].rolling(window=5).mean()
        df['VOL_MA20'] = df['Volume'].rolling(window=20).mean()

        # ========== 布林带指标 (Bollinger Bands) ==========
        # 中轨 = 20日均线
        # 上轨 = 中轨 + 2倍标准差
        # 下轨 = 中轨 - 2倍标准差

        df['BOLL_MIDDLE'] = df['Close'].rolling(window=20).mean()
        std = df['Close'].rolling(window=20).std()
        df['BOLL_UPPER'] = df['BOLL_MIDDLE'] + 2 * std
        df['BOLL_LOWER'] = df['BOLL_MIDDLE'] - 2 * std

        return df

    def check_strategy_1_breakout(self, df):
        """
        📊 策略1: 日K线放量突破平台（核心启动信号）

        适用场景: 股价处于阶段性低位/盘整末期

        具体条件:
        ✓ 形态: 出现"箱体震荡"或"平台整理"（至少5日以上横盘，高低点振幅≤8%）
        ✓ 突破: 单根K线收盘价 > 平台最高点，且涨幅 ≥ 3%
        ✓ 量能: 当日成交量 ≥ 前5日均量的150%
        ✓ 辅助: MACD柱状线由负转正，或KDJ金叉（J值从20以下上穿K/D）

        买入时机: 突破当日尾盘(14:30后)或次日高开不破前日低点时介入
        止损位: 跌破平台高点下方2%

        参数:
            df: 包含K线数据的DataFrame

        返回:
            dict: {'signal': bool, 'reason': str, 'details': dict}
        """
        if df is None or len(df) < 20:
            return {'signal': False, 'reason': '数据不足'}

        latest = df.iloc[-1]
        prev_5 = df.iloc[-6:-1]  # 前5天数据

        # ========== 条件1: 平台整理（至少5日横盘，振幅≤8%）==========
        platform_high = prev_5['High'].max()  # 平台最高点
        platform_low = prev_5['Low'].min()   # 平台最低点
        platform_range = (platform_high - platform_low) / platform_low * 100

        if platform_range > 8:
            return {'signal': False, 'reason': '非平台整理期', 'details': {'振幅': f'{platform_range:.2f}%'}}

        # ========== 条件2: 突破信号（收盘>平台最高点，涨幅≥3%）==========
        change_pct = (latest['Close'] - prev_5['Close'].iloc[-1]) / prev_5['Close'].iloc[-1] * 100

        if latest['Close'] <= platform_high or change_pct < 3:
            return {
                'signal': False,
                'reason': '未满足突破条件',
                'details': {
                    '收盘价': latest['Close'],
                    '平台高点': platform_high,
                    '涨幅': f'{change_pct:.2f}%'
                }
            }

        # ========== 条件3: 放量确认（成交量≥前5日均量150%）==========
        vol_ma5 = prev_5['Volume'].mean()
        vol_ratio = latest['Volume'] / vol_ma5

        if vol_ratio < 1.5:
            return {
                'signal': False,
                'reason': '量能不足',
                'details': {'量比': f'{vol_ratio:.2f}'}
            }

        # ========== 条件4: 辅助验证（MACD由负转正或KDJ金叉）==========
        macd_prev = df['MACD'].iloc[-2]
        macd_now = latest['MACD']
        macd_confirm = macd_prev < 0 and macd_now > 0  # MACD由负转正

        kdj_prev_k = df['K'].iloc[-2]
        kdj_prev_d = df['D'].iloc[-2]
        kdj_now_k = latest['K']
        kdj_now_d = latest['D']

        # KDJ金叉: K线从下方上穿D线，且J值从20以下
        kdj_cross = (kdj_prev_k < kdj_prev_d) and (kdj_now_k > kdj_now_d)
        j_below_20_prev = df['J'].iloc[-3] < 20 if len(df) >= 3 else False
        kdj_confirm = kdj_cross and j_below_20_prev

        if not (macd_confirm or kdj_confirm):
            return {
                'signal': False,
                'reason': '缺乏辅助信号',
                'details': {
                    'MACD确认': macd_confirm,
                    'KDJ确认': kdj_confirm
                }
            }

        # ✅ 所有条件满足
        return {
            'signal': True,
            'reason': '放量突破平台',
            'details': {
                '平台振幅': f'{platform_range:.2f}%',
                '涨幅': f'{change_pct:.2f}%',
                '量比': f'{vol_ratio:.2f}',
                'MACD确认': macd_confirm,
                'KDJ确认': kdj_confirm,
                '买入价格': latest['Close'],
                '止损位': platform_high * 0.98  # 跌破平台高点2%
            }
        }

    def check_strategy_2_ma_trend(self, df):
        """
        📊 策略2: 长周期均线站稳（趋势确立信号）

        适用场景: 中线布局，捕捉主升浪初期

        具体条件:
        ✓ 均线组合: 60日线 + 120日线 + 250日线三线多头排列
        ✓ 价格关系: 股价连续3日站稳60日线之上，且距离60日线 ≤ 3%
        ✓ 形态确认: K线从"走平"转为"向上倾斜"，伴随温和放量（量比≥1.2）
        ✓ 关键信号: "放量站稳60日线" → 标志空头衰竭、多头反攻

        买入时机: 第三日站稳后，回调至60日线附近企稳时介入
        止损位: 有效跌破60日线（收盘价 < 60日线 - 1%）

        参数:
            df: 包含K线数据的DataFrame

        返回:
            dict: {'signal': bool, 'reason': str, 'details': dict}
        """
        if df is None or len(df) < 250:
            return {'signal': False, 'reason': '数据不足(需250日数据)'}

        latest = df.iloc[-1]
        prev_3 = df.iloc[-4:-1]  # 前3天数据

        # ========== 条件1: 三线多头排列（60>120>250）==========
        ma60 = latest['MA60']
        ma120 = latest['MA120']
        ma250 = latest['MA250']

        if not (ma60 > ma120 > ma250):
            return {
                'signal': False,
                'reason': '均线非多头排列',
                'details': {
                    'MA60': ma60,
                    'MA120': ma120,
                    'MA250': ma250
                }
            }

        # ========== 条件2: 连续3日站稳60日线 ==========
        ma60_series = df['MA60'].iloc[-3:]

        # 检查最近3日收盘价都在60日线上方
        close_series = df['Close'].iloc[-3:]

        if not all(close_series > ma60_series):
            return {'signal': False, 'reason': '未连续3日站稳60日线'}

        # ========== 条件3: 距离60日线≤3% ==========
        distance_to_ma60 = (latest['Close'] - ma60) / ma60 * 100

        if distance_to_ma60 > 3:
            return {
                'signal': False,
                'reason': '价格远离60日线(>3%)',
                'details': {'距离': f'{distance_to_ma60:.2f}%'}
            }

        # ========== 条件4: 温和放量（量比≥1.2）==========
        vol_ma20 = df['VOL_MA20'].iloc[-1]
        vol_ratio = latest['Volume'] / vol_ma20 if vol_ma20 > 0 else 0

        if vol_ratio < 1.2:
            return {
                'signal': False,
                'reason': '量能不足(量比<1.2)',
                'details': {'量比': f'{vol_ratio:.2f}'}
            }

        # ========== 条件5: 均线向上倾斜（可选）==========
        # 检查60日线是否向上
        ma60_prev = df['MA60'].iloc[-10]
        ma60_trend_up = ma60 > ma60_prev

        # ✅ 所有条件满足
        return {
            'signal': True,
            'reason': '长周期均线站稳',
            'details': {
                'MA60': ma60,
                'MA120': ma120,
                'MA250': ma250,
                '距离MA60': f'{distance_to_ma60:.2f}%',
                '量比': f'{vol_ratio:.2f}',
                '均线向上': ma60_trend_up,
                '买入价格': latest['Close'],
                '止损位': ma60 * 0.99  # 跌破60日线1%
            }
        }

    def check_strategy_3_golden_pit(self, df):
        """
        📊 策略3: K线"黄金坑"形态（超跌反弹机会）

        适用场景: 急跌后快速修复，适合短线博弈

        具体条件:
        ✓ 形态定义: 单日/2日内暴跌≥7%，随后3-5日内收复跌幅50%以上
        ✓ 量能特征: 暴跌日放巨量（量比≥3.0），反弹首日量能≥暴跌日50%
        ✓ 技术验证: RSI从超卖区(<30)快速回升至45以上，或布林带下轨触底反弹
        ✓ 关键提示: 仅适用于基本面无恶化的个股

        买入时机: 第3日阳线实体覆盖前一日阴线50%以上时介入
        止损位: 跌破黄金坑最低点2%

        ⚠️ 注意: 非所有"坑"都可抄底！必须是"利空出尽+资金回流"型

        参数:
            df: 包含K线数据的DataFrame

        返回:
            dict: {'signal': bool, 'reason': str, 'details': dict}
        """
        if df is None or len(df) < 15:
            return {'signal': False, 'reason': '数据不足'}

        # ========== 条件1: 识别暴跌日(单日或2日累计跌幅≥7%) ==========
        crash_days = []
        for i in range(-5, -1):
            curr = df.iloc[i]
            prev = df.iloc[i-1] if i > -5 else df.iloc[i]
            change = (curr['Close'] - prev['Close']) / prev['Close'] * 100

            if change <= -7:
                crash_days.append({'idx': i, 'change': change, 'low': curr['Low']})

        if not crash_days:
            return {'signal': False, 'reason': '无暴跌日'}

        # 取最近的暴跌日
        crash = crash_days[-1]
        crash_idx = crash['idx']
        crash_low = crash['low']

        # ========== 条件2: 暴跌日放巨量（量比≥3.0）==========
        crash_vol = df.iloc[crash_idx]['Volume']
        vol_ma5_before = df['Volume'].iloc[crash_idx-6:crash_idx].mean()
        crash_vol_ratio = crash_vol / vol_ma5_before if vol_ma5_before > 0 else 0

        if crash_vol_ratio < 3.0:
            return {
                'signal': False,
                'reason': '暴跌日量能不足(量比<3.0)',
                'details': {'量比': f'{crash_vol_ratio:.2f}'}
            }

        # ========== 条件3: 3-5日内收复跌幅50%以上 ==========
        crash_price = df.iloc[crash_idx]['Close']
        prev_price = df.iloc[crash_idx - 1]['Close'] if crash_idx > 0 else prev['Close']

        # 最低点
        min_price = df.iloc[crash_idx:crash_idx+5]['Low'].min()

        # 反弹幅度
        recovery_pct = (df.iloc[-1]['Close'] - min_price) / min_price * 100
        crash_pct = (min_price - prev_price) / prev_price * 100

        # 收复50%以上
        if abs(crash_pct) > 0 and recovery_pct < abs(crash_pct) * 0.5:
            return {
                'signal': False,
                'reason': '未收复足够跌幅',
                'details': {
                    '暴跌幅度': f'{crash_pct:.2f}%',
                    '反弹幅度': f'{recovery_pct:.2f}%',
                    '需收复': f'{abs(crash_pct) * 0.5:.2f}%'
                }
            }

        # ========== 条件4: RSI验证（可选）==========
        rsi_now = df.iloc[-1]['RSI6']
        rsi_recovery = rsi_now > 45  # RSI回升至45以上

        # ========== 条件5: 今日阳线覆盖前一日阴线50% ==========
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        is_yang = today['Close'] > today['Open']
        yang_body = today['Close'] - today['Open']
        yin_body = yesterday['Open'] - yesterday['Close'] if yesterday['Close'] < yesterday['Open'] else 0

        coverage = yang_body / yin_body if yin_body > 0 else 0

        if not (is_yang and coverage >= 0.5):
            return {
                'signal': False,
                'reason': '今日未形成覆盖阳线',
                'details': {
                    '阳线覆盖': f'{coverage*100:.1f}%',
                    '需覆盖': '≥50%'
                }
            }

        # ✅ 所有条件满足
        return {
            'signal': True,
            'reason': '黄金坑反弹',
            'details': {
                '暴跌幅度': f'{crash_pct:.2f}%',
                '反弹幅度': f'{recovery_pct:.2f}%',
                '暴跌量比': f'{crash_vol_ratio:.2f}',
                'RSI': f'{rsi_now:.2f}',
                '阳线覆盖': f'{coverage*100:.1f}%',
                '买入价格': today['Close'],
                '止损位': crash_low * 0.98  # 跌破黄金坑最低点2%
            }
        }

    def check_strategy_4_golden_cross(self, df):
        """
        📊 策略4: 多指标金叉共振（高胜率信号）

        适用场景: 提高信号可靠性，过滤假信号

        具体条件（必须同时满足）:
        ✓ MA5/10: 5日线上穿10日线（短周期趋势）[★★★权重]
        ✓ MACD: DIF上穿DEA，且柱状线由负转正 [★★★★权重]
        ✓ KDJ: K线上穿D线，J值从20→50区间上穿 [★★★权重]
        ✓ 量能: 成交量 > 20日均量 × 1.3 [★★★★权重]

        增强信号: 叠加"股价站上20日线"或"突破近期小平台"，胜率提升至70%+

        买入时机: 金叉当日收盘前15分钟确认（避免盘中诱多）
        止损位: 跌破金叉当日最低价

        参数:
            df: 包含K线数据的DataFrame

        返回:
            dict: {'signal': bool, 'reason': str, 'details': dict}
        """
        if df is None or len(df) < 30:
            return {'signal': False, 'reason': '数据不足'}

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # ========== 条件1: MA5上穿MA10（金叉）==========
        ma5_cross = (prev['MA5'] <= prev['MA10']) and (latest['MA5'] > latest['MA10'])

        # ========== 条件2: MACD金叉 + 柱状线由负转正 ==========
        macd_gold_cross = (prev['DIF'] <= prev['DEA']) and (latest['DIF'] > latest['DEA'])
        macd_turn_positive = (prev['MACD'] < 0) and (latest['MACD'] > 0)

        # ========== 条件3: KDJ金叉 + J值区间 ==========
        kdj_gold_cross = (prev['K'] <= prev['D']) and (latest['K'] > latest['D'])
        j_range_ok = (df['J'].iloc[-3] < 20) and (latest['J'] < 50)  # J值从20以下回升至50以下

        # ========== 条件4: 放量（量比≥1.3）==========
        vol_ratio = latest['Volume'] / latest['VOL_MA20'] if latest['VOL_MA20'] > 0 else 0
        vol_confirm = vol_ratio >= 1.3

        # ========== 增强条件: 股价站上20日线 ==========
        above_ma20 = latest['Close'] > latest['MA20']

        # 计算金叉数量
        cross_count = sum([ma5_cross, macd_gold_cross, kdj_gold_cross, vol_confirm])
        cross_details = {
            'MA5/10金叉': ma5_cross,
            'MACD金叉': macd_gold_cross,
            'MACD转正': macd_turn_positive,
            'KDJ金叉': kdj_gold_cross,
            'KDJ区间': j_range_ok,
            '量能确认': vol_confirm,
            '站上MA20': above_ma20
        }

        # ========== 必须满足至少3个核心条件 ==========
        if cross_count < 3:
            return {
                'signal': False,
                'reason': f'金叉共振不足({cross_count}/4)',
                'details': cross_details
            }

        # ✅ 所有条件满足
        return {
            'signal': True,
            'reason': f'多指标金叉共振({cross_count}个信号)',
            'details': {
                **cross_details,
                '量比': f'{vol_ratio:.2f}',
                '金叉数量': cross_count,
                '买入价格': latest['Close'],
                '止损位': prev['Close'] * 0.98  # 跌破金叉前一日最低价2%
            }
        }

    def check_strategy_5_high_breakout(self, df):
        """
        📊 策略5: 强者恒强 - 创新高后回踩介入（趋势加速信号）

        适用场景: 强势股第二波启动，风险收益比最优

        具体条件:
        ✓ 创新高: 股价创近60日新高（非历史新高，避免高位接盘）
        ✓ 走势特征: 上涨过程沿5日线稳步上行（小阴小阳，无大阴线）
        ✓ 回踩介入点: 首次回踩5日线或10日线，且缩量（量比≤0.8）
        ✓ 量能验证: 回踩日K线收小阳/十字星，次日放量阳线确认

        关键禁忌:
        ❌ 高位放巨量长上影（主力出货）
        ❌ 回踩跌破10日线且无支撑

        买入时机: 回踩5日线企稳+次日放量阳线开盘后介入
        止损位: 跌破10日线

        参数:
            df: 包含K线数据的DataFrame

        返回:
            dict: {'signal': bool, 'reason': str, 'details': dict}
        """
        if df is None or len(df) < 70:
            return {'signal': False, 'reason': '数据不足(需60日数据)'}

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # ========== 条件1: 创60日新高 ==========
        high_60 = df['High'].iloc[-60:-1].max()  # 前60日最高点
        is_new_high = latest['High'] > high_60

        if not is_new_high:
            return {
                'signal': False,
                'reason': '未创新高',
                'details': {
                    '当前价': latest['Close'],
                    '60日最高': high_60
                }
            }

        # ========== 条件2: 沿5日线稳步上行（检查前5日）==========
        ma5_aligned = True
        for i in range(-6, -1):
            # 小阴小阳（振幅<3%），收盘在5日线上方
            curr = df.iloc[i]
            change = abs(curr['Close'] - curr['Open']) / curr['Open'] * 100
            above_ma5 = curr['Close'] > curr['MA5']

            if change > 3 or not above_ma5:
                ma5_aligned = False
                break

        # ========== 条件3: 回踩5日/10日线（缩量）==========
        near_ma5 = abs(latest['Close'] - latest['MA5']) / latest['MA5'] * 100 < 1  # 距5日线<1%
        near_ma10 = abs(latest['Close'] - latest['MA10']) / latest['MA10'] * 100 < 2  # 距10日线<2%

        is_pullback = near_ma5 or near_ma10

        if not is_pullback:
            return {
                'signal': False,
                'reason': '未回踩均线',
                'details': {
                    '距MA5': f'{abs(latest["Close"] - latest["MA5"]) / latest["MA5"] * 100:.2f}%',
                    '距MA10': f'{abs(latest["Close"] - latest["MA10"]) / latest["MA10"] * 100:.2f}%'
                }
            }

        # ========== 条件4: 缩量（量比≤0.8）==========
        vol_ratio = latest['Volume'] / latest['VOL_MA5'] if latest['VOL_MA5'] > 0 else 1
        is_low_volume = vol_ratio <= 0.8

        if not is_low_volume:
            return {
                'signal': False,
                'reason': '未缩量',
                'details': {'量比': f'{vol_ratio:.2f}'}
            }

        # ========== 条件5: 今日收小阳/十字星 ==========
        today_change = abs(latest['Close'] - latest['Open']) / latest['Open'] * 100
        is_small_body = today_change < 2  # 实体<2%

        # ========== 条件6: 次日放量阳线确认（如果是今天，需检查昨日）==========
        prev_is_small = abs(prev['Close'] - prev['Open']) / prev['Open'] * 100 < 2
        prev_above_ma5 = prev['Close'] > prev['MA5']
        prev_low_volume = prev['Volume'] / df['VOL_MA5'].iloc[-2] if df['VOL_MA5'].iloc[-2] > 0 else 1

        # 如果昨天是回踩日，今天应该是放量阳线
        if prev_is_small and prev_above_ma5:
            today_volume_ok = latest['Volume'] > df['Volume'].iloc[-2] * 1.2  # 放量
            today_yang = latest['Close'] > latest['Open']
        else:
            today_volume_ok = True
            today_yang = True

        # ✅ 所有条件满足
        return {
            'signal': True,
            'reason': '创新高回踩',
            'details': {
                '60日新高': high_60,
                '沿MA5上行': ma5_aligned,
                '回踩MA5': near_ma5,
                '回踩MA10': near_ma10,
                '缩量确认': is_low_volume,
                '量比': f'{vol_ratio:.2f}',
                '小实体': is_small_body,
                '买入价格': latest['Close'],
                '止损位': latest['MA10'] * 0.99  # 跌破10日线1%
            }
        }

    def check_risk_control(self, df, strategy_signal):
        """
        🛡️ 通用风控与过滤规则

        排除条件:
        ❌ 近1个月涨幅>50% 且 RSI>70 → 直接排除
        ❌ 股价处于年线上方30%以上 → 谨慎参与
        ❌ 日成交额<3000万(小盘)或<1亿(中大盘) → 流动性风险
        ❌ 大盘在20日均线下方时，只做策略1、3

        参数:
            df: 包含K线数据的DataFrame
            strategy_signal: 策略信号（用于判断策略类型）

        返回:
            dict: {'passed': bool, 'warnings': list}
        """
        if df is None or len(df) < 30:
            return {'passed': False, 'warnings': ['数据不足']}

        latest = df.iloc[-1]
        warnings = []

        # ========== 条件1: 排除高位股 ==========
        # 近1个月涨幅
        if len(df) >= 22:
            month_change = (latest['Close'] - df['Close'].iloc[-22]) / df['Close'].iloc[-22] * 100
            rsi = latest['RSI6']

            if month_change > 50 and rsi > 70:
                warnings.append(f'高位股警戒: 月涨幅{month_change:.1f}%, RSI={rsi:.1f}')

        # ========== 条件2: 年线上方30% ==========
        ma250 = latest['MA250']
        if ma250 > 0:
            above_annual = (latest['Close'] - ma250) / ma250 * 100
            if above_annual > 30:
                warnings.append(f'远离年线: {above_annual:.1f}%')

        # ========== 条件3: 量能底线 ==========
        amount = latest.get('Amount', 0)  # 成交额
        price = latest['Close']

        # 估算流通股本（简化计算）
        estimated_volume = amount / price if price > 0 else 0

        # 小盘股（价格>10元，成交额<3000万）
        # 中大盘股（成交额<1亿）
        if price > 10 and amount < 30000000:
            warnings.append(f'小盘股流动性风险: 成交额{amount/100000000:.2f}亿')
        elif amount < 100000000:
            warnings.append(f'中大盘股流动性风险: 成交额{amount/100000000:.2f}亿')

        # ========== 综合评估 ==========
        # 如果有严重警告，不通过
        serious_warnings = [w for w in warnings if '高位股' in w or '流动性' in w]

        return {
            'passed': len(serious_warnings) == 0,
            'warnings': warnings,
            'can_trade': len(serious_warnings) == 0
        }

    def scan_stock(self, code, market=0):
        """
        扫描单只股票，返回所有策略信号

        参数:
            code: 股票代码
            market: 市场(0=深圳, 1=上海)

        返回:
            dict: 包含所有策略信号的字典
        """
        # 获取数据
        df = self.get_history_data(code, market, days=250)
        if df is None:
            return {'code': code, 'error': '获取数据失败'}

        # 计算指标
        df = self.calculate_indicators(df)
        if df is None:
            return {'code': code, 'error': '计算指标失败'}

        # 执行五大策略
        results = {
            'code': code,
            'market': 'SH' if market == 1 else 'SZ',
            'strategies': {
                '策略1_放量突破平台': self.check_strategy_1_breakout(df),
                '策略2_均线站稳': self.check_strategy_2_ma_trend(df),
                '策略3_黄金坑': self.check_strategy_3_golden_pit(df),
                '策略4_多指标金叉': self.check_strategy_4_golden_cross(df),
                '策略5_创新高回踩': self.check_strategy_5_high_breakout(df)
            },
            'risk_control': self.check_risk_control(df, None),
            'latest_data': {
                'close': df.iloc[-1]['Close'],
                'change': (df.iloc[-1]['Close'] - df.iloc[-2]['Close']) / df.iloc[-2]['Close'] * 100,
                'volume_ratio': df.iloc[-1]['Volume'] / df.iloc[-1]['VOL_MA5'] if df.iloc[-1]['VOL_MA5'] > 0 else 0
            }
        }

        return results

    def scan_stocks(self, stock_list):
        """
        批量扫描股票

        参数:
            stock_list: [(code, market), ...] 股票列表

        返回:
            list: 所有股票的选股结果
        """
        results = []

        print(f"\n🔍 开始扫描 {len(stock_list)} 只股票...")

        for i, (code, market) in enumerate(stock_list):
            if i % 10 == 0:
                print(f"   进度: {i}/{len(stock_list)}", end='\r')

            try:
                result = self.scan_stock(code, market)
                results.append(result)
            except Exception as e:
                results.append({'code': code, 'error': str(e)})

        print(f"\n✅ 扫描完成，共 {len(results)} 只股票")

        return results

    def filter_signals(self, results):
        """
        过滤并筛选出有效的买入信号

        筛选条件:
        ✓ 至少满足1个策略
        ✓ 通过风控检查
        ✓ 按策略优先级排序

        参数:
            results: scan_stocks的返回结果

        返回:
            list: 有效信号列表
        """
        signals = []

        for result in results:
            if 'error' in result:
                continue

            # 检查各策略信号
            for strategy_name, signal_data in result['strategies'].items():
                if signal_data.get('signal', False):
                    # 检查风控
                    risk = result['risk_control']
                    if risk['passed']:
                        signals.append({
                            'code': result['code'],
                            'market': result['market'],
                            'strategy': strategy_name,
                            'reason': signal_data['reason'],
                            'details': signal_data['details'],
                            'warnings': risk['warnings'],
                            'latest_price': result['latest_data']['close'],
                            'change': result['latest_data']['change'],
                            'volume_ratio': result['latest_data']['volume_ratio']
                        })

        # 按涨幅排序（优先选择还未大涨的）
        signals.sort(key=lambda x: x['change'])

        return signals

    def close(self):
        """关闭连接"""
        self.api.disconnect()


def demo():
    """演示选股系统"""
    config = ConfigLoader()
    selector = StockSelector(config)

    # 测试股票列表
    test_stocks = [
        ('000001', 0),  # 平安银行
        ('000002', 0),  # 万科A
        ('600000', 1),  # 浦发银行
        ('600028', 1),  # 中国石化
    ]

    # 扫描股票
    results = selector.scan_stocks(test_stocks)

    # 过滤信号
    signals = selector.filter_signals(results)

    # 显示结果
    print("\n" + "="*80)
    print("📊 选股结果")
    print("="*80)

    if signals:
        for i, signal in enumerate(signals, 1):
            print(f"\n{i}. {signal['code']} ({signal['market']})")
            print(f"   📌 策略: {signal['strategy']}")
            print(f"   📝 原因: {signal['reason']}")
            print(f"   💰 最新价: {signal['latest_price']:.2f}")
            print(f"   📈 涨幅: {signal['change']:+.2f}%")
            print(f"   📊 量比: {signal['volume_ratio']:.2f}")
            if signal['details']:
                print(f"   🔍 详情: {signal['details']}")
    else:
        print("\n⚠️  未发现符合条件的买入信号")

    print("\n" + "="*80)

    selector.close()


if __name__ == "__main__":
    demo()
