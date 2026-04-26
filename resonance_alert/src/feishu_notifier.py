"""
飞书通知模块
支持飞书机器人 webhook 推送
"""

import json
import requests
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """
    飞书机器人通知类
    支持文本消息、富文本消息、卡片消息
    """

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        初始化飞书通知器

        Args:
            webhook_url: 飞书机器人 webhook 地址
            secret: 飞书机器人签名密钥（可选）
        """
        self.webhook_url = webhook_url
        self.secret = secret

    def _send_request(self, payload: Dict) -> bool:
        """发送请求到飞书"""
        try:
            headers = {
                'Content-Type': 'application/json; charset=utf-8'
            }

            response = requests.post(
                self.webhook_url,
                headers=headers,
                json=payload,
                timeout=10
            )

            result = response.json()

            if result.get('code') == 0:
                logger.info("飞书消息发送成功")
                return True
            else:
                logger.error(f"飞书消息发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"发送飞书消息时出错: {e}")
            return False

    def send_text_message(self, text: str) -> bool:
        """
        发送纯文本消息

        Args:
            text: 消息内容
        """
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }

        return self._send_request(payload)

    def send_rich_text(self, title: str, content: List[List[Dict]]) -> bool:
        """
        发送富文本消息

        Args:
            title: 标题
            content: 内容列表，格式为 [[{"tag": "text", "text": "xxx"}, ...], ...]
        """
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": content
                    }
                }
            }
        }

        return self._send_request(payload)

    def send_interactive_card(self, signal_data: Dict) -> bool:
        """
        发送交互式卡片消息（推荐）

        Args:
            signal_data: 信号数据字典
        """
        code = signal_data.get('code', '')
        name = signal_data.get('name', '')
        signal_type = signal_data.get('signal_type', '')
        score = signal_data.get('score', 0)
        reasons = signal_data.get('reasons', [])
        current_price = signal_data.get('current_price', 0)
        day_ma20 = signal_data.get('day_ma20', 0)
        week_trend = signal_data.get('week_trend', '')

        # 构建原因文本
        reasons_text = "\n".join([f"• {r}" for r in reasons])

        # 根据得分设置颜色
        if score >= 80:
            header_color = "red"  # 高分信号
        elif score >= 60:
            header_color = "orange"  # 中等信号
        else:
            header_color = "blue"  # 一般信号

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🎯 多周期共振信号 - {code} {name}"
                    },
                    "template": header_color
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**信号类型:** {signal_type}\n**信号得分:** {score}/100\n**当前价格:** ¥{current_price:.2f}\n**日线MA20:** ¥{day_ma20:.2f}\n**周线趋势:** {week_trend}"
                        }
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**共振条件:**\n{reasons_text}"
                        }
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"⏰ 发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            }
                        ]
                    }
                ]
            }
        }

        return self._send_request(payload)

    def send_batch_signals(self, signals: List[Dict]) -> bool:
        """
        批量发送多个信号

        Args:
            signals: 信号列表
        """
        if not signals:
            return True

        if len(signals) == 1:
            # 单个信号使用卡片消息
            return self.send_interactive_card(signals[0])

        # 多个信号使用富文本消息
        content = []

        # 标题
        content.append([
            {"tag": "text", "text": f"📊 发现 {len(signals)} 个多周期共振信号\n\n"}
        ])

        # 每个信号
        for i, signal in enumerate(signals, 1):
            signal_text = (
                f"{i}. {signal.get('code', '')} {signal.get('name', '')}\n"
                f"   类型: {signal.get('signal_type', '')}\n"
                f"   得分: {signal.get('score', 0)}/100\n"
                f"   价格: ¥{signal.get('current_price', 0):.2f}\n"
                f"   原因: {', '.join(signal.get('reasons', [])[:2])}\n\n"
            )
            content.append([{"tag": "text", "text": signal_text}])

        # 添加时间
        content.append([
            {"tag": "text", "text": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        ])

        return self.send_rich_text("🎯 多周期共振信号提醒", content)

    def send_system_status(self, status: str, details: str = "") -> bool:
        """
        发送系统状态通知

        Args:
            status: 状态 (started/stopped/error)
            details: 详细信息
        """
        status_map = {
            'started': ('🟢 系统启动', 'green'),
            'stopped': ('🟡 系统停止', 'yellow'),
            'error': ('🔴 系统错误', 'red'),
            'running': ('🔵 系统运行中', 'blue')
        }

        title, color = status_map.get(status, ('⚪ 系统通知', 'grey'))

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": color
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": details if details else f"系统状态: {status}"
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            }
                        ]
                    }
                ]
            }
        }

        return self._send_request(payload)


class NotificationManager:
    """
    通知管理器
    支持多种通知渠道
    """

    def __init__(self, config: Dict):
        self.config = config
        self.notifiers = []

        # 初始化飞书通知
        feishu_config = config.get('feishu', {})
        if feishu_config.get('enabled', False):
            webhook_url = feishu_config.get('webhook_url')
            if webhook_url:
                self.notifiers.append(
                    FeishuNotifier(
                        webhook_url=webhook_url,
                        secret=feishu_config.get('secret')
                    )
                )
                logger.info("飞书通知已启用")

    def notify_signal(self, signal: Dict) -> bool:
        """
        发送信号通知

        Args:
            signal: 信号数据
        """
        success = True
        for notifier in self.notifiers:
            if not notifier.send_interactive_card(signal):
                success = False
        return success

    def notify_batch_signals(self, signals: List[Dict]) -> bool:
        """
        批量发送信号通知

        Args:
            signals: 信号列表
        """
        if not signals:
            return True

        success = True
        for notifier in self.notifiers:
            if not notifier.send_batch_signals(signals):
                success = False
        return success

    def notify_system_status(self, status: str, details: str = "") -> bool:
        """
        发送系统状态通知

        Args:
            status: 状态
            details: 详细信息
        """
        success = True
        for notifier in self.notifiers:
            if not notifier.send_system_status(status, details):
                success = False
        return success
