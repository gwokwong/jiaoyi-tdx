#!/usr/bin/env python3
"""
全市场多周期共振监控系统
支持监控整个A股5000+只股票
实现模拟买入和持仓管理
"""

import time
import json
import signal
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import logging

from pytdx.hq import TdxHq_API

from data_fetcher import CrossPeriodDataFetcher
from resonance_strategy import MultiConditionResonance, StockFilter, ResonanceSignal
from feishu_notifier import NotificationManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('full_market_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """模拟持仓"""
    code: str
    name: str
    buy_price: float
    volume: int
    buy_time: datetime
    signal_type: str
    signal_score: int
    
    def current_value(self, current_price: float) -> float:
        return current_price * self.volume
    
    def pnl(self, current_price: float) -> float:
        return (current_price - self.buy_price) * self.volume
    
    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.buy_price) / self.buy_price


@dataclass
class SimulatedTrade:
    """模拟交易记录"""
    time: datetime
    code: str
    name: str
    action: str  # 'BUY' or 'SELL'
    price: float
    volume: int
    amount: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""


class FullMarketMonitor:
    """
    全市场多周期共振监控系统
    支持监控整个A股5000+只股票
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.api = None
        self.data_fetcher = None
        self.strategy = MultiConditionResonance()
        self.notification_manager = NotificationManager(config.get('notification', {}))
        
        # 监控参数
        self.scan_interval = config.get('monitor', {}).get('scan_interval', 300)
        self.stock_limit = config.get('monitor', {}).get('stock_limit', 5500)  # 默认5500只
        self.min_score = config.get('monitor', {}).get('min_score', 60)
        self.trading_hours_only = config.get('monitor', {}).get('trading_hours_only', True)
        self.max_workers = config.get('monitor', {}).get('max_workers', 10)  # 并发线程数
        
        # 模拟交易参数
        self.simulate_trading = config.get('trading', {}).get('simulate', True)
        self.initial_capital = config.get('trading', {}).get('initial_capital', 1000000.0)
        self.position_size = config.get('trading', {}).get('position_size', 0.1)  # 单票仓位10%
        self.max_positions = config.get('trading', {}).get('max_positions', 10)
        self.stop_loss = config.get('trading', {}).get('stop_loss', -0.05)
        self.take_profit = config.get('trading', {}).get('take_profit', 0.10)
        
        # 状态追踪
        self.cash = self.initial_capital
        self.positions: Dict[str, SimulatedPosition] = {}
        self.trade_history: List[SimulatedTrade] = []
        self.last_signals: Dict[str, datetime] = {}
        self.scan_count = 0
        self.total_signals_found = 0
        self.daily_stats = {
            'buy_count': 0,
            'sell_count': 0,
            'max_buys_per_day': config.get('trading', {}).get('max_buys_per_day', 5)
        }
        
        # 股票池缓存
        self.stock_pool: List[Tuple[str, int, str]] = []
        self.stock_pool_updated: Optional[datetime] = None
        
        # 初始化
        self._init_connection()
        self._init_stock_pool()
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("🚀 全市场监控系统初始化完成")
    
    def _init_connection(self):
        """初始化通达信连接"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.api = TdxHq_API()
                ip = self.config.get('tdx', {}).get('server_ip', '123.125.108.14')
                port = self.config.get('tdx', {}).get('server_port', 7709)
                
                if self.api.connect(ip, port):
                    logger.info(f"✅ 已连接通达信服务器 ({ip}:{port})")
                    self.data_fetcher = CrossPeriodDataFetcher(self.api)
                    return
                else:
                    raise ConnectionError(f"连接失败 ({ip}:{port})")
                    
            except Exception as e:
                logger.warning(f"连接尝试 {attempt + 1}/{max_retries} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise Exception(f"连接通达信失败，已重试{max_retries}次")
    
    def _init_stock_pool(self):
        """初始化股票池"""
        logger.info("📥 正在初始化全市场股票池...")
        self.stock_pool = self._get_full_stock_pool()
        self.stock_pool_updated = datetime.now()
        logger.info(f"✅ 股票池初始化完成，共 {len(self.stock_pool)} 只股票")
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"\n👋 接收到信号 {signum}，正在优雅退出...")
        self.running = False
    
    def _cleanup(self):
        """资源清理"""
        logger.info("🧹 正在清理资源...")
        if self.api:
            try:
                self.api.disconnect()
                logger.info("✅ 通达信连接已断开")
            except Exception as e:
                logger.error(f"断开通达信连接失败: {e}")
    
    def is_trading_time(self) -> bool:
        """判断是否在交易时间"""
        if not self.trading_hours_only:
            return True
        
        now = datetime.now()
        
        # 周末不开盘
        if now.weekday() >= 5:
            return False
        
        current_time = now.time()
        
        # 交易时段
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()
        
        return (morning_start <= current_time <= morning_end) or \
               (afternoon_start <= current_time <= afternoon_end)
    
    def get_market_type(self, code: str) -> int:
        """判断市场类型"""
        if code.startswith('6'):
            return 1
        return 0
    
    def _get_full_stock_pool(self) -> List[Tuple[str, int, str]]:
        """
        获取全市场股票池
        支持获取5000+只股票
        """
        stocks = []
        limit = self.stock_limit
        
        try:
            # 上海市场 - 获取全部
            logger.info("  正在获取上海市场股票...")
            sh_count = self.api.get_security_count(1)
            logger.info(f"  上海市场共 {sh_count} 只股票")
            
            sh_limit = min(sh_count, limit)
            for start in range(0, sh_limit, 1000):
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        # 只保留6位数字代码的股票
                        if code.startswith('6') and len(code) == 6:
                            # 基础过滤
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 1, name))
                
                # 每获取1000只暂停一下，避免请求过快
                if start > 0 and start % 1000 == 0:
                    time.sleep(0.3)
            
            logger.info(f"  上海市场筛选后: {len(stocks)} 只")
            
            # 深圳市场 - 获取全部
            logger.info("  正在获取深圳市场股票...")
            sz_count = self.api.get_security_count(0)
            logger.info(f"  深圳市场共 {sz_count} 只股票")
            
            sz_limit = min(sz_count, limit - len(stocks))
            for start in range(0, sz_limit, 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        # 深圳主板(000开头)和中小板(002开头)和创业板(300/301开头)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            # 基础过滤
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 0, name))
                
                if start > 0 and start % 1000 == 0:
                    time.sleep(0.3)
            
            logger.info(f"  深圳市场筛选后: {len(stocks) - len([s for s in stocks if s[1] == 1])} 只")
            
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
        
        return stocks[:limit]
    
    def _scan_single_stock(self, code: str, market: int, name: str) -> Optional[ResonanceSignal]:
        """扫描单只股票"""
        try:
            # 获取跨周期数据
            cross_data = self.data_fetcher.get_cross_period_data(code, market)
            
            if not cross_data['day']:
                return None
            
            # 过滤停牌
            day_data = cross_data['day'].iloc[-1].to_dict() if len(cross_data['day']) > 0 else None
            passed, reason = StockFilter.filter_stock(code, name, day_data)
            if not passed:
                return None
            
            # 计算各周期指标
            day_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['day'])
            week_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['week']) if cross_data['week'] is not None else None
            month_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['month']) if cross_data['month'] is not None else None
            
            if not day_indicators:
                return None
            
            # 评估股票
            signals = self.strategy.evaluate_stock(
                code=code,
                name=name,
                day_indicators=day_indicators,
                week_indicators=week_indicators,
                month_indicators=month_indicators
            )
            
            # 过滤低分信号
            signals = [s for s in signals if s.score >= self.min_score]
            
            if signals:
                # 只保留得分最高的信号
                return max(signals, key=lambda x: x.score)
            
            return None
            
        except Exception as e:
            logger.debug(f"扫描 {code} 时出错: {e}")
            return None
    
    def scan_market_parallel(self) -> List[ResonanceSignal]:
        """
        并行扫描整个市场
        使用线程池提高扫描速度
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 开始第 {self.scan_count + 1} 次全市场扫描")
        logger.info(f"{'='*60}")
        logger.info(f"📊 股票池数量: {len(self.stock_pool)}")
        logger.info(f"🔄 并发线程数: {self.max_workers}")
        
        all_signals = []
        scanned_count = 0
        
        # 使用线程池并行扫描
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_stock = {
                executor.submit(self._scan_single_stock, code, market, name): (code, name)
                for code, market, name in self.stock_pool
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_stock):
                code, name = future_to_stock[future]
                scanned_count += 1
                
                try:
                    signal = future.result()
                    if signal:
                        all_signals.append(signal)
                        logger.info(f"📈 {code} {name}: {signal.signal_type.value} (得分: {signal.score})")
                except Exception as e:
                    logger.debug(f"处理 {code} 结果时出错: {e}")
                
                # 每扫描100只显示进度
                if scanned_count % 100 == 0:
                    logger.info(f"   进度: {scanned_count}/{len(self.stock_pool)}")
        
        # 按得分排序
        all_signals.sort(key=lambda x: x.score, reverse=True)
        
        logger.info(f"✅ 扫描完成，发现 {len(all_signals)} 个信号")
        
        return all_signals
    
    def scan_market_batch(self) -> List[ResonanceSignal]:
        """
        批量扫描市场（单线程，适合少量股票）
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 开始第 {self.scan_count + 1} 次市场扫描")
        logger.info(f"{'='*60}")
        logger.info(f"📊 股票池数量: {len(self.stock_pool)}")
        
        all_signals = []
        
        for i, (code, market, name) in enumerate(self.stock_pool):
            # 每10只股票暂停一下
            if i > 0 and i % 10 == 0:
                time.sleep(0.5)
            
            # 每100只显示进度
            if i > 0 and i % 100 == 0:
                logger.info(f"   进度: {i}/{len(self.stock_pool)}")
            
            signal = self._scan_single_stock(code, market, name)
            
            if signal:
                all_signals.append(signal)
                logger.info(f"📈 {code} {name}: {signal.signal_type.value} (得分: {signal.score})")
        
        # 按得分排序
        all_signals.sort(key=lambda x: x.score, reverse=True)
        
        logger.info(f"✅ 扫描完成，发现 {len(all_signals)} 个信号")
        
        return all_signals
    
    def check_positions(self):
        """检查持仓（止损/止盈）"""
        if not self.positions:
            return
        
        logger.info(f"\n📊 检查 {len(self.positions)} 只持仓...")
        
        for code, pos in list(self.positions.items()):
            try:
                # 获取实时价格
                market = self.get_market_type(code)
                quotes = self.api.get_security_quotes([(market, code)])
                
                if not quotes:
                    continue
                
                current_price = quotes[0].get('price', 0)
                if current_price <= 0:
                    continue
                
                # 计算盈亏
                pnl_pct = pos.pnl_pct(current_price)
                
                # 检查止损
                if pnl_pct <= self.stop_loss:
                    self._execute_sell(code, pos, current_price, f"止损 ({pnl_pct*100:.2f}%)")
                # 检查止盈
                elif pnl_pct >= self.take_profit:
                    self._execute_sell(code, pos, current_price, f"止盈 ({pnl_pct*100:.2f}%)")
                    
            except Exception as e:
                logger.debug(f"检查 {code} 持仓时出错: {e}")
    
    def _execute_buy(self, signal: ResonanceSignal) -> bool:
        """执行模拟买入"""
        if not self.simulate_trading:
            return False
        
        code = signal.code
        name = signal.name
        
        # 检查是否已持仓
        if code in self.positions:
            return False
        
        # 检查持仓数量限制
        if len(self.positions) >= self.max_positions:
            logger.info(f"⚠️ 已达到最大持仓数 {self.max_positions}")
            return False
        
        # 检查每日买入次数限制
        if self.daily_stats['buy_count'] >= self.daily_stats['max_buys_per_day']:
            logger.info(f"⚠️ 已达到每日最大买入次数 {self.daily_stats['max_buys_per_day']}")
            return False
        
        # 计算买入数量
        price = signal.day_indicators.get('close', 0)
        if price <= 0:
            return False
        
        position_value = self.initial_capital * self.position_size
        volume = int(position_value / price / 100) * 100
        
        if volume < 100:
            logger.info(f"⚠️ {code} 计算数量不足100股")
            return False
        
        cost = price * volume
        
        # 检查资金
        if self.cash < cost:
            logger.info(f"⚠️ 资金不足，需要 {cost:,.2f}，可用 {self.cash:,.2f}")
            return False
        
        # 执行买入
        self.cash -= cost
        position = SimulatedPosition(
            code=code,
            name=name,
            buy_price=price,
            volume=volume,
            buy_time=datetime.now(),
            signal_type=signal.signal_type.value,
            signal_score=signal.score
        )
        self.positions[code] = position
        
        # 记录交易
        trade = SimulatedTrade(
            time=datetime.now(),
            code=code,
            name=name,
            action='BUY',
            price=price,
            volume=volume,
            amount=cost,
            reason=f"{signal.signal_type.value} (得分: {signal.score})"
        )
        self.trade_history.append(trade)
        
        self.daily_stats['buy_count'] += 1
        
        logger.info(f"🟢 【模拟买入】{code} {name}")
        logger.info(f"    价格: {price:.2f} x {volume}股 = {cost:,.2f}")
        logger.info(f"    剩余资金: {self.cash:,.2f}")
        logger.info(f"    信号: {signal.signal_type.value} (得分: {signal.score})")
        
        return True
    
    def _execute_sell(self, code: str, pos: SimulatedPosition, current_price: float, reason: str):
        """执行模拟卖出"""
        if not self.simulate_trading:
            return
        
        volume = pos.volume
        income = current_price * volume
        
        # 计算盈亏
        pnl = pos.pnl(current_price)
        pnl_pct = pos.pnl_pct(current_price)
        
        # 更新资金
        self.cash += income
        
        # 记录交易
        trade = SimulatedTrade(
            time=datetime.now(),
            code=code,
            name=pos.name,
            action='SELL',
            price=current_price,
            volume=volume,
            amount=income,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason
        )
        self.trade_history.append(trade)
        
        # 移除持仓
        del self.positions[code]
        
        self.daily_stats['sell_count'] += 1
        
        logger.info(f"🔴 【模拟卖出】{code} {pos.name}")
        logger.info(f"    价格: {current_price:.2f} x {volume}股 = {income:,.2f}")
        logger.info(f"    盈亏: {pnl:+.2f} ({pnl_pct*100:+.2f}%)")
        logger.info(f"    原因: {reason}")
        logger.info(f"    剩余资金: {self.cash:,.2f}")
    
    def process_signals(self, signals: List[ResonanceSignal]):
        """处理信号"""
        if not signals:
            return
        
        new_signals = []
        
        for signal in signals:
            signal_key = f"{signal.code}_{signal.signal_type.value}"
            
            # 检查是否是新信号（避免重复通知）
            if signal_key not in self.last_signals:
                self.last_signals[signal_key] = datetime.now()
                new_signals.append(signal.to_dict())
                
                # 执行模拟买入
                if self.simulate_trading:
                    self._execute_buy(signal)
        
        # 清理过期记录（超过1小时）
        now = datetime.now()
        expired_keys = [
            k for k, v in self.last_signals.items()
            if now - v > timedelta(hours=1)
        ]
        for k in expired_keys:
            del self.last_signals[k]
        
        # 发送通知
        if new_signals:
            self.total_signals_found += len(new_signals)
            logger.info(f"🎯 发现 {len(new_signals)} 个新信号")
            self.notification_manager.notify_batch_signals(new_signals)
    
    def print_portfolio_status(self):
        """打印账户状态"""
        position_value = sum(pos.current_value(pos.buy_price) for pos in self.positions.values())
        total_value = self.cash + position_value
        total_return = (total_value - self.initial_capital) / self.initial_capital
        
        logger.info("\n" + "="*60)
        logger.info("📊 账户状态")
        logger.info("="*60)
        logger.info(f"💰 初始资金: {self.initial_capital:,.2f}")
        logger.info(f"💵 现金余额: {self.cash:,.2f}")
        logger.info(f"📈 持仓市值: {position_value:,.2f}")
        logger.info(f"💎 总资产:   {total_value:,.2f}")
        logger.info(f"📊 总收益:   {total_value - self.initial_capital:+.2f} ({total_return*100:+.2f}%)")
        logger.info(f"📋 持仓数量: {len(self.positions)}/{self.max_positions}")
        
        if self.positions:
            logger.info("\n📋 持仓明细:")
            for code, pos in self.positions.items():
                logger.info(f"   {code} {pos.name}: {pos.volume}股 @ {pos.buy_price:.2f} ({pos.signal_type})")
        
        logger.info("="*60)
    
    def reset_daily_stats(self):
        """重置每日统计"""
        self.daily_stats['buy_count'] = 0
        self.daily_stats['sell_count'] = 0
    
    def run(self):
        """运行监控主循环"""
        self.running = True
        last_date = datetime.now().date()
        
        logger.info("\n" + "="*60)
        logger.info("🚀 全市场多周期共振监控系统启动")
        logger.info("="*60)
        logger.info(f"⏰ 扫描间隔: {self.scan_interval} 秒")
        logger.info(f"📊 股票数量: {len(self.stock_pool)}")
        logger.info(f"🎯 最低得分: {self.min_score}")
        logger.info(f"💰 模拟交易: {'开启' if self.simulate_trading else '关闭'}")
        if self.simulate_trading:
            logger.info(f"💵 初始资金: {self.initial_capital:,.2f}")
            logger.info(f"📊 单票仓位: {self.position_size*100:.0f}%")
            logger.info(f"📋 最大持仓: {self.max_positions}")
        logger.info("="*60)
        
        # 发送启动通知
        self.notification_manager.notify_system_status(
            'started',
            f'全市场监控系统已启动\n股票数量: {len(self.stock_pool)}\n扫描间隔: {self.scan_interval}秒\n模拟交易: {"开启" if self.simulate_trading else "关闭"}'
        )
        
        try:
            while self.running:
                try:
                    now = datetime.now()
                    
                    # 检查是否是新的一天
                    if now.date() != last_date:
                        self.reset_daily_stats()
                        last_date = now.date()
                    
                    # 检查交易时间
                    if self.trading_hours_only and not self.is_trading_time():
                        logger.info("⏰ 非交易时间，休眠中...")
                        time.sleep(60)
                        continue
                    
                    # 检查持仓
                    self.check_positions()
                    
                    # 扫描市场
                    self.scan_count += 1
                    
                    # 根据股票数量选择扫描方式
                    if len(self.stock_pool) > 500:
                        signals = self.scan_market_parallel()
                    else:
                        signals = self.scan_market_batch()
                    
                    # 处理信号
                    self.process_signals(signals)
                    
                    # 打印账户状态
                    if self.simulate_trading:
                        self.print_portfolio_status()
                    
                    # 等待下次扫描
                    logger.info(f"⏳ 等待 {self.scan_interval} 秒后下次扫描...")
                    time.sleep(self.scan_interval)
                    
                except Exception as e:
                    logger.error(f"扫描循环出错: {e}", exc_info=True)
                    time.sleep(30)
                    
        finally:
            self._cleanup()
            
            # 发送停止通知
            self.notification_manager.notify_system_status(
                'stopped',
                f'系统已停止\n扫描次数: {self.scan_count}\n发现信号: {self.total_signals_found}\n最终资产: {self.cash + sum(pos.current_value(pos.buy_price) for pos in self.positions.values()):,.2f}'
            )
            
            logger.info("\n" + "="*60)
            logger.info("👋 监控系统已停止")
            logger.info(f"📊 扫描次数: {self.scan_count}")
            logger.info(f"🎯 发现信号: {self.total_signals_found}")
            if self.simulate_trading:
                self.print_portfolio_status()
            logger.info("="*60)


