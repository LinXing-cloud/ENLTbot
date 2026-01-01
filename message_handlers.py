"""
消息处理器
"""

import json
import re
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import IntEnum

# ============ 枚举定义 ============
class MessageType(IntEnum):
    """消息类型枚举"""
    TEXT = 0
    IMAGE = 1
    FILE = 2
    VOICE = 3
    VIDEO = 4
    USER_CARD = 5
    GROUP_CARD = 6
    STICKER = 7
    QUOTE = 8
    RECALL = 10
    MESSAGE_RECEIPT = 12
    SYSTEM = 21
    NOTICE = 23
    ONLINE_STATUS = 82
    GROUP_INFO_UPDATE = 92
    JOIN_GROUP = 90
    LEAVE_GROUP = 91
    GROUP_ALL_MUTE = 95
    GROUP_USER_MUTE = 96
    AUDIO_CALL_INIT = 200
    AUDIO_CALL_MEMBER = 204
    AUDIO_CALL_STATUS = 212

class Terminal(IntEnum):
    """终端类型枚举"""
    PC = 0
    MOBILE = 1
    WEB = 2

class WSCommand(IntEnum):
    """WebSocket命令枚举"""
    AUTH = 0
    HEARTBEAT = 1
    FORCE_OFFLINE = 2
    PRIVATE_MESSAGE = 3
    GROUP_MESSAGE = 4
    SYSTEM_MESSAGE = 5

# ============ 消息类 ============
class Message:
    """消息类"""
    def __init__(self, data: Dict, is_group: bool = False):
        self.data = data
        self.is_group = is_group
        self.id = self._safe_int(data.get('id'))
        self.type = self._safe_int(data.get('type', 0))
        self.content = data.get('content', '')
        self.send_id = self._safe_int(data.get('sendId'))
        self.recv_id = self._safe_int(data.get('recvId'))
        self.group_id = self._safe_int(data.get('groupId'))
        self.send_time = data.get('sendTime')
        self.sendNickName = data.get('sendNickName')
        self.quote_message = data.get('quoteMessage')
        
        if self.type == MessageType.RECALL:
            self.recalled_message_id = self._safe_int(self.content)
        else:
            self.recalled_message_id = None

    def _safe_int(self, value):
        """安全转换为整数"""
        try:
            if value is None:
                return None
            if isinstance(value, str):
                value_lower = value.lower()
                if value_lower in ['none', 'null', 'undefined']:
                    return None
                return int(value)
            return int(value) if value is not None else None
        except (ValueError, TypeError):
            return None

