"""
BoxIM ENLTbot 主程序入口
Copyright (c) 2025 Entropy Light. All rights reserved.
<v3.3.12 - beta>
"""

import asyncio
import signal
import sys
import os
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 确保日志目录存在
log_dir = Path("data/logs")
log_dir.mkdir(parents=True, exist_ok=True)

# 确保数据库目录存在
db_dir = Path("data/db")
db_dir.mkdir(parents=True, exist_ok=True)

class Application:
    """应用程序主类"""
    
    def __init__(self):
        self.bot = EnhancedBoxIM()
        self.web_ui = WebUI(self.bot)
        self.running = True
    
    async def start(self):
        """启动应用程序"""
        print("=" * 50)
        print("BoxIM ENLTbot - Web界面版")
        print("=" * 50)
        
        # 设置信号处理器
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # 启动Web界面
            web_task = asyncio.create_task(self.web_ui.start())
            
            # 启动机器人
            bot_task = asyncio.create_task(self.bot.robust_start())
            
            # 等待任务完成
            await asyncio.gather(web_task, bot_task)
            
        except KeyboardInterrupt:
            print("\n收到中断信号，正在关闭...")
        except Exception as e:
            print(f"应用程序异常: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """停止应用程序"""
        self.running = False
        
        print("正在停止机器人...")
        await self.bot.stop()
        
        print("正在停止Web界面...")
        await self.web_ui.stop()
        
        print("应用程序已停止")
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n收到信号 {signum}，正在关闭...")
        self.running = False
        # 创建异步任务来停止应用程序
        asyncio.create_task(self.stop())

async def main():
    """主函数"""
    app = Application()
    await app.start()

if __name__ == "__main__":
    # 检查Python版本
    if sys.version_info < (3, 7):
        print("需要Python 3.7或更高版本")
        sys.exit(1)
    
    # 运行主程序
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序异常退出: {e}")