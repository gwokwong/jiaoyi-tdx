import pandas as pd
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


class PytdxBacktester:
    """
    基于 pytdx 的历史回测引擎
    """

    def __init__(self, config):
        self.config = config
        self.api = TdxHq_API()

        # 1. 连接服务器（为了下载历史数据）
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')
        if self.api.connect(ip, port):
            print(f"✅ 已连接服务器，准备拉取历史数据...")
        else:
            raise Exception("连接服务器失败")

        self.db = DatabaseManager(config)
        self.cash = config.get('account', 'initial_capital')
        self.positions = {}  # 回测期间的临时持仓
        self.equity_curve = []  # 记录每天的总资产，用于画图

    def fetch_history_data(self, code, start_date, end_date):
        """
        使用 pytdx 下载历史 K 线数据
        """
        market_id = 1 if code.startswith('6') else 0  # 判断是沪市还是深市
        data = []
        pos = 0

        print(f"📥 正在拉取 {code} 的历史数据，请稍候...")
        while True:
            # get_security_bars: 类别(4=日线), 市场, 代码, 起始位置, 数量
            # 每次拉取 800 条，循环拉取直到覆盖所需时间段
            chunk = self.api.get_security_bars(4, market_id, code, pos, 800)
            if not chunk: break
            data.extend(chunk)
            pos += 800
            # 限制最大拉取量，防止跑太久（演示用）
            if pos > 2000: break

        if not data: return None

        # 整理数据格式
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['datetime'])

        # 筛选出我们想要的时间段（只比较日期部分）
        df['date_only'] = df['date'].dt.date
        start_date_only = pd.to_datetime(start_date).date()
        end_date_only = pd.to_datetime(end_date).date()
        df = df[(df['date_only'] >= start_date_only) & (df['date_only'] <= end_date_only)]

        df.set_index('date', inplace=True)
        return df

    def run(self, code, start_date_str, end_date_str):
        """
        开始回测
        code: 股票代码
        start_date_str: 开始日期 '2025-01-01'
        end_date_str: 结束日期 '2025-12-31'
        """
        # 1. 获取数据
        df = self.fetch_history_data(code, pd.to_datetime(start_date_str), pd.to_datetime(end_date_str))
        if df is None:
            print("❌ 无数据，回测终止")
            return

        print(f"⏳ 开始回放历史行情 ({start_date_str} 至 {end_date_str})...")

        # 2. 逐天遍历（模拟时间的流逝）
        for current_date, row in df.iterrows():
            date_str = current_date.strftime('%Y-%m-%d')
            current_price = row['close']  # 当天的收盘价

            # --- 策略核心逻辑 ---

            # A. 检查持仓止损
            if code in self.positions:
                cost = self.positions[code]['cost']
                pnl_rate = (current_price - cost) / cost
                # 读取配置的止损线
                if pnl_rate <= self.config.get('strategy', 'stop_loss_rate'):
                    self.sell(code, current_price, date_str)

            # B. 模拟买入信号
            # 【重要】这里替换成你的神经网络模型判断
            # 示例：如果是阳线（收盘>开盘）且空仓，则买入
            if code not in self.positions and row['close'] > row['open']:
                self.buy(code, current_price, date_str)

            # C. 记录当天的总资产（用于最后画净值曲线）
            self.record_equity(date_str, current_price)

        # 3. 回测结束，输出报告
        self.report()
        self.api.disconnect()
        self.db.close()

    def buy(self, code, price, date_str):
        """模拟买入"""
        vol = 1000  # 假设每次买 1000 股
        cost = price * vol
        fee = cost * self.config.get('fees', 'commission_rate')

        if self.cash >= cost + fee:
            self.cash -= (cost + fee)
            self.positions[code] = {'vol': vol, 'cost': price}
            # 写入数据库，方便复盘查看
            self.db.save_trade(code, 'BUY', price, vol,
                               self.config.get('fees', 'commission_rate'), 0)
            print(f"[{date_str}] 🟢 买入 {code} @ {price:.2f}")

    def sell(self, code, price, date_str):
        """模拟卖出"""
        vol = self.positions[code]['vol']
        income = price * vol
        # 卖出有印花税
        comm = income * self.config.get('fees', 'commission_rate')
        tax = income * self.config.get('fees', 'stamp_duty_rate')

        self.cash += (income - comm - tax)
        self.db.save_trade(code, 'SELL', price, vol,
                           self.config.get('fees', 'commission_rate'),
                           self.config.get('fees', 'stamp_duty_rate'))
        del self.positions[code]
        print(f"[{date_str}] 🔴 卖出 {code} @ {price:.2f}")

    def record_equity(self, date_str, price):
        """计算当天的总资产 = 现金 + 持仓市值"""
        hold_val = sum(p['vol'] * price for p in self.positions.values())
        total = self.cash + hold_val
        self.equity_curve.append({'date': date_str, 'equity': total})

    def report(self):
        """输出回测报告"""
        if not self.equity_curve: return
        final_equity = self.equity_curve[-1]['equity']
        initial = self.config.get('account', 'initial_capital')

        print("\n" + "=" * 30)
        print("📈 回测报告")
        print("=" * 30)
        print(f"初始资金: {initial}")
        print(f"最终权益: {final_equity:.2f}")
        print(f"总收益率: {(final_equity - initial) / initial:.2%}")
        print("=" * 30)


if __name__ == "__main__":
    config = ConfigLoader()
    bt = PytdxBacktester(config)

    # 设置回测参数：股票代码, 开始日期, 结束日期
    # 选择阳线日期进行回测（会触发买入）
    test_date = '2026-04-08'  # 最近阳线日
    print(f"📅 回测日期: {test_date} (阳线，会买入)")
    bt.run('000001', test_date, test_date)