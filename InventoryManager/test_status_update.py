#!/usr/bin/env python3
"""
测试设备状态更新逻辑
"""

import sys
import os
from datetime import datetime, date, timedelta

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.services.device_status_service import DeviceStatusService
from app.models.device import Device
from app.models.rental import Rental


def test_status_update():
    """测试状态更新逻辑"""
    try:
        app = create_app()
        with app.app_context():
            print("=== 设备状态更新测试 ===")
            
            # 获取当前设备状态统计
            print("\n1. 当前设备状态统计:")
            summary = DeviceStatusService.get_device_status_summary()
            for status, count in summary.items():
                print(f"   {status}: {count}")
            
            # 测试强制更新指定设备状态
            print("\n2. 测试强制更新设备状态:")
            devices = Device.query.limit(3).all()
            for device in devices:
                success, message = DeviceStatusService.force_update_device_status(device.id)
                print(f"   设备 {device.name} (ID: {device.id}): {message}")
            
            # 获取更新后的状态统计
            print("\n3. 更新后的设备状态统计:")
            summary_after = DeviceStatusService.get_device_status_summary()
            for status, count in summary_after.items():
                print(f"   {status}: {count}")
            
            # 测试状态计算逻辑
            print("\n4. 测试状态计算逻辑:")
            today = date.today()
            for device in devices:
                calculated_status = DeviceStatusService._calculate_device_status(device, today)
                print(f"   设备 {device.name}: 当前状态={device.status}, 计算状态={calculated_status}")
            
            print("\n=== 测试完成 ===")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_status_update()
