"""
多周期共振监控系统主程序
实现盘中实时监控和飞书通知
"""

import time
import json
import signal
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

from pytdx.hq import TdxHq_API

from data_fetcher import CrossPeriodDataFetcher
from resonance_strategy import MultiConditionResonance, StockFilter, ResonanceSignal
from feishu_notifier import NotificationManager


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('resonance_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class ResonanceMonitor:
    """
    多周期共振监控系统
    """

    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.api = None
        self.data_fetcher = None
        self.strategy = MultiConditionResonance()
        self.notification_manager = NotificationManager(config.get('notification', {}))

        # 监控参数
        self.scan_interval = config.get('monitor', {}).get('scan_interval', 300)  # 默认5分钟
        self.stock_limit = config.get('monitor', {}).get('stock_limit', 100)
        self.min_score = config.get('monitor', {}).get('min_score', 60)
        self.trading_hours_only = config.get('monitor', {}).get('trading_hours_only', True)

        # 状态追踪
        self.last_signals = {}  # 避免重复通知
        self.scan_count = 0
        self.total_signals_found = 0

        # 初始化连接
        self._init_connection()

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

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
            return 1  # 上海
        return 0  # 深圳

    def get_stock_pool(self) -> List[tuple]:
        """获取股票池"""
        stocks = []
        limit = self.stock_limit

        try:
            # 上海市场
            sh_count = self.api.get_security_count(1)
            sh_limit = min(sh_count, limit // 2)
            for start in range(0, sh_limit, 1000):
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if code.startswith('6') and len(code) == 6:
                            # 基础过滤
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 1, name))

            # 深圳市场
            sz_count = self.api.get_security_count(0)
            sz_limit = min(sz_count, limit // 2)
            for start in range(0, sz_limit, 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            # 基础过滤
                            passed, _ = StockFilter.filter_stock(code, name)
                            if passed:
                                stocks.append((code, 0, name))

        except Exception as e:
            logger.error(f"获取股票池失败: {e}")

        return stocks[:limit]

    def scan_stock(self, code: str, market: int, name: str) -> List[ResonanceSignal]:
        """扫描单个股票"""
        try:
            # 获取跨周期数据
            cross_data = self.data_fetcher.get_cross_period_data(code, market)

            if not cross_data['day']:
                return []

            # 过滤停牌
            day_data = cross_data['day'].iloc[-1].to_dict() if len(cross_data['day']) > 0 else None
            passed, reason = StockFilter.filter_stock(code, name, day_data)
            if not passed:
                return []

            # 计算各周期指标
            day_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['day'])
            week_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['week']) if cross_data['week'] is not None else None
            month_indicators = self.data_fetcher.get_latest_indicator_values(cross_data['month']) if cross_data['month'] is not None else None

            if not day_indicators:
                return []

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

            return signals

        except Exception as e:
            logger.debug(f"扫描 {code} 时出错: {e}")
            return []

    def scan_market(self) -> List[ResonanceSignal]:
        """扫描整个市场"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 开始第 {self.scan_count + 1} 次市场扫描")
        logger.info(f"{'='*60}")

        # 获取股票池
        stock_pool = self.get_stock_pool()
        logger.info(f"📊 股票池数量: {len(stock_pool)}")

        all_signals = []

        for i, (code, market, name) in enumerate(stock_pool):
            # 每10只股票暂停一下
            if i > 0 and i % 10 == 0:
                time.sleep(0.5)

            signals = self.scan_stock(code, market, name)

            if signals:
                # 只保留得分最高的信号
                best_signal = max(signals, key=lambda x: x.score)
                all_signals.append(best_signal)

                logger.info(f"📈 {code} {name}: {best_signal.signal_type.value} (得分: {best_signal.score})")

        # 按得分排序
        all_signals.sort(key=lambda x: x.score, reverse=True)

        logger.info(f"✅ 扫描完成，发现 {len(all_signals)} 个信号")

        return all_signals

    def process_signals(self, signals: List[ResonanceSignal]):
        """处理信号并发送通知"""
        if not signals:
            return

        new_signals = []

        for signal in signals:
            signal_key = f"{signal.code}_{signal.signal_type.value}"

            # 检查是否是新信号（避免重复通知）
            if signal_key not in self.last_signals:
                self.last_signals[signal_key] = datetime.now()
                new_signals.append(signal.to_dict())

        # 清理过期记录（超过1小时）
        now = datetime.now()
        expired_keys = [
            k for k, v in self.last_signals.items()
            if now - v > timedelta(hours=1)
        ]
        for k in expired_keys:
            del self.last_signals[k]

        # 发送新信号通知
        if new_signals:
            self.total_signals_found += len(new_signals)
            logger.info(f"🎯 发现 {len(new_signals)} 个新信号，发送通知...")

            # 批量发送
            self.notification_manager.notify_batch_signals(new_signals)

            # 单独发送高分信号（>=80分）
            high_score_signals = [s for s in new_signals if s.get('score', 0) >= 80]
            for signal in high_score_signals:
                logger.info(f"🔔 高分信号: {signal['code']} {signal['name']} (得分: {signal['score']})")

    def run(self):
        """运行监控主循环"""
        self.running = True

        logger.info("\n" + "="*60)
        logger.info("🚀 多周期共振监控系统启动")
        logger.info("="*60)
        logger.info(f"⏰ 扫描间隔: {self.scan_interval} 秒")
        logger.info(f"📊 股票数量: {self.stock_limit}")
        logger.info(f"🎯 最低得分: {self.min_score}")
        logger.info(f"📅 仅交易时间: {self.trading_hours_only}")
        logger.info("="*60)

        # 发送启动通知
        self.notification_manager.notify_system_status(
            'started',
            f'多周期共振监控系统已启动\n扫描间隔: {self.scan_interval}秒\n股票数量: {self.stock_limit}\n最低得分: {self.min_score}'
        )

        try:
            while self.running:
                try:
                    # 检查交易时间
                    if self.trading_hours_only and not self.is_trading_time():
                        logger.info("⏰ 非交易时间，休眠中...")
                        time.sleep(60)
                        continue

                    # 扫描市场
                    self.scan_count += 1
                    signals = self.scan_market()

                    # 处理信号
                    self.process_signals(signals)

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
                f'系统已停止\n扫描次数: {self.scan_count}\n发现信号: {self.total_signals_found}'
            )

            logger.info("\n" + "="*60)
            logger.info("👋 监控系统已停止")
            logger.info(f"📊 扫描次数: {self.scan_count}")
            logger.info(f"🎯 发现信号: {self.total_signals_found}")
            logger.info("="*60)


def load_config(config_path: str = 'config/config.json') -> Dict:
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"配置文件 {config_path} 不存在，使用默认配置")
        return get_default_config()
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
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
            "stock_limit": 100,
            "min_score": 60,
            "trading_hours_only": True
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

    parser = argparse.ArgumentParser(description='多周期共振监控系统')
    parser.add_argument('--config', '-c', default='config/config.json', help='配置文件路径')
    parser.add_argument('--interval', '-i', type=int, help='扫描间隔（秒）')
    parser.add_argument('--limit', '-l', type=int, help='股票数量限制')
    parser.add_argument('--score', '-s', type=int, help='最低信号得分')
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
    if args.always:
        config.setdefault('monitor', {})['trading_hours_only'] = False

    # 启动监控
    monitor = ResonanceMonitor(config)

    try:
        monitor.run()
    except Exception as e:
        logger.error(f"监控系统异常: {e}", exc_info=True)
        sys.exit(1)
