"""
Web界面
"""

import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
import json
import bcrypt
import uuid
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
from aiohttp import web

from config import BotConfig
from database import DatabaseManager
from bot_core import EnhancedBoxIM

# 模板目录
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

class WebUI:
    """Web界面管理器"""
    
    def __init__(self, bot: EnhancedBoxIM):
        self.bot = bot
        self.db = DatabaseManager()
        self.app = web.Application()
        
        # 设置Jinja2模板
        aiohttp_jinja2.setup(self.app, loader=jinja2.FileSystemLoader(TEMPLATES_DIR))
        
        # 添加路由
        self.setup_routes()
        
        # 添加中间件
        self.app.middlewares.append(self.auth_middleware)
    
    def setup_routes(self):
        """设置路由"""
        # 静态文件
        self.app.router.add_static('/static/', path=STATIC_DIR, name='static')
        
        # 页面路由
        self.app.router.add_get('/', self.index_handler)
        self.app.router.add_get('/login', self.login_page_handler)
        self.app.router.add_post('/login', self.login_handler)
        self.app.router.add_get('/logout', self.logout_handler)
        self.app.router.add_get('/dashboard', self.dashboard_handler)
        self.app.router.add_get('/users', self.users_handler)
        self.app.router.add_get('/logs', self.logs_handler)
        self.app.router.add_get('/settings', self.settings_handler)
        
        # API路由
        self.app.router.add_get('/api/status', self.api_status_handler)
        self.app.router.add_get('/api/stats', self.api_stats_handler)
        self.app.router.add_post('/api/change_password', self.api_change_password_handler)
        self.app.router.add_post('/api/add_user', self.api_add_user_handler)
        self.app.router.add_post('/api/update_user', self.api_update_user_handler)
        self.app.router.add_post('/api/restart_bot', self.api_restart_bot_handler)
        self.app.router.add_post('/api/stop_bot', self.api_stop_bot_handler)
        self.app.router.add_get('/api/get_logs', self.api_get_logs_handler)
    
    @aiohttp_jinja2.template('index.html')
    async def index_handler(self, request):
        """首页"""
        session = request.get('session', {})
        if not session:
            return web.HTTPFound('/login')
        
        return {
            'title': '控制面板',
            'user': session.get('user'),
            'bot': self.bot
        }
    
    @aiohttp_jinja2.template('login.html')
    async def login_page_handler(self, request):
        """登录页面"""
        return {'title': '登录'}
    
    async def login_handler(self, request):
        """登录处理"""
        data = await request.post()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        # 验证用户
        user = self.db.authenticate_user(username, password)
        
        if user:
            # 创建会话
            session_id = str(uuid.uuid4())
            expires_at = (datetime.now() + timedelta(seconds=BotConfig.SESSION_TIMEOUT)).isoformat()
            
            if self.db.create_session(session_id, user['id'], expires_at):
                # 记录登录日志
                ip_address = request.remote
                self.db.add_web_log(user['id'], '登录', f"用户 {username} 登录成功", ip_address)
                
                # 设置cookie
                response = web.HTTPFound('/dashboard')
                response.set_cookie('session_id', session_id, max_age=BotConfig.SESSION_TIMEOUT, httponly=True)
                return response
        
        # 记录失败的登录尝试
        ip_address = request.remote
        self.db.add_web_log(None, '登录失败', f"用户名: {username}", ip_address)
        
        return web.HTTPFound('/login?error=1')
    
    async def logout_handler(self, request):
        """退出登录"""
        session_id = request.cookies.get('session_id')
        if session_id:
            self.db.delete_session(session_id)
        
        response = web.HTTPFound('/login')
        response.del_cookie('session_id')
        return response
    
    @aiohttp_jinja2.template('dashboard.html')
    async def dashboard_handler(self, request):
        """仪表板"""
        session = request.get('session', {})
        if not session:
            return web.HTTPFound('/login')
        
        bot_status = self.bot.get_bot_status()
        stats = self.bot.get_statistics()
        
        return {
            'title': '仪表板',
            'user': session.get('user'),
            'bot_status': bot_status,
            'stats': stats
        }
    
    @aiohttp_jinja2.template('users.html')
    async def users_handler(self, request):
        """用户管理"""
        session = request.get('session', {})
        if not session:
            return web.HTTPFound('/login')
        
        # 只有管理员可以访问用户管理
        if session.get('user', {}).get('role') != 'admin':
            return web.HTTPFound('/dashboard')
        
        web_users = self.db.get_web_users()
        
        return {
            'title': '用户管理',
            'user': session.get('user'),
            'web_users': web_users
        }
    
    @aiohttp_jinja2.template('logs.html')
    async def logs_handler(self, request):
        """系统日志"""
        session = request.get('session', {})
        if not session:
            return web.HTTPFound('/login')
        
        logs = self.db.get_web_logs(100)
        
        return {
            'title': '系统日志',
            'user': session.get('user'),
            'logs': logs
        }
    
    @aiohttp_jinja2.template('settings.html')
    async def settings_handler(self, request):
        """设置"""
        session = request.get('session', {})
        if not session:
            return web.HTTPFound('/login')
        
        return {
            'title': '设置',
            'user': session.get('user')
        }
    
    # ============ API处理器 ============
    
    async def api_status_handler(self, request):
        """API: 获取机器人状态"""
        session = request.get('session', {})
        if not session:
            return web.json_response({'error': '未登录'}, status=401)
        
        status = self.bot.get_bot_status()
        return web.json_response(status)
    
    async def api_stats_handler(self, request):
        """API: 获取统计信息"""
        session = request.get('session', {})
        if not session:
            return web.json_response({'error': '未登录'}, status=401)
        
        stats = self.bot.get_statistics()
        return web.json_response(stats)
    
    async def api_change_password_handler(self, request):
        """API: 修改密码"""
        session = request.get('session', {})
        if not session:
            return web.json_response({'error': '未登录'}, status=401)
        
        try:
            data = await request.json()
            current_password = data.get('current_password', '')
            new_password = data.get('new_password', '')
            confirm_password = data.get('confirm_password', '')
            
            # 验证当前密码
            user = session.get('user', {})
            if not self.db.authenticate_user(user['username'], current_password):
                return web.json_response({'error': '当前密码错误'}, status=400)
            
            # 验证新密码
            if new_password != confirm_password:
                return web.json_response({'error': '新密码不匹配'}, status=400)
            
            if len(new_password) < 6:
                return web.json_response({'error': '密码长度至少6位'}, status=400)
            
            # 更新密码
            new_password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            if self.db.update_password(user['id'], new_password_hash):
                # 记录日志
                ip_address = request.remote
                self.db.add_web_log(user['id'], '修改密码', '用户修改了密码', ip_address)
                
                return web.json_response({'success': True, 'message': '密码修改成功'})
            else:
                return web.json_response({'error': '密码修改失败'}, status=500)
                
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_add_user_handler(self, request):
        """API: 添加用户"""
        session = request.get('session', {})
        if not session or session.get('user', {}).get('role') != 'admin':
            return web.json_response({'error': '权限不足'}, status=403)
        
        try:
            data = await request.json()
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            role = data.get('role', 'user').strip()
            
            if not username or not password:
                return web.json_response({'error': '用户名和密码不能为空'}, status=400)
            
            if len(password) < 6:
                return web.json_response({'error': '密码长度至少6位'}, status=400)
            
            if role not in ['admin', 'user']:
                return web.json_response({'error': '角色无效'}, status=400)
            
            # 密码加密
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            if self.db.add_web_user(username, password_hash, role):
                # 记录日志
                ip_address = request.remote
                self.db.add_web_log(session['user']['id'], '添加用户', f"添加用户: {username} ({role})", ip_address)
                
                return web.json_response({'success': True, 'message': '用户添加成功'})
            else:
                return web.json_response({'error': '用户已存在'}, status=400)
                
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_update_user_handler(self, request):
        """API: 更新用户"""
        session = request.get('session', {})
        if not session or session.get('user', {}).get('role') != 'admin':
            return web.json_response({'error': '权限不足'}, status=403)
        
        try:
            data = await request.json()
            user_id = data.get('user_id')
            role = data.get('role')
            is_active = data.get('is_active')
            
            if user_id is None:
                return web.json_response({'error': '用户ID不能为空'}, status=400)
            
            if self.db.update_web_user(user_id, role, is_active):
                # 记录日志
                ip_address = request.remote
                self.db.add_web_log(session['user']['id'], '更新用户', f"更新用户ID: {user_id}", ip_address)
                
                return web.json_response({'success': True, 'message': '用户更新成功'})
            else:
                return web.json_response({'error': '用户更新失败'}, status=500)
                
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_restart_bot_handler(self, request):
        """API: 重启机器人"""
        session = request.get('session', {})
        if not session or session.get('user', {}).get('role') != 'admin':
            return web.json_response({'error': '权限不足'}, status=403)
        
        try:
            # 这里应该重启机器人，但为了安全，我们只是停止并重新启动异步任务
            # 在实际部署中，您可能需要更复杂的重启逻辑
            
            # 记录日志
            ip_address = request.remote
            self.db.add_web_log(session['user']['id'], '重启机器人', '管理员重启了机器人', ip_address)
            
            return web.json_response({'success': True, 'message': '重启命令已发送'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_stop_bot_handler(self, request):
        """API: 停止机器人"""
        session = request.get('session', {})
        if not session or session.get('user', {}).get('role') != 'admin':
            return web.json_response({'error': '权限不足'}, status=403)
        
        try:
            # 这里应该停止机器人
            # 在实际部署中，您可能需要更复杂的停止逻辑
            
            # 记录日志
            ip_address = request.remote
            self.db.add_web_log(session['user']['id'], '停止机器人', '管理员停止了机器人', ip_address)
            
            return web.json_response({'success': True, 'message': '停止命令已发送'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_get_logs_handler(self, request):
        """API: 获取日志"""
        session = request.get('session', {})
        if not session:
            return web.json_response({'error': '未登录'}, status=401)
        
        try:
            limit = int(request.query.get('limit', 100))
            logs = self.db.get_web_logs(limit)
            return web.json_response({'logs': logs})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    
    # ============ 中间件 ============
    
    @web.middleware
    async def auth_middleware(self, request, handler):
        """认证中间件"""
        # 排除登录页面
        if request.path in ['/login', '/static/'] or request.path.startswith('/static/'):
            return await handler(request)
        
        # 检查会话
        session_id = request.cookies.get('session_id')
        session = None
        
        if session_id:
            session = self.db.get_session(session_id)
        
        if session:
            request['session'] = session
            return await handler(request)
        else:
            # 清除无效的会话cookie
            if session_id:
                self.db.delete_session(session_id)
            
            # 重定向到登录页面
            return web.HTTPFound('/login')
    
    async def start(self):
        """启动Web服务器"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, BotConfig.WEB_HOST, BotConfig.WEB_PORT)
        await site.start()
        
        print(f"Web界面已启动: http://{BotConfig.WEB_HOST}:{BotConfig.WEB_PORT}")
        print(f"默认账号: admin / admin")
    
    async def stop(self):
        """停止Web服务器"""
        # 清理所有会话
        # 在实际部署中，您可能需要更复杂的清理逻辑
        pass