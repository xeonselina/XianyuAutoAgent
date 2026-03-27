"""
测试通义千问 API 连接
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import dashscope
from dashscope import TextEmbedding
from ai_kefu.config.settings import settings


def test_api_key():
    """测试 API Key 是否有效"""
    print("=" * 60)
    print("测试通义千问 API")
    print("=" * 60)
    print()
    
    print(f"API Key: {settings.api_key[:10]}...{settings.api_key[-4:]}")
    print(f"API 地址: {settings.model_base_url}")
    print()
    
    # 设置 API Key
    dashscope.api_key = settings.api_key
    
    print("正在测试向量嵌入 API...")
    try:
        response = TextEmbedding.call(
            model="text-embedding-v3",
            input="测试文本",
            dimension=1024
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response}")
        
        if response.status_code == 200:
            print()
            print("✅ API 调用成功！")
            print(f"向量维度: {len(response.output['embeddings'][0]['embedding'])}")
            return True
        else:
            print()
            print(f"❌ API 调用失败")
            print(f"错误信息: {response.message}")
            print(f"错误代码: {response.code}")
            return False
            
    except Exception as e:
        print()
        print(f"❌ API 调用异常: {e}")
        print()
        print("可能的原因:")
        print("1. API Key 无效或已过期")
        print("2. 账户余额不足")
        print("3. 网络连接问题")
        print("4. API 端点配置错误")
        print()
        print("请访问 https://dashscope.console.aliyun.com/ 检查:")
        print("- API Key 是否正确")
        print("- 账户是否有可用额度")
        print("- API 是否已开通 text-embedding-v3 服务")
        return False


if __name__ == "__main__":
    success = test_api_key()
    sys.exit(0 if success else 1)
