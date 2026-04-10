"""
租赁业务知识库初始化脚本
添加手机租赁相关的知识条目
"""

import os
import sys
from datetime import datetime
import pymysql

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
        "content": """手机租赁定价规则与价格表:

## 设备价格表

| 设备型号 | 首日租金 | 续租租金 |
|---------|---------|---------|
| X300Pro 加增距镜套装 | 168元/天 | 30元/天 |
| X200U 加增距镜套装 | 158元/天 | 30元/天 |

## 附件价格
| 附件名称 | 价格 |
|---------|------|
| 手机支架 | 20元/次 |
| 富图宝fy830演唱会三脚架 | 20元/天 |

## 快速报价（X300Pro）
- 1天使用：168元
- 2天使用：198元（168+30）
- 3天使用：228元（168+30×2）
- 4天使用：258元（168+30×3）
- 5天使用：288元（168+30×4）
- 7天使用：348元（168+30×6）
- 10天使用：438元（168+30×9）

## 快速报价（X200U）
- 1天使用：158元
- 2天使用：188元（158+30）
- 3天使用：218元（158+30×2）
- 4天使用：248元（158+30×3）
- 5天使用：278元（158+30×4）
- 7天使用：338元（158+30×6）
- 10天使用：428元（158+30×9）

## 计算公式
最终价格 = 首日租金 + 续租租金 × (使用天数 - 1)

## ⚠️ 使用天数计算规则（极重要）
收货日 ≠ 使用日，归还日（寄出日）≠ 使用日。收货当天在拆包，归还当天在寄快递，都不算使用。
公式：使用天数 = 归还日期 - 收货日期 - 1（至少1天）
等价理解：租赁开始日 = 收货日期 + 1天，租赁结束日 = 归还日期 - 1天

示例：
- 4.2收到，4.4寄出 → 实际使用4.3一天 → 使用天数=1天（不是2天！）
- 4.26收到，4.28寄出 → 实际使用4.27一天 → 使用天数=1天
- 5.10收到，5.15寄出 → 实际使用5.11~5.14 → 使用天数=4天（不是5天！）
- 5.1收到，5.5寄出 → 实际使用5.2~5.4 → 使用天数=3天

⚠️ 绝对禁止直接用「归还日 - 收货日」当使用天数！

## 客户类型折扣
- 新客户: 无折扣
- 老客户: 每单减10元

## 租期折扣
- 1-4天: 无折扣
- 5-9天: 9折
- 10天及以上: 85折

## 旺季加价
- 春节期间(1月15日-2月28日): 加价15%
- 五一劳动节(4月28日-5月5日): 加价15%
- 国庆节(9月28日-10月7日): 加价15%

注意: 折扣可叠加,先应用折扣再应用旺季加价。""",
        "category": "租赁定价",
        "tags": ["定价", "报价", "折扣", "旺季", "价格", "价格表"],
        "source": "租赁业务规则",
        "priority": 10
    },
    {
        "id": "rental_002",
        "title": "免押金条件",
        "content": """手机租赁免押金条件:

符合以下任一条件可申请免押金:

1. 花呗支付
   - 支付时选择花呗支付即可直接免押，无需提交任何材料

2. 芝麻信用分 ≥ 550分
   - 需提供支付宝芝麻信用截图
   - 需要提供身份证（需要姓名和身份证号，其他可以打码）

3. 老客户直接免押

不符合免押条件的客户需支付押金:
- vivo x300p 加增距镜套装: 押金3000元
- vivo x200u 加增距镜套装: 押金3000元

押金在设备归还并验收通过后24小时内原路退回。""",
        "category": "押金政策",
        "tags": ["押金", "免押", "芝麻信用" ],
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
   - 收货地址(至少包含省)
   - 设备型号(根据当前正在看的设备型号)

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
   - 不得私自拆机维修

2. 正常使用磨损:
   - 正常使用产生的轻微划痕、磨损属于合理范围
   - 不影响设备功能和外观的轻微磨损无需赔偿

3. 需要赔偿的情况:
   - 屏幕碎裂、机身严重变形
   - 进水导致功能损坏
   - 摄像头、按键等部件损坏
   - 设备丢失或被盗

4. 赔偿标准:
   - 设备丢失: 按市场价赔偿
   - 其他损坏: 按官方维修发票价赔偿

""",
        "category": "使用须知",
        "tags": ["使用", "注意事项", "赔偿", "保护"],
        "source": "租赁业务规则",
        "priority": 8
    },
    {
        "id": "rental_005",
        "title": "激光免责说明",
        "content": """关于设备激光打到的说明:

部分演唱会会有激光灯光效果，激光打到设备会造成损坏。
激光打到是免责的
但会影响到你接下来的拍摄，请注意避开激光使用

""",
        "category": "使用须知",
        "tags": ["激光",  "免责"],
        "source": "租赁业务规则",
        "priority": 7
    },
    {
        "id": "rental_006",
        "title": "设备磕碰划痕处理",
        "content": """设备磕碰和划痕的处理规则:

1. 正常使用磨损(不收费):
   - 边框轻微氧化、褪色
   - 背面细微划痕
   - 按键正常磨损
   - 充电口正常插拔痕迹

2. 严重损坏(需维修或赔偿):
   - 屏幕碎裂
   - 背面玻璃碎裂
   - 边框严重变形影响使用
   - 镜头摔坏导致无法安装，镜片碎裂
   - 进水或功能性损坏

3. 避免收费建议:
   - 不要摘除手机壳
   - 放置时避免硬物接触

4. 争议处理:
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
- 发货地: 广东深圳南山区西丽街道松坪村竹苑9栋4单元415
- 物流方式: 顺丰标快
- 包装: 专业防震包装

配送时效(从深圳发货):
- 广东省内，华南: 1天送达
- 华东主要城市: 2天送达
- 华北、华中、西南: 3天送达
- 东北、西北: 4天送达
- 新疆: 6天送达
- 西藏: 7天送达

收货注意事项:
1. 收货时当场验货
2. 检查外包装是否完好
3. 检查设备外观和功能
4. 如有问题当场拍照联系客服

归还物流:
- 用户自行寄回深圳
- 建议使用顺丰快递
- 运费由用户承担(约15元)
- 不需要保价
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
    },
    {
        "id": "rental_008",
        "title": "议价与优惠策略",
        "content": """手机租赁议价与优惠策略:

1. 价格优惠规则:
   - 老客户优惠: 每单减10元
   - 租期折扣: 5-9天9折，10天以上85折
   - 多台租赁: 2台以上每台减20元
   - 折扣可叠加

2. 议价应对策略:
   - 用户要求便宜/打折: 先计算实际价格，告知已有的折扣优惠
   - 用户说"别人更便宜": 强调设备质量和服务保障，可以说"我们的设备都是原装正品，质量有保障"
   - 用户砍价幅度不大(10-20元): 可以建议"租期长一点折扣更多哦"
   - 用户砍价幅度大: 说"价格已经很优惠了，你可以看下我们的评价"
   - 用户说"太贵了不租了": 不要勉强，说"好的 你再考虑下，有需要随时找我"

3. 不能做的:
   - 不能自行承诺低于系统计算价格的报价
   - 不能编造不存在的优惠活动
   - 不确定的优惠需转人工确认""",
        "category": "议价策略",
        "tags": ["议价", "砍价", "优惠", "折扣", "价格"],
        "source": "租赁业务规则",
        "priority": 9
    },
    {
        "id": "rental_009",
        "title": "已下单后处理流程",
        "content": """用户下单后的处理流程:

1. 确认订单信息:
   - 确认收货地址（精确到门牌号）
   - 确认收件人姓名和电话
   - 确认租赁日期

2. 发货通知:
   - 告知预计发货时间（通常下单当天或次日）
   - 发货后提供顺丰快递单号
   - 告知预计到达时间

3. 收货指引:
   - 收到后检查设备外观和功能
   - 拍照留证（正面、背面、各角度）
   - 有问题24小时内联系

4. 归还提醒:
   - 归还日期前1天提醒
   - 告知归还地址: 广东深圳南山区西丽街道松坪村竹苑9栋4单元415
   - 用顺丰寄回，运费约15元
   - 寄出后提供快递单号

5. 常见问题:
   - 用户问"发了吗": 帮查物流状态
   - 用户问"单号多少": 提供快递单号
   - 用户说"地址写错了": 如未发货可修改，已发货需联系快递改地址""",
        "category": "下单流程",
        "tags": ["下单", "发货", "收货", "归还", "订单"],
        "source": "租赁业务规则",
        "priority": 8
    },
    {
        "id": "rental_010",
        "title": "演唱会场景FAQ",
        "content": """演唱会手机租赁常见问题:

1. 提前几天收货:
   - 建议演唱会前1-2天收到，提前熟悉设备
   - 如果距离远（如新疆西藏），需要提前更多天

2. 设备配件说明:
   - X300Pro套装包含: 手机+增距镜+手机壳+充电线+充电头
   - X200U套装包含: 手机+增距镜+手机壳+充电线+充电头
   - 可选配件: 手机支架(20元/次)、富图宝fy830演唱会三脚架(20元/天)

3. 演唱会注意事项:
   - 注意避开激光区域（激光免责但影响拍摄）
   - 建议全程使用手机壳
   - 手机电量建议提前充满
   - 增距镜使用: 对准摄像头安装，可获得约2倍光学变焦

4. 拍摄建议:
   - 提前找好角度和位置
   - 开启防抖功能
   - 建议用4K录像

5. 多人拼租:
   - 同行多人可以一起租，2台以上每台优惠20元
   - 可以一个地址统一收发""",
        "category": "演唱会FAQ",
        "tags": ["演唱会", "配件", "拍摄", "FAQ"],
        "source": "租赁业务规则",
        "priority": 8
    },
    {
        "id": "rental_011",
        "title": "缺货替代方案模板",
        "content": """当用户咨询时间段无货时，优先给替代方案，不要直接终止对话。

建议话术模板：
1. 同型号相邻日期: "这个档期有点紧，我帮你看前后1-2天可以吗？"
2. 替代机型: "这款紧张，X200U同档期还有，你要我按这个给你算价吗？"
3. 保留意向: "你先拍下不付款，我盯到有档期第一时间给你改价安排。"

禁忌：
- 不要只说"没货了"就结束
- 不要编造有货/无货，必须以 check_availability 结果为准""",
        "category": "转化策略",
        "tags": ["缺货", "替代方案", "转化", "话术"],
        "source": "租赁业务规则",
        "priority": 9
    }
]


