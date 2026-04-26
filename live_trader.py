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
    功能：
    1. 盘中实时监控持仓（止损/止盈）
    2. 盘中实时选股并自动买入
    3. 完整的仓位管理和风险控制
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

        # 风控参数
        self.max_single_position = config.get('risk', 'max_single_position', default=0.10)
        self.max_total_position = config.get('risk', 'max_total_position', default=0.80)
        self.max_positions = config.get('risk', 'max_positions', default=10)
        self.max_buys_per_day = config.get('risk', 'max_buys_per_day', default=5)
        self.stop_loss = config.get('strategy', 'stop_loss_rate', default=-0.05)
        self.take_profit = config.get('strategy', 'take_profit_rate', default=0.10)
        self.slippage = config.get('trading', 'slippage', default=self.DEFAULT_SLIPPAGE)

        # 选股参数
        self.scan_stocks_count = config.get('strategy', 'scan_stocks_count', default=100)
        self.min_stock_price = config.get('strategy', 'min_stock_price', default=2.0)
        self.max_stock_price = config.get('strategy', 'max_stock_price', default=500.0)

        # 账户状态
        self.cash = 0.0
        self.positions = {}
        self.daily_stats = {
            'buy_count': 0,
            'sell_count': 0,
            'max_buys_per_day': self.max_buys_per_day,
            'last_scan_time': None
        }

        # 股票池缓存
        self.stock_pool = []  # [(code, market, name), ...]
        self.stock_pool_updated = None

        # 初始化
        self._init_connection()
        self._init_account()
        self._init_stock_pool()

        # 信号处理
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
                    raise Exception(f"连接通达信失败，已重试{max_retries}次")

    def _init_account(self):
        """初始化账户和数据库"""
        try:
            self.db = DatabaseManager(self.config)
            self.positions = self.db.load_positions()
            logger.info(f"📊 从数据库加载 {len(self.positions)} 只持仓")

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

    def _init_stock_pool(self):
        """初始化股票池"""
        logger.info("📥 正在初始化股票池...")
        self.stock_pool = self._get_stock_pool()
        self.stock_pool_updated = datetime.datetime.now()
        logger.info(f"✅ 股票池初始化完成，共 {len(self.stock_pool)} 只股票")

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
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
        """主循环"""
        self.running = True
        scan_interval = self.config.get('strategy', 'scan_interval', default=30)

        try:
            while self.running:
                try:
                    # 1. 检查是否在交易时间
                    if not self.is_trading_time():
                        self._handle_non_trading_time()
                        continue

                    # 2. 监控持仓（止损/止盈）
                    self.check_positions()

                    # 3. 扫描市场并执行买入
                    self.scan_market()

                    # 4. 心跳等待
                    time.sleep(scan_interval)

                except Exception as e:
                    logger.error(f"主循环异常: {e}", exc_info=True)
                    time.sleep(5)

        finally:
            self._cleanup()
            logger.info("👋 策略已停止")

    def _handle_non_trading_time(self):
        """处理非交易时间"""
        now = datetime.datetime.now()

        if now.weekday() >= 5:
            next_open = self._get_next_trading_day(now)
            sleep_seconds = (next_open - now).total_seconds()
            logger.info(f"⏰ 周末休市，下次开盘: {next_open.strftime('%Y-%m-%d %H:%M')}")
            time.sleep(min(sleep_seconds, 3600))
        else:
            logger.info("⏰ 非交易时间，休眠中...")
            time.sleep(60)

    def _get_next_trading_day(self, from_date):
        """获取下一个交易日"""
        next_day = from_date + datetime.timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += datetime.timedelta(days=1)
        return next_day.replace(hour=9, minute=30, second=0, microsecond=0)

    def is_trading_time(self):
        """判断是否在交易时间"""
        now = datetime.datetime.now()

        if now.weekday() >= 5:
            return False

        current_time = now.time()
        morning_start = datetime.time(9, 30)
        morning_end = datetime.time(11, 30)
        afternoon_start = datetime.time(13, 0)
        afternoon_end = datetime.time(15, 0)

        return (morning_start <= current_time <= morning_end) or \
               (afternoon_start <= current_time <= afternoon_end)

    def get_market_type(self, code):
        """根据代码判断市场类型"""
        if code.startswith('6'):
            return 1
        elif code.startswith('0') or code.startswith('3'):
            return 0
        return 0

    def _get_stock_pool(self):
        """
        获取股票池
        返回: [(code, market, name), ...]
        """
        stocks = []

        try:
            # 上海市场
            sh_count = self.api.get_security_count(1)
            sh_limit = min(sh_count, self.scan_stocks_count // 2)
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
            sz_limit = min(sz_count, self.scan_stocks_count // 2)
            for start in range(0, sz_limit, 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            stocks.append((code, 0, name))

        except Exception as e:
            logger.error(f"获取股票池失败: {e}")

        return stocks

    def get_history_data(self, code, market, days=60):
        """获取历史K线数据"""
        try:
            data = self.api.get_security_bars(9, market, code, 0, days)  # 9=1分钟线
            if not data or len(data) < 30:
                # 如果分钟线不足，尝试日线
                data = self.api.get_security_bars(4, market, code, 0, days)

            if not data:
                return None

            # 转换为列表格式
            bars = []
            for item in data:
                bars.append({
                    'datetime': item['datetime'],
                    'open': item['open'],
                    'high': item['high'],
                    'low': item['low'],
                    'close': item['close'],
                    'volume': item['vol'],
                    'amount': item.get('amount', 0)
                })

            return bars
        except Exception as e:
            logger.error(f"获取 {code} 历史数据失败: {e}")
            return None

    def calculate_indicators(self, bars):
        """计算技术指标"""
        if not bars or len(bars) < 30:
            return None

        # 计算MA
        closes = [b['close'] for b in bars]
        volumes = [b['volume'] for b in bars]

        latest = bars[-1]
        prev = bars[-2] if len(bars) >= 2 else latest

        # 简单移动平均线
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20

        # 成交量均线
        vol_ma5 = sum(volumes[-5:]) / 5
        vol_ma20 = sum(volumes[-20:]) / 20

        # 涨跌幅
        change_pct = (latest['close'] - prev['close']) / prev['close'] * 100 if prev['close'] > 0 else 0

        # 量比
        vol_ratio = latest['volume'] / vol_ma5 if vol_ma5 > 0 else 0

        # 是否阳线
        is_yang = latest['close'] > latest['open']

        return {
            'latest': latest,
            'prev': prev,
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'vol_ma5': vol_ma5,
            'vol_ma20': vol_ma20,
            'change_pct': change_pct,
            'vol_ratio': vol_ratio,
            'is_yang': is_yang,
            'high_20': max(b['high'] for b in bars[-20:]),
            'low_20': min(b['low'] for b in bars[-20:])
        }

    def check_buy_signals(self, indicators):
        """
        检查买入信号
        返回: (signal_type, score, reason) 或 None
        """
        if not indicators:
            return None

        ind = indicators
        latest = ind['latest']
        price = latest['close']

        # 价格过滤
        if price < self.min_stock_price or price > self.max_stock_price:
            return None

        signals = []

        # 策略1: 放量突破
        if (ind['is_yang'] and
            ind['change_pct'] >= 1.0 and
            ind['vol_ratio'] >= 1.2):
            signals.append(('放量突破', 3, f"阳线上涨{ind['change_pct']:.1f}%，放量{ind['vol_ratio']:.1f}倍"))

        # 策略2: 均线多头排列
        if (ind['ma5'] > ind['ma10'] > ind['ma20'] and
            price > ind['ma5']):
            signals.append(('均线多头', 2, "5/10/20日均线多头排列"))

        # 策略3: 接近新高
        near_high = price > ind['high_20'] * 0.98
        if near_high and ind['is_yang']:
            signals.append(('接近新高', 2, f"股价接近20日新高{ind['high_20']:.2f}"))

        # 策略4: 超跌反弹
        if len(signals) == 0:
            recent_bars = [b for b in [ind['latest'], ind['prev']] if b]
            if len(recent_bars) >= 2:
                recent_change = (recent_bars[-1]['close'] - recent_bars[0]['close']) / recent_bars[0]['close'] * 100
                if recent_change < -5 and ind['is_yang']:
                    signals.append(('超跌反弹', 2, f"近期下跌后反弹"))

        if signals:
            # 返回得分最高的信号
            best = max(signals, key=lambda x: x[1])
            return best

        return None

    def get_realtime_prices(self, codes):
        """批量获取实时价格"""
        prices = {}

        if not codes:
            return prices

        try:
            batch_size = 80
            for i in range(0, len(codes), batch_size):
                batch = codes[i:i + batch_size]
                market_codes = [(self.get_market_type(code), code) for code in batch]

                quotes = self.api.get_security_quotes(market_codes)

                if quotes:
                    for quote in quotes:
                        code = quote.get('code')
                        price = quote.get('price', 0)
                        if price == 0:
                            price = quote.get('close', 0)

                        prices[code] = {
                            'price': price,
                            'bid': quote.get('bid1', price * 0.999) if price > 0 else 0,
                            'ask': quote.get('ask1', price * 1.001) if price > 0 else 0,
                            'high': quote.get('high', 0),
                            'low': quote.get('low', 0),
                            'volume': quote.get('vol', 0),
                            'open': quote.get('open', 0)
                        }

        except Exception as e:
            logger.error(f"获取实时价格失败: {e}")

        return prices

    def check_positions(self):
        """监控持仓（止损/止盈）"""
        if not self.positions:
            return

        logger.info(f"--- 🛡️ 正在监控 {len(self.positions)} 只持仓 ---")

        codes = list(self.positions.keys())
        quotes = self.get_realtime_prices(codes)

        for code, pos in list(self.positions.items()):
            quote = quotes.get(code)

            if not quote or quote['price'] <= 0:
                logger.warning(f"⚠️ 无法获取 {code} 的实时价格")
                continue

            current_price = quote['price']
            cost_price = pos['cost']
            pnl_rate = (current_price - cost_price) / cost_price

            # 止损
            if pnl_rate <= self.stop_loss:
                logger.warning(f"🔴 触发止损 {code}，亏损 {pnl_rate:.2%}")
                self.execute_sell(code, current_price, pos['vol'])

            # 止盈
            elif pnl_rate >= self.take_profit:
                logger.info(f"🟢 触发止盈 {code}，盈利 {pnl_rate:.2%}")
                self.execute_sell(code, current_price, pos['vol'])

            else:
                logger.info(f"📊 {code}: 成本 {cost_price:.2f}, 现价 {current_price:.2f}, 盈亏 {pnl_rate:+.2%}")

    def scan_market(self):
        """
        盘中实时扫描市场，选股并买入
        """
        # 风险控制检查
        if len(self.positions) >= self.max_positions:
            return

        if self.daily_stats['buy_count'] >= self.max_buys_per_day:
            return

        total_position_value = sum(p['vol'] * p['cost'] for p in self.positions.values())
        total_capital = self.cash + total_position_value

        if total_position_value >= total_capital * self.max_total_position:
            return

        logger.info(f"--- 🔍 开始扫描市场（目标股票数: {len(self.stock_pool)}） ---")

        # 限制扫描数量，避免请求过于频繁
        scan_limit = min(50, len(self.stock_pool))
        candidates = []

        for i, (code, market, name) in enumerate(self.stock_pool[:scan_limit]):
            # 跳过已持仓
            if code in self.positions:
                continue

            try:
                # 获取历史数据
                bars = self.get_history_data(code, market, days=30)
                if not bars:
                    continue

                # 计算指标
                indicators = self.calculate_indicators(bars)
                if not indicators:
                    continue

                # 检查买入信号
                signal = self.check_buy_signals(indicators)
                if signal:
                    signal_type, score, reason = signal
                    latest = indicators['latest']

                    candidates.append({
                        'code': code,
                        'market': market,
                        'name': name,
                        'price': latest['close'],
                        'signal_type': signal_type,
                        'score': score,
                        'reason': reason,
                        'change_pct': indicators['change_pct'],
                        'vol_ratio': indicators['vol_ratio']
                    })

                    logger.info(f"📈 发现信号: {code} {name} | {signal_type} | {reason}")

            except Exception as e:
                logger.debug(f"扫描 {code} 时出错: {e}")
                continue

            # 每扫描10只股票暂停一下，避免请求过快
            if (i + 1) % 10 == 0:
                time.sleep(0.5)

        # 按得分排序，选择最佳候选
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]

            logger.info(f"\n🎯 最佳候选: {best['code']} {best['name']}")
            logger.info(f"   信号: {best['signal_type']}")
            logger.info(f"   原因: {best['reason']}")
            logger.info(f"   当前价: {best['price']:.2f}")

            # 执行买入
            self._execute_buy_for_candidate(best)
        else:
            logger.info("📭 本次扫描未发现买入信号")

    def _execute_buy_for_candidate(self, candidate):
        """为候选股票执行买入"""
        code = candidate['code']
        price = candidate['price']

        # 计算买入数量
        vol = self.calculate_buy_volume(price)

        if vol < self.MIN_TRADE_UNIT:
            logger.warning(f"计算数量不足 {self.MIN_TRADE_UNIT} 股，放弃买入")
            return

        # 检查风控
        if not self.can_buy(code, price, vol):
            return

        # 执行买入
        success = self.execute_buy(code, price, vol)

        if success:
            logger.info(f"✅ 成功买入 {code}，原因: {candidate['reason']}")

    def can_buy(self, code, price, vol):
        """检查是否可以买入"""
        if code in self.positions:
            return False

        if len(self.positions) >= self.max_positions:
            return False

        if self.daily_stats['buy_count'] >= self.max_buys_per_day:
            return False

        required = price * vol * (1 + self.slippage)
        fee = required * self.config.get('fees', 'commission_rate', default=0.00025)
        total_cost = required + fee

        if self.cash < total_cost:
            return False

        total_capital = self.cash + sum(p['vol'] * p['cost'] for p in self.positions.values())
        position_value = price * vol

        if position_value > total_capital * self.max_single_position:
            return False

        return True

    def calculate_buy_volume(self, price, max_position_value=None):
        """计算可买入数量"""
        if max_position_value is None:
            total_capital = self.cash + sum(p['vol'] * p['cost'] for p in self.positions.values())
            max_position_value = total_capital * self.max_single_position

        available_cash = self.cash / (1 + self.slippage) / (1 + self.config.get('fees', 'commission_rate', default=0.00025))
        max_value = min(max_position_value, available_cash)
        vol = int(max_value / price / self.MIN_TRADE_UNIT) * self.MIN_TRADE_UNIT

        return vol

    def execute_buy(self, code, price, vol=None):
        """执行买入"""
        try:
            if vol is None:
                vol = self.calculate_buy_volume(price)

            if vol < self.MIN_TRADE_UNIT:
                return False

            if not self.can_buy(code, price, vol):
                return False

            executed_price = price * (1 + self.slippage)
            required = executed_price * vol

            commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
            min_commission = self.config.get('fees', 'min_commission', default=5.0)
            fee = max(required * commission_rate, min_commission)

            total_cost = required + fee

            if self.cash >= total_cost:
                self.cash -= total_cost

                if code in self.positions:
                    old_pos = self.positions[code]
                    total_vol = old_pos['vol'] + vol
                    total_cost_basis = old_pos['cost'] * old_pos['vol'] + executed_price * vol
                    new_cost = total_cost_basis / total_vol
                    self.positions[code] = {'vol': total_vol, 'cost': new_cost}
                else:
                    self.positions[code] = {'vol': vol, 'cost': executed_price}

                self.db.save_trade(code, 'BUY', executed_price, vol, commission_rate, 0)
                self.daily_stats['buy_count'] += 1

                # 更新数据库中的现金余额
                if hasattr(self.db, 'update_cash_balance'):
                    self.db.update_cash_balance(self.cash)

                logger.info(f"🟢 买入成交：{code} @ {executed_price:.3f}, 数量: {vol}, 手续费: {fee:.2f}")
                return True
            else:
                logger.error(f"❌ 资金不足")
                return False

        except Exception as e:
            logger.error(f"买入 {code} 时发生错误: {e}", exc_info=True)
            return False

    def execute_sell(self, code, price, vol=None):
        """执行卖出"""
        try:
            if code not in self.positions:
                return False

            pos = self.positions[code]

            if vol is None or vol >= pos['vol']:
                vol = pos['vol']
                sell_all = True
            else:
                sell_all = False
                vol = int(vol / self.MIN_TRADE_UNIT) * self.MIN_TRADE_UNIT
                if vol < self.MIN_TRADE_UNIT:
                    return False

            executed_price = price * (1 - self.slippage)
            income = executed_price * vol

            commission_rate = self.config.get('fees', 'commission_rate', default=0.00025)
            min_commission = self.config.get('fees', 'min_commission', default=5.0)
            stamp_duty_rate = self.config.get('fees', 'stamp_duty_rate', default=0.001)

            comm = max(income * commission_rate, min_commission)
            tax = income * stamp_duty_rate
            total_fee = comm + tax

            self.cash += (income - total_fee)

            self.db.save_trade(code, 'SELL', executed_price, vol, commission_rate, stamp_duty_rate)

            if sell_all:
                del self.positions[code]
            else:
                pos['vol'] -= vol

            self.daily_stats['sell_count'] += 1

            # 更新数据库中的现金余额
            if hasattr(self.db, 'update_cash_balance'):
                self.db.update_cash_balance(self.cash)

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
        """获取账户汇总"""
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
    """上下文管理器"""
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
    try:
        config = ConfigLoader()

        with trader_context(config) as trader:
            trader.print_account_summary()
            trader.run()

    except FileNotFoundError as e:
        logger.error(f"配置文件错误: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        sys.exit(1)
