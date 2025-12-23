# 实施计划: AI 客服 Agent (内网 HTTP 服务)

**分支**: `001-ai-customer-service-agent` | **日期**: 2025-12-22 | **规格**: [spec.md](./spec.md)
**输入**: 基于 gemini-cli-agent-analysis.md 参考文档

**说明**: 本模板由 `/speckit.plan` 命令填充。执行工作流参见 `.specify/templates/commands/plan.md`。

## 概要

实现一个 AI 客服 Agent 系统，参考 gemini-cli 的 Plan-Action-Check 架构模式，为内网提供 HTTP API 服务。系统采用主循环 + 工具调度 + Hooks 扩展的架构，支持意图识别、知识库检索、工单创建和转人工等核心客服功能。

## 技术上下文

**语言/版本**: Python 3.11+  
**主要依赖**: 
  - FastAPI (HTTP 服务框架)
  - Alibaba Cloud SDK (dashscope/qwen 系列模型)
  - Pydantic (数据验证)
  - ChromaDB (向量数据库)
  
**存储**: 
  - Redis 7.x (会话状态,非持久化,TTL 30分钟)
  - ChromaDB (知识库,持久化到本地文件)
  - 工单系统: Phase 2 功能,暂不实现
  
**测试**: pytest + httpx (API 测试)  

**目标平台**: 
  - 开发环境: ARM Mac (Apple Silicon)
  - 生产环境: Linux 服务器 (内网部署, Docker 容器化)

**项目类型**: 单体应用 (web service)  

**性能目标**: 
  - API 响应: <2s (P95)
  - 并发支持: 100 req/s (单进程) / 400 req/s (4 workers)
  - 知识库检索: <100ms (5k 文档规模)
  
**约束**: 
  - 内网部署 (无外网访问,无鉴权)
  - 敏感信息: 不需要脱敏
  - 日志: 结构化 JSON 日志,包含审计字段
  - 跨平台兼容: 代码需在 ARM Mac 和 Linux 环境均可运行
  - Docker 容器化: 生产环境统一使用 Docker 部署
  - 构建自动化: 提供 Makefile 简化开发和部署流程
  
**规模/范围**: 
  - 初期: 单一业务领域客服
  - 预期并发: 100 用户 (可扩展至 400+)
  - 知识库: 初期 <10k 文档

## 宪法检查

*门控: 必须在 Phase 0 研究前通过。Phase 1 设计后重新检查。*

**状态**: ⚠️ 宪法文件未配置 (使用默认模板)

**说明**: 项目宪法文件 (`.specify/memory/constitution.md`) 当前为模板状态，未定义具体的项目原则和约束。建议在正式开发前配置项目宪法，定义:
- 代码规范和架构原则
- 测试要求 (单元测试、集成测试)
- 安全和隐私要求
- API 设计原则

**临时原则** (待正式化):
1. ✅ **API 优先**: 所有功能通过 RESTful API 暴露
2. ✅ **测试驱动**: 核心逻辑需要单元测试
3. ✅ **日志完整**: 所有客服交互必须记录日志
4. ✅ **隐私保护**: 敏感信息不得记录到日志
5. ⚠️ **待澄清**: 知识库管理和更新机制

## Project Structure

## 项目结构

### 文档 (本功能)

```text
specs/001-ai-customer-service-agent/
├── plan.md              # 本文件 (/speckit.plan 命令输出)
├── research.md          # Phase 0 输出 (/speckit.plan 命令)
├── data-model.md        # Phase 1 输出 (/speckit.plan 命令)
├── quickstart.md        # Phase 1 输出 (/speckit.plan 命令)
├── contracts/           # Phase 1 输出 (/speckit.plan 命令)
│   ├── openapi.yaml     # HTTP API 规范
│   └── schemas/         # 数据模型 JSON Schema
└── tasks.md             # Phase 2 输出 (/speckit.tasks 命令 - 不由 /speckit.plan 创建)
```

### 源代码 (仓库根目录)

