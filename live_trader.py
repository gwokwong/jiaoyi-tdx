import time
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader, DatabaseManager


class LiveTrader:
    """
    实盘交易器：负责连接实时行情，执行买卖
    """

    def __init__(self, config):
        self.config = config
        # 1. 连接通达信服务器
        self.api = TdxHq_API()
        ip = config.get('tdx', 'server_ip')
        port = config.get('tdx', 'server_port')

        if self.api.connect(ip, port):
            print(f"✅ 已连接通达信服务器 ({ip}:{port})")
        else:
            raise Exception("连接通达信失败，请检查网络或IP配置")

        # 2. 初始化数据库和账户
        self.db = DatabaseManager(config)
        # 从数据库加载之前的持仓（防止重启后丢失）
        self.positions = self.db.load_positions()
        # 模拟现金（实盘中建议从数据库读取余额，这里简化用配置文件的初始资金）
        self.cash = config.get('account', 'initial_capital')

        print("🚀 实盘策略引擎启动，开始监控市场...")

    def run(self):
        """
        主循环：程序会一直在这里跑，直到你按 Ctrl+C 停止
        """
        try:
            while True:
                # 1. 检查是否在交易时间（9:30-11:30, 13:00-15:00）
                if not self.is_trading_time():
                    # 非交易时间，每分钟检查一次，避免空转
                    print("⏰ 非交易时间，休眠中...")
                    time.sleep(60)
                    continue

                # 2. 监控现有持仓（检查止损/止盈）
                self.check_positions()

                # 3. 扫描市场新机会（选股）
                self.scan_market()

                # 4. 心跳等待（每隔 N 秒刷新一次，避免请求太频繁被封IP）
                time.sleep(self.config.get('strategy', 'scan_interval'))

        except KeyboardInterrupt:
            print("\n👋 检测到用户停止指令，策略停止")
            self.db.close()
            self.api.disconnect()

    def is_trading_time(self):
        """判断当前是否在 A 股开盘时间"""
        now = datetime.datetime.now().time()
        # 定义开盘时间段
        morning_start = datetime.time(9, 30)
        morning_end = datetime.time(11, 30)
        afternoon_start = datetime.time(13, 0)
        afternoon_end = datetime.time(15, 0)

        return (morning_start <= now <= morning_end) or \
            (afternoon_start <= now <= afternoon_end)

    def check_positions(self):
        """
        持仓监控：遍历手里的每一只股票，看是否触发止损
        """
        if not self.positions:
            return

        print(f"--- 🛡️ 正在监控 {len(self.positions)} 只持仓 ---")

        # 实际实盘中，这里应该批量获取所有持仓股票的实时价格
        # quotes = self.api.get_realtime_quotes(...)

        for code, pos in list(self.positions.items()):
            # 【重要】这里用 10.0 模拟现价，实际请替换为 quotes[i]['price']
            current_price = 10.0

            # 计算盈亏比例
            pnl_rate = (current_price - pos['cost']) / pos['cost']
            stop_loss = self.config.get('strategy', 'stop_loss_rate')

            # 触发止损
            if pnl_rate <= stop_loss:
                print(f"🔴 触发止损 {code}，亏损 {pnl_rate:.2%}，执行卖出")
                self.execute_sell(code, current_price, pos['vol'])

    def scan_market(self):
        """
        市场扫描：这里写你的选股逻辑
        建议流程：
        1. 获取全市场股票列表
        2. 循环判断每一只股票（量比、大单、神经网络信号）
        3. 如果满足条件，调用 self.execute_buy
        """
        # 这里为了演示，暂时留空
        # 你可以在这里加入你的“动量快速上涨信号”判断逻辑
        pass

    def execute_buy(self, code, price, vol):
        """执行买入操作"""
        required = price * vol
        # 计算手续费
        fee = required * self.config.get('fees', 'commission_rate')

        if self.cash >= required + fee:
            self.cash -= (required + fee)
            # 更新内存持仓
            self.positions[code] = {'vol': vol, 'cost': price}

            # 写入数据库
            self.db.save_trade(code, 'BUY', price, vol,
                               self.config.get('fees', 'commission_rate'), 0)
            print(f"🟢 买入成交：{code} @ {price}, 数量: {vol}")
        else:
            print("❌ 资金不足，买入失败")

    def execute_sell(self, code, price, vol):
        """执行卖出操作"""
        income = price * vol
        # 计算手续费（佣金+印花税）
        comm = income * self.config.get('fees', 'commission_rate')
        tax = income * self.config.get('fees', 'stamp_duty_rate')

        self.cash += (income - comm - tax)

        # 写入数据库
        self.db.save_trade(code, 'SELL', price, vol,
                           self.config.get('fees', 'commission_rate'),
                           self.config.get('fees', 'stamp_duty_rate'))

        # 从内存移除
        if code in self.positions:
            del self.positions[code]
        print(f"🔴 卖出成交：{code} @ {price}, 数量: {vol}")


if __name__ == "__main__":
    # 启动程序
    config = ConfigLoader()
    trader = LiveTrader(config)
    trader.run()