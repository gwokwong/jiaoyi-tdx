# A股量化交易系统

基于 Python + pytdx 的A股量化交易框架，支持历史回测和实盘交易。

## 📁 项目结构

```
jiaoyi/
├── core.py                    # 核心模块
├── backtester.py              # 回测引擎
├── live_trader.py             # 实盘交易
├── config.json                # 配置文件
├── run_backtest.sh            # 回测启动脚本
├── run_live.sh                # 实盘启动脚本
├── check_days.py              # 交易日检查工具
├── trade_history.db           # SQLite数据库（自动创建）
├── strategies/                # 策略监控系统
│   ├── README.md
│   ├── breakout_strategy/     # 放量突破策略
│   ├── ma_trend_strategy/     # 均线趋势策略
│   ├── macd_kdj_strategy/     # MACD+KDJ金叉策略
│   ├── momentum_strategy/     # 动量策略
│   └── resonance_alert/       # 多周期共振策略
└── resonance_alert/           # 多周期共振系统
    └── src/
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip3 install pandas pytdx
```

### 2. 配置文件说明

编辑 `config.json` 配置您的交易参数：

```json
{
  "account": {
    "initial_capital": 1000000,    // 初始资金（元）
    "max_position_ratio": 0.05      // 最大仓位比例
  },
  "strategy": {
    "scan_interval": 3,            // 扫描间隔（秒）
    "stop_loss_rate": -0.05,       // 止损比例（-5%）
    "take_profit_rate": 0.10       // 止盈比例（10%）
  },
  "fees": {
    "commission_rate": 0.0001,     // 佣金费率（万1）
    "stamp_duty_rate": 0.0005      // 印花税费率
  },
  "tdx": {
    "server_ip": "123.125.108.14", // 通达信服务器
    "server_port": 7709
  }
}
```

## 🎯 策略监控系统 (strategies/)

全市场实时监控模块，支持5000+只股票同时监控，自动交易和飞书通知。

### 五大策略

| 策略 | 核心逻辑 | 最低得分 |
|------|----------|----------|
| **放量突破** | 阳线+涨幅≥1%+量比≥1.2+突破20日高点 | 70 |
| **均线趋势** | MA5>MA10>MA20+股价在MA5上+MA20向上 | 75 |
| **MACD+KDJ金叉** | MACD金叉+KDJ金叉+MACD红柱+放量 | 70 |
| **动量突破** | 涨幅>3%+量比>2+MACD红柱+突破5日高点 | 75 |
| **多周期共振** | 跨周期MACD+KDJ+趋势量能动能共振 | 60 |

### 功能特点

- ✅ **全市场监控**：支持5000+只股票（上海+深圳）
- ✅ **交易时间**：9:30-11:30, 13:00-15:00，周末自动休眠
- ✅ **并行扫描**：10线程并发，提高扫描速度
- ✅ **模拟交易**：自动买入、止损止盈、账户管理
- ✅ **飞书通知**：发现信号自动推送飞书消息
- ✅ **独立配置**：每个策略独立的config.json

### 使用方法

```bash
# 放量突破策略
cd strategies/breakout_strategy
python monitor.py

# 均线趋势策略
cd strategies/ma_trend_strategy
python monitor.py

# MACD+KDJ策略
cd strategies/macd_kdj_strategy
python monitor.py

# 动量策略
cd strategies/momentum_strategy
python monitor.py

# 多周期共振策略
cd strategies/resonance_alert/src
python full_market_monitor.py
```

### 配置飞书通知

编辑对应策略的 `config.json`：

```json
{
  "notification": {
    "feishu": {
      "enabled": true,
      "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN",
      "secret": "YOUR_SECRET"
    }
  }
}
```

### 模拟交易参数

```json
{
  "trading": {
    "simulate": true,           // 开启模拟交易
    "initial_capital": 1000000, // 初始资金100万
    "position_size": 0.1,       // 单票10%仓位
    "max_positions": 10,        // 最大10只持仓
    "stop_loss": -0.05,         // 止损-5%
    "take_profit": 0.10,        // 止盈10%
    "max_buys_per_day": 5       // 每日最多买入5次
  }
}
```

