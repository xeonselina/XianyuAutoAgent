.PHONY: help install install-dev clean test lint format docker-build docker-up docker-down
.PHONY: run-xianyu run-api run-api-dev init-knowledge check-env ui-dev ui-build ui-install
.PHONY: build-api build-console build-all build-interceptor push-api push-console push-all push-interceptor build-push-all
.PHONY: pack-interceptor deploy-nas fetch-api-logs tail-api-logs
.DEFAULT_GOAL := help

# ============================================================
# 变量定义
# ============================================================
PYTHON := $(shell test -f $(CURDIR)/.venv/bin/python3.12 && echo $(CURDIR)/.venv/bin/python3.12 || echo python3)
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
DOCKER := docker
DOCKER_COMPOSE := docker-compose

# ── 镜像仓库 / 名称 ──────────────────────────────────────
REGISTRY         := docker.cnb.cool/tdcc-demo/jimmy
API_IMAGE        := $(REGISTRY)/aikefu-api
CONSOLE_IMAGE    := $(REGISTRY)/aikefu-console
INTERCEPTOR_IMAGE := $(REGISTRY)/aikefu-interceptor

# ── 镜像标签：日期+时间，格式 YYYYMMDD-HHMM（可命令行覆盖）
#   示例: make build-all IMAGE_TAG=20260424-0903
IMAGE_TAG     ?= $(shell date +%Y%m%d-%H%M)

# 目标平台（固定 x86-64）
BUILD_PLATFORM := linux/amd64

# 颜色定义
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

# ============================================================
# 帮助信息
# ============================================================
help: ## 显示帮助信息
	@echo "$(GREEN)闲鱼 AI 客服系统 - Makefile 命令$(NC)"
	@echo ""
	@echo "$(YELLOW)安装相关:$(NC)"
	@echo "  make install         - 安装生产环境依赖"
	@echo "  make install-dev     - 安装开发环境依赖（包含测试工具）"
	@echo "  make check-env       - 检查环境配置"
	@echo ""
	@echo "$(YELLOW)运行系统:$(NC)"
	@echo "  make run-xianyu      - 启动闲鱼客服机器人（浏览器模式）"
	@echo "  make run-api         - 启动 AI Agent API 服务"
	@echo "  make init-knowledge  - 初始化知识库（首次运行 API 前需要）"
	@echo ""
	@echo "$(YELLOW)知识库 UI:$(NC)"
	@echo "  make ui-install      - 安装 UI 依赖"
	@echo "  make ui-dev          - 启动 UI 开发服务器"
	@echo "  make ui-build        - 构建生产环境 UI"
	@echo ""
	@echo "$(YELLOW)开发工具:$(NC)"
	@echo "  make test            - 运行所有测试"
	@echo "  make test-unit       - 只运行单元测试"
	@echo "  make test-integration - 只运行集成测试"
	@echo "  make test-cov        - 运行测试并生成覆盖率报告"
	@echo "  make lint            - 代码检查（ruff + mypy）"
	@echo "  make format          - 代码格式化"
	@echo ""
	@echo "$(YELLOW)Docker 相关 (旧):$(NC)"
	@echo "  make docker-build    - 构建 Docker 镜像（原始 Dockerfile）"
	@echo "  make docker-up       - 启动 Docker 容器"
	@echo "  make docker-down     - 停止 Docker 容器"
	@echo "  make docker-logs     - 查看容器日志"
	@echo ""
	@echo "$(YELLOW)构建 x86 镜像 (linux/amd64):$(NC)"
	@echo "  make build-interceptor - 构建拦截器镜像"
	@echo "  make build-api       - 构建 API 后台镜像"
	@echo "  make build-console   - 构建管理控制台镜像（含知识库+对话UI）"
	@echo "  make build-all       - 同时构建 API + 控制台两个镜像"
	@echo "  make push-interceptor - 推送拦截器镜像到 Registry"
	@echo "  make push-api        - 推送 API 镜像到 Registry"
	@echo "  make push-console    - 推送控制台镜像到 Registry"
	@echo "  make push-all        - 推送 API + 控制台镜像到 Registry"
	@echo "  make build-push-all  - 并行构建并推送全部三个镜像 ★"
	@echo "  镜像仓库: docker.cnb.cool/tdcc-demo/jimmy"
	@echo "  默认 tag: 构建时刻 YYYYMMDD-HHMM，如 20260424-0903"
	@echo "  覆盖 tag: IMAGE_TAG=20260424-0903 make build-all"
	@echo ""
	@echo "$(YELLOW)清理相关:$(NC)"
	@echo "  make clean           - 清理临时文件和缓存"
	@echo "  make clean-all       - 清理所有（包括虚拟环境和数据）"
	@echo ""
	@echo "$(YELLOW)拦截器打包 (Mac 独立部署):$(NC)"
	@echo "  make pack-interceptor - 打包拦截器安装包（tar.gz）"
	@echo "  默认包名: xianyu-interceptor-YYYYMMDD-HHMM.tar.gz"
	@echo "  覆盖 tag: IMAGE_TAG=20260424-0903 make pack-interceptor"
	@echo ""
	@echo "$(YELLOW)群晖 NAS 一键部署:$(NC)"
	@echo "  make deploy-nas      - 拉取新镜像并重启群晖上的容器"
	@echo "  必须指定 tag: IMAGE_TAG=20260424-0903 make deploy-nas"
	@echo "  依赖: brew install sshpass"
	@echo ""
	@echo "$(YELLOW)群晖 NAS 日志:$(NC)"
	@echo "  make fetch-api-logs  - 下载 NAS 上的 API 日志到本地 ./logs/nas/"
	@echo "  make tail-api-logs   - 实时 tail NAS 上最新的 API 日志文件"
	@echo "  日志路径 (NAS): /volume1/docker/aikefu/logs/"
	@echo ""

