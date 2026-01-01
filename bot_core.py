"""
机器人核心类
"""

import asyncio
import aiohttp
import websockets
import json
import time
import uuid
import os
import logging
import re
import base64
from collections import defaultdict, deque
from typing import Optional, Dict, List, Callable, Any, Union, Tuple
from datetime import datetime
import ssl

from config import APIConfig, BotConfig, ssl_context
from database import DatabaseManager
from api_client import APIClient
from message_handlers import Message, MessageType, Terminal, WSCommand, MessageContentProcessor

logger = logging.getLogger('BoxIM.Core')

# ============ 用户模块 ============
class UserModule:
    """用户模块"""
    def __init__(self, boxim_instance):
        self.boxim = boxim_instance
        self.api = APIClient(boxim_instance)

    async def get_self_info(self):
        """获取自身信息"""
        result = await self.api.request('GET', '/api/user/self')
        return result['data']

    async def get_user_info(self, user_id: int):
        """获取用户信息"""
        result = await self.api.request('GET', f'/api/user/find/{user_id}')
        return result['data']

    async def get_group_info(self, group_id: int) -> Dict:
        """获取群聊信息"""
        result = await self.api.get_group_info(group_id)
        return result

    async def get_group_members(self, group_id: int) -> Dict:
        """获取群聊成员"""
        result = await self.api.get_group_members(group_id)
        return result

# ============ 消息模块 ============
class MessageModule:
    """消息模块"""
    def __init__(self, boxim_instance):
        self.boxim = boxim_instance
        self.api = APIClient(boxim_instance)
        self.group_mute_status = {}
        self.mute_check_interval = 3600

    async def send_private_message(self, user_id: int, content: str, msg_type: int = 0) -> Optional[int]:
        """发送私聊消息"""
        try:
            tmp_id = str(uuid.uuid4().int)[:16]
            payload = {
                "tmpId": tmp_id,
                "content": content,
                "type": msg_type,
                "recvId": user_id,
                "receipt": False
            }
            
            result = await self.api.request('POST', '/api/message/private/send', json=payload)
            message_id = result['data'].get('id')
            return message_id
        except Exception as e:
            return None

    async def send_group_message(self, group_id: int, content: str, msg_type: int = 0, 
                                at_user_ids: List[int] = None) -> Optional[int]:
        """发送群聊消息"""
        try:
            if self._is_group_muted(group_id):
                return None
                    
            tmp_id = str(uuid.uuid4().int)[:16]
            payload = {
                "tmpId": tmp_id,
                "content": content,
                "type": msg_type,
                "groupId": group_id,
                "atUserIds": at_user_ids or [],
                "receipt": False
            }
            
            result = await self.api.request('POST', '/api/message/group/send', json=payload)
            message_id = result['data'].get('id')
            return message_id
        except Exception as e:
            return None

    def _is_group_muted(self, group_id: int) -> bool:
        """检查群组是否被禁言"""
        if group_id not in self.group_mute_status:
            return False
            
        status = self.group_mute_status[group_id]
        if not status.get('muted', False):
            return False
            
        current_time = time.time()
        detected_time = status.get('detected_time', 0)
        
        if current_time - detected_time > self.mute_check_interval:
            self._set_group_muted(group_id, False)
            return False
            
        return True

    def _set_group_muted(self, group_id: int, muted: bool):
        """设置群组禁言状态"""
        if muted:
            self.group_mute_status[group_id] = {
                'muted': True,
                'detected_time': time.time()
            }
        else:
            if group_id in self.group_mute_status:
                del self.group_mute_status[group_id]

    def get_muted_groups(self) -> List[int]:
        """获取所有被禁言的群组列表"""
        muted_groups = []
        current_time = time.time()
        
        for group_id, status in self.group_mute_status.items():
            if status.get('muted', False):
                detected_time = status.get('detected_time', 0)
                if current_time - detected_time <= self.mute_check_interval:
                    muted_groups.append(group_id)
                else:
                    self._set_group_muted(group_id, False)
        
        return muted_groups

