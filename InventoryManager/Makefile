# 库存管理系统 Makefile
# 适用于 ARM Mac 开发，x86 Docker 部署

# 变量定义
APP_NAME = inventory-manager
DOCKER_IMAGE = inventory-manager
DOCKER_TAG = latest
DOCKER_PLATFORM = linux/amd64  # 目标平台为 x86_64
FLASK_APP = app.py
FLASK_ENV = development

# 从.env文件加载环境变量（如果存在）
ifneq (,$(wildcard ./.env))
    include .env
    export $(shell sed 's/=.*//' .env)
endif

# 默认目标
.DEFAULT_GOAL := help

.PHONY: help
help: ## 显示帮助信息
	@echo "库存管理系统构建脚本"
	@echo "=================="
	@echo ""
	@echo "可用命令:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# =============================================================================
# 开发环境命令
# =============================================================================

.PHONY: install-dev
install-dev: ## 安装开发环境依赖
	@echo "安装开发环境依赖..."
	pip install -r requirements-dev.txt

.PHONY: install
install: ## 安装生产环境依赖
	@echo "安装生产环境依赖..."
	pip install -r requirements.txt

.PHONY: clean
clean: ## 清理Python缓存和临时文件
	@echo "清理Python缓存..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	@echo "清理完成"

.PHONY: clean-all
clean-all: clean ## 清理所有生成的文件
	@echo "清理所有生成的文件..."
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ htmlcov/ .coverage
	@echo "清理完成"

# =============================================================================
# 环境配置命令
# =============================================================================

.PHONY: env-dev
env-dev: ## 配置开发环境
	@echo "配置开发环境..."
	cp env.local .env
	@echo "请编辑 .env 文件配置数据库连接信息"

.PHONY: env-prod
env-prod: ## 配置生产环境
	@echo "配置生产环境..."
	cp env.production .env
	@echo "请编辑 .env 文件配置生产环境信息"

.PHONY: env-docker
env-docker: ## 配置Docker环境
	@echo "配置Docker环境..."
	cp env.docker .env
	@echo "请编辑 .env 文件配置Docker环境信息"

.PHONY: env-check
env-check: ## 检查环境变量配置
	@echo "检查环境变量配置..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@echo "当前 .env 配置:"
	@echo "=================="
	@echo "数据库配置:"
	@echo "  DATABASE_URL: $(DATABASE_URL)"
	@echo "应用配置:"
	@echo "  APP_PORT: $(APP_PORT)"
	@echo "  APP_HOST: $(APP_HOST)"
	@echo "  SECRET_KEY: $(if $(SECRET_KEY),已配置,未配置)"
	@echo "  API_KEY: $(if $(API_KEY),已配置,未配置)"
	@echo "阿里云配置:"
	@echo "  ALIYUN_ACCESS_KEY_ID: $(if $(ALIYUN_ACCESS_KEY_ID),已配置,未配置)"
	@echo "  ALIYUN_ACCESS_KEY_SECRET: $(if $(ALIYUN_ACCESS_KEY_SECRET),已配置,未配置)"
	@echo "顺丰配置:"
	@echo "  SF_PARTNER_ID: $(if $(SF_PARTNER_ID),已配置,未配置)"
	@echo "  SF_CHECKPHONENO: $(if $(SF_CHECKPHONENO),已配置,未配置)"
	@echo "  SF_CHECKWORD: $(if $(SF_CHECKWORD),已配置,未配置)"
	@echo "=================="

# =============================================================================
# 数据库命令
# =============================================================================

.PHONY: init-db
init-db: ## 初始化数据库（从 .env 读取环境变量）
	@echo "初始化数据库（读取 .env）..."
	@[ -f .env ] || { echo "未找到 .env，请先创建并配置数据库连接信息（可参考 env.example）"; exit 1; }
	@set -a; . .env; set +a; python3 init_db.py

.PHONY: db-upgrade
db-upgrade: ## 运行数据库迁移（使用 DATABASE_URL_HOST 如果存在）
	@echo "运行数据库迁移..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@set -a; . .env; set +a; \
	if [ ! -z "$$DATABASE_URL_HOST" ]; then \
		echo "使用主机数据库连接: DATABASE_URL_HOST"; \
		export DATABASE_URL="$$DATABASE_URL_HOST"; \
	else \
		echo "使用默认数据库连接: DATABASE_URL"; \
	fi; \
	python3 -m flask db upgrade