# ============================================================
# 安装相关
# ============================================================
install: ## 安装生产环境依赖
	@echo "$(GREEN)正在安装生产环境依赖...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✓ 依赖安装完成$(NC)"

install-dev: install ## 安装开发环境依赖
	@echo "$(GREEN)正在安装开发环境依赖...$(NC)"
	$(PIP) install pytest pytest-asyncio pytest-cov pytest-mock
	$(PIP) install ruff mypy
	@echo "$(GREEN)✓ 开发依赖安装完成$(NC)"

check-env: ## 检查环境配置
	@echo "$(GREEN)检查环境配置...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(YELLOW)⚠ .env 文件不存在，正在从模板创建...$(NC)"; \
		cp .env.example .env; \
		echo "$(YELLOW)请编辑 .env 文件，配置必要的环境变量$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✓ 环境配置文件存在$(NC)"
	@echo ""
	@echo "$(YELLOW)请确保已配置以下环境变量:$(NC)"
	@echo "  - API_KEY (通义千问 API Key)"
	@echo "  - COOKIES_STR (可选，不设置则使用浏览器保存的会话)"
	@echo "  - QWEN_API_KEY (运行 run-api 需要)"
	@echo "  - MYSQL_USER/MYSQL_PASSWORD (对话记录需要)"
	@echo "  - ENABLE_AI_REPLY (是否启用AI自动回复，默认false)"

# ============================================================
# 运行系统
# ============================================================
run-xianyu: check-env ## 启动闲鱼客服机器人（浏览器模式）
	@echo "$(GREEN)正在启动闲鱼消息拦截器...$(NC)"
	@echo "$(YELLOW)提示: AI自动回复默认禁用，仅记录对话到MySQL$(NC)"
	@echo "$(YELLOW)设置 ENABLE_AI_REPLY=true 启用AI自动回复$(NC)"
	$(PYTHON) run_xianyu.py

run-api: check-env ## 启动 AI Agent API 服务
	@echo "$(GREEN)正在启动 AI Agent API 服务...$(NC)"
	@echo "$(YELLOW)提示: 首次运行前请执行 'make init-knowledge' 初始化知识库$(NC)"
	@if [ ! -f chroma_data/chroma.sqlite3 ]; then \
		echo "$(YELLOW)⚠ 知识库未初始化，请先运行: make init-knowledge$(NC)"; \
		exit 1; \
	fi
	cd .. && $(PYTHON) -m uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000 --workers 4

