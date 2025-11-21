import asyncio
import aiohttp
import websockets
import json
import time
import uuid
import os
import ssl
import logging
import math
import random
import re
from typing import Optional, Dict, List, Callable, Any, Union
from enum import IntEnum
from datetime import datetime, timedelta
import base64
from collections import defaultdict, deque
import certifi
from flask import Flask, jsonify, render_template_string, request, send_file
import threading
import requests
import html
import tempfile
import psutil
import sys
import platform

# SSL上下文配置
ssl_context = ssl.create_default_context(cafile=certifi.where())

# ============================ 日志系统配置 ============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ])
logger = logging.getLogger('BoxIM')

# 创建日志缓冲区用于Web显示
log_buffer = deque(maxlen=1000)

class LogBufferHandler(logging.Handler):
    """自定义日志处理器，将日志记录到缓冲区用于Web显示"""
    
    def __init__(self):
        super().__init__()
        self.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        """发射日志记录到缓冲区"""
        log_entry = self.format(record)
        log_buffer.append(log_entry)

# 添加缓冲区处理器
buffer_handler = LogBufferHandler()
buffer_handler.setLevel(logging.INFO)
logger.addHandler(buffer_handler)

# ============================ Flask应用初始化 ============================
app = Flask(__name__)
bot_instance = None

# ============================ 健康检查端点 ============================

