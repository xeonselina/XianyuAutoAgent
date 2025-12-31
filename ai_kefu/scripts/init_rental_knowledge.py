"""
租赁业务知识库初始化脚本
添加手机租赁相关的知识条目
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


# 租赁业务知识数据
RENTAL_KNOWLEDGE = [
    {
        "id": "rental_001",
        "title": "租赁定价规则",
        "content": """手机租赁定价规则:

1. 基础价格: 每个设备型号有基础日租金,从档期系统获取

2. 客户类型折扣:
   - 新客户: 无折扣
   - 老客户: 享受95折优惠

3. 租期折扣:
   - 7-14天: 95折
   - 15-29天: 9折
   - 30天及以上: 85折

4. 旺季加价:
   - 春节期间(1月15日-2月28日): 加价15%
   - 五一劳动节(4月28日-5月5日): 加价15%
   - 国庆节(9月28日-10月7日): 加价15%

5. 价格计算公式:
   最终价格 = 基础日租金 × 天数 × (1 - 客户折扣 - 租期折扣) × (1 + 旺季加价)

注意: 折扣可叠加,先应用折扣再应用旺季加价。""",
        "category": "租赁定价",
        "tags": ["定价", "报价", "折扣", "旺季"],
        "source": "租赁业务规则",
        "priority": 10
    },
    {
        "id": "rental_002",
        "title": "免押金条件",
        "content": """手机租赁免押金条件:

符合以下任一条件可申请免押金:

1. 芝麻信用分 ≥ 650分
   - 需提供支付宝授权查询
   - 实时审核,当场出结果

2. 老客户且历史租赁记录良好
   - 租赁次数 ≥ 3次
   - 无延迟归还记录
   - 无设备损坏记录

3. 企业客户
   - 提供营业执照
   - 签订合作协议
   - 批量租赁(≥5台)

4. 信用卡预授权
   - 使用信用卡担保
   - 冻结押金额度
   - 归还后自动解冻

不符合免押条件的客户需支付押金:
- iPhone 15系列: 押金3000元
- iPhone 14系列: 押金2500元
- iPhone 13系列: 押金2000元

押金在设备归还并验收通过后3个工作日内原路退回。""",
        "category": "押金政策",
        "tags": ["押金", "免押", "芝麻信用", "信用卡"],
        "source": "租赁业务规则",
        "priority": 9
    },
    {
        "id": "rental_003",
        "title": "租赁流程说明",
        "content": """手机租赁完整流程:

1. 信息收集阶段:
   - 收货日期(用户希望什么时候收到设备)
   - 归还日期(用户什么时候寄回设备)
   - 收货地址(至少包含省市)
   - 设备型号偏好(可选)

2. 档期查询:
   - 根据收货地址计算物流时间
   - 查询档期: 开始日期=收货日期+1天, 结束日期=归还日期-1天
   - 确认是否有可租设备

3. 报价确认:
   - 根据租期、客户类型、季节计算价格
   - 向用户报价并说明优惠信息

4. 押金处理:
   - 询问是否需要免押(满足条件)
   - 不符合免押条件需支付押金

5. 下单发货:
   - 用户确认后下单
   - 从深圳发顺丰标快
   - 提供物流单号

6. 归还验收:
   - 用户按约定日期归还
   - 验收设备状态
   - 无问题退还押金(如有)

注意: 租赁期间设备损坏需按定损标准赔偿。""",
        "category": "租赁流程",
        "tags": ["流程", "租赁", "步骤"],
        "source": "租赁业务规则",
        "priority": 10
    },
    {
        "id": "rental_004",
        "title": "设备使用注意事项",
        "content": """手机租赁使用注意事项:

1. 设备保管:
   - 妥善保管设备,避免丢失或被盗
   - 建议购买碎屏险或意外险
   - 不得私自拆机维修

2. 正常使用磨损:
   - 正常使用产生的轻微划痕、磨损属于合理范围
   - 不影响设备功能和外观的轻微磨损不收费

3. 需要赔偿的情况:
   - 屏幕碎裂、机身严重变形
   - 进水导致功能损坏
   - 摄像头、按键等部件损坏
   - 设备丢失或被盗

4. 赔偿标准:
   - 屏幕碎裂: 500-1500元(根据型号)
   - 功能性损坏: 按维修实际费用
   - 设备丢失: 按市场价80%赔偿
   - 无法修复: 按折旧后价值赔偿

5. 使用建议:
   - 使用手机壳和钢化膜保护
   - 避免在潮湿环境使用
   - 不要安装越狱/ROOT程序
   - 定期备份重要数据

归还前请:
   - 退出所有个人账号(iCloud/Apple ID等)
   - 删除个人数据
   - 恢复出厂设置""",
        "category": "使用须知",
        "tags": ["使用", "注意事项", "赔偿", "保护"],
        "source": "租赁业务规则",
        "priority": 8
    },
    {
        "id": "rental_005",
        "title": "激光雕刻免责说明",
        "content": """关于设备激光雕刻的说明:

部分租赁设备背面可能有激光雕刻标识,说明:

