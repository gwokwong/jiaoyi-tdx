#!/usr/bin/env python3
"""
放量突破策略 - 全市场实时监控
策略逻辑：阳线 + 涨幅≥1% + 量比≥1.2 + 突破近期平台
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../resonance_alert/src'))

import time
import json
import signal
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from pytdx.hq import TdxHq_API

from data_fetcher import CrossPeriodDataFetcher
from feishu_notifier import NotificationManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('breakout_monitor.log', encoding='utf-8')
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
    signal_score: float
    
    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.buy_price) / self.buy_price


class BreakoutStrategyMonitor:
    """
    放量突破策略监控器
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.api = None
        self.data_fetcher = None
        self.notification_manager = NotificationManager(config.get('notification', {}))
        
        # 监控参数
        self.scan_interval = config.get('monitor', {}).get('scan_interval', 300)
        self.stock_limit = config.get('monitor', {}).get('stock_limit', 5500)
        self.min_score = config.get('monitor', {}).get('min_score', 70)
        self.trading_hours_only = config.get('monitor', {}).get('trading_hours_only', True)
        self.max_workers = config.get('monitor', {}).get('max_workers', 10)
        
        # 模拟交易参数
        self.simulate_trading = config.get('trading', {}).get('simulate', True)
        self.initial_capital = config.get('trading', {}).get('initial_capital', 1000000.0)
        self.position_size = config.get('trading', {}).get('position_size', 0.1)
        self.max_positions = config.get('trading', {}).get('max_positions', 10)
        self.stop_loss = config.get('trading', {}).get('stop_loss', -0.05)
        self.take_profit = config.get('trading', {}).get('take_profit', 0.10)
        
        # 策略参数
        self.min_change_pct = 1.0  # 最小涨幅
        self.min_vol_ratio = 1.2   # 最小量比
        self.platform_days = 20    # 平台期天数
        
        # 状态
        self.cash = self.initial_capital
        self.positions: Dict[str, SimulatedPosition] = {}
        self.trade_history = []
        self.last_signals = {}
        self.scan_count = 0
        self.stock_pool = []
        
        self._init_connection()
        self._init_stock_pool()
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _init_connection(self):
        """初始化通达信连接"""
        max_retries = 3
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
                    time.sleep(5)
                else:
                    raise
    
    def _init_stock_pool(self):
        """初始化股票池"""
        logger.info("📥 正在初始化股票池...")
        self.stock_pool = self._get_full_stock_pool()
        logger.info(f"✅ 股票池初始化完成，共 {len(self.stock_pool)} 只股票")
    
    def _signal_handler(self, signum, frame):
        logger.info(f"\n👋 接收到信号 {signum}，正在退出...")
        self.running = False
    
    def _cleanup(self):
        if self.api:
            try:
                self.api.disconnect()
                logger.info("✅ 通达信连接已断开")
            except:
                pass
    
    def is_trading_time(self) -> bool:
        if not self.trading_hours_only:
            return True
        
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        
        current_time = now.time()
        morning = (datetime.strptime("09:30", "%H:%M").time(), 
                   datetime.strptime("11:30", "%H:%M").time())
        afternoon = (datetime.strptime("13:00", "%H:%M").time(),
                     datetime.strptime("15:00", "%H:%M").time())
        
        return (morning[0] <= current_time <= morning[1]) or \
               (afternoon[0] <= current_time <= afternoon[1])
    
    def get_market_type(self, code: str) -> int:
        return 1 if code.startswith('6') else 0
    
    def _get_full_stock_pool(self) -> List[Tuple[str, int, str]]:
        """获取全市场股票池"""
        stocks = []
        limit = self.stock_limit
        
        try:
            # 上海市场
            logger.info("  正在获取上海市场股票...")
            sh_count = self.api.get_security_count(1)
            sh_limit = min(sh_count, limit)
            for start in range(0, sh_limit, 1000):
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if code.startswith('6') and len(code) == 6:
                            if 'ST' not in name and '*ST' not in name:
                                stocks.append((code, 1, name))
                if start > 0 and start % 1000 == 0:
                    time.sleep(0.3)
            
            # 深圳市场
            logger.info("  正在获取深圳市场股票...")
            sz_count = self.api.get_security_count(0)
            sz_limit = min(sz_count, limit - len(stocks))
            for start in range(0, sz_limit, 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            if 'ST' not in name and '*ST' not in name:
                                stocks.append((code, 0, name))
                if start > 0 and start % 1000 == 0:
                    time.sleep(0.3)
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
        
        return stocks[:limit]
    
    def check_breakout_signal(self, code: str, market: int, name: str) -> Optional[Dict]:
        """
        检查放量突破信号
        条件：
        1. 阳线（收盘价 > 开盘价）
        2. 涨幅 >= 1%
        3. 量比 >= 1.2
        4. 突破20日高点平台
        """
        try:
            # 获取日线数据
            df = self.data_fetcher.get_kline_data(code, market, 'day', 30)
            if df is None or len(df) < 20:
                return None
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # 1. 检查阳线
            is_yang = latest['close'] > latest['open']
            if not is_yang:
                return None
            
            # 2. 检查涨幅
            change_pct = (latest['close'] - prev['close']) / prev['close'] * 100
            if change_pct < self.min_change_pct:
                return None
            
            # 3. 检查量比
            vol_ma5 = df['volume'].rolling(window=5).mean().iloc[-1]
            vol_ratio = latest['volume'] / vol_ma5 if vol_ma5 > 0 else 0
            if vol_ratio < self.min_vol_ratio:
                return None
            
            # 4. 检查突破平台（20日高点）
            high_20 = df['high'].rolling(window=20).max().iloc[-2]  # 前19日高点
            if latest['close'] <= high_20:
                return None
            
            # 计算得分
            score = 70  # 基础分
            score += min(change_pct * 2, 15)  # 涨幅加分
            score += min((vol_ratio - 1.2) * 10, 10)  # 量比加分
            score += 5  # 突破平台加分
            
            return {
                'code': code,
                'name': name,
                'signal_type': '放量突破',
                'score': min(score, 100),
                'price': latest['close'],
                'change_pct': change_pct,
                'vol_ratio': vol_ratio,
                'high_20': high_20,
                'reasons': [
                    f"阳线上涨{change_pct:.2f}%",
                    f"量比{vol_ratio:.2f}倍",
                    f"突破20日高点{high_20:.2f}"
                ]
            }
            
        except Exception as e:
            logger.debug(f"检查 {code} 时出错: {e}")
            return None
    
    def scan_market(self) -> List[Dict]:
        """扫描市场"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 放量突破策略 - 第 {self.scan_count + 1} 次扫描")
        logger.info(f"{'='*60}")
        logger.info(f"📊 股票池: {len(self.stock_pool)} 只")
        
        all_signals = []
        scanned = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_stock = {
                executor.submit(self.check_breakout_signal, code, market, name): (code, name)
                for code, market, name in self.stock_pool
            }
            
            for future in as_completed(future_to_stock):
                code, name = future_to_stock[future]
                scanned += 1
                
                try:
                    signal = future.result()
                    if signal and signal['score'] >= self.min_score:
                        all_signals.append(signal)
                        logger.info(f"📈 {code} {name}: 放量突破 (得分: {signal['score']:.0f})")
                except Exception as e:
                    logger.debug(f"处理 {code} 出错: {e}")
                
                if scanned % 100 == 0:
                    logger.info(f"   进度: {scanned}/{len(self.stock_pool)}")
        
        all_signals.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f"✅ 发现 {len(all_signals)} 个信号")
        return all_signals
    
    def check_positions(self):
        """检查持仓"""
        if not self.positions:
            return
        
        logger.info(f"\n📊 检查 {len(self.positions)} 只持仓...")
        
        for code, pos in list(self.positions.items()):
            try:
                market = self.get_market_type(code)
                quotes = self.api.get_security_quotes([(market, code)])
                if not quotes:
                    continue
                
                current_price = quotes[0].get('price', 0)
                if current_price <= 0:
                    continue
                
                pnl_pct = pos.pnl_pct(current_price)
                
                if pnl_pct <= self.stop_loss:
                    self._execute_sell(code, pos, current_price, f"止损 ({pnl_pct*100:.2f}%)")
                elif pnl_pct >= self.take_profit:
                    self._execute_sell(code, pos, current_price, f"止盈 ({pnl_pct*100:.2f}%)")
                    
            except Exception as e:
                logger.debug(f"检查 {code} 持仓出错: {e}")
    
    def _execute_buy(self, signal: Dict) -> bool:
        """执行买入"""
        if not self.simulate_trading:
            return False
        
        code = signal['code']
        name = signal['name']
        
        if code in self.positions:
            return False
        
        if len(self.positions) >= self.max_positions:
            logger.info(f"⚠️ 已达到最大持仓数")
            return False
        
        price = signal['price']
        position_value = self.initial_capital * self.position_size
        volume = int(position_value / price / 100) * 100
        
        if volume < 100:
            return False
        
        cost = price * volume
        if self.cash < cost:
            logger.info(f"⚠️ 资金不足")
            return False
        
        self.cash -= cost
        self.positions[code] = SimulatedPosition(
            code=code, name=name, buy_price=price, volume=volume,
            buy_time=datetime.now(), signal_score=signal['score']
        )
        
        self.trade_history.append({
            'time': datetime.now(), 'code': code, 'name': name,
            'action': 'BUY', 'price': price, 'volume': volume, 'amount': cost
        })
        
        logger.info(f"🟢 【买入】{code} {name} @ {price:.2f} x {volume}股 = {cost:,.2f}")
        return True
    
    def _execute_sell(self, code: str, pos: SimulatedPosition, current_price: float, reason: str):
        """执行卖出"""
        if not self.simulate_trading:
            return
        
        volume = pos.volume
        income = current_price * volume
        pnl = (current_price - pos.buy_price) * volume
        pnl_pct = (current_price - pos.buy_price) / pos.buy_price
        
        self.cash += income
        
        self.trade_history.append({
            'time': datetime.now(), 'code': code, 'name': pos.name,
            'action': 'SELL', 'price': current_price, 'volume': volume,
            'amount': income, 'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': reason
        })
        
        del self.positions[code]
        
        logger.info(f"🔴 【卖出】{code} {pos.name} @ {current_price:.2f} | 盈亏: {pnl:+.2f} ({pnl_pct*100:+.2f}%) | {reason}")
    
    def process_signals(self, signals: List[Dict]):
        """处理信号"""
        if not signals:
            return
        
        new_signals = []
        for signal in signals:
            signal_key = f"{signal['code']}_{signal['signal_type']}"
            if signal_key not in self.last_signals:
                self.last_signals[signal_key] = datetime.now()
                new_signals.append(signal)
                if self.simulate_trading:
                    self._execute_buy(signal)
        
        # 清理过期记录
        now = datetime.now()
        expired = [k for k, v in self.last_signals.items() if now - v > timedelta(hours=1)]
        for k in expired:
            del self.last_signals[k]
        
        if new_signals:
            self.notification_manager.notify_batch_signals(new_signals)
    
    def print_status(self):
        """打印状态"""
        position_value = sum(pos.buy_price * pos.volume for pos in self.positions.values())
        total_value = self.cash + position_value
        total_return = (total_value - self.initial_capital) / self.initial_capital
        
        logger.info("\n" + "="*60)
        logger.info("📊 账户状态")
        logger.info(f"💰 初始: {self.initial_capital:,.2f} | 现金: {self.cash:,.2f} | 持仓: {position_value:,.2f}")
        logger.info(f"💎 总资产: {total_value:,.2f} | 收益: {total_return*100:+.2f}%")
        logger.info(f"📋 持仓: {len(self.positions)}/{self.max_positions}")
        if self.positions:
            for code, pos in self.positions.items():
                logger.info(f"   {code} {pos.name}: {pos.volume}股 @ {pos.buy_price:.2f}")
        logger.info("="*60)
    
    def run(self):
        """运行主循环"""
        self.running = True
        
        logger.info("\n" + "="*60)
        logger.info("🚀 放量突破策略监控启动")
        logger.info("="*60)
        logger.info(f"⏰ 扫描间隔: {self.scan_interval}秒 | 📊 股票: {len(self.stock_pool)} | 💰 模拟: {'开' if self.simulate_trading else '关'}")
        logger.info("="*60)
        
        self.notification_manager.notify_system_status('started', '放量突破策略监控已启动')
        
        try:
            while self.running:
                if not self.is_trading_time():
                    logger.info("⏰ 非交易时间，休眠中...")
                    time.sleep(60)
                    continue
                
                self.check_positions()
                self.scan_count += 1
                signals = self.scan_market()
                self.process_signals(signals)
                
                if self.simulate_trading:
                    self.print_status()
                
                logger.info(f"⏳ 等待 {self.scan_interval} 秒...")
                time.sleep(self.scan_interval)
                
        except Exception as e:
            logger.error(f"运行出错: {e}", exc_info=True)
        finally:
            self._cleanup()
            self.notification_manager.notify_system_status('stopped', '放量突破策略监控已停止')


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {
        "tdx": {"server_ip": "123.125.108.14", "server_port": 7709},
        "monitor": {"scan_interval": 300, "stock_limit": 5500, "min_score": 70, "trading_hours_only": True, "max_workers": 10},
        "trading": {"simulate": True, "initial_capital": 1000000, "position_size": 0.1, "max_positions": 10, "stop_loss": -0.05, "take_profit": 0.10},
        "notification": {"feishu": {"enabled": False, "webhook_url": "", "secret": ""}}
    }


if __name__ == "__main__":
    config = load_config()
    monitor = BreakoutStrategyMonitor(config)
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("\n👋 用户中断")