.PHONY: db-upgrade-docker
db-upgrade-docker: ## 在 Docker 容器中运行数据库迁移
	@echo "在 Docker 容器中运行数据库迁移..."
	@if docker ps --format "table {{.Names}}" | grep -q "inventory_app\|inventorymanager.*app"; then \
		docker exec $$(docker ps --filter "name=inventory_app" --format "{{.Names}}" | head -1) python3 -m flask db upgrade; \
	else \
		echo "未找到运行中的应用容器"; \
		exit 1; \
	fi

.PHONY: db-init
db-init: init-db ## 初始化数据库（兼容旧命令）

.PHONY: db-seed
db-seed: ## 填充示例数据（从.env读取配置）
	@echo "填充示例数据..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@set -a; . .env; set +a; flask seed-data

# =============================================================================
# 应用运行命令
# =============================================================================

.PHONY: run
run: ## 运行开发服务器（从.env读取配置）
	@echo "启动开发服务器..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@set -a; . .env; set +a; python3 app.py

.PHONY: run-scheduler
run-scheduler: ## 运行设备状态自动更新定时任务
	@echo "启动设备状态自动更新定时任务..."
	@echo "使用改进的启动脚本..."
	./start_scheduler.sh

.PHONY: run-scheduler-direct
run-scheduler-direct: ## 直接运行定时任务（从.env读取配置）
	@echo "直接启动设备状态自动更新定时任务..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@set -a; . .env; set +a; python3 device_status_scheduler.py

.PHONY: run-with-scheduler
run-with-scheduler: ## 同时运行Flask应用和定时任务（从.env读取配置）
	@echo "同时启动Flask应用和定时任务..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	@echo "启动Flask应用..."
	@set -a; . .env; set +a; python3 app.py &
	@echo "启动定时任务..."
	@set -a; . .env; set +a; python3 device_status_scheduler.py &
	@echo "所有服务已启动，使用 'make stop-all' 停止"

.PHONY: stop-all
stop-all: ## 停止所有后台服务
	@echo "停止所有后台服务..."
	@pkill -f "python3 app.py" || true
	@pkill -f "python3 device_status_scheduler.py" || true
	@echo "所有服务已停止"

.PHONY: run-gunicorn
run-gunicorn: ## 使用Gunicorn运行（生产模式）
	@echo "使用Gunicorn启动生产服务器..."
	gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app

# =============================================================================
# 前端构建命令
# =============================================================================

.PHONY: frontend-install
frontend-install: ## 安装前端依赖
	@echo "安装前端依赖..."
	cd frontend && npm install

.PHONY: frontend-build
frontend-build: frontend-install ## 构建前端应用
	@echo "构建前端Vue应用..."
	cd frontend && npm run build
	@echo "前端构建完成，输出到: static/vue-dist/"

.PHONY: frontend-dev
frontend-dev: frontend-install ## 启动前端开发服务器
	@echo "启动前端开发服务器..."
	cd frontend && npm run dev

# =============================================================================
# Docker 构建和部署命令
# =============================================================================

.PHONY: docker-build
docker-build: ## 构建Docker镜像（ARM Mac兼容）
	@echo "构建Docker镜像..."
	@echo "目标平台: $(DOCKER_PLATFORM)"
	docker build --platform $(DOCKER_PLATFORM) -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

.PHONY: docker-build-arm
docker-build-arm: ## 构建ARM64镜像（本地测试）
	@echo "构建ARM64镜像..."
	docker build --platform linux/arm64 -t $(DOCKER_IMAGE):arm64 .

.PHONY: docker-build-multiarch
docker-build-multiarch: ## 构建多架构镜像（ARM64 + x86_64）
	@echo "构建多架构镜像..."
	./build-multiarch.sh

.PHONY: setup-buildx
setup-buildx: ## 设置Docker Buildx多架构构建
	@echo "设置Docker Buildx..."
	@if ! docker buildx version > /dev/null 2>&1; then \
		echo "Docker Buildx未安装，请安装后重试"; \
		echo "参考: https://docs.docker.com/buildx/working-with-buildx/"; \
		exit 1; \
	fi
	@docker buildx create --name multiarch-builder --use --bootstrap || true
	@docker buildx inspect
	@echo "Buildx设置完成"

