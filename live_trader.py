import time
import datetime
import logging
import signal
import sys
from contextlib import contextmanager
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class LiveTrader:
    """
    实盘交易器：负责连接实时行情，执行买卖
    优化点：
    1. 使用日志替代print，支持日志级别控制
    2. 添加异常处理和重连机制
    3. 添加止盈逻辑
    4. 批量获取实时价格
    5. 添加仓位管理和风险控制
    6. 添加滑点、最小交易单位等实盘细节
    7. 优雅退出和资源清理
    """

    # A股最小交易单位
    MIN_TRADE_UNIT = 100
    # 默认滑点（买入时加价，卖出时减价）
    DEFAULT_SLIPPAGE = 0.001  # 0.1%

    def __init__(self, config):
        self.config = config
        self.running = False
        self.api = None
        self.db = None

        # 风控参数（从配置读取，使用默认值）
        self.max_single_position = config.get('risk', 'max_single_position', default=0.10)
        self.max_total_position = config.get('risk', 'max_total_position', default=0.80)
        self.max_positions = config.get('risk', 'max_positions', default=10)
        self.stop_loss = config.get('strategy', 'stop_loss_rate', default=-0.05)
        self.take_profit = config.get('strategy', 'take_profit_rate', default=0.10)
        self.slippage = config.get('trading', 'slippage', default=self.DEFAULT_SLIPPAGE)

        # 账户状态
        self.cash = 0.0
        self.positions = {}
        self.daily_stats = {
            'buy_count': 0,
            'sell_count': 0,
            'max_buys_per_day': config.get('risk', 'max_buys_per_day', default=5)
        }

        # 初始化连接
        self._init_connection()
        self._init_account()

        # 设置信号处理（优雅退出）
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("🚀 实盘策略引擎初始化完成")

    def _init_connection(self):
        """初始化通达信连接，带重试机制"""
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                self.api = TdxHq_API()
                ip = self.config.get('tdx', 'server_ip')
                port = self.config.get('tdx', 'server_port')

                if self.api.connect(ip, port):
                    logger.info(f"✅ 已连接通达信服务器 ({ip}:{port})")
                    return
                else:
                    raise ConnectionError(f"连接通达信服务器失败 ({ip}:{port})")

            except Exception as e:
                logger.warning(f"连接尝试 {attempt + 1}/{max_retries} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise Exception(f"连接通达信失败，已重试{max_retries}次，请检查网络或IP配置")

    def _init_account(self):
        """初始化账户和数据库"""
        try:
            self.db = DatabaseManager(self.config)
            # 从数据库加载之前的持仓
            self.positions = self.db.load_positions()
            logger.info(f"📊 从数据库加载 {len(self.positions)} 只持仓")

            # 从数据库读取现金余额，如果没有则使用配置文件的初始资金
            db_cash = self.db.get_cash_balance() if hasattr(self.db, 'get_cash_balance') else None
            if db_cash is not None:
                self.cash = db_cash
                logger.info(f"💰 从数据库加载现金余额: {self.cash:,.2f}")
            else:
                self.cash = self.config.get('account', 'initial_capital', default=100000.0)
                logger.info(f"💰 使用初始资金: {self.cash:,.2f}")

        except Exception as e:
            logger.error(f"初始化账户失败: {e}")
            raise

    def _signal_handler(self, signum, frame):
        """信号处理函数，实现优雅退出"""
        logger.info(f"\n👋 接收到信号 {signum}，正在优雅退出...")
        self.running = False

    def _cleanup(self):
        """资源清理"""
        logger.info("🧹 正在清理资源...")
        try:
            if self.db:
                self.db.close()
                logger.info("✅ 数据库连接已关闭")
        except Exception as e:
            logger.error(f"关闭数据库连接失败: {e}")

        try:
            if self.api:
                self.api.disconnect()
                logger.info("✅ 通达信连接已断开")
        except Exception as e:
            logger.error(f"断开通达信连接失败: {e}")

    def run(self):
        """
        主循环：程序会一直在这里跑，直到接收到停止信号
        """
        self.running = True
        scan_interval = self.config.get('strategy', 'scan_interval', default=30)

        try:
            while self.running:
                try:
                    # 1. 检查是否在交易时间
                    if not self.is_trading_time():
                        self._handle_non_trading_time()
                        continue

                    # 2. 重置每日统计（新的一天）
                    self._reset_daily_stats_if_needed()

                    # 3. 监控现有持仓（检查止损/止盈）
                    self.check_positions()

                    # 4. 扫描市场新机会（选股）
                    self.scan_market()

                    # 5. 心跳等待
                    time.sleep(scan_interval)

                except Exception as e:
                    logger.error(f"主循环异常: {e}", exc_info=True)
                    # 短暂暂停后继续，避免异常时CPU空转
                    time.sleep(5)

        finally:
            self._cleanup()
            logger.info("👋 策略已停止")

    def _handle_non_trading_time(self):
        """处理非交易时间的逻辑"""
        now = datetime.datetime.now()

        # 判断是否是交易日（简化版，实际应该用交易日历）
        if now.weekday() >= 5:  # 周末
            next_open = self._get_next_trading_day(now)
            sleep_seconds = (next_open - now).total_seconds()
            logger.info(f"⏰ 周末休市，下次开盘: {next_open.strftime('%Y-%m-%d %H:%M')}")
            time.sleep(min(sleep_seconds, 3600))  # 最多休眠1小时
        else:
            # 盘中休市时间
            logger.info("⏰ 非交易时间，休眠中...")
            time.sleep(60)

    def _get_next_trading_day(self, from_date):
        """获取下一个交易日的开盘时间"""
        next_day = from_date + datetime.timedelta(days=1)
        while next_day.weekday() >= 5:  # 跳过周末
            next_day += datetime.timedelta(days=1)
        return next_day.replace(hour=9, minute=30, second=0, microsecond=0)

    def _reset_daily_stats_if_needed(self):
        """如果需要，重置每日统计"""
        # 这里可以实现按天重置统计逻辑
        pass

    def is_trading_time(self):
        """
        判断当前是否在 A 股开盘时间
        优化：添加对周末的判断
        """
        now = datetime.datetime.now()

        # 周末不开盘
        if now.weekday() >= 5:
            return False

        current_time = now.time()

        # 定义开盘时间段
        morning_start = datetime.time(9, 30)
        morning_end = datetime.time(11, 30)
        afternoon_start = datetime.time(13, 0)
        afternoon_end = datetime.time(15, 0)

        return (morning_start <= current_time <= morning_end) or \
               (afternoon_start <= current_time <= afternoon_end)

    def get_market_type(self, code):
        """
        根据股票代码判断市场类型
        0: 深圳, 1: 上海
        """
        if code.startswith('6'):
            return 1  # 上海
        elif code.startswith('0') or code.startswith('3'):
            return 0  # 深圳
        else:
            return 0  # 默认深圳

    def get_realtime_prices(self, codes):
        """
        批量获取股票实时价格
        返回: {code: {'price': float, 'bid': float, 'ask': float}, ...}
        """
        prices = {}

        if not codes:
            return prices

        try:
            # 通达信API限制，每次最多获取80只
            batch_size = 80
            for i in range(0, len(codes), batch_size):
                batch = codes[i:i + batch_size]

                # 构建市场代码列表
                market_codes = []
                for code in batch:
                    market = self.get_market_type(code)
                    market_codes.append((market, code))

                # 获取实时行情
                quotes = self.api.get_security_quotes(market_codes)

                if quotes:
                    for quote in quotes:
                        code = quote.get('code')
                        # 使用最新价，如果没有则使用收盘价
                        price = quote.get('price', 0)
                        if price == 0:
                            price = quote.get('close', 0)

                        # 买卖盘价格
                        bid = quote.get('bid1', price * 0.999) if price > 0 else 0
                        ask = quote.get('ask1', price * 1.001) if price > 0 else 0

                        prices[code] = {
                            'price': price,
                            'bid': bid,
                            'ask': ask,
                            'high': quote.get('high', 0),
                            'low': quote.get('low', 0),
                            'volume': quote.get('vol', 0)
                        }

        except Exception as e:
            logger.error(f"获取实时价格失败: {e}")

        return prices

    def check_positions(self):
        """
        持仓监控：遍历手里的每一只股票，看是否触发止损或止盈
        优化：批量获取价格，添加止盈逻辑
        """
        if not self.positions:
            return

        logger.info(f"--- 🛡️ 正在监控 {len(self.positions)} 只持仓 ---")

        # 批量获取所有持仓股票的实时价格
        codes = list(self.positions.keys())
        quotes = self.get_realtime_prices(codes)

        for code, pos in list(self.positions.items()):
            quote = quotes.get(code)

            if not quote or quote['price'] <= 0:
                logger.warning(f"⚠️ 无法获取 {code} 的实时价格，跳过检查")
                continue

            current_price = quote['price']
            cost_price = pos['cost']

            # 计算盈亏比例
            pnl_rate = (current_price - cost_price) / cost_price

            # 触发止损
            if pnl_rate <= self.stop_loss:
                logger.warning(f"🔴 触发止损 {code}，亏损 {pnl_rate:.2%}，执行卖出")
                self.execute_sell(code, current_price, pos['vol'])

            # 触发止盈
            elif pnl_rate >= self.take_profit:
                logger.info(f"🟢 触发止盈 {code}，盈利 {pnl_rate:.2%}，执行卖出")
                self.execute_sell(code, current_price, pos['vol'])

            else:
                # 正常持仓，打印盈亏情况
                logger.info(f"📊 {code}: 成本 {cost_price:.2f}, 现价 {current_price:.2f}, 盈亏 {pnl_rate:+.2%}")

    def scan_market(self):
        """
        市场扫描：选股逻辑
        优化：添加风险控制检查
        """
        # 检查是否达到最大持仓数
        if len(self.positions) >= self.max_positions:
            logger.debug(f"已达到最大持仓数 {self.max_positions}，暂停扫描")
            return

        # 检查当日买入次数限制
        if self.daily_stats['buy_count'] >= self.daily_stats['max_buys_per_day']:
            logger.debug(f"已达到当日最大买入次数 {self.daily_stats['max_buys_per_day']}，暂停扫描")
            return

        # 检查仓位限制
        total_position_value = sum(p['vol'] * p['cost'] for p in self.positions.values())
        total_capital = self.cash + total_position_value

        if total_position_value >= total_capital * self.max_total_position:
            logger.debug(f"已达到最大总仓位 {self.max_total_position:.0%}，暂停扫描")
            return

        # TODO: 在这里实现具体的选股逻辑
        # 示例：
        # candidates = self.select_stocks()
        # for stock in candidates:
        #     if self.can_buy(stock):
        #         self.execute_buy(stock['code'], stock['price'], stock['vol'])

        pass

    def can_buy(self, code, price, vol):
        """
        检查是否可以买入（风险控制）
        """
        # 检查是否已持仓
        if code in self.positions:
            logger.debug(f"{code} 已在持仓中")
            return False

        # 检查持仓数量限制
        if len(self.positions) >= self.max_positions:
            logger.warning(f"已达到最大持仓数 {self.max_positions}")
            return False

        # 检查当日买入次数
        if self.daily_stats['buy_count'] >= self.daily_stats['max_buys_per_day']:
            logger.warning(f"已达到当日最大买入次数")
            return False

        # 计算所需资金（含滑点）
        required = price * vol * (1 + self.slippage)
        fee = required * self.config.get('fees', 'commission_rate', default=0.00025)
        total_cost = required + fee

        # 检查资金是否充足
        if self.cash < total_cost:
            logger.warning(f"资金不足，需要 {total_cost:.2f}，可用 {self.cash:.2f}")
            return False

        # 检查单票仓位限制
        total_capital = self.cash + sum(p['vol'] * p['cost'] for p in self.positions.values())
        position_value = price * vol

        if position_value > total_capital * self.max_single_position:
            logger.warning(f"单票仓位超限，需要调整数量")
            return False

        return True

    def calculate_buy_volume(self, price, max_position_value=None):
        """
        计算可买入数量（考虑最小交易单位）
        """
        if max_position_value is None:
            # 默认使用单票最大仓位
            total_capital = self.cash + sum(p['vol'] * p['cost'] for p in self.positions.values())
            max_position_value = total_capital * self.max_single_position

        # 考虑滑点和手续费后的可用资金
        available_cash = self.cash / (1 + self.slippage) / (1 + self.config.get('fees', 'commission_rate', default=0.00025))

        # 取较小值
        max_value = min(max_position_value, available_cash)

        # 计算股数（100股整数倍）
        vol = int(max_value / price / self.MIN_TRADE_UNIT) * self.MIN_TRADE_UNIT

        return vol

    def execute_buy(self, code, price, vol=None):
        """
        执行买入操作
        优化：添加滑点、自动计算数量、完善错误处理
        """
        try:
            # 如果未指定数量，自动计算
            if vol is None:
                vol = self.calculate_buy_volume(price)

            if vol < self.MIN_TRADE_UNIT:
                logger.warning(f"计算数量 {vol} 小于最小交易单位 {self.MIN_TRADE_UNIT}")
                return False

            # 检查风控
            if not self.can_buy(code, price, vol):
                return False

            # 应用滑点（买入时加价）
            executed_price = price * (1 + self.slippage)
            required = executed_price * vol

            # 计算手续费
            commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
            min_commission = self.config.get('fees', 'min_commission', default=5.0)
            fee = max(required * commission_rate, min_commission)

            total_cost = required + fee

            # 执行买入
            if self.cash >= total_cost:
                self.cash -= total_cost

                # 更新内存持仓
                if code in self.positions:
                    # 加仓，计算新的成本价
                    old_pos = self.positions[code]
                    total_vol = old_pos['vol'] + vol
                    total_cost_basis = old_pos['cost'] * old_pos['vol'] + executed_price * vol
                    new_cost = total_cost_basis / total_vol
                    self.positions[code] = {'vol': total_vol, 'cost': new_cost}
                else:
                    self.positions[code] = {'vol': vol, 'cost': executed_price}

                # 写入数据库
                self.db.save_trade(code, 'BUY', executed_price, vol, commission_rate, 0)

                # 更新统计
                self.daily_stats['buy_count'] += 1

                logger.info(f"🟢 买入成交：{code} @ {executed_price:.3f}, 数量: {vol}, 手续费: {fee:.2f}")
                return True
            else:
                logger.error(f"❌ 资金不足，买入失败。需要: {total_cost:.2f}, 可用: {self.cash:.2f}")
                return False

        except Exception as e:
            logger.error(f"买入 {code} 时发生错误: {e}", exc_info=True)
            return False

    def execute_sell(self, code, price, vol=None):
        """
        执行卖出操作
        优化：添加滑点、支持部分卖出、完善错误处理
        """
        try:
            if code not in self.positions:
                logger.warning(f"⚠️ 持仓中不存在 {code}，无法卖出")
                return False

            pos = self.positions[code]

            # 如果未指定数量，卖出全部
            if vol is None or vol >= pos['vol']:
                vol = pos['vol']
                sell_all = True
            else:
                sell_all = False
                # 检查是否为100的整数倍
                vol = int(vol / self.MIN_TRADE_UNIT) * self.MIN_TRADE_UNIT
                if vol < self.MIN_TRADE_UNIT:
                    logger.warning(f"卖出数量 {vol} 小于最小交易单位")
                    return False

            # 应用滑点（卖出时减价）
            executed_price = price * (1 - self.slippage)
            income = executed_price * vol

            # 计算手续费
            commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
            min_commission = self.config.get('fees', 'min_commission', default=5.0)
            stamp_duty_rate = self.config.get('fees', 'stamp_duty_rate', default=0.001)

            comm = max(income * commission_rate, min_commission)
            tax = income * stamp_duty_rate
            total_fee = comm + tax

            self.cash += (income - total_fee)

            # 写入数据库
            self.db.save_trade(code, 'SELL', executed_price, vol, commission_rate, stamp_duty_rate)

            # 更新内存持仓
            if sell_all:
                del self.positions[code]
            else:
                pos['vol'] -= vol

            # 更新统计
            self.daily_stats['sell_count'] += 1

            # 计算盈亏
            cost_basis = pos['cost'] * vol
            profit = income - cost_basis - total_fee
            pnl_pct = profit / cost_basis if cost_basis > 0 else 0

            logger.info(f"🔴 卖出成交：{code} @ {executed_price:.3f}, 数量: {vol}, "
                       f"手续费: {total_fee:.2f}, 盈亏: {profit:+.2f} ({pnl_pct:+.2%})")
            return True

        except Exception as e:
            logger.error(f"卖出 {code} 时发生错误: {e}", exc_info=True)
            return False

    def get_account_summary(self):
        """
        获取账户汇总信息
        """
        total_position_value = 0
        unrealized_pnl = 0

        codes = list(self.positions.keys())
        quotes = self.get_realtime_prices(codes)

        for code, pos in self.positions.items():
            quote = quotes.get(code, {})
            current_price = quote.get('price', pos['cost'])
            market_value = pos['vol'] * current_price
            cost_value = pos['vol'] * pos['cost']

            total_position_value += market_value
            unrealized_pnl += (market_value - cost_value)

        total_assets = self.cash + total_position_value

        return {
            'cash': self.cash,
            'position_value': total_position_value,
            'total_assets': total_assets,
            'unrealized_pnl': unrealized_pnl,
            'position_count': len(self.positions),
            'positions': self.positions.copy()
        }

    def print_account_summary(self):
        """打印账户汇总"""
        summary = self.get_account_summary()

        logger.info("=" * 60)
        logger.info("📊 账户汇总")
        logger.info("=" * 60)
        logger.info(f"💰 现金余额: {summary['cash']:,.2f}")
        logger.info(f"📈 持仓市值: {summary['position_value']:,.2f}")
        logger.info(f"💵 总资产:   {summary['total_assets']:,.2f}")
        logger.info(f"📊 浮动盈亏: {summary['unrealized_pnl']:+.2f}")
        logger.info(f"📋 持仓数量: {summary['position_count']}")

        if summary['positions']:
            logger.info("\n📋 持仓明细:")
            for code, pos in summary['positions'].items():
                logger.info(f"   {code}: {pos['vol']}股 @ 成本{pos['cost']:.2f}")

        logger.info("=" * 60)


@contextmanager
def trader_context(config):
    """
    上下文管理器，确保资源正确释放
    使用示例：
        with trader_context(config) as trader:
            trader.run()
    """
    trader = None
    try:
        trader = LiveTrader(config)
        yield trader
    except Exception as e:
        logger.error(f"交易器初始化失败: {e}", exc_info=True)
        raise
    finally:
        if trader:
            trader._cleanup()


if __name__ == "__main__":
    # 启动程序
    try:
        config = ConfigLoader()

        # 使用上下文管理器确保资源释放
        with trader_context(config) as trader:
            # 打印初始账户状态
            trader.print_account_summary()
            # 运行主循环
            trader.run()

    except FileNotFoundError as e:
        logger.error(f"配置文件错误: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        sys.exit(1)
