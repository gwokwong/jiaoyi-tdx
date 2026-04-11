#!/usr/bin/env python3
"""
完整流程测试 - 展示选股、买入、卖出全流程
"""

import pandas as pd
import datetime
from pytdx.hq import TdxHq_API
from core import ConfigLoader


def test_full_flow():
    """
    测试完整交易流程
    """
    config = ConfigLoader()
    api = TdxHq_API()
    
    ip = config.get('tdx', 'server_ip')
    port = config.get('tdx', 'server_port')
    
    if not api.connect(ip, port):
        print("❌ 连接服务器失败")
        return
    
    print("✅ 已连接通达信服务器")
    print("\n" + "="*80)
    print("📈 A股量化交易 - 完整流程演示")
    print("="*80)
    
    # 使用几只活跃股票进行演示
    test_stocks = [
        ('000001', 0),  # 平安银行
        ('000002', 0),  # 万科A
        ('600000', 1),  # 浦发银行
        ('600028', 1),  # 中国石化
    ]
    
    # 回测参数
    initial_capital = 1000000
    cash = initial_capital
    positions = {}  # 持仓
    trade_history = []  # 交易记录
    
    # 回测日期范围（选择更长周期确保有卖出）
    start_date = '2026-03-01'
    end_date = '2026-04-10'
    
    date_range = pd.date_range(start=start_date, end=end_date, freq='B')
    
    print(f"\n💰 初始资金: {initial_capital:,.2f} 元")
    print(f"📅 回测期间: {start_date} 至 {end_date}")
    print(f"📋 股票池: {[s[0] for s in test_stocks]}")
    print(f"📊 策略: 阳线买入，止盈10%，止损-5%")
    print("\n" + "="*80)
    
    for current_date in date_range:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # 1. 检查持仓（止盈止损）
        if positions:
            for code in list(positions.keys()):
                pos = positions[code]
                market = pos['market']
                
                # 获取当日数据
                data = api.get_security_bars(4, market, code, 0, 30)
                if not data:
                    continue
                    
                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['datetime']).dt.date
                target_date = current_date.date()
                day_data = df[df['date'] == target_date]
                
                if len(day_data) == 0:
                    continue
                
                current_price = day_data.iloc[0]['close']
                buy_price = pos['buy_price']
                pnl_pct = (current_price - buy_price) / buy_price
                
                # 止盈或止损
                if pnl_pct >= 0.10 or pnl_pct <= -0.05:
                    vol = pos['vol']
                    income = current_price * vol
                    fee = income * 0.0006  # 佣金+印花税
                    profit = income - pos['cost'] - fee - pos['fee']
                    
                    cash += (income - fee)
                    
                    trade_history.append({
                        'date': date_str,
                        'code': code,
                        'action': 'SELL',
                        'price': current_price,
                        'vol': vol,
                        'amount': income,
                        'profit': profit,
                        'pnl_pct': pnl_pct * 100
                    })
                    
                    action_type = "止盈" if pnl_pct >= 0.10 else "止损"
                    print(f"\n📅 {date_str}")
                    print(f"   🔴 卖出 {code} @ {current_price:.2f} | {action_type} | 盈亏: {pnl_pct*100:+.2f}% | 收益: {profit:.2f}元")
                    
                    del positions[code]
        
        # 2. 选股买入
        if cash > initial_capital * 0.3:  # 保留30%现金
            candidates = []
            
            for code, market in test_stocks:
                if code in positions:
                    continue
                    
                data = api.get_security_bars(4, market, code, 0, 30)
                if not data:
                    continue
                    
                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['datetime']).dt.date
                target_date = current_date.date()
                day_data = df[df['date'] == target_date]
                
                if len(day_data) == 0:
                    continue
                
                row = day_data.iloc[0]
                open_price = row['open']
                close_price = row['close']
                
                if open_price == 0:
                    continue
                
                change_pct = (close_price - open_price) / open_price * 100
                
                # 阳线且涨幅适中
                if close_price > open_price and 0.1 <= change_pct <= 10:
                    candidates.append({
                        'code': code,
                        'market': market,
                        'close': close_price,
                        'change_pct': change_pct
                    })
            
            # 买入符合条件的股票
            for stock in candidates[:2]:  # 每天最多买2只
                if len(positions) >= 3:  # 最多持有3只
                    break
                    
                code = stock['code']
                buy_price = stock['close']
                market = stock['market']
                
                # 计算买入数量（每只最多5%仓位）
                position_value = initial_capital * 0.05
                vol = int(position_value / buy_price / 100) * 100
                
                if vol == 0:
                    continue
                
                cost = buy_price * vol
                fee = cost * 0.0001  # 佣金
                
                if cash >= cost + fee:
                    cash -= (cost + fee)
                    positions[code] = {
                        'code': code,
                        'vol': vol,
                        'buy_price': buy_price,
                        'cost': cost,
                        'fee': fee,
                        'market': market
                    }
                    
                    trade_history.append({
                        'date': date_str,
                        'code': code,
                        'action': 'BUY',
                        'price': buy_price,
                        'vol': vol,
                        'amount': cost
                    })
                    
                    print(f"\n📅 {date_str}")
                    print(f"   🟢 买入 {code} @ {buy_price:.2f} x {vol}股 = {cost:.2f}元 (涨幅: {stock['change_pct']:+.2f}%)")
    
    api.disconnect()
    
    # 生成最终报告
    print("\n" + "="*80)
    print("📈 交易报告")
    print("="*80)
    
    # 计算最终资产
    hold_value = sum(p['vol'] * p['buy_price'] for p in positions.values())
    final_equity = cash + hold_value
    total_return = (final_equity - initial_capital) / initial_capital * 100
    
    print(f"\n💰 资金状况:")
    print(f"   初始资金: {initial_capital:,.2f} 元")
    print(f"   最终资金: {final_equity:,.2f} 元")
    print(f"   总收益率: {total_return:+.2f}%")
    print(f"   现金余额: {cash:,.2f} 元")
    print(f"   持仓市值: {hold_value:,.2f} 元")
    
    buy_count = len([t for t in trade_history if t['action'] == 'BUY'])
    sell_count = len([t for t in trade_history if t['action'] == 'SELL'])
    
    print(f"\n📊 交易统计:")
    print(f"   买入次数: {buy_count}")
    print(f"   卖出次数: {sell_count}")
    
    if sell_count > 0:
        profits = [t['profit'] for t in trade_history if t['action'] == 'SELL']
        win_count = len([p for p in profits if p > 0])
        lose_count = len([p for p in profits if p <= 0])
        print(f"   盈利次数: {win_count}")
        print(f"   亏损次数: {lose_count}")
        print(f"   胜率: {win_count/sell_count*100:.1f}%")
        print(f"   总利润: {sum(profits):,.2f} 元")
    
    print(f"\n📋 当前持仓 ({len(positions)} 只):")
    if positions:
        for code, pos in positions.items():
            print(f"   {code}: {pos['vol']}股 @ {pos['buy_price']:.2f}元")
    else:
        print("   无持仓")
    
    print(f"\n📝 完整交易明细:")
    print("-"*80)
    print(f"{'日期':<12} {'代码':<10} {'操作':<6} {'价格':<10} {'数量':<10} {'金额':<12} {'盈亏':<10}")
    print("-"*80)
    for t in trade_history:
        profit_str = f"{t.get('profit', 0):+.2f}" if t['action'] == 'SELL' else "-"
        print(f"{t['date']:<12} {t['code']:<10} {t['action']:<6} "
              f"{t['price']:<10.2f} {t['vol']:<10} {t['amount']:<12.2f} {profit_str:<10}")
    print("-"*80)
    print("\n" + "="*80)


if __name__ == "__main__":
    test_full_flow()
