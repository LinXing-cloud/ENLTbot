"""
配置文件
"""

import os
import ssl
import certifi

# ============ 从环境变量获取配置 ============
def get_env(key, default=None):
    """获取环境变量"""
    return os.environ.get(key, default)

# ============ SSL设置 ============
ssl_context = ssl.create_default_context(cafile=certifi.where())

# ============ API配置 ============
class APIConfig:
    """API配置"""
    BASE_URL = "https://www.boxim.online"
    WS_URL = "wss://www.boxim.online/im"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    REQUEST_TIMEOUT = int(get_env('REQUEST_TIMEOUT', 30))

# ============ 机器人配置 ============
class BotConfig:
    """机器人配置"""
    # 机器人账号
    USERNAME = get_env('BOT_USERNAME', 'ENLT')
    PASSWORD = get_env('BOT_PASSWORD', '114514')
    
    # 管理员用户ID
    ADMIN_USERS = [int(x) for x in get_env('ADMIN_USERS', '35896,115748').split(',')]
    BROADCAST_GROUP = int(get_env('BROADCAST_GROUP', '19316'))
    
    # 重连设置
    RECONNECT_DELAY = int(get_env('RECONNECT_DELAY', 3))
    MAX_RECONNECT_DELAY = int(get_env('MAX_RECONNECT_DELAY', 60))
    MAX_RECONNECT_ATTEMPTS = int(get_env('MAX_RECONNECT_ATTEMPTS', 10))
    
    # 心跳设置
    HEARTBEAT_INTERVAL = int(get_env('HEARTBEAT_INTERVAL', 15))
    CONNECTION_TIMEOUT = int(get_env('CONNECTION_TIMEOUT', 30))
    
    # Token设置
    TOKEN_REFRESH_THRESHOLD = int(get_env('TOKEN_REFRESH_THRESHOLD', 600))
    
    # 统计报告
    STATUS_REPORT_INTERVAL = int(get_env('STATUS_REPORT_INTERVAL', 1800))
    DAILY_REPORT_HOUR = int(get_env('DAILY_REPORT_HOUR', 6))
    
    # 数据库
    DATABASE_PATH = get_env('DATABASE_PATH', 'bot_data.db')
    WEB_USERS_DB = get_env('WEB_USERS_DB', 'web_users.db')
    LOG_FILE = get_env('LOG_FILE', 'bot.log')
    
    # Web界面设置
    WEB_HOST = get_env('WEB_HOST', '0.0.0.0')
    WEB_PORT = int(get_env('WEB_PORT', 8080))
    WEB_SECRET_KEY = get_env('WEB_SECRET_KEY', 'your-secret-key-change-this-in-production')
    SESSION_TIMEOUT = int(get_env('SESSION_TIMEOUT', 3600))  # 1小时

# ============ Web用户管理 ============
class WebUserConfig:
    """Web用户配置"""
    # 初始管理员账号（用户名: admin, 密码: admin）
    DEFAULT_ADMIN = {
        "username": "admin",
        "password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",  # admin 的bcrypt哈希
        "role": "admin",
        "created_at": "2025-01-01 00:00:00"
    }