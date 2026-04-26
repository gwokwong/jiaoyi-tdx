"""
跨周期数据获取模块
支持日线、周线、月线、分钟线数据获取
"""

import pandas as pd
import numpy as np
from pytdx.hq import TdxHq_API
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class CrossPeriodDataFetcher:
    """
    跨周期数据获取器
    实现通达信公式中的 #WEEK, #MONTH, #MIN60 等跨周期引用
    """

    # K线类型映射
    KLINE_TYPES = {
        '1min': 0,      # 1分钟
        '5min': 1,      # 5分钟
        '15min': 2,     # 15分钟
        '30min': 3,     # 30分钟
        '60min': 4,     # 60分钟
        'day': 9,       # 日线
        'week': 5,      # 周线
        'month': 6,     # 月线
    }

    def __init__(self, api: TdxHq_API):
        self.api = api

    def get_kline_data(self, code: str, market: int, period: str, count: int = 100) -> Optional[pd.DataFrame]:
        """
        获取K线数据

        Args:
            code: 股票代码
            market: 市场类型 (0=深圳, 1=上海)
            period: 周期类型 ('1min', '5min', '15min', '30min', '60min', 'day', 'week', 'month')
            count: 获取条数

        Returns:
            DataFrame 包含 OHLCV 数据
        """
        try:
            kline_type = self.KLINE_TYPES.get(period, 9)  # 默认日线
            data = self.api.get_security_bars(kline_type, market, code, 0, count)

            if not data:
                return None

            df = pd.DataFrame(data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

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
            logger.error(f"获取 {code} {period} 数据失败: {e}")
            return None

    def get_cross_period_data(self, code: str, market: int) -> Dict[str, Optional[pd.DataFrame]]:
        """
        获取多周期数据（跨周期引用）

        Returns:
            {
                'day': DataFrame,      # 日线
                'week': DataFrame,     # 周线
                'month': DataFrame,    # 月线
                '60min': DataFrame,    # 60分钟线
            }
        """
        return {
            'day': self.get_kline_data(code, market, 'day', 60),
            'week': self.get_kline_data(code, market, 'week', 30),
            'month': self.get_kline_data(code, market, 'month', 12),
            '60min': self.get_kline_data(code, market, '60min', 100),
            '30min': self.get_kline_data(code, market, '30min', 100),
        }

    def calculate_ma(self, df: pd.DataFrame, period: int) -> pd.Series:
        """计算移动平均线"""
        return df['close'].rolling(window=period).mean()

    def calculate_macd(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        计算MACD指标
        返回: {'dif': Series, 'dea': Series, 'macd': Series}
        """
        close = df['close']

        # EMA12 和 EMA26
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()

        # DIF
        dif = ema12 - ema26

        # DEA (DIF的9日EMA)
        dea = dif.ewm(span=9, adjust=False).mean()

        # MACD柱状线
        macd = (dif - dea) * 2

        return {
            'dif': dif,
            'dea': dea,
            'macd': macd
        }

    def calculate_kdj(self, df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> Dict[str, pd.Series]:
        """
        计算KDJ指标
        """
        low_list = df['low'].rolling(window=n, min_periods=n).min()
        high_list = df['high'].rolling(window=n, min_periods=n).max()
        rsv = (df['close'] - low_list) / (high_list - low_list) * 100

        k = rsv.ewm(alpha=1/m1, adjust=False).mean()
        d = k.ewm(alpha=1/m2, adjust=False).mean()
        j = 3 * k - 2 * d

        return {
            'k': k,
            'd': d,
            'j': j
        }

    def get_latest_indicator_values(self, df: pd.DataFrame) -> Dict:
        """
        获取最新指标值
        """
        if df is None or len(df) < 30:
            return {}

        # 计算指标
        df['ma5'] = self.calculate_ma(df, 5)
        df['ma10'] = self.calculate_ma(df, 10)
        df['ma20'] = self.calculate_ma(df, 20)
        df['ma60'] = self.calculate_ma(df, 60)
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()

        macd = self.calculate_macd(df)
        df['dif'] = macd['dif']
        df['dea'] = macd['dea']
        df['macd'] = macd['macd']

        kdj = self.calculate_kdj(df)
        df['k'] = kdj['k']
        df['d'] = kdj['d']
        df['j'] = kdj['j']

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest

        return {
            'close': latest['close'],
            'open': latest['open'],
            'high': latest['high'],
            'low': latest['low'],
            'volume': latest['volume'],
            'ma5': latest['ma5'],
            'ma10': latest['ma10'],
            'ma20': latest['ma20'],
            'ma60': latest['ma60'],
            'vol_ma5': latest['vol_ma5'],
            'vol_ma20': latest['vol_ma20'],
            'dif': latest['dif'],
            'dea': latest['dea'],
            'macd': latest['macd'],
            'k': latest['k'],
            'd': latest['d'],
            'j': latest['j'],
            'prev_close': prev['close'],
            'prev_dif': prev['dif'],
            'prev_dea': prev['dea'],
            'prev_j': prev['j'],
            'prev_ma20': prev['ma20'],
        }
