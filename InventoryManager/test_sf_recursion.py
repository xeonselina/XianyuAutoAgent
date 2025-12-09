#!/usr/bin/env python3
"""
测试顺丰 SDK 递归问题
"""

import sys
import logging

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 设置递归限制以便快速发现问题
sys.setrecursionlimit(1000)

print("开始测试...")
print(f"递归限制: {sys.getrecursionlimit()}")

try:
    from app.utils.sf.sf_sdk_wrapper import SFExpressSDK

    print("创建 SDK 实例...")
    sdk = SFExpressSDK(
        partner_id='test_partner_id',
        checkword='test_checkword',
        test_mode=True,
        use_oauth=True
    )

    print("调用 create_order...")
    result = sdk.create_order({'orderId': 'TEST_001'})

    print(f"结果: {result}")

except RecursionError as e:
    print("\n=== 递归错误! ===")
    import traceback
    traceback.print_exc(limit=50)

except Exception as e:
    print(f"\n=== 其他错误: {type(e).__name__} ===")
    print(f"消息: {e}")
    import traceback
    traceback.print_exc()