.PHONY: docker-build-amd64
docker-build-amd64: ## 构建AMD64镜像并加载到本地
	@echo "构建AMD64镜像..."
	docker buildx build --platform linux/amd64 -t $(DOCKER_IMAGE):amd64 --load .

.PHONY: docker-build-arm64-local
docker-build-arm64-local: ## 构建ARM64镜像并加载到本地
	@echo "构建ARM64镜像..."
	docker buildx build --platform linux/arm64 -t $(DOCKER_IMAGE):arm64 --load .

# =============================================================================
# 完整构建命令
# =============================================================================

.PHONY: build
build: frontend-build docker-build-multiplatform ## 完整构建：前端+后端多平台Docker镜像
	@echo "==============================================="
	@echo "完整构建完成！"
	@echo "==============================================="
	@echo "前端：已构建到 static/vue-dist/"
	@echo "Docker镜像："
	@echo "  - $(DOCKER_IMAGE):arm64-local (ARM64)"
	@echo "  - $(DOCKER_IMAGE):x86-local (AMD64)"
	@echo "==============================================="

.PHONY: build-arm
build-arm: frontend-build ## 构建ARM64版本（前端+Docker）
	@echo "构建ARM64版本..."
	docker build --platform linux/arm64 -t $(DOCKER_IMAGE):arm64-local .
	@echo "ARM64构建完成: $(DOCKER_IMAGE):arm64-local"

.PHONY: build-x86
build-x86: frontend-build ## 构建x86版本（前端+Docker）
	@echo "构建x86版本..."
	docker build --platform linux/amd64 -t $(DOCKER_IMAGE):x86-local .
	@echo "x86构建完成: $(DOCKER_IMAGE):x86-local"

.PHONY: docker-build-multiplatform
docker-build-multiplatform: ## 构建多平台Docker镜像（ARM64 + x86）
	@echo "构建多平台Docker镜像..."
	@echo "构建ARM64镜像..."
	docker build --platform linux/arm64 -t $(DOCKER_IMAGE):arm64-local .
	@echo "构建x86镜像..."
	docker build --platform linux/amd64 -t $(DOCKER_IMAGE):x86-local .
	@echo "多平台镜像构建完成"

.PHONY: build-and-run-arm
build-and-run-arm: build-arm ## 构建ARM64镜像并运行
	@echo "停止现有容器..."
	@docker stop $(shell docker ps -q --filter "publish=5002") 2>/dev/null || true
	@echo "启动ARM64容器..."
	docker run -d -p 5002:5002 $(DOCKER_IMAGE):arm64-local
	@echo "ARM64容器已启动，访问: http://localhost:5002"

.PHONY: build-and-run-x86
build-and-run-x86: build-x86 ## 构建x86镜像并运行（从.env读取配置）
	@echo "停止现有容器..."
	@docker stop $(shell docker ps -q --filter "publish=5002") 2>/dev/null || true
	@echo "启动x86容器（从.env读取配置）..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	docker run -d -p 5002:5002 \
		--add-host=host.docker.internal:host-gateway \
		--env-file .env \
		$(DOCKER_IMAGE):x86-local
	@echo "x86容器已启动，访问: http://localhost:5002"

.PHONY: docker-run
docker-run: ## 运行Docker容器（从.env文件读取环境变量）
	@echo "运行Docker容器（从.env文件读取环境变量）..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	docker run -p 5002:5002 --add-host=host.docker.internal:host-gateway --env-file .env $(DOCKER_IMAGE):$(DOCKER_TAG)

.PHONY: docker-run-secure
docker-run-secure: ## 安全方式运行Docker容器（推荐，从.env读取）
	@echo "安全方式运行Docker容器..."
	@[ -f .env ] || { echo "未找到 .env 文件，请先创建"; exit 1; }
	docker run -d --name inventory-container -p 5002:5002 \
		--add-host=host.docker.internal:host-gateway \
		--env-file .env \
		$(DOCKER_IMAGE):x86-local
	@echo "容器已启动，访问: http://localhost:5002"

.PHONY: docker-compose-up
docker-compose-up: ## 使用Docker Compose启动所有服务
	@echo "启动Docker Compose服务..."
	docker-compose up -d

