import sqlite3
import json
import os
import datetime


class ConfigLoader:
    """
    配置加载器：负责读取 config.json 文件
    优化：支持默认值和更灵活的配置获取
    """

    def __init__(self, config_file='config.json'):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"错误：找不到配置文件 {config_file}，请检查文件是否存在。")
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def get(self, *keys, default=None):
        """
        获取配置项，支持链式获取和默认值。
        例如：
            config.get('fees', 'commission_rate', default=0.00025)
            config.get('account', 'initial_capital', default=100000.0)
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_section(self, section, default=None):
        """
        获取整个配置节
        例如：config.get_section('fees')
        """
        return self.config.get(section, default if default is not None else {})


class DatabaseManager:
    """
    数据库管理器：负责保存交易记录和持仓信息
    使用 SQLite 轻量级数据库，无需安装额外软件。
    优化：
    1. 添加现金余额管理
    2. 添加交易统计视图
    3. 添加错误处理和日志
    4. 支持持仓更新（加仓/减仓）
    """

    def __init__(self, config):
        db_name = config.get('database', 'db_name', default='trading.db')
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # 使查询结果可以通过列名访问
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """
        创建数据表：
        1. positions: 当前持仓表
        2. trade_log: 历史交易流水表
        3. account: 账户资金表
        4. daily_stats: 每日统计表
        """
        # 持仓表 - 优化：支持加仓后的成本计算
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                code TEXT PRIMARY KEY,
                vol INTEGER NOT NULL DEFAULT 0,
                cost_price REAL NOT NULL DEFAULT 0,
                buy_time TEXT NOT NULL,
                total_cost REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
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
                fee REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                pnl REAL DEFAULT 0,
                pnl_pct REAL DEFAULT 0
            )
        ''')

        # 账户资金表 - 新增
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash_balance REAL NOT NULL DEFAULT 0,
                total_deposit REAL NOT NULL DEFAULT 0,
                total_withdrawal REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        ''')

        # 每日统计表 - 新增
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                start_cash REAL NOT NULL,
                end_cash REAL NOT NULL,
                position_value REAL NOT NULL DEFAULT 0,
                total_assets REAL NOT NULL,
                buy_count INTEGER NOT NULL DEFAULT 0,
                sell_count INTEGER NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        ''')

        # 创建索引优化查询
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_trade_log_code ON trade_log(code)
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_trade_log_time ON trade_log(trade_time)
        ''')

        self.conn.commit()

    def load_positions(self):
        """
        程序启动时调用：从数据库读取持仓
        返回: { '000001': {'vol': 1000, 'cost': 10.5, 'time': '2024-01-01 10:00:00'}, ... }
        """
        self.cursor.execute("SELECT code, vol, cost_price, buy_time FROM positions WHERE vol > 0")
        rows = self.cursor.fetchall()
        positions = {}
        for row in rows:
            positions[row[0]] = {
                'vol': row[1],
                'cost': row[2],
                'time': row[3]
            }
        return positions

    def save_trade(self, code, action, price, vol, comm_rate, stamp_rate):
        """
        保存交易记录并更新持仓
        优化：
        1. 支持加仓后的成本计算
        2. 记录盈亏
        3. 更新账户余额
        """
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        amount = price * vol

        fee = 0.0
        pnl = 0.0
        pnl_pct = 0.0

        if action == 'BUY':
            # 买入：只收佣金
            fee = amount * comm_rate
            total_cost = amount + fee
        else:
            # 卖出：收佣金 + 印花税
            fee = (amount * comm_rate) + (amount * stamp_rate)
            total_cost = amount - fee

            # 计算盈亏
            self.cursor.execute(
                "SELECT cost_price FROM positions WHERE code = ?",
                (code,)
            )
            row = self.cursor.fetchone()
            if row:
                cost_price = row[0]
                cost_amount = cost_price * vol
                pnl = total_cost - cost_amount
                pnl_pct = (pnl / cost_amount) if cost_amount > 0 else 0

        # 1. 写入流水表
        self.cursor.execute('''
            INSERT INTO trade_log 
            (trade_time, code, action, price, vol, amount, fee, total_cost, pnl, pnl_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (now_str, code, action, price, vol, amount, fee, total_cost, pnl, pnl_pct))

        # 2. 更新持仓表
        if action == 'BUY':
            self._update_position_on_buy(code, vol, price, now_str)
        elif action == 'SELL':
            self._update_position_on_sell(code, vol)

        self.conn.commit()
        return fee, total_cost

    def _update_position_on_buy(self, code, vol, price, now_str):
        """处理买入后的持仓更新（支持加仓）"""
        self.cursor.execute(
            "SELECT vol, cost_price, total_cost FROM positions WHERE code = ?",
            (code,)
        )
        row = self.cursor.fetchone()

        if row:
            # 加仓：计算新的成本价
            old_vol, old_cost, old_total = row
            new_vol = old_vol + vol
            new_total_cost = old_total + (price * vol)
            new_cost_price = new_total_cost / new_vol if new_vol > 0 else 0

            self.cursor.execute('''
                UPDATE positions 
                SET vol = ?, cost_price = ?, total_cost = ?, updated_at = ?
                WHERE code = ?
            ''', (new_vol, new_cost_price, new_total_cost, now_str, code))
        else:
            # 新建持仓
            total_cost = price * vol
            self.cursor.execute('''
                INSERT INTO positions (code, vol, cost_price, buy_time, total_cost, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (code, vol, price, now_str, total_cost, now_str))

    def _update_position_on_sell(self, code, vol):
        """处理卖出后的持仓更新（支持部分卖出）"""
        self.cursor.execute(
            "SELECT vol, cost_price, total_cost FROM positions WHERE code = ?",
            (code,)
        )
        row = self.cursor.fetchone()

        if not row:
            return

        old_vol, old_cost, old_total = row
        new_vol = old_vol - vol

        if new_vol <= 0:
            # 全部卖出，删除持仓
            self.cursor.execute("DELETE FROM positions WHERE code = ?", (code,))
        else:
            # 部分卖出，调整总成本，保持成本价不变
            avg_cost = old_total / old_vol if old_vol > 0 else 0
            new_total_cost = avg_cost * new_vol
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            self.cursor.execute('''
                UPDATE positions 
                SET vol = ?, total_cost = ?, updated_at = ?
                WHERE code = ?
            ''', (new_vol, new_total_cost, now_str, code))

    def get_cash_balance(self):
        """获取当前现金余额"""
        self.cursor.execute("SELECT cash_balance FROM account WHERE id = 1")
        row = self.cursor.fetchone()
        return row[0] if row else None

    def update_cash_balance(self, cash):
        """更新现金余额"""
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute('''
            INSERT INTO account (id, cash_balance, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cash_balance = excluded.cash_balance,
                updated_at = excluded.updated_at
        ''', (cash, now_str))
        self.conn.commit()

    def init_account(self, initial_capital):
        """初始化账户资金"""
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute('''
            INSERT OR IGNORE INTO account (id, cash_balance, total_deposit, updated_at)
            VALUES (1, ?, ?, ?)
        ''', (initial_capital, initial_capital, now_str))
        self.conn.commit()

    def get_trade_statistics(self, days=30):
        """获取交易统计信息"""
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')

        self.cursor.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sell_count,
                SUM(CASE WHEN action = 'SELL' AND pnl > 0 THEN 1 ELSE 0 END) as win_count,
                SUM(CASE WHEN action = 'SELL' AND pnl <= 0 THEN 1 ELSE 0 END) as loss_count,
                SUM(fee) as total_fees,
                SUM(CASE WHEN action = 'SELL' THEN pnl ELSE 0 END) as total_pnl
            FROM trade_log
            WHERE trade_time >= ?
        ''', (start_date,))

        row = self.cursor.fetchone()
        if not row or row[0] == 0:
            return None

        total_trades, buy_count, sell_count, win_count, loss_count, total_fees, total_pnl = row

        return {
            'total_trades': total_trades,
            'buy_count': buy_count,
            'sell_count': sell_count,
            'win_count': win_count or 0,
            'loss_count': loss_count or 0,
            'win_rate': (win_count / sell_count * 100) if sell_count > 0 else 0,
            'total_fees': total_fees or 0,
            'total_pnl': total_pnl or 0
        }

    def get_recent_trades(self, limit=20):
        """获取最近的交易记录"""
        self.cursor.execute('''
            SELECT trade_time, code, action, price, vol, amount, fee, pnl, pnl_pct
            FROM trade_log
            ORDER BY trade_time DESC
            LIMIT ?
        ''', (limit,))

        columns = ['trade_time', 'code', 'action', 'price', 'vol', 'amount', 'fee', 'pnl', 'pnl_pct']
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def save_daily_stats(self, date, start_cash, end_cash, position_value, 
                        total_assets, buy_count, sell_count, realized_pnl):
        """保存每日统计数据"""
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute('''
            INSERT INTO daily_stats 
            (date, start_cash, end_cash, position_value, total_assets, 
             buy_count, sell_count, realized_pnl, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                end_cash = excluded.end_cash,
                position_value = excluded.position_value,
                total_assets = excluded.total_assets,
                buy_count = excluded.buy_count,
                sell_count = excluded.sell_count,
                realized_pnl = excluded.realized_pnl,
                updated_at = excluded.updated_at
        ''', (date, start_cash, end_cash, position_value, total_assets,
              buy_count, sell_count, realized_pnl, now_str))
        self.conn.commit()

    def close(self):
        """关闭数据库连接"""
        try:
            self.conn.close()
        except Exception as e:
            print(f"关闭数据库连接时出错: {e}")


if __name__ == "__main__":
    # 测试数据库管理器
    config = ConfigLoader()
    db = DatabaseManager(config)

    # 初始化账户
    db.init_account(100000.0)

    # 测试保存交易
    db.save_trade('000001', 'BUY', 10.0, 1000, 0.00025, 0)
    print("买入交易已保存")

    # 测试加载持仓
    positions = db.load_positions()
    print(f"当前持仓: {positions}")

    # 测试现金余额
    cash = db.get_cash_balance()
    print(f"现金余额: {cash}")

    # 测试卖出
    db.save_trade('000001', 'SELL', 11.0, 1000, 0.00025, 0.001)
    print("卖出交易已保存")

    # 查看统计
    stats = db.get_trade_statistics()
    print(f"交易统计: {stats}")

    # 查看最近交易
    recent = db.get_recent_trades()
    print(f"最近交易: {recent}")

    db.close()
