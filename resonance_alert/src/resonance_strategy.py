"""
多条件共振策略模块
实现趋势+量能+动能三重验证
以及跨周期共振策略
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""
    CROSS_PERIOD_MACD_KDJ = "跨周期MACD+KDJ共振"
    TREND_VOLUME_MOMENTUM = "趋势+量能+动能共振"
    WEEKLY_DIRECTION_DAILY_ENTRY = "周线定方向日线买点"
    HIGH_LEVEL_RESONANCE = "高级多周期共振"


@dataclass
class ResonanceSignal:
    """共振信号数据类"""
    code: str
    name: str
    signal_type: SignalType
    score: int  # 得分 0-100
    reasons: List[str]  # 信号原因列表
    day_indicators: Dict  # 日线指标
    week_indicators: Optional[Dict] = None  # 周线指标
    month_indicators: Optional[Dict] = None  # 月线指标
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'code': self.code,
            'name': self.name,
            'signal_type': self.signal_type.value,
            'score': self.score,
            'reasons': self.reasons,
            'current_price': self.day_indicators.get('close', 0),
            'day_ma20': self.day_indicators.get('ma20', 0),
            'week_trend': 'UP' if self.week_indicators and self.week_indicators.get('ma20', 0) > self.week_indicators.get('prev_ma20', 0) else 'DOWN'
        }


class MultiConditionResonance:
    """
    多条件共振策略
    实现通达信公式中的多条件共振逻辑
    """
    
    def __init__(self):
        self.signals = []
    
    def check_cross_period_macd_kdj(
        self, 
        code: str, 
        name: str,
        day_indicators: Dict,
        week_indicators: Optional[Dict] = None
    ) -> Optional[ResonanceSignal]:
        """
        跨周期MACD+KDJ共振策略
        
        通达信公式逻辑:
        周线MACD金叉:="MACD.DIF#WEEK" > "MACD.DEA#WEEK"
        周线趋势向上:="MACD.DIF#WEEK" > REF("MACD.DIF#WEEK",1)
        日线KDJ金叉:=KDJ.J > REF(KDJ.J,1) AND KDJ.K > KDJ.D
        """
        reasons = []
        score = 0
        
        # 日线KDJ金叉判断
        day_kdj_gold = (
            day_indicators.get('j', 0) > day_indicators.get('prev_j', 0) and
            day_indicators.get('k', 0) > day_indicators.get('d', 0)
        )
        
        if day_kdj_gold:
            reasons.append(f"日线KDJ金叉: K={day_indicators.get('k', 0):.2f}, D={day_indicators.get('d', 0):.2f}")
            score += 30
        
        # 如果有周线数据，检查周线MACD
        if week_indicators:
            week_macd_gold = week_indicators.get('dif', 0) > week_indicators.get('dea', 0)
            week_trend_up = week_indicators.get('dif', 0) > week_indicators.get('prev_dif', 0)
            
            if week_macd_gold:
                reasons.append(f"周线MACD金叉: DIF={week_indicators.get('dif', 0):.3f} > DEA={week_indicators.get('dea', 0):.3f}")
                score += 35
            
            if week_trend_up:
                reasons.append(f"周线DIF拐头向上")
                score += 20
        
        # 日线MACD金叉
        day_macd_gold = day_indicators.get('dif', 0) > day_indicators.get('dea', 0)
        if day_macd_gold:
            reasons.append(f"日线MACD金叉")
            score += 15
        
        if score >= 50:  # 至少满足两个主要条件
            return ResonanceSignal(
                code=code,
                name=name,
                signal_type=SignalType.CROSS_PERIOD_MACD_KDJ,
                score=score,
                reasons=reasons,
                day_indicators=day_indicators,
                week_indicators=week_indicators
            )
        
        return None
    
    def check_trend_volume_momentum(
        self,
        code: str,
        name: str,
        day_indicators: Dict
    ) -> Optional[ResonanceSignal]:
        """
        趋势+量能+动能三重验证
        
        通达信公式逻辑:
        趋势OK:=C>MA(C,20) AND MA(C,20)>REF(MA(C,20),1)
        量能OK:=V>MA(V,5)*1.5 AND V<MA(V,5)*3
        动能OK:=MACD.MACD>REF(MACD.MACD,1) AND MACD.MACD>0
        """
        reasons = []
        score = 0
        
        # 趋势维度: 股价在20日均线之上，且20日均线向上
        trend_ok = (
            day_indicators.get('close', 0) > day_indicators.get('ma20', 0) and
            day_indicators.get('ma20', 0) > day_indicators.get('prev_ma20', 0)
        )
        
        if trend_ok:
            reasons.append(f"趋势OK: 股价{day_indicators.get('close', 0):.2f} > MA20({day_indicators.get('ma20', 0):.2f})")
            score += 35
        
        # 量能维度: 成交量大于5日均量1.5倍，且不是暴量(<3倍)
        vol_ratio = day_indicators.get('volume', 0) / day_indicators.get('vol_ma5', 1)
        volume_ok = 1.5 <= vol_ratio <= 3.0
        
        if volume_ok:
            reasons.append(f"量能OK: 量比{vol_ratio:.2f}倍 (1.5-3倍区间)")
            score += 30
        
        # 动能维度: MACD柱状线由绿翻红或红柱伸长
        momentum_ok = (
            day_indicators.get('macd', 0) > day_indicators.get('prev_macd', 0) and
            day_indicators.get('macd', 0) > 0
        )
        
        if momentum_ok:
            reasons.append(f"动能OK: MACD红柱伸长 {day_indicators.get('macd', 0):.3f}")
            score += 35
        
        if score >= 65:  # 至少满足两个维度
            return ResonanceSignal(
                code=code,
                name=name,
                signal_type=SignalType.TREND_VOLUME_MOMENTUM,
                score=score,
                reasons=reasons,
                day_indicators=day_indicators
            )
        
        return None
    
    def check_weekly_direction_daily_entry(
        self,
        code: str,
        name: str,
        day_indicators: Dict,
        week_indicators: Optional[Dict] = None
    ) -> Optional[ResonanceSignal]:
        """
        周线定方向，日线找买点
        
        通达信公式逻辑:
        周线向上:=MA(C#WEEK,20) > REF(MA(C#WEEK,20),1)
        日线回调:=C>MA(C,20) AND C<REF(HHV(H,10),1) AND V<REF(V,1)*0.8
        """
        if not week_indicators:
            return None
        
        reasons = []
        score = 0
        
        # 周线趋势向上
        week_up = week_indicators.get('ma20', 0) > week_indicators.get('prev_ma20', 0)
        
        if week_up:
            reasons.append(f"周线趋势向上: MA20={week_indicators.get('ma20', 0):.2f}")
            score += 40
        
        # 日线回调买点
        # 股价在20日线上方，但低于近期高点，且缩量
        price = day_indicators.get('close', 0)
        ma20 = day_indicators.get('ma20', 0)
        high_10 = day_indicators.get('high_10', price * 1.1)  # 10日高点
        vol_ratio = day_indicators.get('volume', 0) / day_indicators.get('vol_ma5', 1)
        
        daily_pullback = (
            price > ma20 and 
            price < high_10 * 0.95 and  # 低于10日高点5%
            vol_ratio < 0.8  # 缩量
        )
        
        if daily_pullback:
            reasons.append(f"日线回调买点: 价格{price:.2f}低于高点{high_10:.2f}，缩量{vol_ratio:.2f}倍")
            score += 40
        
        # 日线MACD金叉
        if day_indicators.get('dif', 0) > day_indicators.get('dea', 0):
            reasons.append("日线MACD金叉")
            score += 20
        
        if score >= 60:
            return ResonanceSignal(
                code=code,
                name=name,
                signal_type=SignalType.WEEKLY_DIRECTION_DAILY_ENTRY,
                score=score,
                reasons=reasons,
                day_indicators=day_indicators,
                week_indicators=week_indicators
            )
        
        return None
    
    def check_high_level_resonance(
        self,
        code: str,
        name: str,
        day_indicators: Dict,
        week_indicators: Optional[Dict] = None,
        month_indicators: Optional[Dict] = None
    ) -> Optional[ResonanceSignal]:
        """
        高级多周期共振
        日线+周线+月线三重共振
        """
        reasons = []
        score = 0
        
        # 月线趋势
        if month_indicators:
            month_up = month_indicators.get('ma20', 0) > month_indicators.get('prev_ma20', 0)
            if month_up:
                reasons.append("月线趋势向上")
                score += 30
        
        # 周线趋势
        if week_indicators:
            week_up = week_indicators.get('ma20', 0) > week_indicators.get('prev_ma20', 0)
            week_macd_ok = week_indicators.get('dif', 0) > week_indicators.get('dea', 0)
            
            if week_up:
                reasons.append("周线趋势向上")
                score += 25
            if week_macd_ok:
                reasons.append("周线MACD金叉")
                score += 20
        
        # 日线多重条件
        # 1. 股价在MA20之上
        if day_indicators.get('close', 0) > day_indicators.get('ma20', 0):
            reasons.append("日线股价在MA20之上")
            score += 10
        
        # 2. MACD金叉或红柱
        if day_indicators.get('dif', 0) > day_indicators.get('dea', 0):
            reasons.append("日线MACD金叉")
            score += 10
        
        # 3. 放量
        vol_ratio = day_indicators.get('volume', 0) / day_indicators.get('vol_ma5', 1)
        if vol_ratio > 1.2:
            reasons.append(f"日线放量 {vol_ratio:.2f}倍")
            score += 5
        
        if score >= 70:
            return ResonanceSignal(
                code=code,
                name=name,
                signal_type=SignalType.HIGH_LEVEL_RESONANCE,
                score=score,
                reasons=reasons,
                day_indicators=day_indicators,
                week_indicators=week_indicators,
                month_indicators=month_indicators
            )
        
        return None
    
    def evaluate_stock(
        self,
        code: str,
        name: str,
        day_indicators: Dict,
        week_indicators: Optional[Dict] = None,
        month_indicators: Optional[Dict] = None
    ) -> List[ResonanceSignal]:
        """
        综合评估股票，返回所有触发的信号
        """
        signals = []
        
        # 检查各种策略
        signal1 = self.check_cross_period_macd_kdj(code, name, day_indicators, week_indicators)
        if signal1:
            signals.append(signal1)
        
        signal2 = self.check_trend_volume_momentum(code, name, day_indicators)
        if signal2:
            signals.append(signal2)
        
        signal3 = self.check_weekly_direction_daily_entry(code, name, day_indicators, week_indicators)
        if signal3:
            signals.append(signal3)
        
        signal4 = self.check_high_level_resonance(code, name, day_indicators, week_indicators, month_indicators)
        if signal4:
            signals.append(signal4)
        
        return signals


class StockFilter:
    """
    股票过滤类
    排除ST、停牌、科创板、北交所等
    """
    
    @staticmethod
    def filter_stock(code: str, name: str, day_data: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        过滤股票
        
        Returns:
            (是否通过, 原因)
        """
        # 排除ST和*ST
        if 'ST' in name or '*ST' in name:
            return False, "排除ST股票"
        
        # 排除科创板 (688开头)
        if code.startswith('688'):
            return False, "排除科创板"
        
        # 排除北交所 (8或4开头)
        if code.startswith('8') or code.startswith('4'):
            return False, "排除北交所"
        
        # 排除创业板 (300/301开头)
        if code.startswith('30'):
            return False, "排除创业板"
        
        # 排除停牌 (成交量为0或开盘价为0)
        if day_data:
            if day_data.get('volume', 0) == 0 or day_data.get('open', 0) == 0:
                return False, "排除停牌"
        
        return True, "通过"
