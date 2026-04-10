"""
一次性脚本：将 rental_system_prompt.py 中最新的模板同步到数据库。

运行方式：
    cd ai_kefu && python -m scripts.sync_prompt_to_db

会找到 DB 中 prompt_key='rental_system' 的活跃记录，用代码中最新模板覆盖其 content 字段。
"""
import sys
import argparse
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ai_kefu.prompts.rental_system_prompt import get_rental_system_prompt_template
from ai_kefu.storage.prompt_store import PromptStore
from ai_kefu.config.settings import settings


def main(auto_confirm: bool = False):
    store = PromptStore(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
    )

    # 1. 查找当前活跃的 rental_system prompt
    active = store.get_active("rental_system")
    if not active:
        print("❌ 数据库中没有找到 prompt_key='rental_system' 的活跃记录")
        print("   请先通过 API POST /prompts/init-defaults 初始化")
        return

    print(f"✅ 找到活跃 prompt: id={active.id}, title={active.title}")
    print(f"   更新时间: {active.updated_at}")
    print(f"   内容长度: {len(active.content)} 字符")

    # 2. 获取代码中最新的模板
    new_content = get_rental_system_prompt_template()
    print(f"\n📝 代码中最新模板长度: {len(new_content)} 字符")

    if active.content.strip() == new_content.strip():
        print("\n✅ 数据库内容与代码模板完全一致，无需更新")
        return

    # 3. 显示差异摘要
    old_lines = active.content.strip().splitlines()
    new_lines = new_content.strip().splitlines()
    print(f"\n📊 差异: 旧版 {len(old_lines)} 行 → 新版 {len(new_lines)} 行")

    # 4. 确认后更新
    if not auto_confirm:
        answer = input("\n⚠️  确认用代码中的最新模板覆盖数据库内容？(y/N): ").strip().lower()
        if answer != "y":
            print("已取消")
            return

    result = store.update(active.id, {"content": new_content})
    if result:
        print(f"\n✅ 更新成功！id={result.id}, 新内容长度={len(result.content)} 字符")
        print(f"   更新时间: {result.updated_at}")
        print("\n💡 提示: turn.py 有 5 分钟缓存 (_SYSTEM_PROMPT_CACHE_TTL=300)")
        print("   重启服务可立即生效，否则最多等 5 分钟")
    else:
        print("❌ 更新失败，请检查日志")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将代码中最新的 system prompt 模板同步到数据库")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接更新")
    args = parser.parse_args()
    main(auto_confirm=args.yes)
