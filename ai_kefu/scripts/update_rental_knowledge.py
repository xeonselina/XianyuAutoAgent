"""
更新租赁业务知识库中的使用天数计算规则。
修正 rental_001 (定价规则) 和 rental_003 (流程说明) 中的公式。
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.config.settings import settings


def main():
    """Update rental knowledge entries with corrected day calculation formula."""
    print("=" * 60)
    print("更新租赁知识库 - 修正使用天数计算规则")
    print("=" * 60)
    print()

    # Initialize knowledge store
    print(f"连接知识库 (MySQL + ChromaDB)...")
    knowledge_store = KnowledgeStore()
    print(f"✅ 连接成功，当前条目数: {knowledge_store.count()}")
    print()

    # ---- 更新 rental_001: 租赁定价规则 ----
    print("=" * 40)
    print("更新 rental_001: 租赁定价规则")
    print("=" * 40)

    entry_001 = knowledge_store.get("rental_001")
    if not entry_001:
        print("❌ 未找到 rental_001，跳过")
    else:
        print(f"  找到条目: {entry_001.title}")

        # 检查是否包含旧的错误公式
        if "归还日期 - 收货日期 - 2" in entry_001.content or "归还日期 - 收货日期 - 1天（去程物流）" in entry_001.content:
            print("  ⚠️  发现旧的错误公式，正在更新...")

            # 替换错误内容
            new_content = entry_001.content

            # 替换旧公式段落
            old_formula = """## 计算公式
最终价格 = 首日租金 + 续租租金 × (使用天数 - 1)
使用天数 = 归还日期 - 收货日期 - 1天（去程物流）- 1天（回程物流）

简化计算：使用天数 ≈ 归还日期 - 收货日期 - 2"""

            new_formula = """## 计算公式
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

⚠️ 绝对禁止直接用「归还日 - 收货日」当使用天数！"""

            if old_formula in new_content:
                new_content = new_content.replace(old_formula, new_formula)
            else:
                # 尝试更宽松的替换
                print("  尝试宽松匹配...")
                # 按关键特征替换
                if "简化计算：使用天数 ≈ 归还日期 - 收货日期 - 2" in new_content:
                    # 找到旧公式部分并整体替换
                    lines = new_content.split('\n')
                    new_lines = []
                    skip = False
                    for line in lines:
                        if '使用天数 = 归还日期 - 收货日期 - 1天' in line:
                            skip = True
                            continue
                        if skip and '简化计算' in line:
                            skip = False
                            # 插入新公式
                            new_lines.append("")
                            new_lines.append("## ⚠️ 使用天数计算规则（极重要）")
                            new_lines.append("收货日 ≠ 使用日，归还日（寄出日）≠ 使用日。收货当天在拆包，归还当天在寄快递，都不算使用。")
                            new_lines.append("公式：使用天数 = 归还日期 - 收货日期 - 1（至少1天）")
                            new_lines.append("等价理解：租赁开始日 = 收货日期 + 1天，租赁结束日 = 归还日期 - 1天")
                            new_lines.append("")
                            new_lines.append("示例：")
                            new_lines.append("- 4.2收到，4.4寄出 → 实际使用4.3一天 → 使用天数=1天（不是2天！）")
                            new_lines.append("- 4.26收到，4.28寄出 → 实际使用4.27一天 → 使用天数=1天")
                            new_lines.append("- 5.10收到，5.15寄出 → 实际使用5.11~5.14 → 使用天数=4天（不是5天！）")
                            new_lines.append("- 5.1收到，5.5寄出 → 实际使用5.2~5.4 → 使用天数=3天")
                            new_lines.append("")
                            new_lines.append("⚠️ 绝对禁止直接用「归还日 - 收货日」当使用天数！")
                            continue
                        if not skip:
                            new_lines.append(line)
                    new_content = '\n'.join(new_lines)

            entry_001.content = new_content
            entry_001.updated_at = datetime.utcnow()
            success = knowledge_store.update(entry_001)
            if success:
                print("  ✅ rental_001 已更新到数据库（MySQL + ChromaDB）")
            else:
                print("  ❌ rental_001 更新失败")
        else:
            print("  ℹ️  公式已是最新版本，无需更新")

    print()

    # ---- 更新 rental_003: 租赁流程说明 ----
    print("=" * 40)
    print("更新 rental_003: 租赁流程说明")
    print("=" * 40)

    entry_003 = knowledge_store.get("rental_003")
    if not entry_003:
        print("❌ 未找到 rental_003，跳过")
    else:
        print(f"  找到条目: {entry_003.title}")

        old_text = "查询档期: 开始日期=收货日期+1天, 结束日期=归还日期-1天"
        new_text = "查询档期: 开始日期=收货日期+1天, 结束日期=归还日期-1天（使用天数=归还日期-收货日期-1）"

        if old_text in entry_003.content and new_text not in entry_003.content:
            print("  ⚠️  发现需要补充的说明，正在更新...")
            entry_003.content = entry_003.content.replace(old_text, new_text)
            entry_003.updated_at = datetime.utcnow()
            success = knowledge_store.update(entry_003)
            if success:
                print("  ✅ rental_003 已更新到数据库（MySQL + ChromaDB）")
            else:
                print("  ❌ rental_003 更新失败")
        else:
            print("  ℹ️  内容已是最新版本，无需更新")

    print()
    print("=" * 60)
    print("更新完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
