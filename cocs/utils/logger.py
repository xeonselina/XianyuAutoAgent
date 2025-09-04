from loguru import logger
import sys
import os
from datetime import datetime


def setup_logger(log_level: str = "INFO", log_file: str = None):
    """设置日志配置"""
    
    # 移除默认的logger
    logger.remove()
    
    # 控制台输出格式
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    
    # 添加控制台输出
    logger.add(
        sys.stdout,
        format=console_format,
        level=log_level,
        colorize=True,
        backtrace=True,
        diagnose=True
    )
    
    # 添加文件输出
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        )
        
        logger.add(
            log_file,
            format=file_format,
            level=log_level,
            rotation="10 MB",  # 日志文件大小限制
            retention="30 days",  # 保留天数
            compression="zip",  # 压缩旧日志
            backtrace=True,
            diagnose=True,
            enqueue=True  # 异步写入
        )
    
    logger.info(f"日志系统初始化完成 - 级别: {log_level}")
    
    return logger


def get_logger(name: str = None):
    """获取logger实例"""
    if name:
        return logger.bind(name=name)
    return logger