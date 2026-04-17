#!/usr/bin/env python3
"""
统一启动脚本 - 交互式选择和执行所有交易工具
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta


class TradingSystemLauncher:
    """交易系统启动器"""

    def __init__(self):
        self.scripts = {
            '1': {
                'name': '尾盘选股系统',
                'file': 'afternoon_stock_picker.py',
                'desc': '基于全网最流行的量价关系指标，每天14:30后尾盘选股买入，支持指定日期回测',
                'params': [
                    {
                        'name': '选股数量',
                        'default': '20',
                        'desc': '要精选的股票数量（默认20只）',
                        'example': '10 或 20'
                    },
                    {
                        'name': '回测日期',
                        'default': '',
                        'desc': '指定日期进行历史回测（格式：YYYY-MM-DD），留空表示实时选股',
                        'example': '2026-04-14 或 留空'
                    }
                ]
            },
            '2': {
                'name': '今天全天实时监控',
                'file': 'realtime_monitor_today.py',
                'desc': '从9:20开盘到15:00收盘，实时监控全市场5571只股票，30分钟均线买入提醒',
                'params': [
                    {
                        'name': '扫描间隔',
                        'default': '60',
                        'desc': '每次扫描间隔秒数（默认60秒）',
                        'example': '30 或 60'
                    }
                ]
            },
            '3': {
                'name': '盘中当日盈利模拟',
                'file': 'intraday_pnl_simulator.py',
                'desc': '盘中实时跟踪买入股票的盈亏情况，从9:20运行到15:00',
                'params': [
                    {
                        'name': '扫描间隔',
                        'default': '60',
                        'desc': '每次扫描间隔秒数（默认60秒）',
                        'example': '30 或 60'
                    }
                ]
            },
            '4': {
                'name': '30分钟日内回测',
                'file': 'intraday_30min_demo.py',
                'desc': '基于30分钟K线的单日回测，显示精确买入卖出时间和点位',
                'params': [
                    {
                        'name': '回测日期',
                        'default': datetime.now().strftime('%Y-%m-%d'),
                        'desc': '要回测的日期（格式：YYYY-MM-DD）',
                        'example': '2026-04-14'
                    }
                ]
            },
            '5': {
                'name': '从今天起全新回测',
                'file': 'backtest_from_today.py',
                'desc': '从指定日期开始全新回测，每天使用初始资金1000万，不继承持仓',
                'params': [
                    {
                        'name': '开始日期',
                        'default': datetime.now().strftime('%Y-%m-%d'),
                        'desc': '回测开始日期（格式：YYYY-MM-DD）',
                        'example': '2026-04-14'
                    },
                    {
                        'name': '回测天数',
                        'default': '5',
                        'desc': '要回测的交易日数量',
                        'example': '5 或 10'
                    }
                ]
            },
            '6': {
                'name': '详细交易记录报告',
                'file': 'detailed_trade_report.py',
                'desc': '生成指定月份的详细交易记录，包含完整的买入卖出时间、点位',
                'params': [
                    {
                        'name': '年份',
                        'default': '2026',
                        'desc': '回测年份',
                        'example': '2026'
                    },
                    {
                        'name': '月份',
                        'default': '4',
                        'desc': '回测月份（1-12）',
                        'example': '3 或 4'
                    }
                ]
            },
            '7': {
                'name': '整月回测（3月）',
                'file': 'monthly_backtest_march.py',
                'desc': '回测整月数据，显示每日盈亏和累计盈亏',
                'params': []
            },
            '8': {
                'name': '实时监控系统（通用）',
                'file': 'realtime_monitor.py',
                'desc': '通用实时监控系统，可设置扫描间隔，持续运行直到手动停止',
                'params': [
                    {
                        'name': '扫描间隔',
                        'default': '60',
                        'desc': '每次扫描间隔秒数（默认60秒）',
                        'example': '30 或 60'
                    }
                ]
            },
            '9': {
                'name': '测试监控系统',
                'file': 'test_monitor.py',
                'desc': '测试实时监控功能，单次扫描模式，不进入无限循环',
                'params': []
            },
            '10': {
                'name': '测试交易核心',
                'file': 'trading_core.py',
                'desc': '测试交易核心模块的买入策略',
                'params': []
            },
            '11': {
                'name': '测试数据库',
                'file': 'test_db.py',
                'desc': '测试数据库连接和交易记录功能',
                'params': []
            },
            '12': {
                'name': '测试数据API',
                'file': 'test_data.py',
                'desc': '测试pytdx数据API连接和获取股票数据',
                'params': []
            },
            '13': {
                'name': '测试30分钟数据',
                'file': 'test_30min_data.py',
                'desc': '测试获取30分钟K线数据',
                'params': []
            },
            '14': {
                'name': '测试当天监控',
                'file': 'test_today_monitor.py',
                'desc': '测试今天全天监控系统的单次扫描模式',
                'params': []
            },
            '0': {
                'name': '退出',
                'file': '',
                'desc': '退出系统',
                'params': []
            }
        }

    def clear_screen(self):
        """清屏"""
        os.system('clear' if os.name == 'posix' else 'cls')

    def print_header(self):
        """打印标题"""
        print("\n" + "="*100)
        print("🚀 A股量化交易系统 - 统一启动平台")
        print("="*100)
        print(f"📅 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*100)

    def print_menu(self):
        """打印菜单"""
        self.print_header()
        print("\n📋 可用工具列表:\n")

        for key, script in self.scripts.items():
            if key == '0':
                print("\n" + "-"*100)
            print(f"【{key}】{script['name']}")
            print(f"    📄 文件: {script['file']}")
            print(f"    📝 说明: {script['desc']}")
            if script['params']:
                print(f"    ⚙️  参数: {len(script['params'])}个")
            print()

    def get_user_input(self, script):
        """获取用户输入参数"""
        params = []

        if not script['params']:
            return params

        print("\n" + "="*100)
        print(f"⚙️  配置参数 - {script['name']}")
        print("="*100)

        for i, param in enumerate(script['params'], 1):
            print(f"\n参数 {i}/{len(script['params'])}: {param['name']}")
            print(f"  说明: {param['desc']}")
            print(f"  示例: {param['example']}")
            print(f"  默认: {param['default']}")

            user_input = input(f"  请输入 (直接回车使用默认值): ").strip()

            if user_input:
                params.append(user_input)
            else:
                params.append(param['default'])

        return params

    def execute_script(self, script_key, params):
        """执行脚本"""
        script = self.scripts[script_key]
        file_path = script['file']

        if script_key == '0':
            print("\n👋 感谢使用，再见！")
            return False

        if not os.path.exists(file_path):
            print(f"\n❌ 错误: 文件 {file_path} 不存在")
            input("\n按回车键继续...")
            return True

        # 构建命令
        cmd = ['python3', file_path] + params

        print("\n" + "="*100)
        print(f"🚀 正在启动: {script['name']}")
        print(f"📄 执行文件: {file_path}")
        print(f"⚙️  传入参数: {' '.join(params) if params else '无'}")
        print("="*100)
        print("\n💡 提示: 按 Ctrl+C 可以中断执行\n")

        try:
            # 执行脚本
            result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

            if result.returncode == 0:
                print("\n✅ 执行完成")
            else:
                print(f"\n⚠️  程序退出，返回码: {result.returncode}")

        except KeyboardInterrupt:
            print("\n\n⏹️  用户中断执行")
        except Exception as e:
            print(f"\n❌ 执行出错: {e}")

        input("\n按回车键返回主菜单...")
        return True

    def run(self):
        """主循环"""
        while True:
            self.clear_screen()
            self.print_menu()

            choice = input("请输入编号选择工具 (0-14): ").strip()

            if choice not in self.scripts:
                print("\n❌ 无效选择，请重新输入")
                input("按回车键继续...")
                continue

            script = self.scripts[choice]

            # 获取参数
            params = self.get_user_input(script)

            # 执行脚本
            if not self.execute_script(choice, params):
                break


def main():
    """主函数"""
    launcher = TradingSystemLauncher()

    try:
        launcher.run()
    except KeyboardInterrupt:
        print("\n\n👋 用户退出")
        sys.exit(0)


if __name__ == "__main__":
    main()