@app.route('/health')
def health_check():
    """健康检查端点"""
    try:
        ws_connected = False
        if bot_instance:
            # 安全的WebSocket连接状态检查
            if hasattr(bot_instance, 'ws_connection') and bot_instance.ws_connection:
                # 兼容不同版本的websockets库
                if hasattr(bot_instance.ws_connection, 'closed'):
                    ws_connected = not bot_instance.ws_connection.closed
                elif hasattr(bot_instance.ws_connection, 'open'):
                    ws_connected = bot_instance.ws_connection.open
                else:
                    # 如果无法确定状态，假设连接正常
                    ws_connected = True
        
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "bot_running": bot_instance is not None,
            "ws_connected": ws_connected,
            "environment": os.environ.get('RAILWAY_ENVIRONMENT', 'unknown')
        })
    except Exception as e:
        logger.error(f"健康检查错误: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/ping')
def ping():
    """Ping 端点"""
    return jsonify({"status": "pong", "timestamp": time.time()})

@app.route('/keepalive')
def keepalive():
    """保活端点"""
    return jsonify({"status": "alive", "timestamp": time.time()})

@app.route('/status')
def status():
    """状态端点"""
    try:
        if bot_instance:
            # 安全的WebSocket连接状态检查
            ws_connected = False
            if hasattr(bot_instance, 'ws_connection') and bot_instance.ws_connection:
                if hasattr(bot_instance.ws_connection, 'closed'):
                    ws_connected = not bot_instance.ws_connection.closed
                elif hasattr(bot_instance.ws_connection, 'open'):
                    ws_connected = bot_instance.ws_connection.open
            
            return jsonify({
                "status": "running",
                "user_id": bot_instance.user_id,
                "ws_connected": ws_connected,
                "message_count_today": bot_instance.message_count_today,
                "uptime": time.time() - bot_instance.start_time
            })
        return jsonify({"status": "not_running"})
    except Exception as e:
        logger.error(f"状态检查错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/botinfo')
def botinfo():
    """机器人信息端点"""
    try:
        if bot_instance:
            return jsonify({
                "name": "ENLTbot",
                "version": "2.0",
                "user_id": bot_instance.user_id,
                "status": "running" if bot_instance.ws_running else "stopped",
                "start_time": bot_instance.start_time,
                "total_users": len(bot_instance.user_data)
            })
        return jsonify({"status": "bot_not_initialized"})
    except Exception as e:
        logger.error(f"机器人信息错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================ 真实数据统计系统 ============================
class RealStatistics:
    """
    真实数据统计系统 - 记录所有真实消息和活动数据
    用于Web面板显示真实统计信息
    """
    
    def __init__(self):
        # 消息历史记录，最多保存5000条
        self.message_history = deque(maxlen=5000)
        # 命令使用统计
        self.command_usage = defaultdict(int)
        # 每小时活动统计
        self.hourly_activity = defaultdict(int)
        # 用户活动统计
        self.user_activity = defaultdict(int)
        # 每日消息统计
        self.daily_messages = defaultdict(int)
        # 用户等级记录
        self.user_levels = defaultdict(int)
        # 系统启动时间
        self.start_time = time.time()
        # 消息类型统计
        self.message_types = defaultdict(int)
        # 群组消息统计
        self.group_messages = defaultdict(int)
        # 私聊消息统计
        self.private_messages = defaultdict(int)
        # 用户最后活动时间
        self.user_last_seen = defaultdict(float)
        # 群组最后活动时间
        self.group_last_seen = defaultdict(float)

    def record_message(self,
                       user_id: int,
                       message_type: str,
                       content: str = "",
                       is_group: bool = False,
                       group_id: int = None):
        """
        记录真实消息数据
        
        Args:
            user_id: 用户ID
            message_type: 消息类型
            content: 消息内容
            is_group: 是否为群组消息
            group_id: 群组ID
        """
        current_time = time.time()
        hour_key = datetime.now().strftime("%Y-%m-%d %H:00")
        day_key = datetime.now().strftime("%Y-%m-%d")

        # 创建消息记录
        message_record = {
            'timestamp': current_time,
            'user_id': user_id,
            'type': message_type,
            'content': content[:200],  # 限制内容长度
            'is_group': is_group,
            'group_id': group_id,
            'hour': hour_key,
            'day': day_key
        }

        # 添加到历史记录
        self.message_history.append(message_record)
        
        # 更新各种统计
        self.hourly_activity[hour_key] += 1
        self.user_activity[user_id] += 1
        self.daily_messages[day_key] += 1
        self.message_types[message_type] += 1
        self.user_last_seen[user_id] = current_time

        if is_group and group_id:
            self.group_messages[group_id] += 1
            self.group_last_seen[group_id] = current_time
        else:
            self.private_messages[user_id] += 1

        logger.debug(f"记录真实消息: 用户{user_id}, 类型: {message_type}, 群组: {is_group}, 内容: {content[:50]}...")

    def record_command(self, command: str, user_id: int):
        """记录命令使用情况"""
        self.command_usage[command] += 1

    def update_user_level(self, user_id: int, level: int):
        """更新用户等级"""
        self.user_levels[user_id] = level

    def get_recent_activity(self, hours: int = 24) -> List[Dict]:
        """获取最近活动记录"""
        cutoff_time = time.time() - (hours * 3600)
        return [
            msg for msg in self.message_history
            if msg['timestamp'] > cutoff_time
        ]

    def get_message_stats(self, hours: int = 24) -> Dict:
        """获取消息统计信息"""
        cutoff_time = time.time() - (hours * 3600)
        recent_messages = [
            msg for msg in self.message_history
            if msg['timestamp'] > cutoff_time
        ]

        # 按小时统计
        hourly_data = defaultdict(int)
        for msg in recent_messages:
            hour_key = datetime.fromtimestamp(msg['timestamp']).strftime("%H:00")
            hourly_data[hour_key] += 1

        # 确保所有小时都有数据
        result = {}
        current_hour = datetime.now().hour
        for i in range(24):
            hour = (current_hour - 23 + i) % 24
            hour_key = f"{hour:02d}:00"
            result[hour_key] = hourly_data.get(hour_key, 0)

        return result

    def get_user_stats(self, limit: int = 20) -> List[Dict]:
        """获取用户统计数据"""
        active_users = []
        for user_id, count in self.user_activity.items():
            active_users.append({
                'user_id': user_id,
                'message_count': count,
                'level': self.user_levels.get(user_id, 1),
                'last_seen': self.user_last_seen.get(user_id, 0),
                'private_messages': self.private_messages.get(user_id, 0),
                'group_messages': count - self.private_messages.get(user_id, 0)
            })

        # 按消息数量排序
        return sorted(active_users, key=lambda x: x['message_count'], reverse=True)[:limit]

    def get_command_stats(self, limit: int = 10) -> List[Dict]:
        """获取命令使用统计"""
        commands = []
        total_commands = sum(self.command_usage.values())
        
        for cmd, count in self.command_usage.items():
            percentage = round(count / max(1, total_commands) * 100, 1) if total_commands > 0 else 0
            commands.append({
                'command': cmd,
                'count': count,
                'percentage': percentage
            })

        return sorted(commands, key=lambda x: x['count'], reverse=True)[:limit]

    def get_daily_stats(self, days: int = 7) -> Dict:
        """获取每日统计信息"""
        dates = []
        counts = []

        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(date)
            counts.append(self.daily_messages.get(date, 0))

        return {
            'dates': list(reversed(dates)),
            'counts': list(reversed(counts))
        }

    def get_system_stats(self) -> Dict:
        """获取系统统计信息"""
        total_messages = len(self.message_history)
        unique_users = len(self.user_activity)
        total_commands = sum(self.command_usage.values())

        return {
            'total_messages': total_messages,
            'unique_users': unique_users,
            'total_commands': total_commands,
            'group_messages': sum(self.group_messages.values()),
            'private_messages': sum(self.private_messages.values()),
            'uptime': time.time() - self.start_time
        }

    def get_message_type_stats(self) -> Dict:
        """获取消息类型统计"""
        return dict(self.message_types)

    def get_active_groups(self, limit: int = 10) -> List[Dict]:
        """获取活跃群组统计"""
        groups = []
        for group_id, count in self.group_messages.items():
            groups.append({
                'group_id': group_id,
                'message_count': count,
                'last_seen': self.group_last_seen.get(group_id, 0)
            })

        return sorted(groups, key=lambda x: x['message_count'], reverse=True)[:limit]

# 创建真实统计实例
real_stats = RealStatistics()

# ============================ Web界面HTML模板 ============================
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ENLTbot - 真实数据监控面板</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary-color: #4e73df;
            --success-color: #1cc88a;
            --info-color: #36b9cc;
            --warning-color: #f6c23e;
            --danger-color: #e74a3b;
            --dark-color: #5a5c69;
        }

        body {
            background-color: #f8f9fc;
            font-family: 'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        }

        .sidebar {
            min-height: 100vh;
            background: linear-gradient(180deg, var(--primary-color) 0%, #224abe 100%);
            box-shadow: 0 0.15rem 1.75rem 0 rgba(58, 59, 69, 0.15);
            position: fixed;
            top: 0;
            left: 0;
            width: 250px;
            z-index: 1000;
        }

        .sidebar .nav-link {
            color: rgba(255, 255, 255, 0.8);
            padding: 1rem;
            font-weight: 500;
            border-left: 3px solid transparent;
            transition: all 0.3s;
        }

        .sidebar .nav-link:hover {
            color: #fff;
            background-color: rgba(255, 255, 255, 0.1);
            border-left-color: rgba(255, 255, 255, 0.5);
        }

        .sidebar .nav-link.active {
            color: #fff;
            background-color: rgba(255, 255, 255, 0.2);
            border-left-color: #fff;
        }

        .sidebar .nav-link i {
            width: 20px;
            text-align: center;
            margin-right: 10px;
        }

        .main-content {
            margin-left: 250px;
            padding: 20px;
            min-height: 100vh;
        }

        .stat-card {
            border-left: 0.25rem solid;
            transition: transform 0.3s, box-shadow 0.3s;
            border-radius: 0.35rem;
            box-shadow: 0 0.15rem 1.75rem 0 rgba(58, 59, 69, 0.1);
        }

        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 0.5rem 2rem 0 rgba(58, 59, 69, 0.2);
        }

        .stat-card.primary { border-left-color: var(--primary-color); }
        .stat-card.success { border-left-color: var(--success-color); }
        .stat-card.info { border-left-color: var(--info-color); }
        .stat-card.warning { border-left-color: var(--warning-color); }

        .log-entry { 
            font-family: 'Courier New', monospace; 
            font-size: 0.85rem;
            padding: 8px 12px;
            border-radius: 5px;
            margin-bottom: 5px;
            border-left: 3px solid transparent;
        }

        .log-info { 
            background-color: #e3f2fd; 
            border-left-color: #2196f3;
        }

        .log-warning { 
            background-color: #fff3e0; 
            border-left-color: #ff9800;
        }

        .log-error { 
            background-color: #ffebee; 
            border-left-color: #f44336;
        }

        .log-debug { 
            background-color: #f5f5f5; 
            border-left-color: #9e9e9e;
        }

        .chart-container {
            position: relative;
            height: 300px;
        }

        .badge-rank-1 { background: linear-gradient(45deg, #FFD700, #FFA500); }
        .badge-rank-2 { background: linear-gradient(45deg, #C0C0C0, #A9A9A9); }
        .badge-rank-3 { background: linear-gradient(45deg, #CD7F32, #8B4513); }

        .table-hover tbody tr:hover {
            background-color: rgba(78, 115, 223, 0.05);
        }

        .section-title {
            color: var(--primary-color);
            border-bottom: 2px solid var(--primary-color);
            padding-bottom: 10px;
            margin-bottom: 20px;
        }

        .btn-action {
            transition: all 0.3s;
        }

        .btn-action:hover {
            transform: scale(1.05);
        }

        .user-avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--primary-color);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }

        .message-bubble {
            max-width: 70%;
            padding: 10px 15px;
            border-radius: 18px;
            margin: 5px 0;
        }

        .message-in { 
            background: #f8f9fa; 
            margin-right: auto;
        }

        .message-out { 
            background: var(--primary-color); 
            color: white;
            margin-left: auto;
        }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <!-- 侧边栏导航 -->
            <nav class="col-md-3 col-lg-2 d-md-block sidebar collapse">
                <div class="position-sticky pt-3">
                    <div class="text-center mb-4 p-3">
                        <h4 class="text-white"><i class="fas fa-robot me-2"></i>ENLTbot</h4>
                        <small class="text-white-50">真实数据监控面板</small>
                    </div>
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link active" href="#" onclick="showSection('dashboard')">
                                <i class="fas fa-tachometer-alt"></i>仪表板
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" onclick="showSection('users')">
                                <i class="fas fa-users"></i>用户统计
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" onclick="showSection('messages')">
                                <i class="fas fa-comments"></i>消息分析
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" onclick="showSection('groups')">
                                <i class="fas fa-users"></i>群组统计
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" onclick="showSection('system')">
                                <i class="fas fa-chart-line"></i>系统监控
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" onclick="showSection('logs')">
                                <i class="fas fa-terminal"></i>实时日志
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <!-- 主内容区域 -->
            <main class="col-md-9 ms-sm-auto col-lg-10 px-md-4 main-content">
                <!-- 顶部导航栏 -->
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 id="section-title" class="h2 section-title">仪表板</h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <div class="btn-group me-2">
                            <button type="button" class="btn btn-sm btn-outline-primary btn-action" onclick="refreshAllData()">
                                <i class="fas fa-sync-alt me-1"></i>刷新
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 仪表板内容 -->
                <div id="dashboard" class="section-content">
                    <!-- 统计卡片区域 -->
                    <div class="row">
                        <div class="col-xl-3 col-md-6 mb-4">
                            <div class="card stat-card primary h-100">
                                <div class="card-body">
                                    <div class="row no-gutters align-items-center">
                                        <div class="col mr-2">
                                            <div class="text-xs font-weight-bold text-primary text-uppercase mb-1">
                                                总消息数</div>
                                            <div class="h5 mb-0 font-weight-bold text-gray-800" id="total-messages">0</div>
                                        </div>
                                        <div class="col-auto">
                                            <i class="fas fa-comments fa-2x text-gray-300"></i>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-xl-3 col-md-6 mb-4">
                            <div class="card stat-card success h-100">
                                <div class="card-body">
                                    <div class="row no-gutters align-items-center">
                                        <div class="col mr-2">
                                            <div class="text-xs font-weight-bold text-success text-uppercase mb-1">
                                                活跃用户</div>
                                            <div class="h5 mb-0 font-weight-bold text-gray-800" id="active-users">0</div>
                                        </div>
                                        <div class="col-auto">
                                            <i class="fas fa-user fa-2x text-gray-300"></i>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-xl-3 col-md-6 mb-4">
                            <div class="card stat-card info h-100">
                                <div class="card-body">
                                    <div class="row no-gutters align-items-center">
                                        <div class="col mr-2">
                                            <div class="text-xs font-weight-bold text-info text-uppercase mb-1">
                                                命令使用</div>
                                            <div class="h5 mb-0 font-weight-bold text-gray-800" id="total-commands">0</div>
                                        </div>
                                        <div class="col-auto">
                                            <i class="fas fa-terminal fa-2x text-gray-300"></i>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-xl-3 col-md-6 mb-4">
                            <div class="card stat-card warning h-100">
                                <div class="card-body">
                                    <div class="row no-gutters align-items-center">
                                        <div class="col mr-2">
                                            <div class="text-xs font-weight-bold text-warning text-uppercase mb-1">
                                                运行时间</div>
                                            <div class="h5 mb-0 font-weight-bold text-gray-800" id="uptime">0</div>
                                        </div>
                                        <div class="col-auto">
                                            <i class="fas fa-clock fa-2x text-gray-300"></i>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 图表和活动区域 -->
                    <div class="row">
                        <div class="col-lg-8 mb-4">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3 d-flex justify-content-between align-items-center">
                                    <h6 class="m-0 font-weight-bold text-primary">消息活动趋势 (24小时)</h6>
                                    <div class="btn-group">
                                        <button class="btn btn-sm btn-outline-primary active" onclick="updateChartRange('24h')">24小时</button>
                                        <button class="btn btn-sm btn-outline-primary" onclick="updateChartRange('7d')">7天</button>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="chart-container">
                                        <canvas id="activityChart"></canvas>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-lg-4 mb-4">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">命令使用排行</h6>
                                </div>
                                <div class="card-body">
                                    <div id="command-stats">
                                        <div class="text-center text-muted">加载中...</div>
                                    </div>
                                </div>
                            </div>

                            <!-- 系统状态卡片 -->
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">系统状态</h6>
                                </div>
                                <div class="card-body">
                                    <div class="mb-3">
                                        <small class="text-muted">CPU使用率</small>
                                        <div class="progress">
                                            <div id="cpu-usage" class="progress-bar bg-success" style="width: 0%">0%</div>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <small class="text-muted">内存使用率</small>
                                        <div class="progress">
                                            <div id="memory-usage" class="progress-bar bg-info" style="width: 0%">0%</div>
                                        </div>
                                    </div>
                                    <div class="mb-0">
                                        <small class="text-muted">磁盘使用率</small>
                                        <div class="progress">
                                            <div id="disk-usage" class="progress-bar bg-warning" style="width: 0%">0%</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 最近活动区域 -->
                    <div class="row">
                        <div class="col-12">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3 d-flex justify-content-between align-items-center">
                                    <h6 class="m-0 font-weight-bold text-primary">最近活动</h6>
                                    <small class="text-muted">最后更新: <span id="last-update">--</span></small>
                                </div>
                                <div class="card-body">
                                    <div id="recent-activity" style="max-height: 200px; overflow-y: auto;">
                                        <div class="text-center text-muted">加载中...</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 用户统计页面 -->
                <div id="users" class="section-content" style="display: none;">
                    <div class="card shadow mb-4">
                        <div class="card-header py-3 d-flex justify-content-between align-items-center">
                            <h6 class="m-0 font-weight-bold text-primary">用户活跃度排行</h6>
                            <div class="input-group" style="width: 300px;">
                                <input type="text" class="form-control" placeholder="搜索用户..." id="userSearch">
                                <button class="btn btn-outline-primary" type="button" onclick="searchUsers()">
                                    <i class="fas fa-search"></i>
                                </button>
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="table-responsive">
                                <table class="table table-bordered table-hover" id="usersTable">
                                    <thead class="table-light">
                                        <tr>
                                            <th>排名</th>
                                            <th>用户ID</th>
                                            <th>消息总数</th>
                                            <th>私聊消息</th>
                                            <th>群聊消息</th>
                                            <th>等级</th>
                                            <th>最后活动</th>
                                            <th>操作</th>
                                        </tr>
                                    </thead>
                                    <tbody id="users-table-body">
                                        <tr><td colspan="8" class="text-center">加载中...</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 消息分析页面 -->
                <div id="messages" class="section-content" style="display: none;">
                    <div class="row">
                        <div class="col-lg-8">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">消息类型分布</h6>
                                </div>
                                <div class="card-body">
                                    <div class="chart-container">
                                        <canvas id="messageTypeChart"></canvas>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-lg-4">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">消息统计</h6>
                                </div>
                                <div class="card-body" id="message-stats">
                                    <div class="text-center text-muted">加载中...</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="row">
                        <div class="col-12">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">每日消息统计</h6>
                                </div>
                                <div class="card-body">
                                    <div class="chart-container">
                                        <canvas id="dailyChart"></canvas>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 群组统计页面 -->
                <div id="groups" class="section-content" style="display: none;">
                    <div class="card shadow mb-4">
                        <div class="card-header py-3">
                            <h6 class="m-0 font-weight-bold text-primary">活跃群组排行</h6>
                        </div>
                        <div class="card-body">
                            <div class="table-responsive">
                                <table class="table table-bordered table-hover">
                                    <thead class="table-light">
                                        <tr>
                                            <th>群组ID</th>
                                            <th>消息数量</th>
                                            <th>活跃度</th>
                                            <th>最后活动</th>
                                        </tr>
                                    </thead>
                                    <tbody id="groups-table-body">
                                        <tr><td colspan="4" class="text-center">加载中...</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 系统监控页面 -->
                <div id="system" class="section-content" style="display: none;">
                    <div class="row">
                        <div class="col-lg-6">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">系统资源监控</h6>
                                </div>
                                <div class="card-body">
                                    <div id="system-resources">
                                        <div class="text-center text-muted">加载中...</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-lg-6">
                            <div class="card shadow mb-4">
                                <div class="card-header py-3">
                                    <h6 class="m-0 font-weight-bold text-primary">机器人状态</h6>
                                </div>
                                <div class="card-body">
                                    <div id="bot-status">
                                        <div class="text-center text-muted">加载中...</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 实时日志页面 -->
                <div id="logs" class="section-content" style="display: none;">
                    <div class="card shadow mb-4">
                        <div class="card-header py-3 d-flex justify-content-between align-items-center">
                            <h6 class="m-0 font-weight-bold text-primary">实时系统日志</h6>
                            <div>
                                <div class="btn-group me-2">
                                    <button class="btn btn-sm btn-outline-primary" onclick="refreshLogs()">
                                        <i class="fas fa-sync-alt"></i> 刷新
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="clearAllLogs()">
                                        <i class="fas fa-trash"></i> 清空
                                    </button>
                                </div>
                                <div class="btn-group">
                                    <button class="btn btn-sm btn-outline-secondary active" onclick="filterLogs('all')">全部</button>
                                    <button class="btn btn-sm btn-outline-info" onclick="filterLogs('info')">信息</button>
                                    <button class="btn btn-sm btn-outline-warning" onclick="filterLogs('warning')">警告</button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="filterLogs('error')">错误</button>
                                </div>
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="mb-3">
                                <input type="text" class="form-control" id="logSearch" placeholder="搜索日志内容...">
                            </div>
                            <div id="log-content" style="max-height: 500px; overflow-y: auto; font-family: monospace;">
                                <div class="text-center text-muted">加载中...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        // 全局变量定义
        let currentSection = 'dashboard';
        let activityChart, messageTypeChart, dailyChart;
        let currentChartRange = '24h';
        let currentLogFilter = 'all';

        // 显示指定区域的内容
        function showSection(section) {
            // 隐藏所有区域
            document.querySelectorAll('.section-content').forEach(div => {
                div.style.display = 'none';
            });
            // 显示目标区域
            document.getElementById(section).style.display = 'block';
            currentSection = section;

            // 更新标题
            const titles = {
                'dashboard': '仪表板',
                'users': '用户统计',
                'messages': '消息分析',
                'groups': '群组统计',
                'system': '系统监控',
                'logs': '实时日志'
            };
            document.getElementById('section-title').textContent = titles[section];

            // 刷新区域数据
            refreshSectionData(section);
        }

        // 格式化运行时间显示
        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);

            if (days > 0) {
                return `${days}天 ${hours}小时 ${minutes}分钟`;
            } else if (hours > 0) {
                return `${hours}小时 ${minutes}分钟`;
            } else {
                return `${minutes}分钟`;
            }
        }

        // 格式化时间显示
        function formatTime(timestamp) {
            if (!timestamp) return '从未';
            const date = new Date(timestamp * 1000);
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return '刚刚';
            if (diffMins < 60) return `${diffMins}分钟前`;
            if (diffHours < 24) return `${diffHours}小时前`;
            if (diffDays < 7) return `${diffDays}天前`;
            return date.toLocaleDateString();
        }

        // 刷新所有数据
        function refreshAllData() {
            refreshSectionData(currentSection);
            loadSystemStatus();
            updateSystemResources();
        }

        // 刷新指定区域的数据
        function refreshSectionData(section) {
            switch(section) {
                case 'dashboard':
                    loadDashboard();
                    break;
                case 'users':
                    loadUserStats();
                    break;
                case 'messages':
                    loadMessageStats();
                    break;
                case 'groups':
                    loadGroupStats();
                    break;
                case 'system':
                    loadSystemStatus();
                    break;
                case 'logs':
                    loadLogs();
                    break;
            }
        }

        // 加载仪表板数据
        function loadDashboard() {
            // 加载系统统计
            fetch('/api/system-stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('total-messages').textContent = data.total_messages.toLocaleString();
                    document.getElementById('active-users').textContent = data.unique_users.toLocaleString();
                    document.getElementById('total-commands').textContent = data.total_commands.toLocaleString();
                    document.getElementById('uptime').textContent = formatUptime(data.uptime);
                    document.getElementById('last-update').textContent = new Date().toLocaleString();
                });

            // 加载消息统计图表
            fetch('/api/message-stats?range=' + currentChartRange)
                .then(response => response.json())
                .then(data => {
                    updateActivityChart(data);
                });

            // 加载命令统计
            fetch('/api/command-stats')
                .then(response => response.json())
                .then(commands => {
                    const container = document.getElementById('command-stats');
                    if (commands.length === 0) {
                        container.innerHTML = '<div class="text-center text-muted">暂无命令数据</div>';
                        return;
                    }

                    const html = commands.map(cmd => 
                        `<div class="d-flex justify-content-between align-items-center mb-2 p-2 border rounded">
                            <div>
                                <span class="fw-bold">/${cmd.command}</span>
                            </div>
                            <div class="text-end">
                                <div class="fw-bold">${cmd.count}</div>
                                <small class="text-muted">${cmd.percentage}%</small>
                            </div>
                        </div>`
                    ).join('');
                    container.innerHTML = html;
                });

            // 加载最近活动
            fetch('/api/recent-activity')
                .then(response => response.json())
                .then(activities => {
                    const container = document.getElementById('recent-activity');
                    if (activities.length === 0) {
                        container.innerHTML = '<div class="text-center text-muted">暂无活动</div>';
                        return;
                    }

                    const html = activities.map(activity => {
                        const time = new Date(activity.timestamp * 1000).toLocaleTimeString();
                        const typeBadge = activity.is_group ? 
                            '<span class="badge bg-info">群组</span>' : 
                            '<span class="badge bg-secondary">私聊</span>';

                        return `<div class="d-flex justify-content-between align-items-center mb-2 p-2 border rounded">
                            <div class="flex-grow-1">
                                <div class="d-flex justify-content-between">
                                    <span class="fw-bold">用户 ${activity.user_id}</span>
                                    <small class="text-muted">${time}</small>
                                </div>
                                <div class="text-truncate" style="max-width: 300px;">${activity.content}</div>
                                ${typeBadge}
                            </div>
                        </div>`;
                    }).join('');
                    container.innerHTML = html;
                });
        }

        // 更新活动图表
        function updateActivityChart(data) {
            const ctx = document.getElementById('activityChart').getContext('2d');
            const labels = Object.keys(data);
            const values = Object.values(data);

            // 销毁旧图表
            if (activityChart) activityChart.destroy();

            // 创建新图表
            activityChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '消息数量',
                        data: values,
                        borderColor: '#4e73df',
                        backgroundColor: 'rgba(78, 115, 223, 0.1)',
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#4e73df',
                        pointBorderColor: '#fff',
                        pointHoverBackgroundColor: '#fff',
                        pointHoverBorderColor: '#4e73df'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                display: false
                            }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                precision: 0
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    }
                }
            });
        }

        // 更新图表时间范围
        function updateChartRange(range) {
            currentChartRange = range;
            // 更新按钮状态
            document.querySelectorAll('#dashboard .btn-group .btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            // 重新加载数据
            loadDashboard();
        }

        // 加载用户统计数据
        function loadUserStats() {
            fetch('/api/user-stats')
                .then(response => response.json())
                .then(users => {
                    const tbody = document.getElementById('users-table-body');
                    if (users.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8" class="text-center">暂无用户数据</td></tr>';
                        return;
                    }

                    const html = users.map((user, index) => {
                        const rank = index + 1;
                        let rankBadge = '';
                        if (rank === 1) {
                            rankBadge = '<span class="badge badge-rank-1">🥇</span>';
                        } else if (rank === 2) {
                            rankBadge = '<span class="badge badge-rank-2">🥈</span>';
                        } else if (rank === 3) {
                            rankBadge = '<span class="badge badge-rank-3">🥉</span>';
                        } else {
                            rankBadge = `<span class="badge bg-secondary">${rank}</span>`;
                        }

                        return `<tr>
                            <td>${rankBadge}</td>
                            <td>${user.user_id}</td>
                            <td>${user.message_count}</td>
                            <td>${user.private_messages}</td>
                            <td>${user.group_messages}</td>
                            <td><span class="badge bg-primary">Lv.${user.level}</span></td>
                            <td>${formatTime(user.last_seen)}</td>
                            <td>
                                <button class="btn btn-sm btn-outline-primary" onclick="viewUserDetails(${user.user_id})">
                                    <i class="fas fa-eye"></i>
                                </button>
                            </td>
                        </tr>`;
                    }).join('');
                    tbody.innerHTML = html;
                });
        }

        // 搜索用户
        function searchUsers() {
            const searchTerm = document.getElementById('userSearch').value.toLowerCase();
            const rows = document.querySelectorAll('#users-table-body tr');

            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                if (text.includes(searchTerm)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }

        // 查看用户详情
        function viewUserDetails(userId) {
            alert(`查看用户 ${userId} 的详细信息\n\n功能开发中...`);
        }

        // 加载消息统计数据
        function loadMessageStats() {
            // 加载消息类型分布图表
            fetch('/api/message-type-stats')
                .then(response => response.json())
                .then(data => {
                    const ctx = document.getElementById('messageTypeChart').getContext('2d');
                    if (messageTypeChart) messageTypeChart.destroy();

                    messageTypeChart = new Chart(ctx, {
                        type: 'doughnut',
                        data: {
                            labels: Object.keys(data),
                            datasets: [{
                                data: Object.values(data),
                                backgroundColor: [
                                    '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', 
                                    '#e74a3b', '#858796', '#5a5c69', '#6f42c1'
                                ],
                                borderWidth: 2,
                                borderColor: '#fff'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    position: 'right'
                                }
                            }
                        }
                    });
                });

            // 加载消息统计详情
            fetch('/api/message-stats-detail')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('message-stats');
                    const html = `
                        <div class="mb-3">
                            <div class="d-flex justify-content-between">
                                <span>私聊消息:</span>
                                <span class="fw-bold">${data.private_messages.toLocaleString()}</span>
                            </div>
                        </div>
                        <div class="mb-3">
                            <div class="d-flex justify-content-between">
                                <span>群聊消息:</span>
                                <span class="fw-bold">${data.group_messages.toLocaleString()}</span>
                            </div>
                        </div>
                        <div class="mb-3">
                            <div class="d-flex justify-content-between">
                                <span>今日消息:</span>
                                <span class="fw-bold">${data.today_messages.toLocaleString()}</span>
                            </div>
                        </div>
                        <div class="mb-0">
                            <div class="d-flex justify-content-between">
                                <span>昨日消息:</span>
                                <span class="fw-bold">${data.yesterday_messages.toLocaleString()}</span>
                            </div>
                        </div>
                    `;
                    container.innerHTML = html;
                });

            // 加载每日统计图表
            fetch('/api/daily-stats')
                .then(response => response.json())
                .then(data => {
                    const ctx = document.getElementById('dailyChart').getContext('2d');
                    if (dailyChart) dailyChart.destroy();

                    dailyChart = new Chart(ctx, {
                        type: 'bar',
                        data: {
                            labels: data.dates,
                            datasets: [{
                                label: '每日消息',
                                data: data.counts,
                                backgroundColor: '#36b9cc',
                                borderColor: '#2c9faf',
                                borderWidth: 1
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        precision: 0
                                    }
                                }
                            }
                        }
                    });
                });
        }

        // 加载群组统计数据
        function loadGroupStats() {
            fetch('/api/group-stats')
                .then(response => response.json())
                .then(groups => {
                    const tbody = document.getElementById('groups-table-body');
                    if (groups.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="4" class="text-center">暂无群组数据</td></tr>';
                        return;
                    }

                    const html = groups.map((group, index) => {
                        const rank = index + 1;
                        let rankBadge = '';
                        if (rank === 1) {
                            rankBadge = '<span class="badge badge-rank-1">🥇</span>';
                        } else if (rank === 2) {
                            rankBadge = '<span class="badge badge-rank-2">🥈</span>';
                        } else if (rank === 3) {
                            rankBadge = '<span class="badge badge-rank-3">🥉</span>';
                        } else {
                            rankBadge = `<span class="badge bg-secondary">${rank}</span>`;
                        }

                        return `<tr>
                            <td>${rankBadge} 群组 ${group.group_id}</td>
                            <td>${group.message_count}</td>
                            <td>
                                <div class="progress">
                                    <div class="progress-bar" style="width: ${Math.min(100, group.message_count / 10)}%"></div>
                                </div>
                            </td>
                            <td>${formatTime(group.last_seen)}</td>
                        </tr>`;
                    }).join('');
                    tbody.innerHTML = html;
                });
        }

        // 加载系统状态
        function loadSystemStatus() {
            fetch('/api/bot-status')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('bot-status');
                    const statusClass = data.ws_connected ? 'text-success' : 'text-danger';
                    const statusText = data.ws_connected ? '已连接' : '未连接';

                    const html = `
                        <div class="mb-3">
                            <strong>WebSocket状态:</strong> 
                            <span class="${statusClass}">${statusText}</span>
                        </div>
                        <div class="mb-3">
                            <strong>登录用户:</strong> ${data.user_id || '未登录'}
                        </div>
                        <div class="mb-3">
                            <strong>今日消息:</strong> ${data.message_count_today}
                        </div>
                        <div class="mb-3">
                            <strong>总用户数:</strong> ${data.total_users}
                        </div>
                        <div class="mb-0">
                            <strong>最后活动:</strong> ${data.last_activity}
                        </div>
                    `;
                    container.innerHTML = html;
                });
        }

        // 更新系统资源显示
        function updateSystemResources() {
            fetch('/api/system-resources')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('cpu-usage').style.width = data.cpu_percent + '%';
                    document.getElementById('cpu-usage').textContent = data.cpu_percent.toFixed(1) + '%';

                    document.getElementById('memory-usage').style.width = data.memory_percent + '%';
                    document.getElementById('memory-usage').textContent = data.memory_percent.toFixed(1) + '%';

                    document.getElementById('disk-usage').style.width = data.disk_usage_percent + '%';
                    document.getElementById('disk-usage').textContent = data.disk_usage_percent.toFixed(1) + '%';
                });
        }

        // 加载日志数据
        function loadLogs() {
            fetch('/api/logs')
                .then(response => response.json())
                .then(logs => {
                    displayLogs(logs);
                });
        }

        // 显示日志内容
        function displayLogs(logs) {
            const container = document.getElementById('log-content');

            if (logs.length === 0) {
                container.innerHTML = '<div class="text-center text-muted">暂无日志</div>';
                return;
            }

            // 根据过滤器筛选日志
            let filteredLogs = logs;
            if (currentLogFilter !== 'all') {
                filteredLogs = logs.filter(log => log.level === currentLogFilter);
            }

            // 根据搜索词筛选
            const searchTerm = document.getElementById('logSearch').value.toLowerCase();

            const html = filteredLogs.map(log => {
                if (searchTerm && !log.message.toLowerCase().includes(searchTerm)) {
                    return '';
                }

                return `<div class="log-entry log-${log.level}">${log.message}</div>`;
            }).filter(html => html !== '').join('');

            container.innerHTML = html || '<div class="text-center text-muted">无匹配的日志</div>';
        }

        // 过滤日志显示
        function filterLogs(level) {
            currentLogFilter = level;
            // 更新按钮状态
            document.querySelectorAll('#logs .btn-group .btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            // 重新加载日志
            loadLogs();
        }

        // 刷新日志
        function refreshLogs() {
            loadLogs();
        }

        // 清空所有日志
        function clearAllLogs() {
            if (confirm('确定要清空所有日志吗？此操作不可恢复！')) {
                fetch('/api/clear-all-logs', { method: 'POST' })
                    .then(() => {
                        loadLogs();
                        showToast('所有日志已清空', 'success');
                    });
            }
        }

        // 显示提示信息
        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
            toast.style.top = '20px';
            toast.style.right = '20px';
            toast.style.zIndex = '9999';
            toast.style.minWidth = '300px';
            toast.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(toast);

            // 3秒后自动移除
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 3000);
        }

        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 默认显示仪表板
            showSection('dashboard');

            // 设置自动刷新
            setInterval(() => {
                refreshSectionData(currentSection);
                if (currentSection === 'dashboard') {
                    updateSystemResources();
                }
            }, 5000);

            // 日志搜索功能
            document.getElementById('logSearch').addEventListener('input', function(e) {
                loadLogs();
            });

            // 用户搜索功能
            document.getElementById('userSearch').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchUsers();
                }
            });

            // 初始加载系统资源
            updateSystemResources();
        });
    </script>