run-api-dev: check-env ## 启动 AI Agent API 服务（开发模式，单worker + 热重载）
	@echo "$(GREEN)正在启动 AI Agent API 服务（开发模式）...$(NC)"
	@echo "$(YELLOW)提示: 首次运行前请执行 'make init-knowledge' 初始化知识库$(NC)"
	@if [ ! -f chroma_data/chroma.sqlite3 ]; then \
		echo "$(YELLOW)⚠ 知识库未初始化，请先运行: make init-knowledge$(NC)"; \
		exit 1; \
	fi
	cd .. && $(PYTHON) -m uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000 --reload

init-knowledge: check-env ## 初始化知识库
	@echo "$(GREEN)正在初始化知识库...$(NC)"
	$(PYTHON) scripts/init_knowledge.py
	@echo "$(GREEN)✓ 知识库初始化完成$(NC)"

# ============================================================
# 知识库 UI
# ============================================================
ui-install: ## 安装 UI 依赖
	@echo "$(GREEN)正在安装 UI 依赖...$(NC)"
	cd ui/knowledge && npm install
	@echo "$(GREEN)✓ UI 依赖安装完成$(NC)"

ui-dev: ## 启动 UI 开发服务器
	@echo "$(GREEN)正在启动 UI 开发服务器...$(NC)"
	@echo "$(YELLOW)访问地址: http://localhost:5173$(NC)"
	cd ui/knowledge && npm run dev

ui-build: ## 构建生产环境 UI
	@echo "$(GREEN)正在构建生产环境 UI...$(NC)"
	cd ui/knowledge && npm run build
	@echo "$(GREEN)✓ UI 构建完成$(NC)"
	@echo "$(YELLOW)启动 API 服务后访问: http://localhost:8000/ui/knowledge$(NC)"

# ============================================================
# 开发工具
# ============================================================
test: ## 运行所有测试
	@echo "$(GREEN)运行所有测试...$(NC)"
	$(PYTEST) tests/ -v

test-unit: ## 运行单元测试
	@echo "$(GREEN)运行单元测试...$(NC)"
	$(PYTEST) tests/unit/ -v

test-integration: ## 运行集成测试
	@echo "$(GREEN)运行集成测试...$(NC)"
	$(PYTEST) tests/integration/ -v

test-cov: ## 运行测试并生成覆盖率报告
	@echo "$(GREEN)运行测试并生成覆盖率报告...$(NC)"
	$(PYTEST) tests/ --cov=. --cov-report=html --cov-report=term
	@echo "$(GREEN)✓ 覆盖率报告已生成到 htmlcov/index.html$(NC)"

lint: ## 代码检查
	@echo "$(GREEN)运行代码检查...$(NC)"
	@echo "$(YELLOW)Ruff 检查...$(NC)"
	-ruff check .
	@echo "$(YELLOW)MyPy 类型检查...$(NC)"
	-mypy . --ignore-missing-imports

format: ## 代码格式化
	@echo "$(GREEN)格式化代码...$(NC)"
	ruff check --fix .
	@echo "$(GREEN)✓ 代码格式化完成$(NC)"

# ============================================================
# Docker 相关
# ============================================================
docker-build: ## 构建 Docker 镜像
	@echo "$(GREEN)构建 Docker 镜像...$(NC)"
	$(DOCKER) build -t xianyuautoagent:latest .
	@echo "$(GREEN)✓ 镜像构建完成$(NC)"

docker-up: ## 启动 Docker 容器
	@echo "$(GREEN)启动 Docker 容器...$(NC)"
	$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)✓ 容器已启动$(NC)"
	@echo "查看日志: make docker-logs"

docker-down: ## 停止 Docker 容器
	@echo "$(GREEN)停止 Docker 容器...$(NC)"
	$(DOCKER_COMPOSE) down
	@echo "$(GREEN)✓ 容器已停止$(NC)"

docker-logs: ## 查看容器日志
	$(DOCKER_COMPOSE) logs -f

# ============================================================
# 构建 x86 (linux/amd64) 镜像
# ============================================================

