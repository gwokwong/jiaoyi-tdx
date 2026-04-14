#!/usr/bin/env python3
"""
简化版策略回测 - 用于演示五大策略逻辑
使用更宽松的条件确保能选出股票
"""

import pandas as pd
import numpy as np
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


class SimpleStrategyBacktester:
    """
    简化版策略回测器
    使用宽松的策略条件进行演示
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        # 连接服务器
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if not self.api.connect(ip, port):
            raise Exception("连接服务器失败")

        print(f"✅ 已连接通达信服务器 ({ip}:{port})")

        # 初始化数据库
        self.db = DatabaseManager(config)

        # 账户状态
        self.initial_capital = config.get('account', 'initial_capital')
        self.cash = self.initial_capital
        self.positions = {}
        self.trade_history = []
        self.daily_records = []

        # 动态获取A股股票池
        self.stock_pool = self.get_all_stocks()
        print(f"📋 股票池: 共 {len(self.stock_pool)} 只股票")

        # 创建代码到名称的映射
        self.stock_names = {code: name for code, market, name in self.stock_pool}

    def get_all_stocks(self):
        """
        动态获取A股所有股票
        返回: [(code, market, name), ...]
        """
        stocks = []
        print("📥 正在获取A股股票列表...")

        try:
            # 上海市场 (market=1)
            print("   获取上海市场...")
            sh_count = self.api.get_security_count(1)
            for start in range(0, min(sh_count, 2000), 1000):  # 限制数量，演示用
                chunk = self.api.get_security_list(1, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        # 只保留主板股票 (60xxxx)
                        if code.startswith('6') and len(code) == 6:
                            stocks.append((code, 1, name))

            # 深圳市场 (market=0)
            print("   获取深圳市场...")
            sz_count = self.api.get_security_count(0)
            for start in range(0, min(sz_count, 2000), 1000):
                chunk = self.api.get_security_list(0, start)
                if chunk:
                    for item in chunk:
                        code = item['code']
                        name = item.get('name', code)
                        # 只保留主板和中小板股票 (000/001/002/300)
                        if (code.startswith('0') or code.startswith('3')) and len(code) == 6:
                            stocks.append((code, 0, name))

        except Exception as e:
            print(f"   获取股票列表失败: {e}")
            # 使用默认股票池作为备用
            stocks = [
                ('000001', 0, '平安银行'), ('000002', 0, '万科A'), ('000063', 0, '中兴通讯'),
                ('000100', 0, 'TCL科技'), ('000333', 0, '美的集团'), ('000568', 0, '泸州老窖'),
                ('000625', 0, '长安汽车'), ('000651', 0, '格力电器'), ('000725', 0, '京东方A'),
                ('000858', 0, '五粮液'), ('002001', 0, '新和成'), ('002230', 0, '科大讯飞'),
                ('002304', 0, '洋河股份'), ('002415', 0, '海康威视'), ('002475', 0, '立讯精密'),
                ('002594', 0, '比亚迪'), ('300001', 0, '特锐德'), ('300750', 0, '宁德时代'),
                ('600000', 1, '浦发银行'), ('600004', 1, '白云机场'), ('600009', 1, '上海机场'),
                ('600010', 1, '包钢股份'), ('600015', 1, '华夏银行'), ('600016', 1, '民生银行'),
                ('600019', 1, '宝钢股份'), ('600028', 1, '中国石化'), ('600030', 1, '中信证券'),
                ('600031', 1, '三一重工'), ('600036', 1, '招商银行'), ('600048', 1, '保利发展'),
                ('600050', 1, '中国联通'), ('600061', 1, '国投资本'), ('600276', 1, '恒瑞医药'),
                ('600519', 1, '贵州茅台'),
            ]

        print(f"✅ 成功获取 {len(stocks)} 只股票")
        return stocks

    def get_history_data(self, code, market, days=60):
        """获取历史数据"""
        try:
            data = self.api.get_security_bars(4, market, code, 0, days)
            if not data:
                return None

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['datetime'])
            df.set_index('date', inplace=True)

            # 计算基础指标
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA10'] = df['close'].rolling(window=10).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()
            df['MA60'] = df['close'].rolling(window=60).mean()
            df['VOL_MA5'] = df['vol'].rolling(window=5).mean()

            # MACD
            ema12 = df['close'].ewm(span=12, adjust=False).mean()
            ema26 = df['close'].ewm(span=26, adjust=False).mean()
            df['DIF'] = ema12 - ema26
            df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
            df['MACD'] = (df['DIF'] - df['DEA']) * 2

            return df
        except:
            return None

    def check_strategies(self, df, date_str):
        """
        检查五大策略（简化版）
        只要满足其中一个策略就返回
        """
        if df is None or len(df) < 30:
            return None

        # 获取目标日期的数据
        target_date = pd.to_datetime(date_str)
        date_only = target_date.date()

        # 找到最接近的交易日
        df['date_only'] = df.index.date
        matching = df[df['date_only'] == date_only]

        if len(matching) == 0:
            return None

        idx = matching.index[-1]
        latest = df.loc[idx]

        # 获取前一日数据
        prev_idx = df.index[df.index < idx][-1] if len(df.index[df.index < idx]) > 0 else None
        if prev_idx is None:
            return None

        prev = df.loc[prev_idx]

        strategies_triggered = []

        # ========== 策略1: 放量突破（阳线+放量）==========
        is_yang = latest['close'] > latest['open']
        change_pct = (latest['close'] - prev['close']) / prev['close'] * 100 if prev['close'] > 0 else 0
        vol_ratio = latest['vol'] / latest['VOL_MA5'] if latest['VOL_MA5'] > 0 else 0

        if is_yang and change_pct >= 1.0 and vol_ratio >= 1.2:
            strategies_triggered.append({
                'name': '策略1_放量突破',
                'reason': f'阳线上涨{change_pct:.1f}%，放量{vol_ratio:.1f}倍',
                'score': 3
            })

        # ========== 策略2: 均线多头排列 ==========
        if latest['MA5'] > latest['MA10'] > latest['MA20']:
            # 股价在均线上方
            if latest['close'] > latest['MA5']:
                strategies_triggered.append({
                    'name': '策略2_均线多头',
                    'reason': '5/10/20日均线多头排列，股价在MA5上方',
                    'score': 2
                })

        # ========== 策略3: MACD金叉 ==========
        macd_cross = (prev['DIF'] <= prev['DEA']) and (latest['DIF'] > latest['DEA'])
        if macd_cross and latest['MACD'] > 0:
            strategies_triggered.append({
                'name': '策略3_MACD金叉',
                'reason': 'DIF上穿DEA，MACD柱状线为正',
                'score': 3
            })

        # ========== 策略4: 超跌反弹（黄金坑简化版）==========
        # 近5日跌幅超过5%，今日阳线反弹
        if len(df) >= 6:
            recent_5 = df.iloc[-6:-1]
            recent_change = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0] * 100

            if recent_change < -5 and is_yang and change_pct > 0.5:
                strategies_triggered.append({
                    'name': '策略4_超跌反弹',
                    'reason': f'近5日下跌{abs(recent_change):.1f}%，今日反弹{change_pct:.1f}%',
                    'score': 2
                })

        # ========== 策略5: 创新高回踩（简化版）==========
        if len(df) >= 20:
            high_20 = df['high'].iloc[-20:-1].max()
            if latest['close'] > high_20 * 0.98 and latest['close'] < high_20 * 1.02:
                # 接近20日新高
                if is_yang:
                    strategies_triggered.append({
                        'name': '策略5_接近新高',
                        'reason': f'股价接近20日新高，今日阳线',
                        'score': 2
                    })

        if strategies_triggered:
            # 返回得分最高的策略
            best = max(strategies_triggered, key=lambda x: x['score'])
            return {
                'signal': True,
                'strategy': best['name'],
                'reason': best['reason'],
                'all_strategies': [s['name'] for s in strategies_triggered],
                'price': latest['close'],
                'change': change_pct,
                'vol_ratio': vol_ratio
            }

        return None

    def scan_for_signals(self, date_str):
        """扫描股票池寻找信号"""
        print(f"\n🔍 正在扫描 {date_str} 的策略信号...")

        candidates = []

        for i, (code, market, name) in enumerate(self.stock_pool):
            if i % 5 == 0:
                print(f"   进度: {i}/{len(self.stock_pool)}", end='\r')

            df = self.get_history_data(code, market, days=60)
            signal = self.check_strategies(df, date_str)

            if signal and signal['signal']:
                candidates.append({
                    'code': code,
                    'name': name,
                    'market': market,
                    'strategy': signal['strategy'],
                    'reason': signal['reason'],
                    'all_strategies': signal['all_strategies'],
                    'buy_price': signal['price'],
                    'change': signal['change'],
                    'vol_ratio': signal['vol_ratio']
                })

        print(f"\n✅ 发现 {len(candidates)} 只符合条件的股票")
        return candidates

    def execute_buy(self, stock, date_str):
        """执行买入"""
        code = stock['code']
        name = stock.get('name', self.stock_names.get(code, '未知'))
        buy_price = stock['buy_price']
        market = stock['market']

        # 计算买入数量（单票最多2%仓位）
        position_value = self.initial_capital * 0.02
        vol = int(position_value / buy_price / 100) * 100

        if vol == 0:
            return False

        cost = buy_price * vol
        fee = cost * self.config.get('fees', 'commission_rate')

        if self.cash < cost + fee:
            return False

        self.cash -= (cost + fee)

        self.positions[code] = {
            'code': code,
            'name': name,
            'market': market,
            'vol': vol,
            'buy_price': buy_price,
            'buy_date': date_str,
            'cost': cost,
            'fee': fee,
            'strategy': stock['strategy']
        }

        self.trade_history.append({
            'date': date_str,
            'code': code,
            'name': name,
            'action': 'BUY',
            'price': buy_price,
            'vol': vol,
            'amount': cost,
            'fee': fee,
            'strategy': stock['strategy'],
            'reason': stock['reason'],
            'cash_after': self.cash
        })

        self.db.save_trade(code, 'BUY', buy_price, vol,
                          self.config.get('fees', 'commission_rate'), 0)

        print(f"   🟢 买入 {code} {name} @ {buy_price:.2f} x {vol}股 = {cost:.2f}元")
        print(f"      触发策略: {stock['strategy']}")
        print(f"      策略说明: {stock['reason']}")
        if len(stock['all_strategies']) > 1:
            print(f"      同时满足: {', '.join(stock['all_strategies'])}")

        return True

    def check_sell_signals(self, date_str):
        """
        检查卖出信号（五大卖出原则）
        1. 止盈止损（原有）
        2. 跌破关键支撑线（原则6）
        3. 头肩顶破颈线（原则7）
        4. MACD顶背离（原则8）
        5. 均线空头排列（原则9）
        """
        sold_stocks = []

        for code, pos in list(self.positions.items()):
            df = self.get_history_data(code, pos['market'], days=60)  # 需要更多历史数据
            if df is None or len(df) < 30:
                continue

            # 计算技术指标
            df = self.calculate_sell_indicators(df)
            if df is None:
                continue

            target_date = pd.to_datetime(date_str).date()
            df['date_only'] = df.index.date
            matching = df[df['date_only'] == target_date]

            if len(matching) == 0:
                continue

            current_price = matching.iloc[-1]['close']
            buy_price = pos['buy_price']
            pnl_pct = (current_price - buy_price) / buy_price

            # 检查各种卖出信号
            sell_signals = []

            # 1. 止盈止损
            stop_loss = -0.05  # 固定止损5%
            take_profit = 0.10   # 固定止盈10%

            if pnl_pct <= stop_loss:
                sell_signals.append(("止损", f"亏损达到{pnl_pct*100:.1f}%"))
            elif pnl_pct >= take_profit:
                sell_signals.append(("止盈", f"盈利达到{pnl_pct*100:.1f}%"))

            # 2. 原则6: 跌破关键支撑线（20日线）
            support_break = self.check_support_break(df)
            if support_break:
                sell_signals.append(("跌破支撑", "收盘价跌破20日均线且放量"))

            # 3. 原则7: 头肩顶破颈线（简化版：双顶形态）
            head_shoulder = self.check_head_shoulder(df)
            if head_shoulder:
                sell_signals.append(("形态破位", "双顶形态跌破颈线"))

            # 4. 原则8: MACD顶背离
            macd_divergence = self.check_macd_divergence(df)
            if macd_divergence:
                sell_signals.append(("MACD顶背离", "价格新高但MACD未新高"))

            # 5. 原则9: 均线空头排列
            ma_bearish = self.check_ma_bearish(df)
            if ma_bearish:
                sell_signals.append(("空头排列", "5/10/20/60日均线空头排列"))

            if sell_signals:
                vol = pos['vol']
                income = current_price * vol
                comm = income * self.config.get('fees', 'commission_rate')
                tax = income * self.config.get('fees', 'stamp_duty_rate')
                total_fee = comm + tax

                profit = income - pos['cost'] - total_fee - pos['fee']
                self.cash += (income - total_fee)

                name = pos.get('name', self.stock_names.get(code, '未知'))

                # 取第一个卖出信号
                action_type, reason = sell_signals[0]

                self.trade_history.append({
                    'date': date_str,
                    'code': code,
                    'name': name,
                    'action': 'SELL',
                    'price': current_price,
                    'vol': vol,
                    'amount': income,
                    'fee': total_fee,
                    'profit': profit,
                    'pnl_pct': pnl_pct * 100,
                    'type': action_type,
                    'reason': reason,
                    'cash_after': self.cash
                })

                self.db.save_trade(code, 'SELL', current_price, vol,
                                  self.config.get('fees', 'commission_rate'),
                                  self.config.get('fees', 'stamp_duty_rate'))

                print(f"   🔴 卖出 {code} {name} @ {current_price:.2f} | {action_type}")
                print(f"      原因: {reason}")
                print(f"      盈亏: {pnl_pct*100:+.2f}% | 收益: {profit:+.2f}元")

                del self.positions[code]
                sold_stocks.append(code)

        return sold_stocks

    def calculate_sell_indicators(self, df):
        """
        计算卖出所需的技术指标
        """
        if df is None or len(df) < 30:
            return None

        # 移动平均线
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['MACD'] = (df['DIF'] - df['DEA']) * 2

        # 成交量均线
        df['VOL_MA5'] = df['vol'].rolling(window=5).mean()

        return df

    def check_support_break(self, df):
        """
        原则6: 跌破关键支撑线（20日均线）
        条件:
        - 收盘价 < 20日均线 * 0.995
        - 昨日收盘价 > 20日均线
        - 放量(量比≥1.3) 或 大阴线(跌幅≥3%)
        """
        if len(df) < 2:
            return False

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 有效跌破: 收盘价 < 20日均线 * 0.995
        support_line = latest['MA20']
        break_down = latest['close'] < support_line * 0.995
        was_above = prev['close'] > prev['MA20']

        # 放量或大阴线
        vol_ratio = latest['vol'] / latest['VOL_MA5'] if latest['VOL_MA5'] > 0 else 0
        high_volume = vol_ratio >= 1.3

        change_pct = (latest['close'] - latest['open']) / latest['open'] * 100
        big_drop = change_pct <= -3

        return break_down and was_above and (high_volume or big_drop)

    def check_head_shoulder(self, df):
        """
        原则7: 头肩顶破颈线（简化版：双顶形态）
        条件:
        - 近30日有两个相近的高点（双顶）
        - 跌破颈线（两低点连线）
        - 放量破位
        """
        if len(df) < 30:
            return False

        recent = df.iloc[-30:]
        highs = recent['high'].values
        lows = recent['low'].values

        # 找近30日的两个最高点
        max1_idx = recent['high'].idxmax()
        max1_val = recent.loc[max1_idx, 'high']

        # 排除最高点附近的次高点
        exclude_range = 5
        mask = (recent.index < max1_idx - pd.Timedelta(days=exclude_range)) | \
               (recent.index > max1_idx + pd.Timedelta(days=exclude_range))
        remaining = recent[mask]

        if len(remaining) < 5:
            return False

        max2_idx = remaining['high'].idxmax()
        max2_val = remaining.loc[max2_idx, 'high']

        # 双顶条件：两个高点相近（差距<5%），且都较高
        if abs(max1_val - max2_val) / max1_val > 0.05:
            return False

        # 找颈线（两个高点之间的最低点）
        between = recent[(recent.index > min(max1_idx, max2_idx)) &
                         (recent.index < max(max1_idx, max2_idx))]
        if len(between) == 0:
            return False

        neckline = between['low'].min()

        # 当前价格跌破颈线
        latest = df.iloc[-1]
        break_neckline = latest['close'] < neckline * 0.995

        # 放量
        vol_ratio = latest['vol'] / latest['VOL_MA5'] if latest['VOL_MA5'] > 0 else 0
        high_volume = vol_ratio >= 1.5

        return break_neckline and high_volume

    def check_macd_divergence(self, df):
        """
        原则8: MACD顶背离
        条件:
        - 价格创近30日新高
        - MACD(DIF)未创新高（下降≥5%）
        - 柱状线未创新高
        - 量能萎缩（<前一高点80%）
        """
        if len(df) < 30:
            return False

        recent = df.iloc[-30:]

        # 价格新高
        price_high = recent['high'].max()
        latest_price = df.iloc[-1]['close']

        if latest_price < price_high * 0.98:  # 当前价格接近高点
            return False

        # 找到价格高点对应的MACD值
        high_idx = recent['high'].idxmax()
        macd_at_high = df.loc[high_idx, 'DIF']

        # 当前MACD
        latest_macd = df.iloc[-1]['DIF']

        # MACD未新高（下降≥5%）
        if latest_macd >= macd_at_high * 0.95:
            return False

        # 柱状线也未新高
        hist_at_high = df.loc[high_idx, 'MACD']
        latest_hist = df.iloc[-1]['MACD']

        if latest_hist >= hist_at_high * 0.95:
            return False

        return True

    def check_ma_bearish(self, df):
        """
        原则9: 均线空头排列
        条件:
        - 5日 < 10日 < 20日 < 60日
        - 股价连续3日在20日线下方
        - 无明显缩量企稳
        """
        if len(df) < 5:
            return False

        latest = df.iloc[-1]

        # 空头排列
        bearish = (latest['MA5'] < latest['MA10'] < latest['MA20'] < latest['MA60'])

        if not bearish:
            return False

        # 连续3日在20日线下方
        recent_3 = df.iloc[-3:]
        below_ma20 = all(recent_3['close'] < recent_3['MA20'])

        return below_ma20

    def record_daily_status(self, date_str):
        """记录每日状态"""
        hold_value = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        total = self.cash + hold_value

        self.daily_records.append({
            'date': date_str,
            'cash': self.cash,
            'hold_value': hold_value,
            'total': total,
            'positions': len(self.positions)
        })

    def run_backtest(self, start_date, end_date):
        """执行回测"""
        print("\n" + "="*80)
        print("📈 简化版策略回测系统")
        print("="*80)
        # 配置参数
        self.max_positions = 60  # 最大持仓数量
        self.min_cash_ratio = 0.5  # 最小现金比例(50%)，即总仓位不超过50%
        self.max_total_position = 0.5  # 最大总仓位50%

        print(f"\n💰 初始资金: {self.initial_capital:,.2f} 元")
        print(f"📅 回测期间: {start_date} 至 {end_date}")
        print(f"📋 股票池: {len(self.stock_pool)} 只股票")
        print(f"📊 策略: 五大策略（满足其一即可买入）")
        print(f"🛡️ 风控: 单票仓位≤2%, 最大持仓{self.max_positions}只, 总仓位≤50%, 止盈10%, 止损5%")
        print("\n" + "="*80)

        date_range = pd.date_range(start=start_date, end=end_date, freq='B')

        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"\n📅 {date_str}")
            print("-" * 60)

            # 1. 检查持仓卖出
            if self.positions:
                print(f"   检查 {len(self.positions)} 只持仓...")
                self.check_sell_signals(date_str)

            # 2. 选股买入
            if self.cash > self.initial_capital * self.min_cash_ratio and len(self.positions) < self.max_positions:
                candidates = self.scan_for_signals(date_str)

                # 买入前10只(增加买入数量)
                for stock in candidates[:10]:
                    if stock['code'] not in self.positions and len(self.positions) < self.max_positions:
                        self.execute_buy(stock, date_str)
            elif len(self.positions) >= self.max_positions:
                print(f"   持仓已满({self.max_positions}只)，暂停买入")
            else:
                print("   资金不足，暂停买入")

            self.record_daily_status(date_str)

        self.generate_report()

    def generate_report(self):
        """生成报告"""
        print("\n" + "="*80)
        print("📊 回测报告")
        print("="*80)

        final_record = self.daily_records[-1] if self.daily_records else {'total': self.cash}
        final_equity = final_record['total']
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        print(f"\n💰 资金状况:")
        print(f"   初始资金: {self.initial_capital:,.2f} 元")
        print(f"   最终资金: {final_equity:,.2f} 元")
        print(f"   总收益率: {total_return:+.2f}%")
        print(f"   现金余额: {self.cash:,.2f} 元")

        # 计算持仓市值和浮动盈亏
        hold_cost = sum(p['vol'] * p['buy_price'] for p in self.positions.values())
        hold_value = 0
        hold_profit = 0

        # 获取当前持仓的最新价格计算浮动盈亏
        for code, pos in self.positions.items():
            df = self.get_history_data(code, pos['market'], days=5)
            if df is not None and len(df) > 0:
                latest_price = df.iloc[-1]['close']
                current_value = pos['vol'] * latest_price
                hold_value += current_value
                hold_profit += current_value - pos['cost']
            else:
                hold_value += pos['vol'] * pos['buy_price']

        print(f"   持仓成本: {hold_cost:,.2f} 元")
        print(f"   持仓市值: {hold_value:,.2f} 元")
        print(f"   持仓盈亏: {hold_profit:,.2f} 元 ({hold_profit/hold_cost*100 if hold_cost > 0 else 0:+.2f}%)")

        buy_trades = [t for t in self.trade_history if t['action'] == 'BUY']
        sell_trades = [t for t in self.trade_history if t['action'] == 'SELL']

        print(f"\n📈 交易统计:")
        print(f"   买入次数: {len(buy_trades)}")
        print(f"   卖出次数: {len(sell_trades)}")

        # 已卖出股票盈亏统计
        if sell_trades:
            profits = [t['profit'] for t in sell_trades]
            win_trades = [p for p in profits if p > 0]
            lose_trades = [p for p in profits if p <= 0]

            print(f"\n📊 已卖出股票盈亏:")
            print(f"   盈利次数: {len(win_trades)}")
            print(f"   亏损次数: {len(lose_trades)}")
            print(f"   胜率: {len(win_trades)/len(sell_trades)*100:.1f}%")
            print(f"   总利润: {sum(profits):,.2f} 元")

            if win_trades:
                print(f"   平均盈利: {sum(win_trades)/len(win_trades):,.2f} 元")
            if lose_trades:
                print(f"   平均亏损: {sum(lose_trades)/len(lose_trades):,.2f} 元")

        # 策略分布
        print(f"\n📊 策略分布:")
        strategy_count = {}
        for t in buy_trades:
            strategy = t.get('strategy', '未知')
            strategy_count[strategy] = strategy_count.get(strategy, 0) + 1

        for strategy, count in sorted(strategy_count.items(), key=lambda x: x[1], reverse=True):
            print(f"   {strategy}: {count}次")

        # 当前持仓详情（含浮动盈亏）
        print(f"\n📋 当前持仓 ({len(self.positions)} 只) - 含浮动盈亏:")
        if self.positions:
            print("-"*100)
            print(f"{'代码':<10} {'名称':<10} {'数量':<10} {'成本价':<10} {'当前价':<10} {'成本':<12} {'市值':<12} {'盈亏':<12} {'盈亏%':<8}")
            print("-"*100)

            for code, pos in self.positions.items():
                name = pos.get('name', self.stock_names.get(code, '未知'))[:8]
                df = self.get_history_data(code, pos['market'], days=5)

                if df is not None and len(df) > 0:
                    latest_price = df.iloc[-1]['close']
                    current_value = pos['vol'] * latest_price
                    cost = pos['cost']
                    profit = current_value - cost
                    profit_pct = profit / cost * 100 if cost > 0 else 0

                    print(f"{code:<10} {name:<10} {pos['vol']:<10} {pos['buy_price']:<10.2f} {latest_price:<10.2f} "
                          f"{cost:<12.2f} {current_value:<12.2f} {profit:<12.2f} {profit_pct:<8.2f}%")
                else:
                    print(f"{code:<10} {name:<10} {pos['vol']:<10} {pos['buy_price']:<10.2f} {'--':<10} "
                          f"{pos['cost']:<12.2f} {'--':<12} {'--':<12} {'--':<8}")
            print("-"*100)
        else:
            print("   无持仓")

        # 已卖出明细
        if sell_trades:
            print(f"\n🔴 已卖出明细:")
            print("-"*100)
            print(f"{'日期':<12} {'代码':<10} {'名称':<10} {'卖出价':<10} {'成本价':<10} {'盈亏':<12} {'盈亏%':<8} {'类型':<6}")
            print("-"*100)

            for t in sell_trades:
                name = t.get('name', self.stock_names.get(t['code'], '未知'))[:8]
                buy_trade = next((b for b in buy_trades if b['code'] == t['code'] and b['date'] < t['date']), None)
                buy_price = buy_trade['price'] if buy_trade else 0
                profit_pct = t.get('pnl_pct', 0)

                print(f"{t['date']:<12} {t['code']:<10} {name:<10} {t['price']:<10.2f} {buy_price:<10.2f} "
                      f"{t.get('profit', 0):<12.2f} {profit_pct:<8.2f}% {t.get('type', '-'):<6}")
            print("-"*100)

        # ========== 新增：总体盈亏分析 ==========
        print(f"\n📊 总体盈亏分析:")
        print("-"*80)

        # 计算总体盈亏
        total_realized_profit = sum(t.get('profit', 0) for t in sell_trades) if sell_trades else 0
        total_unrealized_profit = hold_profit
        total_overall_profit = total_realized_profit + total_unrealized_profit

        print(f"   已实现盈亏（已卖出）: {total_realized_profit:,.2f} 元")
        print(f"   未实现盈亏（持仓中）: {total_unrealized_profit:,.2f} 元")
        print(f"   总体盈亏: {total_overall_profit:,.2f} 元 ({total_overall_profit/self.initial_capital*100:+.2f}%)")

        # 最大盈利和最大亏损
        if sell_trades:
            profits = [t.get('profit', 0) for t in sell_trades]
            max_profit = max(profits)
            max_loss = min(profits)
            print(f"\n   单笔最大盈利: {max_profit:,.2f} 元")
            print(f"   单笔最大亏损: {max_loss:,.2f} 元")

        # 每日盈亏统计
        print(f"\n📅 每日盈亏统计:")
        print("-"*80)
        print(f"{'日期':<12} {'当日盈亏':<15} {'盈亏比例':<12} {'累计盈亏':<15} {'累计收益率':<12}")
        print("-"*80)

        cumulative_profit = 0
        daily_changes = []

        for i, record in enumerate(self.daily_records):
            if i == 0:
                daily_profit = 0
                daily_return = 0
            else:
                prev_total = self.daily_records[i-1]['total']
                curr_total = record['total']
                daily_profit = curr_total - prev_total
                daily_return = daily_profit / self.initial_capital * 100

            cumulative_profit = record['total'] - self.initial_capital
            cumulative_return = cumulative_profit / self.initial_capital * 100
            daily_changes.append(daily_profit)

            # 只显示有交易的日期或每周第一天
            if daily_profit != 0 or i % 5 == 0 or i == len(self.daily_records) - 1:
                print(f"{record['date']:<12} {daily_profit:>+15,.2f} {daily_return:>+11.2f}% "
                      f"{cumulative_profit:>+15,.2f} {cumulative_return:>+11.2f}%")

        print("-"*80)

        # 统计信息
        if daily_changes:
            positive_days = [d for d in daily_changes if d > 0]
            negative_days = [d for d in daily_changes if d < 0]

            print(f"\n📈 每日盈亏统计:")
            print(f"   总交易日: {len(daily_changes)} 天")
            print(f"   盈利天数: {len(positive_days)} 天")
            print(f"   亏损天数: {len(negative_days)} 天")
            print(f"   持平天数: {len(daily_changes) - len(positive_days) - len(negative_days)} 天")

            if positive_days:
                print(f"   最大单日盈利: {max(positive_days):,.2f} 元")
                print(f"   平均单日盈利: {sum(positive_days)/len(positive_days):,.2f} 元")
            if negative_days:
                print(f"   最大单日亏损: {min(negative_days):,.2f} 元")
                print(f"   平均单日亏损: {sum(negative_days)/len(negative_days):,.2f} 元")

            print(f"   日均盈亏: {sum(daily_changes)/len(daily_changes):,.2f} 元")

        # 风险指标
        print(f"\n🛡️ 风险指标:")
        print("-"*80)

        # 计算最大回撤
        if self.daily_records:
            max_drawdown = 0
            max_equity = self.initial_capital
            max_dd_start = None
            max_dd_end = None

            for record in self.daily_records:
                if record['total'] > max_equity:
                    max_equity = record['total']
                else:
                    drawdown = (max_equity - record['total']) / max_equity * 100
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                        max_dd_end = record['date']

            print(f"   最大回撤: {max_drawdown:.2f}%")

        # 计算波动率（收益率的标准差）
        if len(daily_changes) > 1:
            daily_returns = [d / self.initial_capital * 100 for d in daily_changes]
            volatility = np.std(daily_returns) * np.sqrt(252)  # 年化波动率
            print(f"   年化波动率: {volatility:.2f}%")

            # 计算夏普比率（假设无风险利率为3%）
            avg_daily_return = np.mean(daily_returns)
            sharpe_ratio = (avg_daily_return * 252 - 3) / volatility if volatility > 0 else 0
            print(f"   夏普比率: {sharpe_ratio:.2f}")

        print("\n" + "="*80)

    def close(self):
        """关闭连接"""
        self.api.disconnect()
        self.db.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=30)
        start_date = start.strftime('%Y-%m-%d')
        end_date = end.strftime('%Y-%m-%d')
        print(f"使用默认日期范围: {start_date} 至 {end_date}")

    config = ConfigLoader()
    backtester = SimpleStrategyBacktester(config)

    try:
        backtester.run_backtest(start_date, end_date)
    finally:
        backtester.close()
