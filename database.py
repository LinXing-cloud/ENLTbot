"""
数据库管理器
"""

import sqlite3
import json
import threading
import os
import bcrypt
from datetime import datetime
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger('BoxIM.Database')

class DatabaseManager:
    """数据库管理器 - 单例模式"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        """初始化数据库"""
        # 使用相对导入避免循环依赖
        from config import BotConfig, WebUserConfig
        
        self.bot_config = BotConfig
        self.web_user_config = WebUserConfig
        
        self.db_path = self.bot_config.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        
        # 初始化Web用户数据库
        self._init_web_users_db()
    
    def _init_web_users_db(self):
        """初始化Web用户数据库"""
        web_db_path = self.bot_config.WEB_USERS_DB
        self.web_conn = sqlite3.connect(web_db_path, check_same_thread=False)
        self.web_conn.row_factory = sqlite3.Row
        
        with self.web_conn:
            # 创建用户表
            self.web_conn.execute('''
                CREATE TABLE IF NOT EXISTS web_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # 创建会话表
            self.web_conn.execute('''
                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES web_users (id)
                )
            ''')
            
            # 创建日志表
            self.web_conn.execute('''
                CREATE TABLE IF NOT EXISTS web_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES web_users (id)
                )
            ''')
            
            # 插入默认管理员账号
            self.web_conn.execute('''
                INSERT OR IGNORE INTO web_users (username, password_hash, role, created_at)
                VALUES (?, ?, ?, ?)
            ''', (
                self.web_user_config.DEFAULT_ADMIN['username'],
                self.web_user_config.DEFAULT_ADMIN['password'],
                self.web_user_config.DEFAULT_ADMIN['role'],
                self.web_user_config.DEFAULT_ADMIN['created_at']
            ))
    
    # ============ Web用户管理 ============
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """验证用户"""
        cursor = self.web_conn.execute(
            'SELECT * FROM web_users WHERE username = ? AND is_active = 1',
            (username,)
        )
        user = cursor.fetchone()
        
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return dict(user)
        return None
    
    def create_session(self, session_id: str, user_id: int, expires_at: str) -> bool:
        """创建会话"""
        try:
            self.web_conn.execute('''
                INSERT INTO web_sessions (session_id, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (session_id, user_id, datetime.now().isoformat(), expires_at))
            self.web_conn.commit()
            return True
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话"""
        cursor = self.web_conn.execute('''
            SELECT s.*, u.username, u.role 
            FROM web_sessions s
            JOIN web_users u ON s.user_id = u.id
            WHERE s.session_id = ? AND s.expires_at > ?
        ''', (session_id, datetime.now().isoformat()))
        session = cursor.fetchone()
        return dict(session) if session else None
    
    def delete_session(self, session_id: str):
        """删除会话"""
        self.web_conn.execute('DELETE FROM web_sessions WHERE session_id = ?', (session_id,))
        self.web_conn.commit()
    
    def update_password(self, user_id: int, new_password_hash: str) -> bool:
        """更新密码"""
        try:
            self.web_conn.execute('''
                UPDATE web_users 
                SET password_hash = ?, last_login = ?
                WHERE id = ?
            ''', (new_password_hash, datetime.now().isoformat(), user_id))
            self.web_conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新密码失败: {e}")
            return False
    
    def add_web_log(self, user_id: Optional[int], action: str, details: str = "", ip_address: str = ""):
        """添加Web日志"""
        self.web_conn.execute('''
            INSERT INTO web_logs (user_id, action, details, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, action, details, ip_address, datetime.now().isoformat()))
        self.web_conn.commit()
    
    def get_web_users(self) -> List[Dict]:
        """获取所有Web用户"""
        cursor = self.web_conn.execute('SELECT * FROM web_users ORDER BY created_at DESC')
        return [dict(row) for row in cursor.fetchall()]
    
    def add_web_user(self, username: str, password_hash: str, role: str = "user") -> bool:
        """添加Web用户"""
        try:
            self.web_conn.execute('''
                INSERT INTO web_users (username, password_hash, role, created_at)
                VALUES (?, ?, ?, ?)
            ''', (username, password_hash, role, datetime.now().isoformat()))
            self.web_conn.commit()
            return True
        except Exception as e:
            logger.error(f"添加Web用户失败: {e}")
            return False
    
    def update_web_user(self, user_id: int, role: str = None, is_active: int = None) -> bool:
        """更新Web用户"""
        try:
            updates = []
            params = []
            
            if role is not None:
                updates.append("role = ?")
                params.append(role)
            
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(is_active)
            
            if updates:
                params.append(user_id)
                query = f"UPDATE web_users SET {', '.join(updates)} WHERE id = ?"
                self.web_conn.execute(query, params)
                self.web_conn.commit()
            
            return True
        except Exception as e:
            logger.error(f"更新Web用户失败: {e}")
            return False
    
    def get_web_logs(self, limit: int = 100) -> List[Dict]:
        """获取Web日志"""
        cursor = self.web_conn.execute('''
            SELECT l.*, u.username 
            FROM web_logs l
            LEFT JOIN web_users u ON l.user_id = u.id
            ORDER BY l.created_at DESC 
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]
    
    # ============ 机器人数据表操作 ============
    
    def _create_tables(self):
        """创建数据表"""
        with self.conn:
            # 用户数据表
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    exp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    total_messages INTEGER DEFAULT 0,
                    last_message_time REAL DEFAULT 0,
                    spam_warnings INTEGER DEFAULT 0,
                    last_warning_time REAL DEFAULT 0,
                    current_label TEXT DEFAULT '普通用户',
                    points INTEGER DEFAULT 0,
                    last_sign_date TEXT,
                    consecutive_days INTEGER DEFAULT 0,
                    total_sign_days INTEGER DEFAULT 0,
                    lottery_count INTEGER DEFAULT 0,
                    lottery_wins INTEGER DEFAULT 0,
                    command_count INTEGER DEFAULT 0,
                    created_time REAL DEFAULT (strftime('%s', 'now')),
                    updated_time REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # 创建索引
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_users_exp ON users(exp)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_users_level ON users(level)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_users_points ON users(points)')
            
            # 每日统计表
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    message_count INTEGER DEFAULT 0,
                    active_users INTEGER DEFAULT 0,
                    created_time REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # 群聊信息表
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS group_info (
                    group_id INTEGER PRIMARY KEY,
                    name TEXT,
                    owner_id INTEGER,
                    notice TEXT,
                    is_all_muted INTEGER DEFAULT 0,
                    is_allow_invite INTEGER DEFAULT 1,
                    is_allow_share_card INTEGER DEFAULT 1,
                    dissolve INTEGER DEFAULT 0,
                    quit INTEGER DEFAULT 0,
                    is_muted INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    is_dnd INTEGER DEFAULT 0,
                    is_top INTEGER DEFAULT 0,
                    last_sync_time REAL DEFAULT 0,
                    created_time REAL DEFAULT (strftime('%s', 'now')),
                    updated_time REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # 消息记录表
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER UNIQUE,
                    message_type INTEGER,
                    content TEXT,
                    send_id INTEGER,
                    send_nickname TEXT,
                    send_time REAL,
                    is_group INTEGER DEFAULT 0,
                    group_id INTEGER,
                    recv_id INTEGER,
                    has_quote INTEGER DEFAULT 0,
                    quote_message TEXT,
                    recalled INTEGER DEFAULT 0,
                    recall_time REAL,
                    recall_by INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_time REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # 创建消息索引
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_send_id ON messages(send_id)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_send_time ON messages(send_time)')
            
            # 配置表
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    description TEXT,
                    updated_time REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # 插入默认配置
            default_configs = [
                ('TOKEN_REFRESH_THRESHOLD', '600', 'Token刷新阈值(秒)'),
                ('MAX_RECONNECT_ATTEMPTS', '10', '最大重连尝试次数'),
                ('HEARTBEAT_INTERVAL', '15', '心跳间隔(秒)'),
                ('STATUS_REPORT_INTERVAL', '1800', '状态报告间隔(秒)'),
                ('DAILY_REPORT_HOUR', '6', '每日报告时间(小时)'),
                ('MONITOR_GROUP_ID', '20250', '监控群聊ID'),
            ]
            
            for key, value, description in default_configs:
                self.conn.execute('''
                    INSERT OR IGNORE INTO config (key, value, description) 
                    VALUES (?, ?, ?)
                ''', (key, value, description))
    
    # ============ 用户数据操作 ============
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """获取用户数据"""
        cursor = self.conn.execute(
            'SELECT * FROM users WHERE user_id = ?',
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    
    def save_user(self, user_id: int, data: Dict):
        """保存用户数据"""
        user_db_data = {
            'user_id': user_id,
            'exp': data.get('exp', 0),
            'level': data.get('level', 1),
            'total_messages': data.get('total_messages', 0),
            'last_message_time': data.get('last_message_time', 0),
            'spam_warnings': data.get('spam_warnings', 0),
            'last_warning_time': data.get('last_warning_time', 0),
            'current_label': data.get('current_label', '普通用户'),
            'points': data.get('points', 0),
            'last_sign_date': data.get('last_sign_date'),
            'consecutive_days': data.get('consecutive_days', 0),
            'total_sign_days': data.get('total_sign_days', 0),
            'lottery_count': data.get('lottery_count', 0),
            'lottery_wins': data.get('lottery_wins', 0),
            'command_count': data.get('command_count', 0),
        }
        
        # 检查用户是否存在
        existing = self.get_user(user_id)
        
        if existing:
            # 更新数据
            update_fields = []
            values = []
            for key, value in user_db_data.items():
                if key != 'user_id':
                    update_fields.append(f"{key} = ?")
                    values.append(value)
            values.append(user_id)
            
            query = f'''
                UPDATE users SET {', '.join(update_fields)}, 
                updated_time = strftime('%s', 'now')
                WHERE user_id = ?
            '''
            self.conn.execute(query, values)
        else:
            # 插入新数据
            columns = ', '.join(user_db_data.keys())
            placeholders = ', '.join(['?'] * len(user_db_data))
            self.conn.execute(
                f'INSERT INTO users ({columns}) VALUES ({placeholders})',
                list(user_db_data.values())
            )
        
        self.conn.commit()
    
    def delete_user(self, user_id: int):
        """删除用户数据"""
        self.conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def get_all_users(self) -> List[Dict]:
        """获取所有用户数据"""
        cursor = self.conn.execute('SELECT * FROM users')
        return [dict(row) for row in cursor.fetchall()]
    
    def get_user_count(self) -> int:
        """获取用户总数"""
        cursor = self.conn.execute('SELECT COUNT(*) as count FROM users')
        return cursor.fetchone()[0]
    
    def get_top_users(self, field: str = 'exp', limit: int = 10) -> List[Dict]:
        """获取排行榜用户"""
        valid_fields = {'exp', 'level', 'points', 'total_sign_days', 'consecutive_days', 'command_count'}
        if field not in valid_fields:
            field = 'exp'
        
        cursor = self.conn.execute(
            f'SELECT * FROM users WHERE {field} > 0 ORDER BY {field} DESC LIMIT ?',
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    # ============ 每日统计操作 ============
    
    def save_daily_stat(self, date: str, message_count: int, active_users: int):
        """保存每日统计"""
        self.conn.execute('''
            INSERT OR REPLACE INTO daily_stats (date, message_count, active_users)
            VALUES (?, ?, ?)
        ''', (date, message_count, active_users))
        self.conn.commit()
    
    def get_daily_stat(self, date: str) -> Optional[Dict]:
        """获取每日统计"""
        cursor = self.conn.execute(
            'SELECT * FROM daily_stats WHERE date = ?',
            (date,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    # ============ 群聊信息操作 ============
    
    def save_group_info(self, group_id: int, info: Dict):
        """保存群聊信息"""
        self.conn.execute('''
            INSERT OR REPLACE INTO group_info (
                group_id, name, owner_id, notice, is_all_muted, is_allow_invite,
                is_allow_share_card, dissolve, quit, is_muted, is_banned,
                is_dnd, is_top, last_sync_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            group_id,
            info.get('name'),
            info.get('ownerId'),
            info.get('notice'),
            1 if info.get('isAllMuted') else 0,
            1 if info.get('isAllowInvite') else 0,
            1 if info.get('isAllowShareCard') else 0,
            1 if info.get('dissolve') else 0,
            1 if info.get('quit') else 0,
            1 if info.get('isMuted') else 0,
            1 if info.get('isBanned') else 0,
            1 if info.get('isDnd') else 0,
            1 if info.get('isTop') else 0,
            info.get('last_sync_time', 0)
        ))
        self.conn.commit()
    
    def get_group_info(self, group_id: int) -> Optional[Dict]:
        """获取群聊信息"""
        cursor = self.conn.execute(
            'SELECT * FROM group_info WHERE group_id = ?',
            (group_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_groups(self) -> List[Dict]:
        """获取所有群聊信息"""
        cursor = self.conn.execute('SELECT * FROM group_info ORDER BY group_id')
        return [dict(row) for row in cursor.fetchall()]
    
    def delete_group_info(self, group_id: int):
        """删除群聊信息"""
        self.conn.execute('DELETE FROM group_info WHERE group_id = ?', (group_id,))
        self.conn.commit()
    
    # ============ 消息记录操作 ============
    
    def save_message(self, message_data: Dict) -> int:
        """保存消息记录"""
        try:
            cursor = self.conn.execute('''
                INSERT OR REPLACE INTO messages (
                    message_id, message_type, content, send_id, send_nickname,
                    send_time, is_group, group_id, recv_id, has_quote,
                    quote_message, recalled, recall_time, recall_by, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message_data.get('message_id'),
                message_data.get('message_type'),
                message_data.get('content'),
                message_data.get('send_id'),
                message_data.get('send_nickname'),
                message_data.get('send_time'),
                message_data.get('is_group', 0),
                message_data.get('group_id'),
                message_data.get('recv_id'),
                message_data.get('has_quote', 0),
                json.dumps(message_data.get('quote_message')) if message_data.get('quote_message') else None,
                message_data.get('recalled', 0),
                message_data.get('recall_time'),
                message_data.get('recall_by'),
                json.dumps(message_data.get('metadata', {}))
            ))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"保存消息失败: {e}")
            return -1
    
    def get_message(self, message_id: int) -> Optional[Dict]:
        """获取消息记录"""
        cursor = self.conn.execute(
            'SELECT * FROM messages WHERE message_id = ?',
            (message_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_user_messages(self, user_id: int, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取用户消息"""
        cursor = self.conn.execute('''
            SELECT * FROM messages 
            WHERE send_id = ? 
            ORDER BY send_time DESC 
            LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_group_messages(self, group_id: int, limit: int = 200, offset: int = 0) -> List[Dict]:
        """获取群聊消息"""
        cursor = self.conn.execute('''
            SELECT * FROM messages 
            WHERE group_id = ? 
            ORDER BY send_time DESC 
            LIMIT ? OFFSET ?
        ''', (group_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]
    
    def search_messages(self, keyword: str, limit: int = 50) -> List[Dict]:
        """搜索消息"""
        cursor = self.conn.execute('''
            SELECT * FROM messages 
            WHERE content LIKE ? 
            ORDER BY send_time DESC 
            LIMIT ?
        ''', (f'%{keyword}%', limit))
        return [dict(row) for row in cursor.fetchall()]
    
    # ============ 配置操作 ============
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        cursor = self.conn.execute(
            'SELECT value FROM config WHERE key = ?',
            (key,)
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row['value'])
            except:
                return row['value']
        return default
    
    def set_config(self, key: str, value: Any):
        """设置配置"""
        value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        self.conn.execute('''
            INSERT OR REPLACE INTO config (key, value, updated_time)
            VALUES (?, ?, strftime('%s', 'now'))
        ''', (key, value_str))
        self.conn.commit()
    
    # ============ 统计操作 ============
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        stats = {}
        
        cursor = self.conn.execute('SELECT COUNT(*) as count FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        cursor = self.conn.execute('SELECT COUNT(*) as count FROM users WHERE exp > 0')
        stats['active_users'] = cursor.fetchone()[0]
        
        cursor = self.conn.execute('SELECT COUNT(*) as count FROM messages')
        stats['total_messages'] = cursor.fetchone()[0]
        
        cursor = self.conn.execute('SELECT COUNT(*) as count FROM group_info')
        stats['total_groups'] = cursor.fetchone()[0]
        
        return stats
    
    def backup(self, backup_path: str = None):
        """备份数据库"""
        if not backup_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"bot_data_backup_{timestamp}.db"
        
        backup_conn = sqlite3.connect(backup_path)
        with backup_conn:
            self.conn.backup(backup_conn)
        backup_conn.close()
        
        return backup_path
    
    def optimize(self):
        """优化数据库"""
        self.conn.execute('VACUUM')
        self.conn.execute('ANALYZE')
        self.conn.commit()
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
        if hasattr(self, 'web_conn') and self.web_conn:
            self.web_conn.close()