## 构建 API 后台镜像 (linux/amd64)
##   镜像名: $(API_IMAGE):$(IMAGE_TAG)
##   默认:   xianyuautoagent/api:latest
##   覆盖示例: IMAGE_PREFIX=registry.cn-xxx.aliyuncs.com/myns IMAGE_TAG=v1.2 make build-api
build-api: ## 构建 API 后台 x86 镜像
	@echo "$(GREEN)构建 API 后台镜像 [$(BUILD_PLATFORM)]...$(NC)"
	@echo "$(YELLOW)镜像: $(API_IMAGE):$(IMAGE_TAG)$(NC)"
	$(DOCKER) build \
		--platform $(BUILD_PLATFORM) \
		--file Dockerfile.api \
		--tag $(API_IMAGE):$(IMAGE_TAG) \
		.
	@echo "$(GREEN)✓ API 镜像构建完成: $(API_IMAGE):$(IMAGE_TAG)$(NC)"

## 构建管理控制台镜像 (linux/amd64)
##   包含: 知识库管理 UI + 对话管理 UI + nginx 反向代理
##   镜像名: $(CONSOLE_IMAGE):$(IMAGE_TAG)
##   默认:   xianyuautoagent/console:latest
build-console: ## 构建管理控制台 x86 镜像
	@echo "$(GREEN)构建管理控制台镜像 [$(BUILD_PLATFORM)]...$(NC)"
	@echo "$(YELLOW)镜像: $(CONSOLE_IMAGE):$(IMAGE_TAG)$(NC)"
	$(DOCKER) build \
		--platform $(BUILD_PLATFORM) \
		--file Dockerfile.console \
		--tag $(CONSOLE_IMAGE):$(IMAGE_TAG) \
		.
	@echo "$(GREEN)✓ 控制台镜像构建完成: $(CONSOLE_IMAGE):$(IMAGE_TAG)$(NC)"

## 同时构建 API + 控制台两个 x86 镜像
build-all: build-api build-console ## 构建全部 x86 镜像
	@echo "$(GREEN)✓ 全部镜像构建完成$(NC)"
	@echo "  $(API_IMAGE):$(IMAGE_TAG)"
	@echo "  $(CONSOLE_IMAGE):$(IMAGE_TAG)"

## 构建拦截器镜像 (linux/amd64)
build-interceptor: ## 构建拦截器 x86 镜像
	@echo "$(GREEN)构建拦截器镜像 [$(BUILD_PLATFORM)]...$(NC)"
	@echo "$(YELLOW)镜像: $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)$(NC)"
	$(DOCKER) build \
		--platform $(BUILD_PLATFORM) \
		--file docker/Dockerfile.interceptor \
		--tag $(INTERCEPTOR_IMAGE):$(IMAGE_TAG) \
		xianyu_provider/upstream
	@echo "$(GREEN)✓ 拦截器镜像构建完成: $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)$(NC)"

## 推送拦截器镜像到 Registry
push-interceptor: ## 推送拦截器镜像
	@echo "$(GREEN)推送拦截器镜像...$(NC)"
	$(DOCKER) push $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)
	@echo "$(GREEN)✓ 推送完成: $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)$(NC)"

## 一键构建并推送三个镜像（拦截器 + API + 控制台）
build-push-all: ## 构建并推送全部三个镜像
	@echo "$(GREEN)开始并行构建三个镜像 [$(BUILD_PLATFORM)] tag=$(IMAGE_TAG)...$(NC)"
	$(MAKE) build-interceptor IMAGE_TAG=$(IMAGE_TAG) & \
	$(MAKE) build-api         IMAGE_TAG=$(IMAGE_TAG) & \
	$(MAKE) build-console     IMAGE_TAG=$(IMAGE_TAG) & \
	wait
	@echo "$(GREEN)三个镜像构建完成，开始推送...$(NC)"
	$(DOCKER) push $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)
	$(DOCKER) push $(API_IMAGE):$(IMAGE_TAG)
	$(DOCKER) push $(CONSOLE_IMAGE):$(IMAGE_TAG)
	@echo ""
	@echo "$(GREEN)╔══════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║  全部推送完成                                    ║$(NC)"
	@echo "$(GREEN)╚══════════════════════════════════════════════════╝$(NC)"
	@echo "  $(INTERCEPTOR_IMAGE):$(IMAGE_TAG)"
	@echo "  $(API_IMAGE):$(IMAGE_TAG)"
	@echo "  $(CONSOLE_IMAGE):$(IMAGE_TAG)"

