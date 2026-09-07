"""文档治理守卫。

历史教训：本项目曾累积 69 份根级 md/txt（715KB），其中大量是「某次 AI 任务干完了」
的过程报告——8 份 71KB 只为记录 3 行代码的修复。它们会在每次全仓检索时被大量召回，
抬高 AI 协作成本，并在与代码漂移后主动误导（README 曾描述一套根本不存在的 make target）。

本文件的断言就是防复发机制。它比 .gitignore 更有效：gitignore 既拦不住 AI 创建文件，
也拦不住 AI 检索。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 根级允许存在的 md / txt（含本文件列举的守卫本身）
ALLOWED_ROOT_MD = {"README.md", "AGENTS.md", "CLAUDE.md", "DEPLOY.md"}
ALLOWED_ROOT_TXT = {"requirements.txt", "requirements-dev.txt"}

# 过程性文档的命名特征。注意用 _ 前缀匹配，避免误伤 docs/INDEX.md 这类正常文件。
FORBIDDEN_STEM = re.compile(
    r"(_SUMMARY|_COMPLETE|_REPORT|_FIX|_ANALYSIS|_INDEX|"
    r"^QUICK_|^PHASE_|^ALL_DONE|^READY_TO|交付|总结)",
    re.IGNORECASE,
)


def _live_doc_paths():
    """当前维护中的文档（不含 docs/archive/）。"""
    paths = [ROOT / name for name in sorted(ALLOWED_ROOT_MD)]
    for base in (ROOT / "docs", ROOT / "openspec"):
        if base.exists():
            paths.extend(
                path for path in base.rglob("*.md")
                if "archive" not in path.parts and "node_modules" not in path.parts
            )
    return [path for path in paths if path.exists()]


def test_root_markdown_footprint_is_bounded():
    assert {p.name for p in ROOT.glob("*.md")} == ALLOWED_ROOT_MD
    assert {p.name for p in ROOT.glob("*.txt")} == ALLOWED_ROOT_TXT


def test_no_process_report_outside_archive():
    offenders = [
        str(path.relative_to(ROOT))
        for path in _live_doc_paths()
        if FORBIDDEN_STEM.search(path.stem)
    ]
    assert offenders == [], f"archive 之外出现过程性文档：{offenders}"


def test_live_doc_scope_is_not_empty():
    """守卫自身：扫描范围不能退化为空，否则上面两条会变成永远通过的空断言。"""
    paths = _live_doc_paths()
    assert len(paths) > 10, f"活文档扫描范围异常偏小：{len(paths)}"


def test_docs_only_reference_real_make_targets():
    """README 曾描述一套完全不存在的 make target，照做必失败。

    这里改为反向校验：文档里出现的每个 `make <target>` 都必须在真实 Makefile 中存在。
    """
    makefile = (ROOT / "Makefile").read_text()
    real = set(re.findall(r"^([A-Za-z0-9_.-]+):", makefile, re.M))
    assert real, "未解析到任何 make target，正则可能已失效"

    for name in sorted(ALLOWED_ROOT_MD):
        doc = ROOT / name
        if not doc.exists():
            continue
        referenced = set(re.findall(r"\bmake\s+([A-Za-z0-9_.-]+)", doc.read_text()))
        missing = referenced - real
        assert not missing, f"{name} 引用了不存在的 make target：{sorted(missing)}"


# 索引漂移守卫：只「读」不「写」的索引必然腐烂。
# 下面两条是双向校验——新模块必须进索引，索引里的路径必须还存在。
INDEX_RELATIVE = "docs/INDEX.md"

# 需要被索引覆盖的后端层。routes/handlers 是入口，models 是领域概念，
# services 顶层是业务逻辑；子包只校验目录名，避免过细导致噪音。
INDEXED_LAYERS = (
    ("app/routes", "*.py"),
    ("app/handlers", "*.py"),
    ("app/models", "*.py"),
    ("app/services", "*.py"),
)


def _index_text():
    return (ROOT / INDEX_RELATIVE).read_text(errors="ignore")


def test_index_covers_backend_modules():
    """新增路由/handler/模型/service 后必须同步更新 docs/INDEX.md。

    这是「索引腐烂」的主方向：功能加进去了，索引没写，下次 AI 就定位不到。
    """
    index = _index_text()
    missing = []
    for layer, pattern in INDEXED_LAYERS:
        base = ROOT / layer
        if not base.exists():
            continue
        for path in sorted(base.glob(pattern)):
            if path.name == "__init__.py":
                continue
            if path.name not in index:
                missing.append(f"{layer}/{path.name}")
    # services 子包：只校验目录名，不逐文件
    services = ROOT / "app" / "services"
    for pkg in sorted(p for p in services.iterdir() if p.is_dir()):
        if pkg.name.startswith(("__", ".")):
            continue
        if pkg.name not in index:
            missing.append(f"app/services/{pkg.name}/")
    assert missing == [], (
        f"这些模块未出现在 {INDEX_RELATIVE}，请补进对应功能域：{missing}"
    )


def test_index_listed_paths_still_exist():
    """反向：索引里列出的路径必须真实存在。

    这是「索引腐烂」的另一方向：文件被删或改名了，索引还指着旧位置，
    AI 照着读会失败——和当初 README 撒谎是同一类问题。
    """
    index = _index_text()
    # 只校验「完整限定」路径。INDEX 里另有简写形式（前端列的 views/X.vue 实为
    # frontend/src/views/X.vue）与示意性路径，那些不参与校验，否则全是误报。
    qualified = ("app/", "frontend/", "frontend-mobile/", "templates/", "static/",
                 "scripts/", "tests/", "docs/", "migrations/", "control_migrations/")
    # 前端列写成 `views/X.vue` 这样的简写，基准目录由 PC / 移动 列头决定，
    # 逐个在两个前端 src 下都试一次即可判定。
    shorthand = re.compile(
        r"^(components|views|stores|composables|utils|api|types|router|config)/"
        r"[\w\-/]+\.(vue|ts|js)$"
    )
    broken = []
    for raw in set(re.findall(r"`([^`\s]+)`", index)):
        if "*" in raw or "{" in raw or "}" in raw:  # 通配/花括号展开，跳过
            continue
        if raw.startswith(qualified):
            if (ROOT / raw).exists() or (ROOT / "app" / raw).exists():
                continue
            broken.append(raw)
        elif shorthand.match(raw):
            if (ROOT / "frontend" / "src" / raw).exists():
                continue
            if (ROOT / "frontend-mobile" / "src" / raw).exists():
                continue
            broken.append(f"{raw}（frontend/src/ 与 frontend-mobile/src/ 下均不存在）")
    assert broken == [], f"{INDEX_RELATIVE} 指向了不存在的文件：{sorted(broken)}"


def test_no_broken_markdown_links_in_live_docs():
    """活文档里的 markdown 链接必须能解析到真实文件。

    归档移动很容易留下断链（2026-09 那次搬完有 9 处指向已不存在的旧文件名）。
    只校验 `[text](target.md)` 链接语法，不校验反引号里的文件名——
    DEPLOY.md 会刻意列举已废弃的文档名作警示，那不是链接。
    """
    broken = []
    for path in _live_doc_paths():
        for target in re.findall(r"\[[^\]]*\]\(([^)\s]+\.md)\)", path.read_text(errors="ignore")):
            if target.startswith(("http://", "https://", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert broken == [], f"活文档存在断链：{broken}"


def test_docs_only_reference_existing_env_files():
    """同理：文档提到的 env 文件必须真实存在（.env 由部署时生成，豁免）。"""
    for name in sorted(ALLOWED_ROOT_MD):
        doc = ROOT / name
        if not doc.exists():
            continue
        # 前导点可选，用于匹配 ".env.example" 而非截断成 "env.example"
        referenced = set(re.findall(r"(\.?env\.[A-Za-z0-9_.-]+)", doc.read_text()))
        missing = {r for r in referenced if r != ".env" and not (ROOT / r).exists()}
        assert not missing, f"{name} 引用了不存在的环境文件：{sorted(missing)}"