# ============ 聊天助手 ============
class ChatHelper:
    """聊天助手"""
    def __init__(self, boxim_instance):
        self.boxim = boxim_instance
        self.message = MessageModule(boxim_instance)

    async def send_private_text(self, user_id: int, text: str) -> Optional[int]:
        """发送私聊文本"""
        return await self.message.send_private_message(user_id, text, MessageType.TEXT)

    async def send_group_text(self, group_id: int, text: str, at_user_ids: List[int] = None) -> Optional[int]:
        """发送群聊文本"""
        return await self.message.send_group_message(group_id, text, MessageType.TEXT, at_user_ids)

# ============ 增强版机器人主类 ============
class EnhancedBoxIM:
    """增强版机器人主类"""
    
    def __init__(self):
        # 设置日志
        self._setup_logging()
        
        # 初始化数据库
        self.db = DatabaseManager()
        
        # 从数据库加载数据
        self._load_data_from_db()
        
        # 原有属性初始化
        self.access_token = None
        self.refresh_token = None
        self.access_token_expires = 0
        self.refresh_token_expires = 0
        self.user_id = None
        self.terminal = Terminal.PC
        self.username = BotConfig.USERNAME
        self.password = BotConfig.PASSWORD
        
        self.username_cache = {}
        self.username_cache_time = {}
        
        self.ws_connection = None
        self.ws_task = None
        self.ws_reconnect_count = 0
        self.ws_running = False
        self._ws_connected_flag = False
        self._last_connection_time = 0
        self._connection_quality = 1.0
        
        self.message_handlers = defaultdict(list)
        self.command_handlers = {}
        
        self._tasks = []
        
        self.start_time = time.time()
        self.message_count_today = 0
        self.last_reset_time = self._get_today_start()
        self._last_save_time = time.time()
        self.heartbeat_task = None
        
        self.last_message_time = 0
        self.consecutive_silence_count = 0
        self.max_consecutive_silence = 3
        
        self.monitor_group_id = 20250
        
        self.monitor_spam_detection = defaultdict(list)
        self.monitor_spam_warnings = {}
        self.monitor_spam_threshold = 5
        self.monitor_spam_interval = 5
        self.monitor_spam_cooldown = 300
        
        # 添加Token刷新控制
        self._last_token_refresh_time = 0
        self._token_refresh_cooldown = 30  # 至少30秒才刷新一次
        self._is_refreshing_token = False
        
        # 初始化模块
        self.user = UserModule(self)
        self.message = MessageModule(self)
        self.chat = ChatHelper(self)
        self.api = APIClient(self)
        
        # 初始化命令处理器
        self._init_command_handlers()
        
        self.message_handlers['private'].append(lambda msg: self._handle_private_message(msg))
        self.message_handlers['group'].append(lambda msg: self._handle_group_message(msg))
        
        logger.info("增强版机器人初始化完成")
    
    def _setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('bot.log', encoding='utf-8')
            ])
    
    def _load_data_from_db(self):
        """从数据库加载数据"""
        # 用户数据
        self.user_data = {}
        users = self.db.get_all_users()
        for user in users:
            user_id = user['user_id']
            
            # 转换数据格式
            user_dict = {
                'exp': user['exp'],
                'level': user['level'],
                'total_messages': user['total_messages'],
                'last_message_time': user['last_message_time'],
                'spam_warnings': user['spam_warnings'],
                'last_warning_time': user['last_warning_time'],
                'current_label': user['current_label'],
                'points': user['points'],
                'last_sign_date': user['last_sign_date'],
                'consecutive_days': user['consecutive_days'],
                'total_sign_days': user['total_sign_days'],
                'lottery_count': user['lottery_count'],
                'lottery_wins': user['lottery_wins'],
                'command_count': user['command_count'],
            }
            
            self.user_data[str(user_id)] = user_dict
        
        # 每日统计
        self.daily_message_stats = {}
        self.daily_active_users = {}
        
        logger.info(f"从数据库加载数据: {len(self.user_data)}用户")
    
    def _save_data(self):
        """保存数据到数据库"""
        try:
            # 保存用户数据
            for user_id_str, user_data in self.user_data.items():
                try:
                    user_id = int(user_id_str)
                    self.db.save_user(user_id, user_data)
                except (ValueError, TypeError) as e:
                    logger.warning(f"跳过无效用户ID {user_id_str}: {e}")
            
            # 保存每日统计
            today = datetime.now().strftime("%Y-%m-%d")
            self.db.save_daily_stat(
                today,
                self.message_count_today,
                len([uid for uid, data in self.user_data.items()
                     if data.get('last_message_time', 0) >= self.last_reset_time])
            )
            
            logger.info("数据保存完成")
            
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
    
    def _init_command_handlers(self):
        """初始化命令处理器"""
        # 这里可以添加命令处理器
        pass
    
    def _get_today_start(self):
        """获取今天开始时间"""
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        return today_start.timestamp()
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Host": "www.boxim.online",
            "Origin": APIConfig.BASE_URL,
            "Referer": f"{APIConfig.BASE_URL}/",
            "User-Agent": APIConfig.USER_AGENT,
        }
        
        if self.access_token:
            headers["accessToken"] = self.access_token
            
        return headers
    
    @property
    def is_logged_in(self) -> bool:
        """检查是否登录"""
        if not self.access_token:
            return False
        
        current_time = time.time()
        # 如果Token即将过期（5分钟内），则认为需要刷新
        if current_time >= (self.access_token_expires - 300):
            return False
            
        return True
    
    async def ensure_valid_token(self) -> bool:
        """确保Token有效"""
        current_time = time.time()
        
        # 防止频繁检查，至少间隔10秒
        if current_time - self._last_token_refresh_time < 10:
            return True
        
        if not self.access_token or current_time >= (self.access_token_expires - 300):
            logger.warning("Token无效或即将过期，尝试刷新...")
            result = await self.refresh_token_if_needed()
            self._last_token_refresh_time = current_time
            return result
        return True
    
    async def refresh_token_if_needed(self):
        """刷新Token如果需要"""
        current_time = time.time()
        
        # 防止并发刷新
        if self._is_refreshing_token:
            logger.info("Token刷新正在进行中，跳过...")
            return False
        
        # 防止频繁刷新
        if current_time - self._last_token_refresh_time < self._token_refresh_cooldown:
            logger.info(f"Token刷新冷却中，还需{self._token_refresh_cooldown - (current_time - self._last_token_refresh_time):.0f}秒")
            return True
        
        # 检查Token是否即将过期或已过期
        if current_time >= (self.access_token_expires - 300):  # 提前5分钟刷新
            self._is_refreshing_token = True
            try:
                logger.info("Token即将过期，尝试刷新...")
                
                # 使用refreshToken刷新
                refresh_data = {
                    "refreshToken": self.refresh_token,
                    "terminal": self.terminal.value
                }
                
                async with aiohttp.ClientSession(
                        connector=aiohttp.TCPConnector(ssl=ssl_context),
                        timeout=aiohttp.ClientTimeout(total=APIConfig.REQUEST_TIMEOUT)) as session:
                    async with session.post(
                        f"{APIConfig.BASE_URL}/api/refresh",
                        json=refresh_data,
                        headers=self._get_headers()
                    ) as response:
                        
                        if response.status == 200:
                            result = await response.json()
                            if result.get("code") == 200:
                                data = result['data']
                                self.access_token = data['accessToken']
                                self.refresh_token = data.get('refreshToken', self.refresh_token)
                                self.access_token_expires = time.time() + data['accessTokenExpiresIn']
                                if 'refreshTokenExpiresIn' in data:
                                    self.refresh_token_expires = time.time() + data['refreshTokenExpiresIn']
                                
                                self._last_token_refresh_time = current_time
                                logger.info(f"Token刷新成功，有效期: {data['accessTokenExpiresIn']}秒")
                                return True
                            else:
                                logger.error(f"Token刷新API返回错误: {result.get('message')}")
                        else:
                            logger.error(f"Token刷新请求失败，状态码: {response.status}")
                
                # 如果刷新失败，尝试重新登录
                logger.info("尝试重新登录...")
                if await self.login(self.username, self.password):
                    logger.info("重新登录成功")
                    self._last_token_refresh_time = current_time
                    return True
                else:
                    logger.error("重新登录失败")
                    return False
                    
            except Exception as e:
                logger.error(f"Token刷新失败: {e}")
                return False
            finally:
                self._is_refreshing_token = False
        
        return True
    
    async def get_username(self, user_id: int) -> str:
        """获取用户名"""
        current_time = time.time()
        if user_id in self.username_cache and current_time - self.username_cache_time.get(user_id, 0) < 3600:
            return self.username_cache[user_id]

        try:
            user_info = await self.user.get_user_info(user_id)
            if user_info and user_info.get('nickName'):
                username = user_info['nickName']
                self.username_cache[user_id] = username
                self.username_cache_time[user_id] = current_time
                return username
            else:
                return f"用户{user_id}"
        except:
            return f"用户{user_id}"
    
    async def _handle_private_message(self, message: Message):
        """处理私聊消息"""
        try:
            if message.type == MessageType.ONLINE_STATUS:
                return
                
            logger.info(f"收到私聊消息: 用户{message.send_id} 类型:{message.type}")
            
            if message.type == MessageType.TEXT:
                current_time = time.time()
                self.last_message_time = current_time
                self.message_count_today += 1
                
        except Exception as e:
            logger.error(f"处理私聊消息时发生异常: {e}")
    
    async def _handle_group_message(self, message: Message):
        """处理群聊消息"""
        try:
            # 跳过群操作消息
            if message.type in [MessageType.JOIN_GROUP, MessageType.LEAVE_GROUP,
                              MessageType.GROUP_ALL_MUTE, MessageType.GROUP_USER_MUTE]:
                return
                
            logger.info(f"收到群聊消息: 群{message.group_id} 用户{message.send_id} 类型:{message.type}")
            
            # 处理文本和表情消息
            if message.type in [MessageType.TEXT, MessageType.STICKER]:
                current_time = time.time()
                self.last_message_time = current_time
                self.message_count_today += 1
                
        except Exception as e:
            logger.error(f"处理群聊消息时发生异常: {e}")
    
    async def login(self, username: str, password: str, terminal: Terminal = Terminal.PC) -> bool:
        """登录"""
        self.terminal = terminal
        self.username = username
        self.password = password
        
        self.access_token = None
        self.refresh_token = None
        
        logger.info(f"尝试登录用户: {username}")
        
        try:
            # 直接调用API登录，不检查Token（因为此时还没有Token）
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_context),
                    timeout=aiohttp.ClientTimeout(total=APIConfig.REQUEST_TIMEOUT)) as session:
                async with session.post(
                    f"{APIConfig.BASE_URL}/api/login",
                    json={
                        "terminal": terminal.value,
                        "userName": username,
                        "password": password
                    },
                    headers=self._get_headers()
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        if result.get("code") == 200:
                            data = result['data']
                            self.access_token = data['accessToken']
                            self.refresh_token = data['refreshToken']
                            self.access_token_expires = time.time() + data['accessTokenExpiresIn']
                            self.refresh_token_expires = time.time() + data['refreshTokenExpiresIn']

                            logger.info(f"登录成功，Token有效期: {data['accessTokenExpiresIn']}秒")

                            try:
                                parts = self.access_token.split('.')
                                if len(parts) != 3:
                                    raise ValueError("Invalid JWT token format")
                                payload_part = parts[1]
                                padding = 4 - (len(payload_part) % 4)
                                if padding != 4:
                                    payload_part += '=' * padding
                                payload_bytes = base64.urlsafe_b64decode(payload_part)
                                payload_str = payload_bytes.decode('utf-8')
                                payload_data = json.loads(payload_str)

                                user_id = None
                                if 'userId' in payload_data:
                                    user_id = payload_data['userId']
                                elif 'sub' in payload_data:
                                    user_id = payload_data['sub']
                                elif 'user_id' in payload_data:
                                    user_id = payload_data['user_id']

                                if user_id:
                                    self.user_id = int(user_id)
                                else:
                                    # 通过API获取自身信息
                                    user_info = await self.user.get_self_info()
                                    if user_info and user_info.get('id'):
                                        self.user_id = user_info['id']
                                    else:
                                        logger.error("无法获取用户ID")
                                        return False
                            except Exception as e:
                                logger.error(f"解析token失败: {e}")
                                # 通过API获取自身信息
                                user_info = await self.user.get_self_info()
                                if user_info and user_info.get('id'):
                                    self.user_id = user_info['id']
                                else:
                                    logger.error("通过API获取用户信息也失败")
                                    return False

                            logger.info(f"登录成功: 用户ID={self.user_id}")
                            self.last_message_time = time.time()
                            self._last_connection_time = time.time()
                            self._last_token_refresh_time = time.time()
                            return True
                        else:
                            error_msg = result.get("message", "未知错误")
                            logger.error(f"登录失败: {error_msg}")
                            return False
                    else:
                        logger.error(f"登录请求失败，状态码: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"登录失败: {e}")
            return False
    
    async def connect(self) -> bool:
        """连接WebSocket"""
        if not self.is_logged_in:
            logger.error("未登录，无法连接WebSocket")
            return False
        if self.ws_running:
            logger.warning("WebSocket已在运行")
            return True

        self.ws_running = True
        self.ws_task = asyncio.create_task(self._ws_loop())
        self._tasks.append(self.ws_task)

        for _ in range(10):
            if self._ws_connected_flag:
                return True
            await asyncio.sleep(0.5)
        return False
    
    async def _ws_loop(self):
        """WebSocket循环"""
        consecutive_failures = 0
        max_failures = BotConfig.MAX_RECONNECT_ATTEMPTS
        
        while self.ws_running:
            try:
                await self._ws_connect()
                self.ws_reconnect_count = 0
                consecutive_failures = 0
                logger.info("WebSocket连接成功，重置失败计数")
                
                # 连接成功后等待连接断开
                while self._ws_connected_flag and self.ws_running:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"WebSocket异常: {e}")
                consecutive_failures += 1
                logger.warning(f"WebSocket连接失败，连续失败次数: {consecutive_failures}/{max_failures}")

            if self.ws_running and not self._ws_connected_flag:
                if consecutive_failures >= max_failures:
                    logger.error(f"达到最大重连次数({max_failures})，尝试重新登录...")
                    if await self.relogin():
                        logger.info("重新登录成功，重置重连计数")
                        consecutive_failures = 0
                        self.ws_reconnect_count = 0
                    else:
                        logger.error("重新登录失败，继续重连...")
                        consecutive_failures = max_failures - 1
                        
                self.ws_reconnect_count += 1
                delay = min(
                    BotConfig.RECONNECT_DELAY * (2**self.ws_reconnect_count),
                    BotConfig.MAX_RECONNECT_DELAY)
                logger.info(f"将在{delay}秒后重连...")
                await asyncio.sleep(delay)
    
    async def _ws_connect(self):
        """WebSocket连接"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        logger.info(f"正在连接WebSocket... (第{self.ws_reconnect_count + 1}次)")

        for attempt in range(3):
            try:
                self.ws_connection = await asyncio.wait_for(
                    websockets.connect(
                        APIConfig.WS_URL,
                        ssl=ssl_context,
                        ping_interval=BotConfig.HEARTBEAT_INTERVAL,
                        ping_timeout=10,
                        close_timeout=10,
                        max_size=2**20,
                        open_timeout=BotConfig.CONNECTION_TIMEOUT
                    ),
                    timeout=BotConfig.CONNECTION_TIMEOUT
                )
                logger.info(f"WebSocket连接成功 (尝试 {attempt + 1})")
                break
            except asyncio.TimeoutError:
                logger.warning(f"WebSocket连接超时，第{attempt + 1}次重试")
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"WebSocket连接异常，第{attempt + 1}次重试: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        self.ws_reconnect_count = 0
        self._ws_connected_flag = True
        self._last_connection_time = time.time()
        await self._ws_auth()

        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()

        self.heartbeat_task = asyncio.create_task(self._ws_heartbeat())

        try:
            await self._ws_receive()
        finally:
            self._ws_connected_flag = False
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass
    
    async def _ws_auth(self):
        """WebSocket认证"""
        auth_msg = json.dumps({
            "cmd": WSCommand.AUTH.value,
            "data": {
                "accessToken": self.access_token
            }
        })
        await asyncio.wait_for(self.ws_connection.send(auth_msg), timeout=5.0)
        logger.info("WebSocket认证已发送")
        
        await asyncio.sleep(1)
    
    async def _ws_heartbeat(self):
        """WebSocket心跳"""
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while self.ws_running and self._ws_connected_flag:
            try:
                heartbeat_msg = json.dumps({
                    "cmd": WSCommand.HEARTBEAT.value,
                    "data": {}
                })
                await asyncio.wait_for(self.ws_connection.send(heartbeat_msg), timeout=3.0)
                logger.debug("心跳发送成功")
                consecutive_failures = 0
                await asyncio.sleep(BotConfig.HEARTBEAT_INTERVAL)
                
            except asyncio.TimeoutError:
                consecutive_failures += 1
                logger.warning(f"心跳发送超时，连续失败次数: {consecutive_failures}")
                if consecutive_failures >= max_consecutive_failures:
                    logger.error("心跳连续失败，断开连接")
                    self._ws_connected_flag = False
                    break
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接已关闭，停止心跳")
                self._ws_connected_flag = False
                break
                
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"心跳发送失败: {e}")
                if consecutive_failures >= max_consecutive_failures:
                    self._ws_connected_flag = False
                    break
                await asyncio.sleep(2)
    
    async def _ws_receive(self):
        """WebSocket接收消息"""
        logger.info("开始WebSocket消息接收循环")
        try:
            async for message in self.ws_connection:
                self.last_message_time = time.time()
                data = json.loads(message)
                await self._handle_ws_message(data)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket连接已关闭")
            self._ws_connected_flag = False
    
    async def _handle_ws_message(self, data: Dict):
        """处理WebSocket消息"""
        cmd = data.get('cmd')
        msg_data = data.get('data', {})
        
        if cmd == WSCommand.PRIVATE_MESSAGE:
            msg = Message(msg_data, is_group=False)
            await self._dispatch_message(msg, 'private')
        elif cmd == WSCommand.GROUP_MESSAGE:
            msg = Message(msg_data, is_group=True)
            await self._dispatch_message(msg, 'group')
        elif cmd == WSCommand.SYSTEM_MESSAGE:
            logger.info(f"收到系统消息: {msg_data}")
        elif cmd == WSCommand.HEARTBEAT:
            logger.debug("收到心跳消息，无需回复")
        elif cmd == WSCommand.FORCE_OFFLINE:
            logger.warning("收到强制下线通知")
            self.ws_running = False
            self._ws_connected_flag = False
    
    async def _dispatch_message(self, message: Message, msg_type: str):
        """分发消息"""
        handlers = self.message_handlers.get(msg_type, [])
        
        for handler in handlers:
            try:
                await handler(message)
            except Exception as e:
                logger.error(f"消息处理器异常: {e}")
    
    async def relogin(self) -> bool:
        """重新登录"""
        logger.info("检测到Token过期，尝试重新登录...")
        
        # 重置Token状态
        self.access_token = None
        self.refresh_token = None
        self.access_token_expires = 0
        self.refresh_token_expires = 0
        
        # 尝试重新登录
        success = await self.login(self.username, self.password)
        if success:
            logger.info("重新登录成功")
            
            # 尝试重新连接WebSocket
            if self.ws_running:
                await self.disconnect()
                await asyncio.sleep(2)
                await self.connect()
            return True
        else:
            logger.error("重新登录失败")
            return False
    
    async def disconnect(self):
        """断开WebSocket连接"""
        self.ws_running = False
        self._ws_connected_flag = False
        if self.ws_connection:
            await self.ws_connection.close()
            self.ws_connection = None
        if self.ws_task and not self.ws_task.done():
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

    async def robust_start(self):
        """稳健启动"""
        logger.info("增强版机器人启动...")
        
        # 登录
        logger.info("正在进行登录...")
        if await self.login(self.username, self.password):
            logger.info("登录成功")
            self._last_token_refresh_time = time.time()
            
            # 连接WebSocket
            logger.info("连接WebSocket...")
            success = await self.connect()
            if success:
                logger.info("机器人启动成功！开始监听消息...")
                last_activity_time = time.time()

                while self.ws_running:
                    await asyncio.sleep(1)

                    current_time = time.time()

                    # 定期记录状态
                    if current_time - last_activity_time > 600:
                        last_activity_time = current_time
                        if self._ws_connected_flag:
                            silence_minutes = (current_time - self.last_message_time) / 60
                            logger.info(f"机器人运行中... 最后消息: {silence_minutes:.1f}分钟前")

                    # 自动保存数据
                    if current_time - self._last_save_time > 1800:
                        self._save_data()
                        self._last_save_time = current_time
                        logger.info("自动保存数据完成")
            else:
                logger.error("连接失败，机器人启动失败")
        else:
            logger.error("登录失败，无法启动")
    
    async def stop(self):
        """停止机器人"""
        logger.info("停止增强版机器人...")
        
        # 保存数据
        self._save_data()
        
        # 优化数据库
        self.db.optimize()
        
        # 断开连接
        await self.disconnect()
        
        # 关闭数据库
        self.db.close()
        
        logger.info("机器人已停止")
    
    # Web界面使用的状态获取方法
    def get_bot_status(self) -> Dict:
        """获取机器人状态"""
        current_time = time.time()
        uptime_seconds = current_time - self.start_time
        
        def format_time(seconds: float) -> str:
            if seconds < 60:
                return f"{int(seconds)}秒"
            elif seconds < 3600:
                minutes = int(seconds // 60)
                seconds = int(seconds % 60)
                return f"{minutes}分{seconds}秒"
            elif seconds < 86400:
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                return f"{hours}小时{minutes}分"
            else:
                days = int(seconds // 86400)
                hours = int((seconds % 86400) // 3600)
                return f"{days}天{hours}小时"
        
        status = {
            "is_running": self.ws_running,
            "is_connected": self._ws_connected_flag,
            "is_logged_in": self.is_logged_in,
            "user_id": self.user_id,
            "username": self.username,
            "uptime": format_time(uptime_seconds),
            "start_time": datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S'),
            "last_message_time": datetime.fromtimestamp(self.last_message_time).strftime('%Y-%m-%d %H:%M:%S') if self.last_message_time > 0 else "从未",
            "message_count_today": self.message_count_today,
            "ws_reconnect_count": self.ws_reconnect_count,
            "access_token_expires": datetime.fromtimestamp(self.access_token_expires).strftime('%Y-%m-%d %H:%M:%S') if self.access_token_expires > 0 else "无效",
            "refresh_token_expires": datetime.fromtimestamp(self.refresh_token_expires).strftime('%Y-%m-%d %H:%M:%S') if self.refresh_token_expires > 0 else "无效",
        }
        
        return status
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        stats = self.db.get_statistics()
        return stats