## 推送 API 镜像到 Registry
push-api: ## 推送 API 镜像
	@echo "$(GREEN)推送 API 镜像...$(NC)"
	$(DOCKER) push $(API_IMAGE):$(IMAGE_TAG)
	@echo "$(GREEN)✓ 推送完成: $(API_IMAGE):$(IMAGE_TAG)$(NC)"

## 推送控制台镜像到 Registry
push-console: ## 推送控制台镜像
	@echo "$(GREEN)推送控制台镜像...$(NC)"
	$(DOCKER) push $(CONSOLE_IMAGE):$(IMAGE_TAG)
	@echo "$(GREEN)✓ 推送完成: $(CONSOLE_IMAGE):$(IMAGE_TAG)$(NC)"

## 推送两个镜像到 Registry
push-all: push-api push-console ## 推送全部镜像
	@echo "$(GREEN)✓ 全部镜像推送完成$(NC)"

# ============================================================
# 清理相关
# ============================================================
clean: ## 清理临时文件和缓存
	@echo "$(GREEN)清理临时文件...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ 2>/dev/null || true
	rm -f .coverage 2>/dev/null || true
	@echo "$(GREEN)✓ 清理完成$(NC)"

clean-all: clean ## 清理所有（包括虚拟环境和数据）
	@echo "$(YELLOW)警告: 这将删除虚拟环境、知识库数据和浏览器数据$(NC)"
	@read -p "确认继续? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf venv/ .venv/ 2>/dev/null || true; \
		rm -rf chroma_data/ 2>/dev/null || true; \
		rm -rf browser_data/ 2>/dev/null || true; \
		rm -rf logs/ 2>/dev/null || true; \
		echo "$(GREEN)✓ 完全清理完成$(NC)"; \
	else \
		echo "$(YELLOW)已取消$(NC)"; \
	fi