1. 雕刻位置:
   - 通常在设备背面下方
   - 字体很小,不影响外观
   - 雕刻内容为设备编号或标识

2. 雕刻目的:
   - 防止设备丢失
   - 便于设备管理
   - 防止串货

3. 用户权益:
   - 雕刻不影响设备功能
   - 不影响正常使用
   - 使用手机壳可完全遮盖
   - 不影响拍照等功能

4. 免责条款:
   - 租赁即表示接受设备可能存在激光雕刻
   - 雕刻不作为减免租金的理由
   - 不接受因雕刻要求退租/换机

如果介意激光雕刻,建议:
   - 租赁前询问具体设备是否有雕刻
   - 使用手机壳遮盖雕刻位置
   - 选择其他没有雕刻的设备型号

注意: 所有租赁设备均为正品行货,激光雕刻仅为管理需要。""",
        "category": "使用须知",
        "tags": ["激光", "雕刻", "外观", "免责"],
        "source": "租赁业务规则",
        "priority": 7
    },
    {
        "id": "rental_006",
        "title": "设备磕碰划痕处理",
        "content": """设备磕碰和划痕的处理规则:

1. 正常使用磨损(不收费):
   - 边框轻微氧化、褪色
   - 背面细微划痕(需贴膜不可见)
   - 按键正常磨损
   - 充电口正常插拔痕迹

2. 轻度磕碰(酌情收费50-200元):
   - 边框轻微磕碰掉漆
   - 背面玻璃可见划痕
   - 摄像头外圈划痕
   - 不影响功能的外观瑕疵

3. 中度损坏(收费300-800元):
   - 边框明显变形
   - 背面玻璃多处划痕
   - 屏幕有划痕但不影响显示
   - 摄像头有划痕影响拍照

4. 严重损坏(需维修或赔偿):
   - 屏幕碎裂
   - 背面玻璃碎裂
   - 边框严重变形影响使用
   - 进水或功能性损坏

5. 避免收费建议:
   - 租赁时选择带手机壳和钢化膜
   - 日常使用注意保护
   - 放置时避免硬物接触
   - 归还前检查外观

6. 争议处理:
   - 租赁时会拍摄设备状态照片
   - 归还时对比验收
   - 如有争议以租赁时照片为准
   - 可申请第三方鉴定

注意: 建议租赁时拍照留证,归还时减少纠纷。正常使用磨损我们不会收费,请放心使用。""",
        "category": "使用须知",
        "tags": ["磕碰", "划痕", "损坏", "赔偿", "外观"],
        "source": "租赁业务规则",
        "priority": 8
    },
    {
        "id": "rental_007",
        "title": "物流配送说明",
        "content": """手机租赁物流配送说明:

发货信息:
- 发货地: 广东深圳
- 物流方式: 顺丰标快
- 包装: 专业防震包装

配送时效(从深圳发货):
- 广东省内: 1天送达
- 华南、华东主要城市: 2天送达
- 华北、华中、西南: 3天送达
- 东北、西北: 4天送达
- 新疆: 6天送达
- 西藏: 7天送达

收货注意事项:
1. 收货时当场验货
2. 检查外包装是否完好
3. 检查设备外观和功能
4. 如有问题当场拍照联系客服
5. 签收即表示设备完好

归还物流:
- 用户自行寄回深圳
- 建议使用顺丰快递
- 运费由用户承担(约15-30元)
- 务必保价并妥善包装
- 提供快递单号以便追踪

物流费用:
- 发货物流费: 由我方承担
- 归还物流费: 由客户承担
- 特殊情况(设备问题): 往返运费由我方承担

注意: 
- 请在约定日期前寄回,避免延期
- 归还时务必恢复出厂设置
- 建议购买物流保价""",
        "category": "物流配送",
        "tags": ["物流", "配送", "快递", "时效"],
        "source": "租赁业务规则",
        "priority": 7
    }
]


def main():
    """Initialize rental knowledge base."""
    print("=" * 60)
    print("手机租赁业务知识库初始化")
    print("=" * 60)
    print()
    
    # Initialize knowledge store
    print(f"初始化知识库存储 (路径: {settings.chroma_persist_path})...")
    knowledge_store = KnowledgeStore()
    
    # Check existing entries
    existing_count = knowledge_store.count()
    print(f"当前知识库条目数: {existing_count}")
    print()
    
    # Add rental knowledge
    print(f"准备添加 {len(RENTAL_KNOWLEDGE)} 条租赁业务知识...")
    print()
    
    success_count = 0
    
    for item in RENTAL_KNOWLEDGE:
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
    print(f"初始化完成！成功添加 {success_count}/{len(RENTAL_KNOWLEDGE)} 条知识")
    print(f"知识库总条目数: {knowledge_store.count()}")
    print("=" * 60)
    print()
    print("提示: 运行以下命令测试知识库:")
    print("  python -c \"from ai_kefu.tools.knowledge_search import knowledge_search; print(knowledge_search('租赁定价规则'))\"")
    print()


if __name__ == "__main__":
    main()
