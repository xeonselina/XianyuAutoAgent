"""
Pytest 配置文件
"""

import sys
import os

# 将项目根目录添加到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pytest


@pytest.fixture
def test_cookies():
    """测试用 Cookie 字符串"""
    return "unb=test_user; cookie2=test_cookie"


@pytest.fixture
def test_chat_id():
    """测试会话 ID"""
    return "chat_12345"


@pytest.fixture
def test_user_id():
    """测试用户 ID"""
    return "user_67890"


@pytest.fixture
def test_item_id():
    """测试商品 ID"""
    return "item_99999"