# ============================================================
# 拦截器打包 — Mac 独立部署安装包
# ============================================================
## 打包目录结构：
##   xianyu-interceptor-YYYYMMDD-HHMM/
##   ├── install.sh                    ← 一键安装脚本
##   ├── run.sh                        ← 启动脚本
##   ├── requirements.interceptor.txt  ← 最小 Python 依赖
##   └── ai_kefu/
##       ├── __init__.py
##       ├── run_xianyu.py
##       ├── .env.example
##       ├── config/
##       ├── utils/
##       ├── xianyu_interceptor/
##       ├── xianyu_provider/
##       └── services/                 ← 仅钉钉相关文件
pack-interceptor: ## 打包闲鱼拦截器为可传输 tar.gz 安装包
	$(eval PKG_NAME := xianyu-interceptor-$(IMAGE_TAG))
	$(eval PKG_DIR  := /tmp/$(PKG_NAME))
	@echo "$(GREEN)打包拦截器安装包: $(PKG_NAME).tar.gz$(NC)"
	@# ── 清理旧的临时目录 ──────────────────────────────────
	@rm -rf "$(PKG_DIR)"
	@# ── 创建目录骨架 ──────────────────────────────────────
	@mkdir -p \
		"$(PKG_DIR)" \
		"$(PKG_DIR)/ai_kefu/config" \
		"$(PKG_DIR)/ai_kefu/utils" \
		"$(PKG_DIR)/ai_kefu/xianyu_interceptor" \
		"$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/message" \
		"$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/utils" \
		"$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/static" \
		"$(PKG_DIR)/ai_kefu/services"
	@# ── 安装 / 启动脚本 + 依赖文件（打包根目录）──────────
	@cp scripts/interceptor/install.sh          "$(PKG_DIR)/install.sh"
	@cp scripts/interceptor/run.sh              "$(PKG_DIR)/run.sh"
	@cp scripts/interceptor/requirements.interceptor.txt "$(PKG_DIR)/requirements.interceptor.txt"
	@chmod +x "$(PKG_DIR)/install.sh" "$(PKG_DIR)/run.sh"
	@# ── ai_kefu 包顶层文件 ────────────────────────────────
	@cp __init__.py                             "$(PKG_DIR)/ai_kefu/__init__.py"
	@cp run_xianyu.py                           "$(PKG_DIR)/ai_kefu/run_xianyu.py"
	@[ -f .env.example ] && cp .env.example    "$(PKG_DIR)/ai_kefu/.env.example" || true
	@[ -f .env ] && cp .env                    "$(PKG_DIR)/ai_kefu/.env" || true
	@# ── config ────────────────────────────────────────────
	@cp config/__init__.py                      "$(PKG_DIR)/ai_kefu/config/__init__.py"
	@cp config/settings.py                      "$(PKG_DIR)/ai_kefu/config/settings.py"
	@cp config/constants.py                     "$(PKG_DIR)/ai_kefu/config/constants.py"
	@[ -f config/inventory_config.py ] && cp config/inventory_config.py "$(PKG_DIR)/ai_kefu/config/inventory_config.py" || true
	@# ── utils ─────────────────────────────────────────────
	@cp utils/__init__.py                       "$(PKG_DIR)/ai_kefu/utils/__init__.py"
	@cp utils/xianyu_utils.py                   "$(PKG_DIR)/ai_kefu/utils/xianyu_utils.py"
	@cp utils/logging.py                        "$(PKG_DIR)/ai_kefu/utils/logging.py"
	@[ -f utils/errors.py ] && cp utils/errors.py "$(PKG_DIR)/ai_kefu/utils/errors.py" || true
	@[ -f utils/inventory_manager.py ] && cp utils/inventory_manager.py "$(PKG_DIR)/ai_kefu/utils/inventory_manager.py" || true
	@[ -f utils/tencent_docs_api.py ] && cp utils/tencent_docs_api.py "$(PKG_DIR)/ai_kefu/utils/tencent_docs_api.py" || true
	@# ── xianyu_interceptor（全部 .py）──────────────────────
	@cp xianyu_interceptor/__init__.py          "$(PKG_DIR)/ai_kefu/xianyu_interceptor/__init__.py"
	@for f in xianyu_interceptor/*.py; do \
		[ "$$f" = "xianyu_interceptor/__init__.py" ] && continue; \
		cp "$$f" "$(PKG_DIR)/ai_kefu/$$f"; \
	done
	@# ── xianyu_provider（全部 .py + upstream 子目录）───────
	@cp xianyu_provider/__init__.py             "$(PKG_DIR)/ai_kefu/xianyu_provider/__init__.py"
	@cp xianyu_provider/base.py                 "$(PKG_DIR)/ai_kefu/xianyu_provider/base.py"
	@cp xianyu_provider/goofish_provider.py     "$(PKG_DIR)/ai_kefu/xianyu_provider/goofish_provider.py"
	@cp xianyu_provider/upstream/blackboxprotobuf.py "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/blackboxprotobuf.py"
	@cp xianyu_provider/upstream/goofish_apis.py "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/goofish_apis.py"
	@cp xianyu_provider/upstream/goofish_live.py "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/goofish_live.py"
	@cp xianyu_provider/upstream/message/__init__.py "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/message/__init__.py"
	@cp xianyu_provider/upstream/message/types.py    "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/message/types.py"
	@cp xianyu_provider/upstream/utils/__init__.py   "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/utils/__init__.py"
	@cp xianyu_provider/upstream/utils/goofish_utils.py "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/utils/goofish_utils.py"
	@cp xianyu_provider/upstream/static/goofish_js_origin_version_2.js "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/static/goofish_js_origin_version_2.js"
	@cp xianyu_provider/upstream/static/goofish_js_version_1.js        "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/static/goofish_js_version_1.js"
	@cp xianyu_provider/upstream/static/goofish_js_version_2.js        "$(PKG_DIR)/ai_kefu/xianyu_provider/upstream/static/goofish_js_version_2.js"
	@# ── services（仅钉钉相关）────────────────────────────
	@cp services/__init__.py                    "$(PKG_DIR)/ai_kefu/services/__init__.py"
	@cp services/dingtalk_notify.py             "$(PKG_DIR)/ai_kefu/services/dingtalk_notify.py"
	@cp services/dingtalk_reply_handler.py      "$(PKG_DIR)/ai_kefu/services/dingtalk_reply_handler.py"
	@cp services/dingtalk_stream_client.py      "$(PKG_DIR)/ai_kefu/services/dingtalk_stream_client.py"
	@[ -f services/human_request_store.py ] && cp services/human_request_store.py "$(PKG_DIR)/ai_kefu/services/human_request_store.py" || true
	@[ -f services/loop_detection.py ] && cp services/loop_detection.py "$(PKG_DIR)/ai_kefu/services/loop_detection.py" || true
	@[ -f services/sentiment_service.py ] && cp services/sentiment_service.py "$(PKG_DIR)/ai_kefu/services/sentiment_service.py" || true
	@# ── 打包为 tar.gz ─────────────────────────────────────
	@cd /tmp && tar -czf "$(CURDIR)/$(PKG_NAME).tar.gz" "$(PKG_NAME)"
	@rm -rf "$(PKG_DIR)"
	@echo ""
	@echo "$(GREEN)╔══════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║  安装包已生成                                    ║$(NC)"
	@echo "$(GREEN)╚══════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "  文件: $(YELLOW)$(PKG_NAME).tar.gz$(NC)"
	@echo ""
	@echo "  传输到目标 Mac 后执行："
	@echo "    $(BLUE)tar xzf $(PKG_NAME).tar.gz$(NC)"
	@echo "    $(BLUE)cd $(PKG_NAME)$(NC)"
	@echo "    $(BLUE)chmod +x install.sh run.sh && ./install.sh$(NC)"
	@echo ""

# ============================================================
# 群晖 NAS 一键部署
# ============================================================
## 用法：IMAGE_TAG=20260424-0903 make deploy-nas
## 前提：brew install sshpass
deploy-nas: ## 拉取新镜像并在群晖 NAS 上重启容器
	@if [ -z "$(IMAGE_TAG)" ]; then \
		echo "$(RED)[ERR ]$(NC)  请指定 IMAGE_TAG，例如:"; \
		echo "         IMAGE_TAG=20260424-0903 make deploy-nas"; \
		exit 1; \
	fi
	@bash scripts/deploy_nas.sh "$(IMAGE_TAG)"

# ── NAS 日志变量（与 deploy_nas.sh 保持一致）─────────────────
NAS_HOST     := 192.168.50.132
NAS_USER     := xeon_pan
NAS_PASS     := oLwQpzUgXKae8Dae8UJC
NAS_LOG_DIR  := /volume1/docker/aikefu/logs
LOCAL_LOG_DIR := logs/nas

fetch-api-logs: ## 下载 NAS 上的 API 日志到本地 ./logs/nas/
	@echo "$(GREEN)正在从 NAS 下载 API 日志...$(NC)"
	@mkdir -p $(LOCAL_LOG_DIR)
	@sshpass -p "$(NAS_PASS)" \
	    rsync -avz --progress \
	    -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10" \
	    "$(NAS_USER)@$(NAS_HOST):$(NAS_LOG_DIR)/" \
	    "$(LOCAL_LOG_DIR)/"
	@echo ""
	@echo "$(GREEN)✓ 日志已下载到: $(LOCAL_LOG_DIR)/$(NC)"
	@ls -lh $(LOCAL_LOG_DIR)/ 2>/dev/null || true

tail-api-logs: ## 实时 tail NAS 上最新的 API 日志（Ctrl-C 退出）
	@echo "$(GREEN)正在实时查看 NAS API 日志（Ctrl-C 退出）...$(NC)"
	@echo "$(YELLOW)日志路径: $(NAS_HOST):$(NAS_LOG_DIR)/$(NC)"
	@sshpass -p "$(NAS_PASS)" \
	    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
	    "$(NAS_USER)@$(NAS_HOST)" \
	    "tail -f \$$(ls -t $(NAS_LOG_DIR)/backend_*.log 2>/dev/null | head -1)"
