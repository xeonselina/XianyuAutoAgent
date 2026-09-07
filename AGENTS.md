# AGENTS.md — 仓库根（monorepo 路由器）

本仓库是 **4 个互不相关的子项目的集合**，它们只是共用 git 历史，代码无依赖关系。
**在动手前先确定目标子项目，然后只读那一个子目录。禁止跨子项目全仓 glob/grep。**

## 子项目路由

| 子项目 | 说明 | 入口 |
|---|---|---|
| `InventoryManager/` | 摄影器材租赁库存管理 SaaS（Flask + Vue，多租户） | 先读 `InventoryManager/AGENTS.md` |
| `ai_kefu/` | 闲鱼客服机器人（FastAPI + 浏览器自动化） | `ai_kefu/` 下自行查找 |
| `cocs/` | 独立子项目 | `cocs/` 下自行查找 |
| `camera-quality/` | Android 相机画质相关 | `camera-quality/` 下自行查找 |

## Git 习惯

用户说「push 一下」或「提交推送」时，直接执行 `git add` → `git commit` → `git push`，无需确认。
**默认不推送远程**——除非用户明确要求，只提交到本地。不自动切换分支。

## 检索警告

仓库根下散落的 `*.md` / `*.txt`（`AI_EVALUATION_*`、`EXPLORATION_*`、`PROJECT_*`、
`FILES_DISCOVERED.txt` 等）**全部属于 `ai_kefu`**，与 InventoryManager 无关。
其中写的文件路径是过时的 `/Users/jimmypan/git_repo/XianyuAutoAgent/...`，
**按那些路径去读文件一定失败**。不要读它们，也不要据此推断仓库结构。

`docs/` 在仓库根也有一个（含 `deployment/saas-main-lite.md` 等），
**不要与 `InventoryManager/docs/` 混淆**。
