# 策略监控系统

包含5个独立的策略监控模块，每个都支持：
- 全市场5000+只股票实时监控
- 盘中实时买入卖出
- 飞书通知

## 策略列表

### 1. 放量突破策略 (breakout_strategy)
**策略逻辑：**
- 阳线（收盘价 > 开盘价）
- 涨幅 ≥ 1%
- 量比 ≥ 1.2
- 突破20日高点平台

**运行：**
```bash
cd breakout_strategy
python monitor.py
```

### 2. 均线趋势策略 (ma_trend_strategy)
**策略逻辑：**
- MA5 > MA10 > MA20（多头排列）
- 收盘价 > MA5
- MA20向上
- 成交量 > MA5均量

**运行：**
```bash
cd ma_trend_strategy
python monitor.py
```

### 3. MACD+KDJ金叉策略 (macd_kdj_strategy)
**策略逻辑：**
- MACD金叉（DIF上穿DEA）
- KDJ金叉（K上穿D）
- MACD柱状线为正
- 放量

**运行：**
```bash
cd macd_kdj_strategy
python monitor.py
```

### 4. 动量策略 (momentum_strategy)
**策略逻辑：**
- 涨幅 > 3%
- 量比 > 2
- MACD红柱
- 突破5日高点

**运行：**
```bash
cd momentum_strategy
python monitor.py
```

### 5. 多周期共振策略 (resonance_alert)
**策略逻辑：**
- 跨周期MACD+KDJ共振
- 趋势+量能+动能三重验证
- 周线定方向日线买点
- 高级多周期共振

**运行：**
```bash
cd ../resonance_alert/src
python full_market_monitor.py
```

## 配置说明

每个策略文件夹都有独立的 `config.json`：

```json
{
  "tdx": {
    "server_ip": "123.125.108.14",
    "server_port": 7709
  },
  "monitor": {
    "scan_interval": 300,      // 扫描间隔（秒）
    "stock_limit": 5500,       // 监控股票数量
    "min_score": 70,           // 最低信号得分
    "trading_hours_only": true,// 仅交易时间运行
    "max_workers": 10          // 并发线程数
  },
  "trading": {
    "simulate": true,          // 开启模拟交易
    "initial_capital": 1000000,// 初始资金
    "position_size": 0.1,      // 单票仓位
    "max_positions": 10,       // 最大持仓数
    "stop_loss": -0.05,        // 止损线
    "take_profit": 0.10,       // 止盈线
    "max_buys_per_day": 5      // 每日最大买入次数
  },
  "notification": {
    "feishu": {
      "enabled": true,
      "webhook_url": "...",
      "secret": "..."
    }
  }
}
```

## 运行时间

所有策略默认只在A股交易时间运行：
- 上午：9:30 - 11:30
- 下午：13:00 - 15:00
- 周末自动休眠

## 飞书通知

1. 在飞书群中添加自定义机器人
2. 获取 Webhook 地址和签名密钥
3. 修改对应策略的 `config.json`
4. 收到信号时会自动推送飞书消息

## 模拟交易

- 发现信号自动模拟买入
- 自动监控持仓（止损/止盈）
- 实时显示账户状态
- 记录完整交易历史

## 注意事项

1. 确保已安装依赖：`pip install pytdx pandas requests`
2. 每个策略独立运行，互不干扰
3. 可以同时运行多个策略
4. 建议使用不同的飞书机器人，便于区分
