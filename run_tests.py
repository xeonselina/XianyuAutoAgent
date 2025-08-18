#!/usr/bin/env python3
"""
库存管理系统测试运行脚本
"""

import unittest
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_all_tests():
    """运行所有测试"""
    print("🧪 开始运行库存管理系统单元测试...")
    print("=" * 60)
    
    # 发现并运行所有测试
    loader = unittest.TestLoader()
    start_dir = os.path.join(os.path.dirname(__file__), 'tests')
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出测试结果摘要
    print("\n" + "=" * 60)
    print("📊 测试结果摘要:")
    print(f"运行测试数量: {result.testsRun}")
    print(f"失败测试数量: {len(result.failures)}")
    print(f"错误测试数量: {len(result.errors)}")
    print(f"跳过测试数量: {len(result.skipped)}")
    
    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split('AssertionError:')[-1].strip()}")
    
    if result.errors:
        print("\n💥 错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split('Exception:')[-1].strip()}")
    
    # 返回退出码
    return 0 if result.wasSuccessful() else 1

def run_specific_test(test_name):
    """运行特定的测试"""
    print(f"🧪 运行特定测试: {test_name}")
    print("=" * 60)
    
    # 构建测试套件
    loader = unittest.TestLoader()
    
    if test_name == "inventory":
        from tests.test_inventory_manager import TestInventoryManager, TestInventoryManagerIntegration
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(TestInventoryManager))
        suite.addTests(loader.loadTestsFromTestCase(TestInventoryManagerIntegration))
    elif test_name == "tencent_docs":
        from tests.test_tencent_docs_api import TestTencentDocsAPI, TestTencentDocsInventoryManager
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(TestTencentDocsAPI))
        suite.addTests(loader.loadTestsFromTestCase(TestTencentDocsInventoryManager))
    else:
        print(f"❌ 未知的测试名称: {test_name}")
        print("可用的测试: inventory, tencent_docs")
        return 1
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1

def main():
    """主函数"""
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        return run_specific_test(test_name)
    else:
        return run_all_tests()

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