.PHONY: docker-compose-down
docker-compose-down: ## 停止Docker Compose服务
	@echo "停止Docker Compose服务..."
	docker-compose down

.PHONY: docker-logs
docker-logs: ## 查看Docker Compose日志
	@echo "查看Docker Compose日志..."
	docker-compose logs -f

# =============================================================================
# 测试命令
# =============================================================================

.PHONY: test
test: ## 运行测试
	@echo "运行测试..."
	python3 -m pytest tests/ -v

.PHONY: test-cov
test-cov: ## 运行测试并生成覆盖率报告
	@echo "运行测试并生成覆盖率报告..."
	python3 -m pytest tests/ --cov=app --cov-report=html --cov-report=term

# =============================================================================
# 代码质量命令
# =============================================================================

.PHONY: lint
lint: ## 运行代码检查
	@echo "运行代码检查..."
	flake8 app/ tests/ --max-line-length=120 --ignore=E501,W503

.PHONY: format
format: ## 格式化代码
	@echo "格式化代码..."
	black app/ tests/ --line-length=120
	isort app/ tests/

# =============================================================================
# 部署命令
# =============================================================================

.PHONY: deploy-dev
deploy-dev: ## 部署到开发环境
	@echo "部署到开发环境..."
	$(MAKE) env-dev
	$(MAKE) install-dev
	$(MAKE) db-init
	@echo "开发环境部署完成"

.PHONY: deploy-docker
deploy-docker: ## 部署Docker环境
	@echo "部署Docker环境..."
	$(MAKE) env-docker
	$(MAKE) docker-build
	$(MAKE) docker-compose-up
	@echo "Docker环境部署完成"

# =============================================================================
# 监控和维护命令
# =============================================================================

.PHONY: status
status: ## 检查服务状态
	@echo "检查服务状态..."
	@echo "Docker Compose服务状态:"
	docker-compose ps

.PHONY: health
health: ## 健康检查
	@echo "执行健康检查..."
	curl -f http://localhost:5000/health || echo "服务未运行"

# =============================================================================
# 快速启动命令
# =============================================================================

.PHONY: dev
dev: ## 快速启动开发环境
	@echo "快速启动开发环境..."
	$(MAKE) env-dev
	$(MAKE) install-dev
	$(MAKE) run

.PHONY: docker-dev
docker-dev: ## 快速启动Docker开发环境
	@echo "快速启动Docker开发环境..."
	$(MAKE) env-docker
	$(MAKE) docker-compose-up
	@echo "Docker开发环境启动完成，访问 http://localhost:5000"

.PHONY: reset
reset: ## 重置整个环境
	@echo "重置整个环境..."
	$(MAKE) clean-all
	$(MAKE) docker-compose-down
	@echo "环境重置完成"

# =============================================================================
# ARM Mac 特殊命令
# =============================================================================

.PHONY: setup-arm
setup-arm: ## 设置ARM Mac开发环境
	@echo "设置ARM Mac开发环境..."
	@echo "检测系统架构..."
	@uname -m
	@echo "检测Python版本..."
	@python3 --version
	@echo "安装ARM兼容的依赖..."
	$(MAKE) install-dev
	@echo "ARM Mac开发环境设置完成"

.PHONY: docker-x86-deploy
docker-x86-deploy: ## 构建x86镜像并部署（用于生产环境）
	@echo "构建x86镜像并部署..."
	$(MAKE) docker-build
	$(MAKE) docker-compose-up
	@echo "x86环境部署完成"

# =============================================================================
# 帮助信息
# =============================================================================

.PHONY: info
info: ## 显示系统信息
	@echo "系统信息:"
	@echo "  OS: $(shell uname -s)"
	@echo "  架构: $(shell uname -m)"
	@echo "  Python: $(shell python3 --version 2>/dev/null || echo '未安装')"
	@echo "  Docker: $(shell docker --version 2>/dev/null || echo '未安装')"
	@echo "  Docker Compose: $(shell docker-compose --version 2>/dev/null || echo '未安装')"
	@echo "  当前目录: $(shell pwd)"
	@echo "  环境文件: $(shell ls -la .env 2>/dev/null || echo '未找到.env文件')"
