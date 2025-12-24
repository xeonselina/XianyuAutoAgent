"""
Knowledge base initialization script.
T050 - Add sample knowledge entries to Chroma.
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.models.knowledge import KnowledgeEntry
from ai_kefu.llm.embeddings import generate_embedding
from ai_kefu.config.settings import settings


# Sample knowledge data
SAMPLE_KNOWLEDGE = [
    {
        "id": "kb_001",
        "title": "退款政策",
        "content": "用户在收到商品后7天内可申请无理由退款。退款流程：1. 在订单页面点击申请退款 2. 填写退款原因 3. 等待审核（通常1-3个工作日）4. 审核通过后原路退回。注意：商品需保持完好，不影响二次销售。",
        "category": "售后服务",
        "tags": ["退款", "售后", "政策"],
        "source": "官方文档",
        "priority": 10
    },
    {
        "id": "kb_002",
        "title": "发货时间",
        "content": "订单通常在付款后24小时内发货。节假日可能延迟1-2天。您可以在订单详情页查看物流信息和预计送达时间。如果超过3天未发货，请联系客服。",
        "category": "物流配送",
        "tags": ["发货", "物流", "配送"],
        "source": "官方文档",
        "priority": 8
    },
    {
        "id": "kb_003",
        "title": "会员积分规则",
        "content": "每消费1元可获得1积分。积分可用于兑换优惠券或商品。积分有效期为1年，到期自动清零。会员等级分为：普通会员、银卡会员（累计消费1000元）、金卡会员（累计消费5000元）、钻石会员（累计消费10000元）。",
        "category": "会员服务",
        "tags": ["会员", "积分", "等级"],
        "source": "官方文档",
        "priority": 6
    },
    {
        "id": "kb_004",
        "title": "商品质量问题处理",
        "content": "如果收到的商品存在质量问题（破损、瑕疵、功能异常等），请在收货后48小时内联系客服并提供照片证明。我们将提供以下解决方案：1. 免费退换货 2. 部分退款 3. 重新发货。质量问题导致的退换货运费由商家承担。",
        "category": "售后服务",
        "tags": ["质量", "退换货", "售后"],
        "source": "官方文档",
        "priority": 9
    },
    {
        "id": "kb_005",
        "title": "支付方式",
        "content": "我们支持以下支付方式：1. 微信支付 2. 支付宝 3. 银联卡支付 4. 信用卡支付（支持分期）。所有支付均采用加密传输，保证交易安全。支付成功后会立即收到确认短信。",
        "category": "支付相关",
        "tags": ["支付", "付款", "方式"],
        "source": "官方文档",
        "priority": 7
    },
    {
        "id": "kb_006",
        "title": "优惠券使用规则",
        "content": "优惠券使用规则：1. 每个订单限用一张优惠券 2. 优惠券不可叠加使用 3. 部分商品不参与优惠券活动 4. 优惠券有使用期限，过期自动作废 5. 优惠券不可兑换现金。使用时在结算页面选择可用优惠券即可。",
        "category": "优惠活动",
        "tags": ["优惠券", "折扣", "活动"],
        "source": "官方文档",
        "priority": 5
    }
]


def main():
    """Initialize knowledge base with sample data."""
    print("=" * 60)
    print("AI 客服知识库初始化")
    print("=" * 60)
    print()
    
    # Initialize knowledge store
    print(f"初始化知识库存储 (路径: {settings.chroma_persist_path})...")
    knowledge_store = KnowledgeStore()
    
    # Check existing entries
    existing_count = knowledge_store.count()
    print(f"当前知识库条目数: {existing_count}")
    print()
    
    # Add sample knowledge
    print(f"准备添加 {len(SAMPLE_KNOWLEDGE)} 条示例知识...")
    print()
    
    success_count = 0
    
    for item in SAMPLE_KNOWLEDGE:
        try:
            print(f"处理: {item['title']} ({item['category']})...")
            
            # Create knowledge entry
            entry = KnowledgeEntry(
                id=item["id"],
                title=item["title"],
                content=item["content"],
                category=item["category"],
                tags=item["tags"],
                source=item["source"],
                priority=item["priority"],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            # Generate embedding
            print(f"  生成向量嵌入...")
            embedding = generate_embedding(entry.content, task_type="retrieval_document")
            
            # Add to knowledge store
            print(f"  添加到知识库...")
            success = knowledge_store.add(entry, embedding)
            
            if success:
                print(f"  ✅ 成功添加: {item['title']}")
                success_count += 1
            else:
                print(f"  ❌ 添加失败: {item['title']}")
            
            print()
            
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            print()
    
    # Summary
    print("=" * 60)
    print(f"初始化完成！成功添加 {success_count}/{len(SAMPLE_KNOWLEDGE)} 条知识")
    print(f"知识库总条目数: {knowledge_store.count()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