def load_config(config_path: str = '../config/config.json') -> Dict:
    """加载配置"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"配置文件不存在，使用默认配置")
        return get_default_config()


def get_default_config() -> Dict:
    """获取默认配置"""
    return {
        "tdx": {
            "server_ip": "123.125.108.14",
            "server_port": 7709
        },
        "monitor": {
            "scan_interval": 300,
            "stock_limit": 5500,
            "min_score": 60,
            "trading_hours_only": True,
            "max_workers": 10
        },
        "trading": {
            "simulate": True,
            "initial_capital": 1000000.0,
            "position_size": 0.1,
            "max_positions": 10,
            "stop_loss": -0.05,
            "take_profit": 0.10,
            "max_buys_per_day": 5
        },
        "notification": {
            "feishu": {
                "enabled": False,
                "webhook_url": "",
                "secret": ""
            }
        }
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='全市场多周期共振监控系统')
    parser.add_argument('--config', '-c', default='../config/config.json', help='配置文件路径')
    parser.add_argument('--interval', '-i', type=int, help='扫描间隔（秒）')
    parser.add_argument('--limit', '-l', type=int, help='股票数量限制')
    parser.add_argument('--score', '-s', type=int, help='最低信号得分')
    parser.add_argument('--workers', '-w', type=int, help='并发线程数')
    parser.add_argument('--no-trading', action='store_true', help='关闭模拟交易')
    parser.add_argument('--capital', type=float, help='初始资金')
    parser.add_argument('--always', '-a', action='store_true', help='非交易时间也运行')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 命令行参数覆盖配置
    if args.interval:
        config.setdefault('monitor', {})['scan_interval'] = args.interval
    if args.limit:
        config.setdefault('monitor', {})['stock_limit'] = args.limit
    if args.score:
        config.setdefault('monitor', {})['min_score'] = args.score
    if args.workers:
        config.setdefault('monitor', {})['max_workers'] = args.workers
    if args.no_trading:
        config.setdefault('trading', {})['simulate'] = False
    if args.capital:
        config.setdefault('trading', {})['initial_capital'] = args.capital
    if args.always:
        config.setdefault('monitor', {})['trading_hours_only'] = False
    
    # 启动监控
    monitor = FullMarketMonitor(config)
    
    try:
        monitor.run()
    except Exception as e:
        logger.error(f"监控系统异常: {e}", exc_info=True)
        sys.exit(1)