def check_api_key():
    """检查 API Key 配置"""
    print("检查通义千问 API Key...")
    
    if not settings.api_key or settings.api_key == "your_api_key_here":
        print("❌ API Key 未设置或使用默认占位符")
        print()
        print("请按以下步骤配置:")
        print("1. 访问 https://dashscope.console.aliyun.com/")
        print("2. 登录阿里云账号")
        print("3. 创建 API Key")
        print("4. 编辑 .env 文件:")
        print("   API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        return False
    
    print(f"✅ API Key 已配置: {settings.api_key[:10]}...{settings.api_key[-4:]}")
    return True


def check_and_create_database():
    """检查并创建 MySQL 数据库和表"""
    print("检查 MySQL 数据库...")
    
    try:
        # 尝试连接到 MySQL（不指定数据库）
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            charset='utf8mb4'
        )
        
        cursor = connection.cursor()
        
        # 检查数据库是否存在
        cursor.execute("SHOW DATABASES LIKE %s", (settings.mysql_database,))
        result = cursor.fetchone()
        
        if result:
            print(f"✅ 数据库 '{settings.mysql_database}' 已存在")
        else:
            print(f"⚠️  数据库 '{settings.mysql_database}' 不存在，正在创建...")
            cursor.execute(f"CREATE DATABASE {settings.mysql_database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"✅ 成功创建数据库 '{settings.mysql_database}'")
        
        cursor.close()
        connection.close()
        
        # 连接到指定的数据库
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset='utf8mb4'
        )
        
        cursor = connection.cursor()
        
        # 检查 knowledge_entries 表是否存在
        print("检查数据库表...")
        cursor.execute("SHOW TABLES LIKE 'knowledge_entries'")
        result = cursor.fetchone()
        
        if result:
            print("✅ 表 'knowledge_entries' 已存在")
        else:
            print("⚠️  表 'knowledge_entries' 不存在，正在创建...")
            
            # 创建表的 SQL 语句
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
                kb_id VARCHAR(50) NOT NULL UNIQUE COMMENT 'Stable knowledge base ID (e.g., kb_001)',

                -- Content
                title VARCHAR(500) NOT NULL COMMENT 'Knowledge entry title',
                content TEXT NOT NULL COMMENT 'Full knowledge content',

                -- Classification
                category VARCHAR(100) DEFAULT NULL COMMENT 'Category tag',
                tags JSON DEFAULT NULL COMMENT 'Array of tag strings',

                -- Metadata
                source VARCHAR(200) DEFAULT NULL COMMENT 'Source of knowledge (e.g., Official Documentation)',
                priority INT DEFAULT 0 COMMENT 'Priority for sorting (0-100)',
                active BOOLEAN DEFAULT TRUE COMMENT 'Is entry active',

                -- Audit trail
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',

                -- Indexes for performance
                INDEX idx_kb_id (kb_id),
                INDEX idx_category (category),
                INDEX idx_active (active),
                INDEX idx_priority (priority),
                INDEX idx_created_at (created_at),
                FULLTEXT INDEX idx_content_search (title, content)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Knowledge base entries - MySQL source of truth for ChromaDB vector search'
            """
            
            cursor.execute(create_table_sql)
            print("✅ 成功创建表 'knowledge_entries'")
        
        cursor.close()
        connection.close()
        return True
        
    except pymysql.MySQLError as e:
        print(f"❌ MySQL 错误: {e}")
        print("提示: 请确保 MySQL 服务已启动，并且 .env 文件中的数据库配置正确")
        return False
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        print("提示: 请检查 .env 文件中的数据库配置")
        return False


def main():
    """Initialize rental knowledge base."""
    print("=" * 60)
    print("手机租赁业务知识库初始化")
    print("=" * 60)
    print()
    
    # Check API Key first
    if not check_api_key():
        print()
        print("❌ API Key 检查失败，无法继续初始化")
        print("提示: 向量嵌入需要调用通义千问 API")
        return
    print()
    
    # Check and create database if needed
    if not check_and_create_database():
        print()
        print("❌ 数据库检查失败，无法继续初始化")
        return
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
            try:
                embedding = generate_embedding(entry.content, task_type="retrieval_document")
            except Exception as embed_error:
                print(f"  ❌ 向量嵌入生成失败: {embed_error}")
                print(f"  提示: 请检查 API Key 是否有效，或网络是否正常")
                print()
                continue
            
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
            import traceback
            traceback.print_exc()
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
