#!/usr/bin/env python3
"""
测试定时任务应用上下文修复
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.utils.scheduler import init_scheduler, run_task_now, get_scheduler_status, stop_scheduler
import time

def test_scheduler_context():
    """测试调度器的Flask应用上下文"""
    print("创建Flask应用...")
    app = create_app()
    
    print("初始化调度器...")
    init_scheduler(app)
    
    print("获取调度器状态...")
    status = get_scheduler_status()
    print(f"调度器状态: {status}")
    
    print("测试立即执行设备状态更新任务...")
    try:
        result = run_task_now("update_device_status")
        if result:
            print("✓ 设备状态更新任务执行成功")
        else:
            print("✗ 设备状态更新任务执行失败")
    except Exception as e:
        print(f"✗ 设备状态更新任务执行异常: {e}")
    
    print("测试立即执行快递状态更新任务...")
    try:
        result = run_task_now("update_tracking")
        if result:
            print("✓ 快递状态更新任务执行成功")
        else:
            print("✗ 快递状态更新任务执行失败")
    except Exception as e:
        print(f"✗ 快递状态更新任务执行异常: {e}")
    
    print("等待5秒查看后台定时任务...")
    time.sleep(5)
    
    print("停止调度器...")
    stop_scheduler()
    
    print("测试完成！")

if __name__ == "__main__":
    test_scheduler_context()