---

## 📊 基础功能模块

### 1. 回测引擎 (backtester.py)

基于历史数据的策略回测工具。

**策略逻辑：**
- **买入信号**：当日为阳线（收盘价 > 开盘价）且空仓时买入
- **卖出信号**：持仓亏损达到止损线（默认-5%）时卖出
- **记录**：自动保存交易记录到数据库

**使用方法：**
```bash
# 方式1：直接运行
python3 backtester.py

# 方式2：使用启动脚本
./run_backtest.sh
```

**修改回测日期：**
编辑 `backtester.py` 文件末尾：
```python
# 选择回测日期
test_date = '2026-04-08'  # 修改为想要回测的日期
bt.run('000001', test_date, test_date)
```

### 2. 实盘交易 (live_trader.py)

实盘交易监控程序，自动执行买卖操作。

**功能特点：**
- 自动连接通达信行情服务器
- 实时监控持仓（止损检查）
- 交易时间判断（9:30-11:30, 13:00-15:00）
- 自动保存交易记录

**⚠️ 风险提示：**
- 实盘交易有风险，请谨慎使用
- 建议先充分回测验证策略
- 首次使用请用小资金测试

**使用方法：**
```bash
# 方式1：直接运行
python3 live_trader.py

# 方式2：使用启动脚本
./run_live.sh
```

**停止程序：**
按 `Ctrl+C` 安全退出

### 3. 核心模块 (core.py)

提供基础功能支持：

| 类名 | 功能 |
|------|------|
| `ConfigLoader` | 读取 `config.json` 配置文件 |
| `DatabaseManager` | SQLite数据库管理（持仓、交易记录） |

**数据库表结构：**
- `positions` - 当前持仓表
- `trade_log` - 历史交易流水表

### 4. 交易日检查 (check_days.py)

查看最近阳线交易日，帮助选择回测日期。

```bash
python3 check_days.py
```

输出示例：
```
📈 最近阳线（会买入）的交易日：
==================================================
2026-04-01 | 开盘: 11.09 | 收盘: 11.15 | 涨幅: +0.54% | ✅ 阳线
2026-04-02 | 开盘: 11.15 | 收盘: 11.27 | 涨幅: +1.08% | ✅ 阳线
2026-04-08 | 开盘: 11.11 | 收盘: 11.22 | 涨幅: +0.99% | ✅ 阳线
==================================================
💡 建议选择: 2026-04-08 进行回测
```

## 📝 使用流程

### 回测流程
1. 配置 `config.json` 参数
2. 运行 `python3 check_days.py` 查看可选日期
3. 修改 `backtester.py` 设置回测日期
4. 运行 `./run_backtest.sh` 执行回测
5. 查看回测报告和数据库记录

### 实盘流程
1. 确保回测结果满意
2. 配置 `config.json` 交易参数
3. 交易时段运行 `./run_live.sh`
4. 监控程序输出和数据库记录

## ⚙️ 自定义策略

当前策略为简单示例（阳线买入），您可以修改：

**在 `backtester.py` 中：**
```python
# 第91行附近，修改买入条件
if code not in self.positions and 您的买入条件:
    self.buy(code, current_price, date_str)
```

**在 `live_trader.py` 中：**
```python
# 第97行 scan_market 方法中添加选股逻辑
def scan_market(self):
    # 您的选股策略代码
    pass
```

## 🔧 常见问题

**Q: 连接服务器失败？**
A: 检查 `config.json` 中的服务器地址，或尝试更换其他通达信服务器。

**Q: 回测没有交易？**
A: 检查所选日期是否为阳线（收盘价 > 开盘价），或修改买入条件。

**Q: 如何清空交易记录？**
A: 删除 `trade_history.db` 文件，程序会自动重建。

## 📌 注意事项

1. **数据延迟**：免费行情接口有延迟，不适合高频交易
2. **服务器稳定性**：通达信免费服务器可能不稳定
3. **风险控制**：实盘交易前请充分测试，设置合理的止损线
4. **法律责任**：本程序仅供学习研究，使用风险自负

## 📄 许可证

MIT License - 仅供学习研究使用
