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
