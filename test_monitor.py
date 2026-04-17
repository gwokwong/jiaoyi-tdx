#!/usr/bin/env python3
"""
测试实时监控系统 - 单次扫描模式
"""

from realtime_monitor import RealtimeMonitor
from core import ConfigLoader


def test_monitor():
    """测试监控功能"""
    config = ConfigLoader()
    monitor = RealtimeMonitor(config)

    try:
        print("\n" + "="*80)
        print("🧪 测试实时监控系统")
        print("="*80)

        # 测试获取数据
        print("\n📊 测试获取30分钟数据...")
        df = monitor.get_30min_data('000001', 0)  # 平安银行
        if df is not None:
            print(f"✅ 成功获取数据，最新价格: {df.iloc[-1]['close']:.2f}")
            print(f"   时间: {df.index[-1]}")
            print(f"   MA3: {df.iloc[-1]['ma3']:.2f}")
            print(f"   MACD: {df.iloc[-1]['macd']:.2f}")
        else:
            print("❌ 获取数据失败")

        # 测试信号检测
        print("\n🔍 测试买入信号检测...")
        signals = monitor.check_buy_signals(df, '000001', '平安银行')
        if signals:
            print(f"✅ 发现 {len(signals)} 个买入信号:")
            for signal in signals:
                print(f"   - {signal['type']} (强度: {signal['strength']})")
                print(f"     {signal['desc']}")
        else:
            print("⏳ 暂无买入信号")

        # 测试扫描所有股票
        print("\n🔄 测试扫描所有股票...")
        alert_count = monitor.scan_all_stocks()
        print(f"\n📊 扫描完成，发现 {alert_count} 只提醒股票")

        # 测试系统提醒
        print("\n🔔 测试系统提醒...")
        monitor.system_alert("测试提醒", "这是测试消息")
        print("✅ 提醒已发送")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        monitor.close()
        print("\n" + "="*80)
        print("✅ 测试完成")
        print("="*80)


if __name__ == "__main__":
    test_monitor()
