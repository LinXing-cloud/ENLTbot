"""
API客户端
"""

import aiohttp
import json
import time
import logging
from typing import Dict, Optional
from config import APIConfig, ssl_context

logger = logging.getLogger('BoxIM.APIClient')

class APIClient:
    """API客户端"""
    def __init__(self, boxim_instance):
        self.boxim = boxim_instance
        self._last_token_check = 0
        self._token_check_interval = 60

    async def request(self, method: str, path: str, **kwargs) -> Dict:
        """发送API请求"""
        # 对于登录请求，不检查Token
        if path != '/api/login':
            # 确保Token有效
            if not await self.boxim.ensure_valid_token():
                raise Exception("Token无效，无法发送请求")
        
        url = f"{APIConfig.BASE_URL}{path}"
        headers = self.boxim._get_headers()
        if 'headers' not in kwargs:
            kwargs['headers'] = headers
        else:
            kwargs['headers'].update(headers)
        
        try:
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_context),
                    timeout=aiohttp.ClientTimeout(total=APIConfig.REQUEST_TIMEOUT)) as session:
                async with session.request(method, url, **kwargs) as response:
                    # 如果Token过期，尝试刷新后重试
                    if response.status == 401:
                        current_time = time.time()
                        # 防止频繁刷新，至少间隔30秒
                        if current_time - self._last_token_check < 30:
                            raise Exception("Token刷新过于频繁")
                        
                        self._last_token_check = current_time
                        logger.warning("Token过期，尝试刷新并重试...")
                        if await self.boxim.refresh_token_if_needed():
                            # 更新headers后重试
                            kwargs['headers']['accessToken'] = self.boxim.access_token
                            async with session.request(method, url, **kwargs) as retry_response:
                                response_text = await retry_response.text()
                                data = json.loads(response_text)
                                
                                if data.get("code") != 200:
                                    error_msg = f"API错误: {data.get('message')} (代码: {data.get('code')})"
                                    raise Exception(error_msg)
                                
                                return data
                        else:
                            raise Exception("Token刷新失败")
                    
                    response_text = await response.text()
                    data = json.loads(response_text)
                    
                    if data.get("code") != 200:
                        error_msg = f"API错误: {data.get('message')} (代码: {data.get('code')})"
                        raise Exception(error_msg)
                    
                    return data
        except Exception as e:
            raise

    async def get_group_info(self, group_id: int) -> Dict:
        """获取群聊信息"""
        result = await self.request('GET', f'/api/group/find/{group_id}')
        return result

    async def get_group_members(self, group_id: int) -> Dict:
        """获取群聊成员"""
        result = await self.request('GET', f'/api/group/members/{group_id}')
        return result

    async def get_joined_groups(self) -> Dict:
        """获取机器人已加入的群聊列表"""
        result = await self.request('GET', '/api/group/list')
        return result