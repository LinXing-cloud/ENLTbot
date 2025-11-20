import asyncio
import os
import sys
import logging

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(__file__))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BoxIM-Worker')

async def run_bot():
    """运行机器人主程序"""
    try:
        from main import main  # 导入主函数
        logger.info("启动BoxIM机器人...")
        await main()
    except Exception as e:
        logger.error(f"机器人运行失败: {e}")
        return False
    return True

async def main_worker():
    """主工作循环"""
    restart_delay = 30
    max_restart_delay = 300
    restart_count = 0
    
    while True:
        try:
            logger.info(f"尝试启动机器人 (重启次数: {restart_count})")
            success = await run_bot()
            
            if not success:
                restart_count += 1
                delay = min(restart_delay * (2 ** min(restart_count, 5)), max_restart_delay)
                logger.info(f"机器人停止，{delay}秒后重启...")
                await asyncio.sleep(delay)
            else:
                restart_count = 0
                logger.info("机器人正常退出")
                break
                
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出工作进程")
            break
        except Exception as e:
            logger.error(f"工作进程异常: {e}")
            restart_count += 1
            delay = min(restart_delay * (2 ** min(restart_count, 5)), max_restart_delay)
            logger.info(f"异常后 {delay}秒后重启...")
            await asyncio.sleep(delay)

if __name__ == "__main__":
    asyncio.run(main_worker())