# ============ 消息内容处理器 ============
class MessageContentProcessor:
    """消息内容处理器"""
    
    @staticmethod
    def get_online_status_preview(content: str) -> str:
        """获取在线状态预览"""
        try:
            content_data = json.loads(content)
            online = content_data.get('online', False)
            terminal = content_data.get('terminal', 0)
            
            terminal_text = {
                0: "PC",
                1: "手机",
                2: "网页"
            }.get(terminal, f"终端{terminal}")
            
            if online:
                return f"[在线状态更新] 上线 ({terminal_text})"
            else:
                return f"[在线状态更新] 下线 ({terminal_text})"
        except:
            return "[在线状态更新]"
    
    @staticmethod
    def get_sticker_preview(content: str) -> str:
        """获取表情包预览"""
        try:
            content_data = json.loads(content)
            name = content_data.get('name', '表情包')
            return f"[表情包] {name}"
        except:
            return "[表情包]"
    
    @staticmethod
    def get_group_action_preview(message: Message) -> str:
        """获取群操作预览"""
        try:
            if message.content:
                content_data = json.loads(message.content)
            else:
                content_data = {}
            
            if message.type == MessageType.JOIN_GROUP:
                user_id = content_data.get('userId') or content_data.get('user_id')
                group_id = content_data.get('groupId') or content_data.get('group_id')
                user_name = content_data.get('userName', '')
                
                if user_name:
                    return f"[加入群聊] {user_name} 加入了群聊 {group_id}"
                elif user_id:
                    return f"[加入群聊] 用户{user_id} 加入了群聊 {group_id}"
                else:
                    return "[加入群聊]"
                    
            elif message.type == MessageType.LEAVE_GROUP:
                user_id = content_data.get('userId') or content_data.get('user_id')
                group_id = content_data.get('groupId') or content_data.get('group_id')
                user_name = content_data.get('userName', '')
                is_dissolve = content_data.get('dissolve', False)
                
                if is_dissolve:
                    return f"[解散群聊] 群聊 {group_id} 已解散"
                elif user_name:
                    return f"[退出群聊] {user_name} 退出了群聊 {group_id}"
                elif user_id:
                    return f"[退出群聊] 用户{user_id} 退出了群聊 {group_id}"
                else:
                    return "[群聊成员变动]"
                    
            elif message.type == MessageType.GROUP_ALL_MUTE:
                muted = content_data.get('muted', False)
                group_id = content_data.get('groupId') or content_data.get('group_id')
                group_name = content_data.get('groupName', '')
                
                if muted:
                    return f"[全员禁言] 群聊 {group_id} 已开启全员禁言"
                else:
                    return f"[解除全员禁言] 群聊 {group_id} 已解除全员禁言"
                    
            elif message.type == MessageType.GROUP_USER_MUTE:
                user_id = content_data.get('userId') or content_data.get('user_id')
                group_id = content_data.get('groupId') or content_data.get('group_id')
                user_name = content_data.get('userName', '')
                muted = content_data.get('muted', False)
                duration = content_data.get('duration', 0)
                
                duration_text = f" {duration}分钟" if duration > 0 else ""
                
                if muted:
                    if user_name:
                        return f"[禁言成员] {user_name} 在群聊 {group_id} 被禁言{duration_text}"
                    elif user_id:
                        return f"[禁言成员] 用户{user_id} 在群聊 {group_id} 被禁言{duration_text}"
                    else:
                        return "[成员禁言]"
                else:
                    if user_name:
                        return f"[解除禁言] {user_name} 在群聊 {group_id} 的禁言已解除"
                    elif user_id:
                        return f"[解除禁言] 用户{user_id} 在群聊 {group_id} 的禁言已解除"
                    else:
                        return "[解除成员禁言]"
                        
        except:
            if message.type == MessageType.JOIN_GROUP:
                return "[加入群聊]"
            elif message.type == MessageType.LEAVE_GROUP:
                return "[退出群聊]"
            elif message.type == MessageType.GROUP_ALL_MUTE:
                return "[全员禁言状态变更]"
            elif message.type == MessageType.GROUP_USER_MUTE:
                return "[成员禁言状态变更]"
    
    @staticmethod
    def get_content_preview(message: Message) -> str:
        """获取消息内容预览"""
        if message.type == MessageType.TEXT:
            return message.content
        elif message.type == MessageType.IMAGE:
            return "[图片消息]"
        elif message.type == MessageType.FILE:
            return "[文件消息]"
        elif message.type == MessageType.VOICE:
            return "[语音消息]"
        elif message.type == MessageType.VIDEO:
            return "[视频消息]"
        elif message.type == MessageType.STICKER:
            return MessageContentProcessor.get_sticker_preview(message.content)
        elif message.type == MessageType.RECALL:
            return f"[撤回消息] 撤回的消息ID: {message.recalled_message_id}"
        elif message.type == MessageType.ONLINE_STATUS:
            return MessageContentProcessor.get_online_status_preview(message.content)
        elif message.type == MessageType.GROUP_INFO_UPDATE:
            return "[置顶消息更新]"
        elif message.type == MessageType.SYSTEM:
            return "[系统消息]"
        elif message.type == MessageType.NOTICE:
            return "[通知消息]"
        elif message.type == MessageType.MESSAGE_RECEIPT:
            return "[私聊消息已读]"
        elif message.type == MessageType.AUDIO_CALL_INIT:
            return "[语音通话初始化]"
        elif message.type == MessageType.AUDIO_CALL_MEMBER:
            return "[语音通话成员更新]"
        elif message.type == MessageType.AUDIO_CALL_STATUS:
            return "[语音通话状态]"
        elif message.type in [MessageType.JOIN_GROUP, MessageType.LEAVE_GROUP,
                            MessageType.GROUP_ALL_MUTE, MessageType.GROUP_USER_MUTE]:
            return MessageContentProcessor.get_group_action_preview(message)
        else:
            return f"[类型{message.type}消息]"