```text
# 根目录构建文件
Dockerfile               # Docker 容器化配置
Makefile                 # 构建和部署自动化
docker-compose.yml       # 本地开发环境编排 (可选)
requirements.txt         # Python 依赖
.dockerignore           # Docker 构建忽略文件

# Option 1: 单体应用结构 (选用)
ai_kefu/
├── agent/                    # Agent 核心引擎
│   ├── executor.py          # 主执行器 (Plan-Action-Check 循环)
│   ├── turn.py              # 单轮对话管理
│   └── types.py             # Agent 类型定义
├── tools/                   # 工具集
│   ├── knowledge_search.py  # 知识库检索
│   ├── ask_human_agent.py   # 请求人工协助 (Human-in-the-Loop)
│   ├── complete_task.py     # 完成任务
│   └── tool_registry.py     # 工具注册表
├── hooks/                   # Hooks 扩展系统
│   ├── event_handler.py     # 事件处理器
│   ├── logging_hook.py      # 日志钩子
│   └── sensitive_filter.py  # 敏感信息过滤
├── services/                # 业务服务
│   ├── intent_service.py    # 意图识别
│   ├── sentiment_service.py # 情绪分析
│   └── loop_detection.py    # 循环检测
├── api/                     # HTTP API 层
│   ├── routes.py            # 路由定义
│   ├── models.py            # API 数据模型
│   └── dependencies.py      # FastAPI 依赖
├── prompts/                 # 提示词管理
│   ├── system_prompt.py     # 主系统提示
│   └── workflow_prompts.py  # 工作流提示
└── config/                  # 配置管理
    ├── settings.py          # 配置加载
    └── constants.py         # 常量定义

tests/
├── unit/                    # 单元测试
│   ├── test_agent/
│   ├── test_tools/
│   └── test_services/
├── integration/             # 集成测试
│   ├── test_api/
│   └── test_workflow/
└── fixtures/                # 测试数据

docs/                        # 文档 (已存在)
└── gemini-cli-agent-analysis.md  # 参考架构分析
```

**结构决策**: 
- 选用单体应用结构,参考 gemini-cli 的核心架构设计
- `agent/` 目录实现 Plan-Action-Check 主循环
- `tools/` 目录替换为客服场景专用工具
- `hooks/` 提供扩展点用于日志、过滤、监控等
- `api/` 提供 HTTP 服务接口
- 保持与现有 `ai_kefu/` 目录一致
- **Docker 化部署**: 使用多阶段构建优化镜像大小
- **跨平台支持**: 通过 Docker 解决 ARM Mac 和 Linux 环境差异

## 部署和构建配置

### Dockerfile 要求

**目标**: 创建一个适用于生产环境的 Docker 镜像

**关键要求**:
- 基础镜像: `python:3.11-slim` (适配 Linux 生产环境)
- 多阶段构建: 分离依赖安装和运行时环境
- 非 root 用户运行: 安全性考虑
- 暴露端口: 8000 (FastAPI 默认端口,可配置)
- 环境变量: 支持通过环境变量配置 Qwen API key、Redis 连接等
- 健康检查: 添加 HEALTHCHECK 指令确保容器状态
- 工作目录: `/app`
- 启动命令: `uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000`

**优化点**:
- 利用 Docker layer caching 加速构建
- 仅复制必要文件 (通过 .dockerignore 排除测试、文档等)
- 安装生产依赖 (不包含开发工具)

### Makefile 要求

**目标**: 简化常用开发和部署操作

**必需目标 (targets)**:

```makefile
# 开发环境
.PHONY: install          # 安装 Python 依赖到本地虚拟环境
.PHONY: dev              # 启动本地开发服务器 (ARM Mac)
.PHONY: test             # 运行所有测试
.PHONY: lint             # 代码质量检查

# Docker 相关
.PHONY: docker-build     # 构建 Docker 镜像
.PHONY: docker-run       # 运行 Docker 容器 (本地测试)
.PHONY: docker-push      # 推送镜像到私有仓库 (可选)

# 清理
.PHONY: clean            # 清理临时文件、缓存
.PHONY: clean-docker     # 清理 Docker 镜像和容器

# 帮助
.PHONY: help             # 显示所有可用命令
```

**变量配置**:
- `IMAGE_NAME`: Docker 镜像名称 (默认: `ai-kefu-agent`)
- `IMAGE_TAG`: 镜像标签 (默认: `latest` 或 git commit hash)
- `CONTAINER_NAME`: 容器名称 (默认: `ai-kefu-agent`)
- `PORT`: 映射端口 (默认: 8000)

### 跨平台兼容性策略

**开发环境 (ARM Mac)**:
- 使用 Python 虚拟环境进行本地开发
- 通过 `make dev` 启动本地服务器
- 使用 Docker Desktop for Mac 进行容器测试

**生产环境 (Linux)**:
- 使用 Docker 运行应用,隔离系统依赖
- 通过 `docker-compose` 或 Kubernetes 编排 (未来扩展)
- 环境变量配置所有外部服务连接

**CI/CD 考虑**:
- Docker 镜像在 Linux CI 环境构建 (或使用 buildx 多架构支持)
- 测试在 Docker 容器中运行,确保环境一致性

## 复杂度追踪

> **仅在宪法检查有需要解释的违规时填写**

| 违规项 | 为何需要 | 拒绝更简单替代方案的原因 |
|--------|----------|--------------------------|
| N/A | N/A | 当前设计未发现违反宪法的项目 |

**说明**: 
- 单体应用架构符合初期快速迭代需求
- Hooks 系统虽增加一定复杂度,但为后续扩展提供必要的灵活性
- 待宪法正式化后重新评估
