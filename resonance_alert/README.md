# 多周期共振监控系统

基于通达信公式系统高阶玩法的实时监控系统，实现跨周期引用与多条件共振策略，并通过飞书实时推送信号。

## 功能特性

### 1. 跨周期引用策略
- **周线定方向，日线找买点**
- 支持日线、周线、月线、60分钟线、30分钟线
- 实现通达信 `#WEEK`, `#MONTH`, `#MIN60` 等跨周期引用

### 2. 多条件共振策略

#### 策略一：跨周期MACD+KDJ共振
```
周线MACD金叉 + 周线趋势向上 + 日线KDJ金叉
```

#### 策略二：趋势+量能+动能三重验证
```
趋势OK: 股价在MA20之上，且MA20向上
量能OK: 成交量 > MA5的1.5倍，且 < 3倍
动能OK: MACD红柱伸长且为正
```

#### 策略三：周线定方向，日线找买点
```
周线趋势向上 + 日线回调买点 + 日线MACD金叉
```

#### 策略四：高级多周期共振
```
月线趋势向上 + 周线趋势向上 + 周线MACD金叉 + 日线多重条件
```

### 3. 智能过滤
- 排除ST/*ST股票
- 排除停牌股票
- 排除科创板(688开头)
- 排除北交所(8/4开头)
- 排除创业板(300/301开头)

### 4. 飞书通知
- 交互式卡片消息
- 批量信号推送
- 系统状态通知
- 高分信号(>=80分)单独提醒

### 5. 回测功能
- 支持单日回测
- 支持多日连续回测
- 完整的交易记录和盈亏统计
- 详细的回测报告生成

### 6. 云端部署
- Docker容器化
- Docker Compose编排
- 支持定时任务模式

## 项目结构

```
resonance_alert/
├── src/                          # 源代码
│   ├── __init__.py
│   ├── data_fetcher.py          # 跨周期数据获取
│   ├── resonance_strategy.py    # 多条件共振策略
│   ├── feishu_notifier.py       # 飞书通知模块
│   ├── monitor.py               # 主监控程序
│   └── backtest.py              # 回测模块
├── config/                       # 配置文件
│   └── config.json
├── deploy/                       # 部署文件
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt              # Python依赖
└── README.md                     # 说明文档
```

## 快速开始

### 1. 配置飞书机器人

1. 在飞书群中添加自定义机器人
2. 获取 Webhook 地址和签名密钥
3. 修改 `config/config.json`：

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

### 2. 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行监控
cd src
python monitor.py

# 使用自定义参数
python monitor.py --interval 300 --limit 100 --score 60
```

### 3. Docker部署

```bash
# 构建镜像
cd deploy
docker-compose build

# 运行监控
docker-compose up -d resonance-monitor

# 查看日志
docker-compose logs -f resonance-monitor

# 停止服务
docker-compose down
```

### 4. 回测测试

```bash
cd src

# 单日回测
python backtest.py --date 2026-04-17 --limit 100 --capital 1000000

# 多日回测
python backtest.py --date 2026-04-01 --end-date 2026-04-17 --limit 100

# 自定义参数
python backtest.py --date 2026-04-17 --limit 200 --capital 500000
```

### 5. 云端部署（推荐）

使用定时任务模式，只在交易时间运行：

```bash
cd deploy
docker-compose --profile scheduler up -d
```

## 配置说明

### config.json

```json
{
  "tdx": {
    "server_ip": "123.125.108.14",    // 通达信服务器IP
    "server_port": 7709                // 通达信服务器端口
  },
  "monitor": {
    "scan_interval": 300,               // 扫描间隔（秒）
    "stock_limit": 100,                 // 监控股票数量
    "min_score": 60,                    // 最低信号得分
    "trading_hours_only": true          // 仅交易时间运行
  },
  "notification": {
    "feishu": {
      "enabled": true,
      "webhook_url": "",
      "secret": ""
    }
  }
}
```

### 命令行参数

#### 实时监控
```bash
python monitor.py [选项]

选项:
  -c, --config PATH    配置文件路径 (默认: config/config.json)
  -i, --interval INT   扫描间隔（秒）
  -l, --limit INT      股票数量限制
  -s, --score INT      最低信号得分
  -a, --always         非交易时间也运行
```

#### 回测
```bash
python backtest.py [选项]

选项:
  -d, --date DATE      回测日期 (YYYY-MM-DD) [必填]
  -e, --end-date DATE  结束日期，用于多日回测
  -c, --config PATH    配置文件路径
  -l, --limit INT      股票数量限制
  --capital FLOAT      初始资金
```

## 信号评分规则

### 跨周期MACD+KDJ共振 (最高85分)
- 日线KDJ金叉: +30分
- 周线MACD金叉: +35分
- 周线DIF拐头向上: +20分
- 日线MACD金叉: +15分

### 趋势+量能+动能共振 (最高100分)
- 趋势OK: +35分
- 量能OK: +30分
- 动能OK: +35分

### 周线定方向日线买点 (最高100分)
- 周线趋势向上: +40分
- 日线回调买点: +40分
- 日线MACD金叉: +20分

### 高级多周期共振 (最高100分)
- 月线趋势向上: +30分
- 周线趋势向上: +25分
- 周线MACD金叉: +20分
- 日线股价在MA20之上: +10分
- 日线MACD金叉: +10分
- 日线放量: +5分

## 飞书消息示例

### 单信号卡片
```
🎯 多周期共振信号 - 000001 平安银行

信号类型: 趋势+量能+动能共振
信号得分: 85/100
当前价格: ¥12.50
日线MA20: ¥12.30
周线趋势: UP

共振条件:
• 趋势OK: 股价12.50 > MA20(12.30)
• 量能OK: 量比1.80倍 (1.5-3倍区间)
• 动能OK: MACD红柱伸长 0.125

⏰ 发送时间: 2025-01-15 10:30:25
```

## 注意事项

1. **通达信连接**: 确保网络可以连接到通达信服务器
2. **飞书频率限制**: 飞书机器人有频率限制，避免过于频繁的扫描
3. **信号去重**: 系统会自动去重，同一信号1小时内不会重复通知
4. **交易时间**: 默认只在A股交易时间运行(9:30-11:30, 13:00-15:00)

## 技术栈

- Python 3.9+
- pytdx: 通达信数据接口
- pandas: 数据处理
- requests: HTTP请求
- Docker: 容器化部署

## 许可证

MIT License
