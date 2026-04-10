import sqlite3
import json
import os
import datetime


class ConfigLoader:
    """
    配置加载器：负责读取 config.json 文件
    """

    def __init__(self, config_file='config.json'):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"错误：找不到配置文件 {config_file}，请检查文件是否存在。")
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def get(self, *keys, default=None):
        """
        获取配置项，支持链式获取。
        例如：config.get('fees', 'commission_rate')
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


class DatabaseManager:
    """
    数据库管理器：负责保存交易记录和持仓信息
    使用 SQLite 轻量级数据库，无需安装额外软件。
    """

    def __init__(self, config):
        db_name = config.get('database', 'db_name')
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """
        创建两张表：
        1. positions: 当前持仓表（记录手里拿着什么票）
        2. trade_log: 历史交易流水表（记录每一笔买卖细节）
        """
        # 持仓表
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                code TEXT PRIMARY KEY,
                vol INTEGER NOT NULL,
                cost_price REAL NOT NULL,
                buy_time TEXT NOT NULL
            )
        ''')
        # 交易流水表
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_time TEXT NOT NULL,
                code TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                vol INTEGER NOT NULL,
                amount REAL NOT NULL,
                fee REAL NOT NULL,
                total_cost REAL NOT NULL
            )
        ''')
        self.conn.commit()

    def load_positions(self):
        """
        程序启动时调用：从数据库读取昨天的持仓
        保证程序重启后，不会忘记手里还拿着什么股票
        """
        self.cursor.execute("SELECT code, vol, cost_price, buy_time FROM positions")
        rows = self.cursor.fetchall()
        positions = {}
        for row in rows:
            # 组装成字典格式：{ '000001': {'vol': 1000, 'cost': 10.5, ...} }
            positions[row[0]] = {'vol': row[1], 'cost': row[2], 'time': row[3]}
        return positions

    def save_trade(self, code, action, price, vol, comm_rate, stamp_rate):
        """
        保存交易记录
        参数说明：
        - code: 股票代码
        - action: 'BUY' 或 'SELL'
        - price: 成交价格
        - vol: 成交数量
        - comm_rate: 佣金费率
        - stamp_rate: 印花税费率
        """
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        amount = price * vol  # 成交金额

        fee = 0.0
        if action == 'BUY':
            # 买入：只收佣金 (万一免五)
            fee = amount * comm_rate
            total_cost = amount + fee  # 实际扣除的钱
        else:
            # 卖出：收佣金 + 印花税
            fee = (amount * comm_rate) + (amount * stamp_rate)
            total_cost = amount - fee  # 实际到手的钱

        # 1. 写入流水表
        self.cursor.execute('''
            INSERT INTO trade_log (trade_time, code, action, price, vol, amount, fee, total_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (now_str, code, action, price, vol, amount, fee, total_cost))

        # 2. 更新持仓表
        if action == 'BUY':
            # 如果是买入，更新或插入持仓
            self.cursor.execute('''
                INSERT OR REPLACE INTO positions (code, vol, cost_price, buy_time)
                VALUES (?, ?, ?, ?)
            ''', (code, vol, price, now_str))
        elif action == 'SELL':
            # 如果是卖出，从持仓表删除
            self.cursor.execute("DELETE FROM positions WHERE code=?", (code,))

        self.conn.commit()
        return fee, total_cost

    def close(self):
        """关闭数据库连接"""
        self.conn.close()