</body>
</html>
'''

# ============================ Flask路由定义 ============================

@app.route('/')
def home():
    """主页路由"""
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/admin')
def admin_dashboard():
    """管理员面板路由"""
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/api/system-stats')
def api_system_stats():
    """系统统计API"""
    stats = real_stats.get_system_stats()
    return jsonify(stats)

@app.route('/api/message-stats')
def api_message_stats():
    """消息统计API"""
    range_type = request.args.get('range', '24h')
    if range_type == '7d':
        # 7天统计
        hourly_stats = real_stats.get_message_stats(24 * 7)
    else:
        # 24小时统计
        hourly_stats = real_stats.get_message_stats(24)

    return jsonify(hourly_stats)

@app.route('/api/command-stats')
def api_command_stats():
    """命令统计API"""
    commands = real_stats.get_command_stats(10)
    return jsonify(commands)

@app.route('/api/user-stats')
def api_user_stats():
    """用户统计API"""
    users = real_stats.get_user_stats(20)
    return jsonify(users)

@app.route('/api/message-type-stats')
def api_message_type_stats():
    """消息类型统计API"""
    return jsonify(real_stats.get_message_type_stats())

@app.route('/api/message-stats-detail')
def api_message_stats_detail():
    """消息统计详情API"""
    stats = real_stats.get_system_stats()

    # 获取今日和昨日消息数
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    return jsonify({
        'private_messages': stats['private_messages'],
        'group_messages': stats['group_messages'],
        'today_messages': real_stats.daily_messages.get(today, 0),
        'yesterday_messages': real_stats.daily_messages.get(yesterday, 0)
    })

@app.route('/api/daily-stats')
def api_daily_stats():
    """每日统计API"""
    daily_stats = real_stats.get_daily_stats(7)
    return jsonify(daily_stats)

@app.route('/api/group-stats')
def api_group_stats():
    """群组统计API"""
    groups = real_stats.get_active_groups(10)
    return jsonify(groups)

@app.route('/api/system-resources')
def api_system_resources():
    """系统资源API"""
    try:
        process = psutil.Process()
        memory = process.memory_info()
        memory_total = psutil.virtual_memory().total

        return jsonify({
            'cpu_percent': psutil.cpu_percent(),
            'memory_usage_mb': memory.rss / 1024 / 1024,
            'memory_percent': (memory.rss / memory_total) * 100,
            'disk_usage_percent': psutil.disk_usage('/').percent
        })
    except Exception as e:
        logger.error(f"获取系统资源失败: {e}")
        return jsonify({
            'cpu_percent': 0,
            'memory_usage_mb': 0,
            'memory_percent': 0,
            'disk_usage_percent': 0
        })

@app.route('/api/bot-status')
def api_bot_status():
    """机器人状态API"""
    try:
        if bot_instance:
            # 安全的WebSocket连接状态检查
            ws_connected = False
            if hasattr(bot_instance, 'ws_connection') and bot_instance.ws_connection:
                if hasattr(bot_instance.ws_connection, 'closed'):
                    ws_connected = not bot_instance.ws_connection.closed
                elif hasattr(bot_instance.ws_connection, 'open'):
                    ws_connected = bot_instance.ws_connection.open
            
            # 获取最近活动时间
            last_activity = "从未"
            if real_stats.message_history:
                last_msg = real_stats.message_history[-1]
                last_activity = format_time(last_msg['timestamp'])
            
            return jsonify({
                'ws_connected': ws_connected,
                'user_id': bot_instance.user_id,
                'message_count_today': bot_instance.message_count_today,
                'total_users': len(real_stats.user_activity),
                'last_activity': last_activity
            })
        return jsonify({
            'ws_connected': False,
            'user_id': None,
            'message_count_today': 0,
            'total_users': 0,
            'last_activity': '从未'
        })
    except Exception as e:
        logger.error(f"机器人状态检查错误: {e}")
        return jsonify({
            'ws_connected': False,
            'user_id': None,
            'message_count_today': 0,
            'total_users': 0,
            'last_activity': '错误'
        }), 500

@app.route('/api/recent-activity')
def api_recent_activity():
    """最近活动API"""
    activities = real_stats.get_recent_activity(1)  # 最近1小时
    # 只返回最近10条
    return jsonify(activities[-10:])

@app.route('/api/logs')
def api_logs():
    """系统日志API"""
    logs_data = []
    for log in log_buffer:
        level = "info"
        if "WARNING" in log:
            level = "warning"
        elif "ERROR" in log:
            level = "error"
        elif "DEBUG" in log:
            level = "debug"

        logs_data.append({"message": log, "level": level})

    return jsonify(logs_data)

@app.route('/api/clear-all-logs', methods=['POST'])
def api_clear_all_logs():
    """清空所有日志API"""
    log_buffer.clear()
    try:
        open('bot.log', 'w').close()
    except:
        pass
    return jsonify({"message": "所有日志已清空"})

# ============================ 辅助函数 ============================

def format_time(timestamp):
    """格式化时间显示"""
    if not timestamp:
        return '从未'
    
    now = time.time()
    diff = now - timestamp
    
    if diff < 60:
        return '刚刚'
    elif diff < 3600:
        return f'{int(diff // 60)}分钟前'
    elif diff < 86400:
        return f'{int(diff // 3600)}小时前'
    elif diff < 604800:
        return f'{int(diff // 86400)}天前'
    else:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')

# ============================ BoxIM机器人核心类定义 ============================

class MessageType(IntEnum):
    """消息类型枚举"""
    TEXT = 0
    IMAGE = 1
    FILE = 2
    VOICE = 3
    VIDEO = 4
    USER_CARD = 5
    GROUP_CARD = 6
    LOCATION = 7
    QUOTE = 8
    MESSAGE_RECEIPT = 12
    SYSTEM = 21
    RECALL = 22
    NOTICE = 23
    GROUP_INFO = 82

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

class Config:
    """配置类"""
    BASE_URL = "https://www.boxim.online"
    WS_URL = "wss://www.boxim.online/im"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    RECONNECT_DELAY = 2
    MAX_RECONNECT_DELAY = 300
    HEARTBEAT_INTERVAL = 15
    TOKEN_REFRESH_THRESHOLD = 300
    REQUEST_TIMEOUT = 30

class Message:
    """消息类"""
    
    def __init__(self, data: Dict, is_group: bool = False):
        """
        初始化消息
        
        Args:
            data: 消息数据字典
            is_group: 是否为群组消息
        """
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

    def _safe_int(self, value):
        """安全转换为整数"""
        try:
            return int(value) if value is not None else None
        except:
            return None

class BoxIM:
    """BoxIM机器人主类"""
    
    def __init__(self):
        """初始化机器人"""
        # 认证信息
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.access_token_expires: float = 0
        self.refresh_token_expires: float = 0
        self.user_id: Optional[int] = None
        self.terminal = Terminal.PC

        # 数据存储
        self.data_file = "level_bot_data.json"
        self.all_data = self._load_data()
        self.user_data = self.all_data.get('users', {})

        # 用户名缓存
        self.username_cache = {}
        self.username_cache_time = {}

        # WebSocket连接
        self.ws_connection = None
        self.ws_task: Optional[asyncio.Future] = None
        self.ws_reconnect_count: int = 0
        self.ws_running: bool = False

        # 消息和命令处理器
        self.message_handlers = defaultdict(list)
        self.command_handlers = {}

        # 功能模块
        self.user = UserModule(self)
        self.message = MessageModule(self)
        self.chat = ChatHelper(self)
        self.level_system = LevelSystem(self)

        # 任务管理
        self._tasks: List[asyncio.Future] = []

        # 统计信息
        self.start_time = time.time()
        self.message_count_today = 0
        self.last_reset_time = self._get_today_start()
        self._last_save_time = time.time()
        self.heartbeat_task = None

        # 注册命令处理器
        self.command_handlers.update({
            'help': lambda msg, args: self.cmd_help(msg, args),
            'lv': lambda msg, args: self.cmd_level(msg, args),
            'rank': lambda msg, args: self.cmd_rank(msg, args),
            'label': lambda msg, args: self.cmd_label(msg, args),
            'sign': lambda msg, args: self.cmd_sign(msg, args),
            'points': lambda msg, args: self.cmd_points(msg, args),
            'exchange': lambda msg, args: self.cmd_exchange(msg, args),
            'lottery': lambda msg, args: self.cmd_lottery(msg, args),
            'top': lambda msg, args: self.cmd_top(msg, args),
        })

        # 注册消息处理器
        self.message_handlers['private'].append(
            lambda msg: self._handle_private_message(msg))
        self.message_handlers['group'].append(
            lambda msg: self._handle_group_message(msg))

        logger.info("BoxIM机器人初始化完成 - Railway修复版本")

    @property
    def ws_connected(self):
        """WebSocket 连接状态 - 修复版本"""
        if self.ws_connection is None:
            return False
        
        # 兼容不同版本的websockets库
        if hasattr(self.ws_connection, 'closed'):
            return not self.ws_connection.closed
        elif hasattr(self.ws_connection, 'open'):
            return self.ws_connection.open
        else:
            # 如果无法确定状态，假设连接正常
            return True

    def _get_today_start(self):
        """获取今天开始的时间戳"""
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        return today_start.timestamp()

    def _reset_daily_stats(self):
        """重置每日统计"""
        now = time.time()
        if now - self.last_reset_time >= 86400:
            self.message_count_today = 0
            self.last_reset_time = self._get_today_start()

    async def _handle_private_message(self, message: Message):
        """处理私聊消息"""
        if message.type != MessageType.TEXT:
            return

        # 更新统计
        self.message_count_today += 1

        # 记录真实消息数据
        real_stats.record_message(
            user_id=message.send_id,
            message_type="text",
            content=message.content,
            is_group=False
        )

        # 处理经验系统和命令
        await self.level_system.add_experience(message.send_id, message)
        await self._process_command(message)

    async def _handle_group_message(self, message: Message):
        """处理群聊消息"""
        if message.type != MessageType.TEXT:
            return

        # 更新统计
        self.message_count_today += 1

        # 记录真实消息数据
        real_stats.record_message(
            user_id=message.send_id,
            message_type="text", 
            content=message.content,
            is_group=True,
            group_id=message.group_id
        )

        # 处理经验系统和命令
        await self.level_system.add_experience(message.send_id, message)
        await self._process_command(message)

    async def _process_command(self, message: Message):
        """处理命令"""
        text = message.content.strip()
        if not text.startswith('/'):
            return

        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].lower()
        args = parts[1] if len(parts) > 1 else ''

        if cmd in self.command_handlers:
            # 记录命令使用
            real_stats.record_command(cmd, message.send_id)
            await self.command_handlers[cmd](message, args)

    # ============================ 命令处理方法 ============================

    async def cmd_help(self, message: Message, args: str):
        """显示帮助信息"""
        help_text = """
🤖 ENLTbot - 使用帮助

📋 可用命令:
/help - 显示此帮助信息
/lv - 查看自己的等级信息
/rank - 查看自己的排名信息  
/label - 查看标签体系说明
/top [页数] - 查看排行榜 (默认第1页)

🎮 积分系统:
/sign - 每日签到获得积分
/points - 查看积分信息
/exchange [数量] - 积分兑换经验 (1积分=10经验)
/lottery - 抽奖 (2积分/次)

⚠️ 注意事项:
• 第一次刷屏: 禁言1分钟警告
• 多次刷屏: 清空所有等级数据"""
        await send_reply(message, self, help_text.strip())

    async def cmd_level(self, message: Message, args: str):
        """显示等级信息"""
        user_id = message.send_id
        level_info = await self.level_system.get_level_info(user_id)
        username = await self.get_username(user_id)
        clean_username = self.level_system._clean_username(username)

        reply = f"""🎮 {clean_username} 的等级信息

🏅 当前等级: Lv.{level_info['level']}
⭐ 累计经验: {level_info['exp']}
📊 当前等级进度: {level_info['current_level_earned_exp']}/{level_info['current_level_total_needed_exp']}
📈 还需经验: {level_info['exp_needed_for_next_level']}
🎯 升级进度: {level_info['progress']:.1f}%
💬 总消息数: {level_info['total_messages']}
🏷️ 当前标签: {level_info['label']}"""
        await send_reply(message, self, reply)

    async def cmd_rank(self, message: Message, args: str):
        """显示排名信息"""
        user_id = message.send_id
        rank = await self.level_system.get_user_rank(user_id)
        level_info = await self.level_system.get_level_info(user_id)
        username = await self.get_username(user_id)
        clean_username = self.level_system._clean_username(username)

        total_users = len(
            [uid for uid, data in self.user_data.items() if 'exp' in data])

        reply = f"""🏆 {clean_username} 的排名信息

📊 当前排名: 第{rank}名
👥 总用户数: {total_users}人
🏅 等级: Lv.{level_info['level']}
⭐ 经验值: {level_info['exp']}
🏷️ 标签: {level_info['label']}"""
        await send_reply(message, self, reply)

    async def cmd_label(self, message: Message, args: str):
        """显示标签信息"""
        user_id = message.send_id
        level_info = await self.level_system.get_level_info(user_id)
        username = await self.get_username(user_id)
        clean_username = self.level_system._clean_username(username)

        reply = f"""🏷️ {clean_username} 的标签信息

当前标签: {level_info['label']}
当前等级: Lv.{level_info['level']}
经验值: {level_info['exp']}

📋 标签体系:
普通用户 - Lv.1 到 Lv.10
活跃用户 - Lv.11 到 Lv.20  
资深用户 - Lv.21 到 Lv.30
传奇 - Lv.31 到 Lv.35
神话 - Lv.36 到 Lv.45
巅峰 - Lv.46 到 Lv.99
无敌 - Lv.100+"""
        await send_reply(message, self, reply)

    async def cmd_sign(self, message: Message, args: str):
        """每日签到"""
        user_id = message.send_id
        success = await self.level_system.daily_sign(user_id, message)
        if not success:
            username = await self.get_username(user_id)
            clean_username = self.level_system._clean_username(username)
            await send_reply(message, self,
                             f"❌ {clean_username} 今天已经签到过了，明天再来吧！")

    async def cmd_points(self, message: Message, args: str):
        """显示积分信息"""
        user_id = message.send_id
        points_info = await self.level_system.get_points_info(user_id)
        username = await self.get_username(user_id)
        clean_username = self.level_system._clean_username(username)

        reply = f"""💰 {clean_username} 的积分信息

🎯 当前积分: {points_info['points']} 点
📅 最后签到: {points_info['last_sign_date'] or '从未签到'}
🔥 连续签到: {points_info['consecutive_days']} 天
📊 总签到天数: {points_info['total_sign_days']} 天

🎰 抽奖统计:
  ├─ 抽奖次数: {points_info['lottery_count']} 次
  ├─ 中奖次数: {points_info['lottery_wins']} 次
  └─ 中奖率: {points_info['win_rate']}%

💡 使用说明:
  ├─ /sign - 每日签到
  ├─ /exchange [数量] - 积分兑换经验
  └─ /lottery - 抽奖 (2积分/次)"""
        await send_reply(message, self, reply)

    async def cmd_exchange(self, message: Message, args: str):
        """积分兑换经验"""
        user_id = message.send_id
        try:
            if not args.strip():
                await send_reply(message, self,
                                 "❌ 请指定要兑换的积分数量，例如: /exchange 10")
                return
            amount = int(args.strip())
            await self.level_system.exchange_points(user_id, amount, message)
        except ValueError:
            await send_reply(message, self, "❌ 请输入有效的数字，例如: /exchange 10")

    async def cmd_lottery(self, message: Message, args: str):
        """抽奖功能"""
        user_id = message.send_id
        await self.level_system.lottery_draw(user_id, message)

    async def cmd_top(self, message: Message, args: str):
        """显示排行榜"""
        try:
            page = int(args.strip()) if args.strip() else 1
        except ValueError:
            page = 1

        if page < 1:
            page = 1

        leaderboard_data = await self.level_system.get_leaderboard(
            page=page, page_size=10)

        if not leaderboard_data['users']:
            await send_reply(message, self, "📊 排行榜暂无数据")
            return

        reply = f"🏆 经验排行榜 (第{leaderboard_data['page']}页/共{leaderboard_data['total_pages']}页)\n\n"

        for user in leaderboard_data['users']:
            rank_emoji = self._get_rank_emoji(user['rank'])
            reply += f"{rank_emoji} {user['rank']}. {user['username']} - Lv.{user['level']} - {user['exp']}exp\n"

        reply += f"\n📊 总用户数: {leaderboard_data['total_users']}人"
        reply += f"\n💡 使用 /top [页数] 查看其他页"

        await send_reply(message, self, reply)

    def _get_rank_emoji(self, rank: int) -> str:
        """获取排名表情"""
        if rank == 1:
            return "🥇"
        elif rank == 2:
            return "🥈"
        elif rank == 3:
            return "🥉"
        elif rank <= 10:
            return "⭐"
        else:
            return "🔸"

    def _load_data(self) -> Dict:
        """加载数据文件"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return {'users': {}}

    def _save_data(self):
        """保存数据文件"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump({'users': self.user_data},
                          f,
                          ensure_ascii=False,
                          indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    async def get_username(self, user_id: int) -> str:
        """获取用户名"""
        current_time = time.time()
        # 检查缓存
        if user_id in self.username_cache and current_time - self.username_cache_time.get(
                user_id, 0) < 3600:
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

    @property
    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return self.access_token is not None and time.time(
        ) < self.access_token_expires

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Host": "www.boxim.online",
            "Origin": Config.BASE_URL,
            "Referer": f"{Config.BASE_URL}/",
            "User-Agent": Config.USER_AGENT,
            "accessToken": self.access_token or "",
        }

    async def login(self,
                    username: str,
                    password: str,
                    terminal: Terminal = Terminal.PC) -> bool:
        """登录BoxIM"""
        self.terminal = terminal
        api = APIClient(self)
        try:
            result = await api.request('POST',
                                       '/api/login',
                                       json={
                                           "terminal": terminal.value,
                                           "userName": username,
                                           "password": password
                                       })
            data = result['data']
            self.access_token = data['accessToken']
            self.refresh_token = data['refreshToken']
            self.access_token_expires = time.time(
            ) + data['accessTokenExpiresIn']
            self.refresh_token_expires = time.time(
            ) + data['refreshTokenExpiresIn']

            # 从token中解析用户ID
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
                    user_info = await self.user.get_self_info()
                    if user_info and user_info.get('id'):
                        self.user_id = user_info['id']
                    else:
                        logger.error("无法获取用户ID")
                        return False
            except Exception as e:
                logger.error(f"解析token失败: {e}")
                user_info = await self.user.get_self_info()
                if user_info and user_info.get('id'):
                    self.user_id = user_info['id']
                else:
                    logger.error("通过API获取用户信息也失败")
                    return False

            logger.info(f"登录成功: 用户ID={self.user_id}")

            # 记录登录事件
            real_stats.record_message(self.user_id, "system", "用户登录成功")

            return True
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

        # 等待连接建立
        for _ in range(10):
            if self.ws_connection is not None:
                return True
            await asyncio.sleep(0.5)
        return False

    async def disconnect(self):
        """断开WebSocket连接"""
        self.ws_running = False
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

    async def _ws_loop(self):
        """WebSocket主循环"""
        while self.ws_running:
            try:
                await self._ws_connect()
            except Exception as e:
                logger.error(f"WebSocket异常: {e}")

            if self.ws_running:
                self.ws_reconnect_count += 1
                delay = min(
                    Config.RECONNECT_DELAY * (2**self.ws_reconnect_count),
                    Config.MAX_RECONNECT_DELAY)
                logger.info(f"将在{delay}秒后重连...")
                await asyncio.sleep(delay)
            else:
                break

    async def _ws_connect(self):
        """WebSocket连接"""
        try:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            logger.info(f"正在连接WebSocket... (第{self.ws_reconnect_count + 1}次)")

            self.ws_connection = await websockets.connect(
                Config.WS_URL,
                ssl=ssl_context,
                ping_interval=Config.HEARTBEAT_INTERVAL,
                ping_timeout=10,
                close_timeout=10,
                max_size=2**20,
                open_timeout=30)

            self.ws_reconnect_count = 0
            await self._ws_auth()

            # 重启心跳任务
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()

            self.heartbeat_task = asyncio.create_task(self._ws_heartbeat())

            try:
                await self._ws_receive()
            finally:
                if self.heartbeat_task and not self.heartbeat_task.done():
                    self.heartbeat_task.cancel()
                    try:
                        await self.heartbeat_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            if self.ws_connection:
                await self.ws_connection.close()
                self.ws_connection = None
            raise

    async def _ws_auth(self):
        """WebSocket认证"""
        auth_msg = json.dumps({
            "cmd": WSCommand.AUTH.value,
            "data": {
                "accessToken": self.access_token
            }
        })
        await self.ws_connection.send(auth_msg)
        logger.info("WebSocket认证已发送")

    async def _ws_heartbeat(self):
        """WebSocket心跳"""
        while self.ws_running and self.ws_connection:
            try:
                heartbeat_msg = json.dumps({
                    "cmd": WSCommand.HEARTBEAT.value,
                    "data": {}
                })
                await self.ws_connection.send(heartbeat_msg)
                logger.debug("心跳发送成功")
                await asyncio.sleep(Config.HEARTBEAT_INTERVAL)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接已关闭，停止心跳")
                break
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
                break

    async def _ws_receive(self):
        """WebSocket消息接收"""
        try:
            async for message in self.ws_connection:
                try:
                    data = json.loads(message)
                    await self._handle_ws_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {e}, 原始消息: {message}")
                except Exception as e:
                    logger.error(f"处理WebSocket消息失败: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket连接关闭: {e}")
        except Exception as e:
            logger.error(f"WebSocket接收消息异常: {e}")
        finally:
            if self.ws_running:
                logger.info("接收循环结束，准备重连")

    async def _handle_ws_message(self, data: Dict):
        """处理WebSocket消息"""
        cmd = data.get('cmd')
        msg_data = data.get('data', {})

        try:
            if cmd == WSCommand.PRIVATE_MESSAGE:
                msg = Message(msg_data, is_group=False)
                await self._dispatch_message(msg, 'private')
            elif cmd == WSCommand.GROUP_MESSAGE:
                msg = Message(msg_data, is_group=True)
                await self._dispatch_message(msg, 'group')
            elif cmd == WSCommand.SYSTEM_MESSAGE:
                logger.info(f"收到系统消息: {msg_data}")
                # 记录系统消息
                real_stats.record_message(0, "system", f"系统消息: {msg_data}")
            elif cmd == WSCommand.FORCE_OFFLINE:
                logger.warning("收到强制下线通知")
                self.ws_running = False
        except Exception as e:
            logger.error(f"处理WebSocket消息异常: {e}")

    async def _dispatch_message(self, message: Message, msg_type: str):
        """分发消息给处理器"""
        try:
            for handler in self.message_handlers.get(msg_type, []):
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"消息处理器失败: {e}")
        except Exception as e:
            logger.error(f"消息分发处理失败: {e}")

    async def robust_start(self):
        """稳健启动机器人"""
        max_retries = 5
        retry_count = 0

        while retry_count < max_retries:
            try:
                self._reset_daily_stats()

                if not self.is_logged_in:
                    logger.info("尝试登录...")
                    if await self.login("ENLT", "114514"):
                        logger.info("登录成功")
                        retry_count = 0
                    else:
                        logger.error("登录失败，30秒后重试")
                        await asyncio.sleep(30)
                        retry_count += 1
                        continue

                logger.info("连接WebSocket...")
                success = await self.connect()
                if success:
                    logger.info("机器人启动成功！开始监听真实消息...")
                    last_activity_time = time.time()

                    while self.ws_running:
                        await asyncio.sleep(1)

                        current_time = time.time()

                        # 定期日志
                        if current_time - last_activity_time > 30:
                            last_activity_time = current_time
                            logger.debug("机器人运行中...")

                        # 自动保存数据
                        if current_time - self._last_save_time > 3600:
                            self._save_data()
                            self._last_save_time = current_time
                            logger.info("自动保存数据完成")

                else:
                    logger.error("连接失败，30秒后重试")
                    await asyncio.sleep(30)
                    retry_count += 1

            except KeyboardInterrupt:
                logger.info("收到中断信号")
                break
            except Exception as e:
                logger.error(f"机器人运行异常: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 2**retry_count
                    logger.info(f"{wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("达到最大重试次数，退出程序")
            finally:
                await self.stop()
                self._save_data()

    async def stop(self):
        """停止机器人"""
        logger.info("正在停止机器人...")
        await self.disconnect()
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("机器人已停止")

# ============================ 等级系统类 ============================

class LevelSystem:
    """等级和经验系统"""
    
    def __init__(self, boxim_instance):
        """
        初始化等级系统
        
        Args:
            boxim_instance: BoxIM实例
        """
        self.boxim = boxim_instance
        self.user_message_times = {}
        self.spam_warnings = {}
        self.temp_blacklist = {}
        
        # 标签体系配置
        self.labels = {
            "普通用户": {"min_level": 1, "max_level": 10},
            "活跃用户": {"min_level": 11, "max_level": 20},
            "资深用户": {"min_level": 21, "max_level": 30},
            "传奇": {"min_level": 31, "max_level": 35},
            "神话": {"min_level": 36, "max_level": 45},
            "巅峰": {"min_level": 46, "max_level": 99},
            "无敌": {"min_level": 100, "max_level": 999}
        }

    def _get_user_data(self, user_id: int) -> Dict:
        """获取用户数据，如果不存在则创建"""
        user_id_str = str(user_id)
        if user_id_str not in self.boxim.user_data:
            self.boxim.user_data[user_id_str] = {
                "exp": 0,
                "level": 1,
                "total_messages": 0,
                "last_message_time": 0,
                "spam_warnings": 0,
                "last_warning_time": 0,
                "current_label": "普通用户",
                "points": 0,
                "last_sign_date": None,
                "consecutive_days": 0,
                "total_sign_days": 0,
                "lottery_count": 0,
                "lottery_wins": 0,
            }
        else:
            # 确保新字段存在
            user_data = self.boxim.user_data[user_id_str]
            defaults = {
                "points": 0,
                "last_sign_date": None,
                "consecutive_days": 0,
                "total_sign_days": 0,
                "lottery_count": 0,
                "lottery_wins": 0,
            }
            for key, default_value in defaults.items():
                if key not in user_data:
                    user_data[key] = default_value
        return self.boxim.user_data[user_id_str]

    def _calculate_exp_for_level(self, level: int) -> int:
        """计算达到指定等级所需的总经验"""
        if level <= 1:
            return 0
        total_exp = 0
        for lvl in range(1, level):
            exp_needed = round((lvl * lvl) / 2)
            total_exp += exp_needed
        return total_exp

    def _calculate_level_from_exp(self, exp: int) -> int:
        """根据经验值计算当前等级"""
        level = 1
        total_exp_needed = 0
        while True:
            next_level_exp = round((level * level) / 2)
            total_exp_needed += next_level_exp
            if exp >= total_exp_needed:
                level += 1
            else:
                break
            if level > 999:
                break
        return level

    def _calculate_exp_for_next_level(self, current_level: int) -> int:
        """计算升级到下一级所需的经验"""
        if current_level < 1:
            return 0
        return round((current_level * current_level) / 2)

    async def add_experience(self, user_id: int, message: Message) -> bool:
        """为用户添加经验"""
        current_time = time.time()
        user_data = self._get_user_data(user_id)

        # 检查是否在临时黑名单中
        if user_id in self.temp_blacklist:
            if current_time < self.temp_blacklist[user_id]:
                return False
            else:
                del self.temp_blacklist[user_id]
                if user_id in self.spam_warnings:
                    del self.spam_warnings[user_id]

        # 检查刷屏行为
        if user_id not in self.user_message_times:
            self.user_message_times[user_id] = []

        self.user_message_times[user_id].append(current_time)
        five_seconds_ago = current_time - 5
        self.user_message_times[user_id] = [
            t for t in self.user_message_times[user_id] if t > five_seconds_ago
        ]

        # 如果5秒内发送超过5条消息，视为刷屏
        if len(self.user_message_times[user_id]) >= 5:
            await self._handle_spam(user_id, message)
            return False

        # 添加经验和更新统计数据
        user_data["exp"] += 1
        user_data["total_messages"] += 1
        user_data["last_message_time"] = current_time

        # 检查是否升级
        old_level = user_data["level"]
        new_level = self._calculate_level_from_exp(user_data["exp"])
        if new_level > old_level:
            old_label = user_data.get("current_label", "普通用户")
            new_label = self.get_user_label(new_level)
            user_data["level"] = new_level

            if new_label != old_label:
                user_data["current_label"] = new_label

            await self._send_level_up_message(user_id, old_level, new_level,
                                              old_label, new_label, message)

        self.boxim._save_data()

        # 更新用户等级到统计系统
        real_stats.update_user_level(user_id, user_data["level"])

        return True

    async def _handle_spam(self, user_id: int, message: Message):
        """处理刷屏行为"""
        current_time = time.time()

        if user_id not in self.spam_warnings:
            self.spam_warnings[user_id] = 0

        self.spam_warnings[user_id] += 1

        if self.spam_warnings[user_id] == 1:
            # 第一次刷屏：禁言1分钟
            self.temp_blacklist[user_id] = current_time + 60
            username = await self.boxim.get_username(user_id)
            clean_username = self._clean_username(username)
            warning_msg = f"⚠️ {clean_username} 检测到刷屏行为！您已被暂时禁言1分钟，请勿频繁发送消息。"
            await self._send_warning(user_id, warning_msg, message)
            logger.warning(f"用户 {user_id} 第一次刷屏，禁言1分钟")
        else:
            # 多次刷屏：清空所有数据
            await self._reset_user_data(user_id)
            username = await self.boxim.get_username(user_id)
            clean_username = self._clean_username(username)
            warning_msg = f"🚫 {clean_username} 多次刷屏警告！您的所有数据已被清空。"
            await self._send_warning(user_id, warning_msg, message)
            self.spam_warnings[user_id] = 0
            if user_id in self.temp_blacklist:
                del self.temp_blacklist[user_id]
            if user_id in self.user_message_times:
                del self.user_message_times[user_id]
            logger.warning(f"用户 {user_id} 多次刷屏，数据已清空")

    def _clean_username(self, username: str) -> str:
        """清理用户名中的特殊字符"""
        cleaned = re.sub(r'[\x00-\x1F\x7F-\x9F\u200B-\u200F\u202A-\u202E]', '',
                         username)
        if not cleaned.strip():
            return "用户"
        return cleaned

    async def _send_warning(self, user_id: int, warning_msg: str,
                            message: Message):
        """发送警告消息"""
        try:
            if message.is_group and message.group_id:
                await self.boxim.chat.send_group_text(message.group_id,
                                                      warning_msg)
            else:
                await self.boxim.chat.send_private_text(user_id, warning_msg)
        except Exception as e:
            logger.error(f"发送警告消息失败: {e}")

    async def _send_level_up_message(self, user_id: int, old_level: int,
                                     new_level: int, old_label: str,
                                     new_label: str, message: Message):
        """发送升级消息"""
        username = await self.boxim.get_username(user_id)
        clean_username = self._clean_username(username)

        if new_label != old_label:
            level_up_msg = f"🎉 {clean_username} 升级到 Lv.{new_level}！获得了新标签：{new_label}"
        else:
            level_up_msg = f"🎉 {clean_username} 升级到 Lv.{new_level}！"

        try:
            target_group_id = 19316  # 需要替换为实际的群组ID
            await self.boxim.chat.send_group_text(target_group_id,
                                                  level_up_msg)
        except Exception as e:
            logger.error(f"发送升级消息失败: {e}")

    async def _reset_user_data(self, user_id: int):
        """重置用户数据"""
        user_id_str = str(user_id)
        self.boxim.user_data[user_id_str] = {
            "exp": 0,
            "level": 1,
            "total_messages": 0,
            "last_message_time": 0,
            "spam_warnings": 0,
            "last_warning_time": 0,
            "current_label": "普通用户",
            "points": 0,
            "last_sign_date": None,
            "consecutive_days": 0,
            "total_sign_days": 0,
            "lottery_count": 0,
            "lottery_wins": 0,
        }
        self.boxim._save_data()

    def get_user_label(self, level: int) -> str:
        """根据等级获取用户标签"""
        for label, range_info in self.labels.items():
            if range_info["min_level"] <= level <= range_info["max_level"]:
                return label
        return "无敌"

    async def get_user_rank(self, user_id: int) -> int:
        """获取用户排名"""
        ranked_users = []
        for uid_str, user_data in self.boxim.user_data.items():
            if 'exp' in user_data:
                ranked_users.append({
                    'user_id': int(uid_str),
                    'exp': user_data['exp'],
                    'level': user_data.get('level', 1)
                })
        ranked_users.sort(key=lambda x: x['exp'], reverse=True)
        for rank, user in enumerate(ranked_users, 1):
            if user['user_id'] == user_id:
                return rank
        return len(ranked_users) + 1

    async def get_level_info(self, user_id: int) -> Dict:
        """获取用户等级信息"""
        user_data = self._get_user_data(user_id)
        current_level = user_data.get("level", 1)
        current_exp = user_data.get("exp", 0)

        current_level_total_exp = self._calculate_exp_for_level(current_level)
        next_level_total_exp = self._calculate_exp_for_level(current_level + 1)

        # 计算升级进度
        if next_level_total_exp > current_level_total_exp:
            progress = min(100, (current_exp - current_level_total_exp) /
                           (next_level_total_exp - current_level_total_exp) *
                           100)
        else:
            progress = 100

        exp_needed_for_next_level = next_level_total_exp - current_exp
        current_level_earned_exp = current_exp - current_level_total_exp
        current_level_total_needed_exp = next_level_total_exp - current_level_total_exp

        return {
            "level": current_level,
            "exp": current_exp,
            "exp_needed_for_next_level": exp_needed_for_next_level,
            "current_level_earned_exp": current_level_earned_exp,
            "current_level_total_needed_exp": current_level_total_needed_exp,
            "progress": progress,
            "total_messages": user_data.get("total_messages", 0),
            "label": user_data.get("current_label", "普通用户"),
            "current_level_total_exp": current_level_total_exp,
            "next_level_total_exp": next_level_total_exp
        }

    async def daily_sign(self, user_id: int, message: Message) -> bool:
        """每日签到"""
        user_data = self._get_user_data(user_id)
        current_date = datetime.now().strftime("%Y-%m-%d")

        # 检查今天是否已经签到
        if user_data.get("last_sign_date") == current_date:
            return False

        # 检查连续签到
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if user_data.get("last_sign_date") == yesterday:
            user_data["consecutive_days"] = user_data.get(
                "consecutive_days", 0) + 1
        else:
            user_data["consecutive_days"] = 1

        # 计算积分奖励
        base_points = random.randint(5, 15)
        consecutive_bonus = min(user_data["consecutive_days"] * 2, 20)
        total_points = base_points + consecutive_bonus

        # 更新用户数据
        user_data["points"] = user_data.get("points", 0) + total_points
        user_data["last_sign_date"] = current_date
        user_data["total_sign_days"] = user_data.get("total_sign_days", 0) + 1

        self.boxim._save_data()

        # 发送签到成功消息
        username = await self.boxim.get_username(user_id)
        clean_username = self._clean_username(username)

        sign_msg = f"""🎉 {clean_username} 签到成功！

💰 获得积分: {total_points} 点
  ├─ 基础奖励: {base_points} 点
  └─ 连续奖励: {consecutive_bonus} 点

📊 签到统计:
  ├─ 连续签到: {user_data['consecutive_days']} 天
  ├─ 总签到: {user_data['total_sign_days']} 天
  └─ 当前积分: {user_data['points']} 点

💡 使用 /exchange 命令兑换经验 (1积分=10经验)"""

        await send_reply(message, self.boxim, sign_msg)
        return True

    async def exchange_points(self, user_id: int, amount: int,
                              message: Message) -> bool:
        """积分兑换经验"""
        user_data = self._get_user_data(user_id)
        current_points = user_data.get("points", 0)

        if amount <= 0:
            await send_reply(message, self.boxim, "❌ 兑换数量必须大于0")
            return False

        if current_points < amount:
            await send_reply(message, self.boxim,
                             f"❌ 积分不足！当前积分: {current_points}点")
            return False

        # 执行兑换
        exp_gained = amount * 10
        user_data["points"] = current_points - amount
        user_data["exp"] = user_data.get("exp", 0) + exp_gained

        # 检查是否升级
        old_level = user_data.get("level", 1)
        new_level = self._calculate_level_from_exp(user_data["exp"])
        level_up = new_level > old_level

        if level_up:
            user_data["level"] = new_level
            old_label = user_data.get("current_label", "普通用户")
            new_label = self.get_user_label(new_level)
            if new_label != old_label:
                user_data["current_label"] = new_label

        self.boxim._save_data()

        # 发送兑换成功消息
        username = await self.boxim.get_username(user_id)
        clean_username = self._clean_username(username)

        exchange_msg = f"""✅ {clean_username} 积分兑换成功！

💰 消耗积分: {amount} 点
⭐ 获得经验: {exp_gained} 点
📊 当前积分: {user_data['points']} 点
🏅 当前等级: Lv.{new_level}"""

        if level_up:
            exchange_msg += f"\n🎉 恭喜升级到 Lv.{new_level}！"

        await send_reply(message, self.boxim, exchange_msg)
        return True

    async def lottery_draw(self, user_id: int, message: Message) -> bool:
        """抽奖功能"""
        user_data = self._get_user_data(user_id)
        current_points = user_data.get("points", 0)

        if current_points < 2:
            await send_reply(message, self.boxim,
                             f"❌ 积分不足！抽奖需要2积分，当前积分: {current_points}点")
            return False

        # 扣除积分
        user_data["points"] = current_points - 2
        user_data["lottery_count"] = user_data.get("lottery_count", 0) + 1

        # 抽奖配置
        lottery_config = [
            {"name": "🎉 超级大奖", "points": 50, "probability": 0.01},
            {"name": "🔥 暴击奖励", "points": 20, "probability": 0.02},
            {"name": "⭐ 幸运奖励", "points": 10, "probability": 0.05},
            {"name": "💰 不错奖励", "points": 5, "probability": 0.10},
            {"name": "🎁 普通奖励", "points": 2, "probability": 0.15},
            {"name": "🍀 小奖", "points": 1, "probability": 0.20},
            {"name": "🤝 安慰奖", "points": 0, "probability": 0.47}
        ]

        # 执行抽奖
        rand = random.random()
        cumulative_prob = 0
        result = None

        for prize in lottery_config:
            cumulative_prob += prize["probability"]
            if rand <= cumulative_prob:
                result = prize
                break

        # 处理中奖结果
        points_won = result["points"]
        if points_won > 0:
            user_data["points"] += points_won
            user_data["lottery_wins"] = user_data.get("lottery_wins", 0) + 1

        self.boxim._save_data()

        # 发送抽奖结果
        username = await self.boxim.get_username(user_id)
        clean_username = self._clean_username(username)

        lottery_msg = f"""🎰 {clean_username} 的抽奖结果：

💸 消耗积分: 2点
🎯 抽奖结果: {result['name']}"""

        if points_won > 0:
            lottery_msg += f"\n💰 获得积分: {points_won}点"
            lottery_msg += f"\n📊 当前积分: {user_data['points']}点"

            if points_won >= 20:
                lottery_msg += "\n\n🎊 哇！运气爆棚！再来一次说不定还有惊喜！"
            elif points_won >= 10:
                lottery_msg += "\n\n🎯 太棒了！手气不错！继续抽奖可能获得更大奖励！"
            elif points_won >= 5:
                lottery_msg += "\n\n👍 不错哦！再试一次也许能中大奖！"
            else:
                lottery_msg += "\n\n👏 恭喜中奖！继续挑战更高奖励吧！"
        else:
            lottery_msg += "\n😢 很遗憾，这次没有中奖"
            lottery_msg += "\n\n💪 别灰心！下次一定行！再试一次吧！"

        lottery_count = user_data.get("lottery_count", 0)
        lottery_wins = user_data.get("lottery_wins", 0)
        lottery_msg += f"\n\n📈 抽奖统计: 共{lottery_count}次，中奖{lottery_wins}次"

        await send_reply(message, self.boxim, lottery_msg)
        return True

    async def get_points_info(self, user_id: int) -> Dict:
        """获取积分信息"""
        user_data = self._get_user_data(user_id)
        lottery_count = user_data.get("lottery_count", 0)
        lottery_wins = user_data.get("lottery_wins", 0)
        win_rate = round((lottery_wins / lottery_count) *
                         100, 1) if lottery_count > 0 else 0

        return {
            "points": user_data.get("points", 0),
            "last_sign_date": user_data.get("last_sign_date"),
            "consecutive_days": user_data.get("consecutive_days", 0),
            "total_sign_days": user_data.get("total_sign_days", 0),
            "lottery_count": lottery_count,
            "lottery_wins": lottery_wins,
            "win_rate": win_rate
        }

    async def get_leaderboard(self,
                              page: int = 1,
                              page_size: int = 10) -> Dict:
        """获取排行榜"""
        ranked_users = []
        for uid_str, user_data in self.boxim.user_data.items():
            if 'exp' in user_data and user_data['exp'] > 0:
                ranked_users.append({
                    'user_id': int(uid_str),
                    'exp': user_data['exp'],
                    'level': user_data.get('level', 1),
                    'total_messages': user_data.get('total_messages', 0),
                    'label': user_data.get('current_label', '普通用户')
                })

        # 按经验值排序
        ranked_users.sort(key=lambda x: x['exp'], reverse=True)

        # 分页计算
        total_users = len(ranked_users)
        total_pages = max(1, (total_users + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_index = (page - 1) * page_size
        end_index = min(start_index + page_size, total_users)
        page_users = ranked_users[start_index:end_index]

        # 添加用户名和排名
        for user in page_users:
            user_id = user['user_id']
            username = await self.boxim.get_username(user_id)
            user['username'] = self._clean_username(username)
            user['rank'] = ranked_users.index(user) + 1

        return {
            'page': page,
            'total_pages': total_pages,
            'total_users': total_users,
            'users': page_users
        }

# ============================ API客户端类 ============================

class APIClient:
    """API客户端"""
    
    def __init__(self, boxim_instance):
        """
        初始化API客户端
        
        Args:
            boxim_instance: BoxIM实例
        """
        self.boxim = boxim_instance

    async def request(self, method: str, path: str, **kwargs) -> Dict:
        """
        发送API请求
        
        Args:
            method: HTTP方法
            path: API路径
            **kwargs: 其他参数
            
        Returns:
            响应数据
        """
        url = f"{Config.BASE_URL}{path}"
        if 'headers' not in kwargs:
            kwargs['headers'] = self.boxim._get_headers()
            
        async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                timeout=aiohttp.ClientTimeout(
                    total=Config.REQUEST_TIMEOUT)) as session:
            async with session.request(method, url, **kwargs) as response:
                data = await response.json()
                if data.get("code") != 200:
                    raise Exception(f"API错误: {data.get('message')}")
                return data

# ============================ 用户模块类 ============================

class UserModule:
    """用户管理模块"""
    
    def __init__(self, boxim_instance):
        """
        初始化用户模块
        
        Args:
            boxim_instance: BoxIM实例
        """
        self.boxim = boxim_instance
        self.api = APIClient(boxim_instance)

    async def get_self_info(self):
        """获取自身用户信息"""
        try:
            result = await self.api.request('GET', '/api/user/self')
            return result['data']
        except:
            return None

    async def get_user_info(self, user_id: int):
        """获取指定用户信息"""
        try:
            result = await self.api.request('GET', f'/api/user/find/{user_id}')
            return result['data']
        except:
            return None

# ============================ 消息模块类 ============================

class MessageModule:
    """消息管理模块"""
    
    def __init__(self, boxim_instance):
        """
        初始化消息模块
        
        Args:
            boxim_instance: BoxIM实例
        """
        self.boxim = boxim_instance
        self.api = APIClient(boxim_instance)

    async def send_private_message(self,
                                   user_id: int,
                                   content: str,
                                   msg_type: int = 0) -> Optional[int]:
        """
        发送私聊消息
        
        Args:
            user_id: 用户ID
            content: 消息内容
            msg_type: 消息类型
            
        Returns:
            消息ID
        """
        tmp_id = str(uuid.uuid4().int)[:16]
        payload = {
            "tmpId": tmp_id,
            "content": content,
            "type": msg_type,
            "recvId": user_id,
            "receipt": False
        }
        try:
            result = await self.api.request('POST',
                                            '/api/message/private/send',
                                            json=payload)
            return result['data'].get('id')
        except:
            return None

    async def send_group_message(
            self,
            group_id: int,
            content: str,
            msg_type: int = 0,
            at_user_ids: List[int] = None) -> Optional[int]:
        """
        发送群组消息
        
        Args:
            group_id: 群组ID
            content: 消息内容
            msg_type: 消息类型
            at_user_ids: @的用户ID列表
            
        Returns:
            消息ID
        """
        tmp_id = str(uuid.uuid4().int)[:16]
        payload = {
            "tmpId": tmp_id,
            "content": content,
            "type": msg_type,
            "groupId": group_id,
            "atUserIds": at_user_ids or [],
            "receipt": False
        }
        try:
            result = await self.api.request('POST',
                                            '/api/message/group/send',
                                            json=payload)
            return result['data'].get('id')
        except:
            return None

# ============================ 聊天助手类 ============================

class ChatHelper:
    """聊天助手"""
    
    def __init__(self, boxim_instance):
        """
        初始化聊天助手
        
        Args:
            boxim_instance: BoxIM实例
        """
        self.boxim = boxim_instance
        self.message = MessageModule(boxim_instance)

    async def send_private_text(self, user_id: int,
                                text: str) -> Optional[int]:
        """
        发送私聊文本消息
        
        Args:
            user_id: 用户ID
            text: 文本内容
            
        Returns:
            消息ID
        """
        return await self.message.send_private_message(user_id, text,
                                                       MessageType.TEXT)

    async def send_group_text(self,
                              group_id: int,
                              text: str,
                              at_user_ids: List[int] = None) -> Optional[int]:
        """
        发送群组文本消息
        
        Args:
            group_id: 群组ID
            text: 文本内容
            at_user_ids: @的用户ID列表
            
        Returns:
            消息ID
        """
        return await self.message.send_group_message(group_id, text,
                                                     MessageType.TEXT,
                                                     at_user_ids)

# ============================ 辅助函数 ============================

async def send_reply(message: Message, bot_instance, text: str):
    """
    发送回复消息
    
    Args:
        message: 原始消息
        bot_instance: 机器人实例
        text: 回复文本
    """
    try:
        if message.is_group and message.group_id:
            await bot_instance.chat.send_group_text(message.group_id, text)
        else:
            await bot_instance.chat.send_private_text(message.send_id, text)
    except Exception as e:
        logger.error(f"发送回复消息失败: {e}")

# ============================ Web服务器函数 ============================

def run_web_server():
    """运行Web服务器"""
    try:
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Web服务器启动失败: {e}")

# ============================ 保活服务 ============================

def keep_alive():
    """保活服务 - 防止应用休眠"""
    
    def ping_self():
        """自ping保持应用活跃"""
        time.sleep(10)

        # 构建可能的URL列表
        base_urls = []
        repl_slug = os.environ.get('REPL_SLUG')
        repl_owner = os.environ.get('REPL_OWNER')
        if repl_slug and repl_owner:
            base_urls.append(f"https://{repl_slug}.{repl_owner}.repl.co")

        base_urls.append("http://0.0.0.0:8080")
        base_urls.append("http://127.0.0.1:8080")

        repl_id = os.environ.get('REPL_ID')
        if repl_id:
            base_urls.append(f"https://{repl_id}.id.repl.co")

        if repl_slug:
            base_urls.append(f"https://{repl_slug}.repl.co")

        base_urls = list(set([url for url in base_urls if url]))

        logger.info(f"可用的自ping地址: {base_urls}")

        while True:
            for base_url in base_urls:
                try:
                    # 优先使用 /ping 端点，如果失败则尝试其他端点
                    endpoints = ['/ping', '/health', '/keepalive', '/status', '/botinfo', '/']
                    
                    for endpoint in endpoints:
                        try:
                            response = requests.get(f"{base_url}{endpoint}", timeout=10)
                            if response.status_code == 200:
                                logger.info(f"自ping成功 - {base_url}{endpoint}")
                                break  # 成功就跳出内层循环
                            else:
                                logger.warning(f"自ping返回异常状态 {endpoint}: {response.status_code}")
                        except Exception as e:
                            logger.debug(f"自ping失败 {base_url}{endpoint}: {e}")
                            continue  # 继续尝试下一个端点

                except Exception as e:
                    logger.debug(f"自ping完全失败 {base_url}: {e}")

            sleep_time = random.randint(45, 75)
            time.sleep(sleep_time)

    thread = threading.Thread(target=ping_self)
    thread.daemon = True
    thread.start()

def external_keepalive():
    """外部保活服务"""
    
    def ping_external():
        """外部ping保持应用活跃"""
        time.sleep(30)

        your_replit_url = os.environ.get('YOUR_REPLIT_URL', '')
        if not your_replit_url:
            repl_slug = os.environ.get('REPL_SLUG')
            repl_owner = os.environ.get('REPL_OWNER')
            if repl_slug and repl_owner:
                your_replit_url = f"https://{repl_slug}.{repl_owner}.repl.co"

        while True:
            if your_replit_url:
                try:
                    # 尝试多个端点
                    endpoints = ['/ping', '/health', '/', '/status']
                    for endpoint in endpoints:
                        try:
                            response = requests.get(f"{your_replit_url}{endpoint}", timeout=10)
                            if response.status_code == 200:
                                logger.info(f"外部保活检查 {endpoint}: {response.status_code}")
                                break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"外部保活失败: {e}")

            time.sleep(240)

    thread = threading.Thread(target=ping_external)
    thread.daemon = True
    thread.start()

# ============================ 主函数 ============================

async def main():
    """主函数"""
    global bot_instance
    bot_instance = BoxIM()
    
    # 从环境变量读取配置
    username = os.environ.get('BOXIM_USERNAME', 'ENLT')
    password = os.environ.get('BOXIM_PASSWORD', '114514')

    logger.info(f"正在使用账号 {username} 登录...")

    # 启动保活服务
    keep_alive()
    external_keepalive()
    logger.info("保活服务已启动")

    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:
        try:
            logger.info(f"第 {retry_count + 1} 次尝试启动...")

            success = await bot_instance.login(username, password)
            if not success:
                logger.error("登录失败，30秒后重试")
                await asyncio.sleep(30)
                retry_count += 1
                continue

            logger.info("登录成功！开始运行BoxIM机器人...")
            await bot_instance.robust_start()

        except Exception as e:
            logger.error(f"主程序异常: {e}")
            retry_count += 1
            if retry_count < max_retries:
                wait_time = 2**retry_count
                logger.info(f"{wait_time}秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("达到最大重试次数，退出程序")
                break

# ============================ Railway部署适配 ============================

if __name__ == "__main__":
    # 检查是否在Railway环境中
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        print("🚄 检测到Railway环境")
        print(f"📊 Web面板地址: https://{os.environ.get('RAILWAY_STATIC_URL', '你的应用')}.railway.app")
        
        # 在Railway中，Web服务由gunicorn启动
        # 机器人工作进程由worker进程处理
        print("🌐 Web服务运行中...")
    else:
        # 本地开发模式
        print("💻 本地开发模式")
        
        # 启动Web服务器线程
        web_thread = threading.Thread(target=run_web_server)
        web_thread.daemon = True
        web_thread.start()

        logger.info("Web服务器线程已启动")
        time.sleep(3)

        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("程序被用户中断")
        except Exception as e:
            logger.error(f"程序异常退出: {e}")
