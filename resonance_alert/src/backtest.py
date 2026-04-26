#!/usr/bin/env python3
"""
多周期共振策略回测模块
支持单日回测和多日连续回测
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging

from pytdx.hq import TdxHq_API

from data_fetcher import CrossPeriodDataFetcher
from resonance_strategy import MultiConditionResonance, StockFilter, ResonanceSignal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    date: str
    code: str
    name: str
    action: str  # 'BUY' or 'SELL'
    price: float
    volume: int
    signal_type: str
    score: int
    reasons: List[str]
    pnl: float = 0.0  # 盈亏金额
    pnl_pct: float = 0.0  # 盈亏比例
    hold_days: int = 0  # 持仓天数


@dataclass
class BacktestResult:
    """回测结果"""
    date: str
    signals_found: int
    trades_executed: int
    daily_return: float
    positions: Dict
    cash: float
    total_value: float


class ResonanceBacktester:
    """
    多周期共振策略回测器
    """

    def __init__(self, config: Dict):
        self.config = config
        self.api = None
        self.data_fetcher = None
        self.strategy = MultiConditionResonance()

        # 回测参数
        self.initial_capital = config.get('backtest', {}).get('initial_capital', 1000000.0)
        self.position_size = config.get('backtest', {}).get('position_size', 0.1)  # 单票仓位10%
        self.max_positions = config.get('backtest', {}).get('max_positions', 5)
        self.stop_loss = config.get('backtest', {}).get('stop_loss', -0.05)
        self.take_profit = config.get('backtest', {}).get('take_profit', 0.10)
        self.hold_days_limit = config.get('backtest', {}).get('hold_days_limit', 5)

        # 回测状态
        self.cash = self.initial_capital
        self.positions = {}  # {code: {'volume': x, 'cost': y, 'buy_date': z}}
        self.trade_history = []
        self.daily_results = []
        self.signals_history = []

        # 初始化连接
        self._init_connection()

    def _init_connection(self):
        """初始化通达信连接"""
        try:
            self.api = TdxHq_API()
            ip = self.config.get('tdx', {}).get('server_ip', '123.125.108.14')
            port = self.config.get('tdx', {}).get('server_port', 7709)

            if self.api.connect(ip, port):
                logger.info(f"✅ 已连接通达信服务器 ({ip}:{port})")
                self.data_fetcher = CrossPeriodDataFetcher(self.api)
            else:
                raise ConnectionError(f"连接失败 ({ip}:{port})")
        except Exception as e:
            logger.error(f"连接通达信失败: {e}")
            raise

    def get_market_type(self, code: str) -> int:
        """判断市场类型"""
        if code.startswith('6'):
            return 1
        return 0

    def get_stock_pool(self, limit: int = 100) -> List[Tuple[str, int, str]]:
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
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 1, name))

            # 深圳市场
            for start in range(0, min(500, limit), 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk[:limit//2]:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 0, name))
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")

        return stocks[:limit]

    def get_historical_data(self, code: str, market: int, date_str: str, days: int = 60) -> Optional[pd.DataFrame]:
        """
        获取历史数据直到指定日期
        """
        try:
            # 获取日线数据
            data = self.api.get_security_bars(9, market, code, 0, days * 2)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            # 筛选指定日期之前的数据
            target_date = pd.to_datetime(date_str)
            df = df[df.index <= target_date]

            if len(df) < 30:
                return None

            return df

        except Exception as e:
            logger.debug(f"获取 {code} 历史数据失败: {e}")
            return None

    def get_day_data(self, code: str, market: int, date_str: str) -> Optional[Dict]:
        """获取指定日期的数据"""
        try:
            df = self.get_historical_data(code, market, date_str, days=1)
            if df is None or len(df) == 0:
                return None

            # 获取指定日期的数据
            target_date = pd.to_datetime(date_str).date()
            day_data = df[df.index.date == target_date]

            if len(day_data) == 0:
                return None

            latest = day_data.iloc[-1]
            return {
                'open': latest['open'],
                'high': latest['high'],
                'low': latest['low'],
                'close': latest['close'],
                'volume': latest['vol'],
                'datetime': day_data.index[-1]
            }
        except Exception as e:
            return None

    def scan_date(self, date_str: str, stock_pool: List[Tuple[str, int, str]]) -> List[ResonanceSignal]:
        """
        扫描指定日期的信号
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📅 扫描日期: {date_str}")
        logger.info(f"{'='*60}")

        all_signals = []

        for i, (code, market, name) in enumerate(stock_pool):
            if i > 0 and i % 10 == 0:
                logger.info(f"   进度: {i}/{len(stock_pool)}")

            try:
                # 获取历史数据（包含指定日期）
                df = self.get_historical_data(code, market, date_str, days=60)
                if df is None or len(df) < 30:
                    continue

                # 获取周线和月线数据
                week_df = self.data_fetcher.get_kline_data(code, market, 'week', 30)
                month_df = self.data_fetcher.get_kline_data(code, market, 'month', 12)

                # 计算指标
                day_indicators = self.data_fetcher.get_latest_indicator_values(df)
                week_indicators = self.data_fetcher.get_latest_indicator_values(week_df) if week_df is not None else None
                month_indicators = self.data_fetcher.get_latest_indicator_values(month_df) if month_df is not None else None

                if not day_indicators:
                    continue

                # 评估信号
                signals = self.strategy.evaluate_stock(
                    code=code,
                    name=name,
                    day_indicators=day_indicators,
                    week_indicators=week_indicators,
                    month_indicators=month_indicators
                )

                # 过滤低分信号
                signals = [s for s in signals if s.score >= 60]

                if signals:
                    best_signal = max(signals, key=lambda x: x.score)
                    all_signals.append(best_signal)
                    logger.info(f"📈 {code} {name}: {best_signal.signal_type.value} (得分: {best_signal.score})")

            except Exception as e:
                logger.debug(f"扫描 {code} 出错: {e}")
                continue

        # 按得分排序
        all_signals.sort(key=lambda x: x.score, reverse=True)

        logger.info(f"\n✅ 扫描完成，发现 {len(all_signals)} 个信号")

        return all_signals

    def execute_buy(self, signal: ResonanceSignal, date_str: str) -> bool:
        """执行买入"""
        code = signal.code
        name = signal.name

        # 检查是否已持仓
        if code in self.positions:
            return False

        # 检查持仓数量
        if len(self.positions) >= self.max_positions:
            return False

        # 计算买入数量
        price = signal.day_indicators.get('close', 0)
        if price <= 0:
            return False

        position_value = self.initial_capital * self.position_size
        volume = int(position_value / price / 100) * 100

        if volume < 100:
            return False

        cost = price * volume

        # 检查资金
        if self.cash < cost:
            return False

        # 执行买入
        self.cash -= cost
        self.positions[code] = {
            'volume': volume,
            'cost': cost,
            'price': price,
            'buy_date': date_str,
            'name': name,
            'signal_type': signal.signal_type.value,
            'score': signal.score
        }

        # 记录交易
        trade = BacktestTrade(
            date=date_str,
            code=code,
            name=name,
            action='BUY',
            price=price,
            volume=volume,
            signal_type=signal.signal_type.value,
            score=signal.score,
            reasons=signal.reasons
        )
        self.trade_history.append(trade)

        logger.info(f"🟢 买入: {code} {name} @ {price:.2f} x {volume}股 = {cost:,.2f}")

        return True

    def check_sell(self, code: str, pos: Dict, date_str: str, current_price: float) -> bool:
        """检查是否需要卖出"""
        buy_price = pos['price']
        buy_date = datetime.strptime(pos['buy_date'], '%Y-%m-%d')
        current_date = datetime.strptime(date_str, '%Y-%m-%d')

        # 计算盈亏
        pnl_pct = (current_price - buy_price) / buy_price
        hold_days = (current_date - buy_date).days

        # 检查止损
        if pnl_pct <= self.stop_loss:
            return True

        # 检查止盈
        if pnl_pct >= self.take_profit:
            return True

        # 检查持仓天数限制
        if hold_days >= self.hold_days_limit:
            return True

        return False

    def execute_sell(self, code: str, pos: Dict, date_str: str, current_price: float, reason: str) -> bool:
        """执行卖出"""
        volume = pos['volume']
        buy_price = pos['price']
        buy_date = datetime.strptime(pos['buy_date'], '%Y-%m-%d')
        current_date = datetime.strptime(date_str, '%Y-%m-%d')

        # 计算盈亏
        income = current_price * volume
        cost = pos['cost']
        pnl = income - cost
        pnl_pct = (current_price - buy_price) / buy_price
        hold_days = (current_date - buy_date).days

        # 更新资金
        self.cash += income

        # 记录交易
        trade = BacktestTrade(
            date=date_str,
            code=code,
            name=pos['name'],
            action='SELL',
            price=current_price,
            volume=volume,
            signal_type=pos['signal_type'],
            score=pos['score'],
            reasons=[reason],
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_days=hold_days
        )
        self.trade_history.append(trade)

        # 移除持仓
        del self.positions[code]

        logger.info(f"🔴 卖出: {code} {pos['name']} @ {current_price:.2f} | 盈亏: {pnl:+.2f} ({pnl_pct*100:+.2f}%) | 持仓: {hold_days}天")

        return True

    def update_positions(self, date_str: str, stock_pool: List[Tuple[str, int, str]]):
        """更新持仓（检查卖出）"""
        if not self.positions:
            return

        logger.info(f"\n📊 检查 {len(self.positions)} 只持仓...")

        for code, pos in list(self.positions.items()):
            market = self.get_market_type(code)
            day_data = self.get_day_data(code, market, date_str)

            if not day_data:
                continue

            current_price = day_data['close']

            # 检查是否需要卖出
            if self.check_sell(code, pos, date_str, current_price):
                # 确定卖出原因
                pnl_pct = (current_price - pos['price']) / pos['price']
                if pnl_pct <= self.stop_loss:
                    reason = f"止损 ({pnl_pct*100:.2f}%)"
                elif pnl_pct >= self.take_profit:
                    reason = f"止盈 ({pnl_pct*100:.2f}%)"
                else:
                    reason = "持仓天数到期"

                self.execute_sell(code, pos, date_str, current_price, reason)

    def calculate_portfolio_value(self, date_str: str, stock_pool: List[Tuple[str, int, str]]) -> float:
        """计算组合总价值"""
        total_value = self.cash

        for code, pos in self.positions.items():
            market = self.get_market_type(code)
            day_data = self.get_day_data(code, market, date_str)

            if day_data:
                current_price = day_data['close']
                market_value = pos['volume'] * current_price
                total_value += market_value

        return total_value

    def backtest_single_day(self, date_str: str, stock_limit: int = 100) -> BacktestResult:
        """
        回测单日
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 开始回测: {date_str}")
        logger.info(f"{'='*80}")

        # 重置状态
        self.cash = self.initial_capital
        self.positions = {}
        self.trade_history = []

        # 获取股票池
        stock_pool = self.get_stock_pool(stock_limit)
        logger.info(f"📊 股票池: {len(stock_pool)} 只")

        # 扫描信号
        signals = self.scan_date(date_str, stock_pool)

        # 保存信号历史
        for signal in signals:
            self.signals_history.append({
                'date': date_str,
                'code': signal.code,
                'name': signal.name,
                'signal_type': signal.signal_type.value,
                'score': signal.score,
                'reasons': signal.reasons
            })

        # 执行买入（前N个信号）
        buy_count = 0
        for signal in signals[:self.max_positions]:
            if self.execute_buy(signal, date_str):
                buy_count += 1

        # 计算当日收盘价值
        total_value = self.calculate_portfolio_value(date_str, stock_pool)
        daily_return = (total_value - self.initial_capital) / self.initial_capital

        result = BacktestResult(
            date=date_str,
            signals_found=len(signals),
            trades_executed=buy_count,
            daily_return=daily_return,
            positions=self.positions.copy(),
            cash=self.cash,
            total_value=total_value
        )

        logger.info(f"\n📈 回测结果:")
        logger.info(f"   发现信号: {len(signals)}")
        logger.info(f"   执行买入: {buy_count}")
        logger.info(f"   当日收益: {daily_return*100:+.2f}%")
        logger.info(f"   总资产: {total_value:,.2f}")

        return result

    def backtest_multi_days(self, start_date: str, end_date: str, stock_limit: int = 100) -> List[BacktestResult]:
        """
        多日连续回测
        """
        # 生成交易日列表
        date_range = pd.date_range(start=start_date, end=end_date, freq='B')
        trading_days = [d.strftime('%Y-%m-%d') for d in date_range]

        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 多日回测: {start_date} 至 {end_date}")
        logger.info(f"📅 交易日: {len(trading_days)} 天")
        logger.info(f"{'='*80}")

        results = []

        for date_str in trading_days:
            # 更新持仓（检查卖出）
            stock_pool = self.get_stock_pool(stock_limit)
            self.update_positions(date_str, stock_pool)

            # 扫描新信号
            result = self.backtest_single_day(date_str, stock_limit)
            results.append(result)

        return results

    def generate_report(self, results: List[BacktestResult]):
        """生成回测报告"""
        print("\n" + "="*80)
        print("📊 回测报告")
        print("="*80)

        # 总体统计
        total_signals = sum(r.signals_found for r in results)
        total_trades = len(self.trade_history)
        buy_trades = [t for t in self.trade_history if t.action == 'BUY']
        sell_trades = [t for t in self.trade_history if t.action == 'SELL']

        # 计算收益
        final_value = results[-1].total_value if results else self.initial_capital
        total_return = (final_value - self.initial_capital) / self.initial_capital

        # 计算胜率
        if sell_trades:
            win_trades = [t for t in sell_trades if t.pnl > 0]
            loss_trades = [t for t in sell_trades if t.pnl <= 0]
            win_rate = len(win_trades) / len(sell_trades) * 100

            total_pnl = sum(t.pnl for t in sell_trades)
            avg_pnl = total_pnl / len(sell_trades)
        else:
            win_rate = 0
            total_pnl = 0
            avg_pnl = 0

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f}")
        print(f"   最终资金: {final_value:,.2f}")
        print(f"   总收益率: {total_return*100:+.2f}%")
        print(f"   总盈亏: {final_value - self.initial_capital:+.2f}")

        print(f"\n📈 交易统计:")
        print(f"   总信号数: {total_signals}")
        print(f"   买入次数: {len(buy_trades)}")
        print(f"   卖出次数: {len(sell_trades)}")
        print(f"   胜率: {win_rate:.1f}%")
        print(f"   总盈亏: {total_pnl:+.2f}")
        print(f"   平均盈亏: {avg_pnl:+.2f}")

        if sell_trades:
            print(f"   盈利次数: {len(win_trades)}")
            print(f"   亏损次数: {len(loss_trades)}")

        # 每日明细
        print(f"\n📅 每日明细:")
        print("-"*80)
        print(f"{'日期':<12} {'信号数':<8} {'交易数':<8} {'日收益率':<12} {'总资产':<15}")
        print("-"*80)

        for r in results:
            print(f"{r.date:<12} {r.signals_found:<8} {r.trades_executed:<8} {r.daily_return*100:<+11.2f}% {r.total_value:<15,.2f}")

        print("-"*80)

        # 交易明细
        if self.trade_history:
            print(f"\n📝 交易明细:")
            print("-"*100)
            print(f"{'日期':<12} {'操作':<6} {'代码':<10} {'名称':<10} {'价格':<10} {'数量':<8} {'盈亏':<12} {'持仓天数':<8}")
            print("-"*100)

            for t in self.trade_history:
                if t.action == 'SELL':
                    pnl_str = f"{t.pnl:+.2f}"
                    hold_str = str(t.hold_days)
                else:
                    pnl_str = "--"
                    hold_str = "--"

                print(f"{t.date:<12} {t.action:<6} {t.code:<10} {t.name:<10} {t.price:<10.2f} {t.volume:<8} {pnl_str:<12} {hold_str:<8}")

            print("-"*100)

        # 信号统计
        if self.signals_history:
            print(f"\n📊 信号类型统计:")
            signal_types = defaultdict(int)
            for s in self.signals_history:
                signal_types[s['signal_type']] += 1

            for signal_type, count in sorted(signal_types.items(), key=lambda x: x[1], reverse=True):
                print(f"   {signal_type}: {count}次")

        print("="*80)

    def close(self):
        """关闭连接"""
        if self.api:
            self.api.disconnect()
            logger.info("✅ 通达信连接已断开")


def load_config(config_path: str = 'config/config.json') -> Dict:
    """加载配置"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"配置文件不存在，使用默认配置")
        return {
            'tdx': {'server_ip': '123.125.108.14', 'server_port': 7709},
            'backtest': {
                'initial_capital': 1000000.0,
                'position_size': 0.1,
                'max_positions': 5,
                'stop_loss': -0.05,
                'take_profit': 0.10,
                'hold_days_limit': 5
            }
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='多周期共振策略回测')
    parser.add_argument('--date', '-d', required=True, help='回测日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', '-e', help='结束日期，用于多日回测')
    parser.add_argument('--config', '-c', default='config/config.json', help='配置文件路径')
    parser.add_argument('--limit', '-l', type=int, default=100, help='股票数量限制')
    parser.add_argument('--capital', type=float, default=1000000, help='初始资金')

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    config['backtest']['initial_capital'] = args.capital

    # 创建回测器
    backtester = ResonanceBacktester(config)

    try:
        if args.end_date:
            # 多日回测
            results = backtester.backtest_multi_days(args.date, args.end_date, args.limit)
        else:
            # 单日回测
            result = backtester.backtest_single_day(args.date, args.limit)
            results = [result]

        # 生成报告
        backtester.generate_report(results)

    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)
    finally:
        backtester.close()
