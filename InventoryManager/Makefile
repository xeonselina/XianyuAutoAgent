# 库存管理系统 Makefile
# 适用于 ARM Mac 开发，x86 Docker 部署

# 变量定义
APP_NAME = inventory-manager
DOCKER_IMAGE = inventory-manager
DOCKER_TAG = latest
DOCKER_PLATFORM = linux/amd64  # 目标平台为 x86_64
FLASK_APP = app.py
FLASK_ENV = development

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

# =============================================================================
# 数据库命令
# =============================================================================

.PHONY: init-db
init-db: ## 初始化数据库（从 .env 读取环境变量）
	@echo "初始化数据库（读取 .env）..."
	@[ -f .env ] || { echo "未找到 .env，请先创建并配置数据库连接信息（可参考 env.example）"; exit 1; }
	@set -a; . .env; set +a; python3 init_db.py

.PHONY: db-init
db-init: init-db ## 初始化数据库（兼容旧命令）

.PHONY: db-seed
db-seed: ## 填充示例数据
	@echo "填充示例数据..."
	export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && flask seed-data

# =============================================================================
# 应用运行命令
# =============================================================================

.PHONY: run
run: ## 运行开发服务器
	@echo "启动开发服务器..."
	export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && python3 app.py

.PHONY: run-scheduler
run-scheduler: ## 运行设备状态自动更新定时任务
	@echo "启动设备状态自动更新定时任务..."
	@echo "使用改进的启动脚本..."
	./start_scheduler.sh

.PHONY: run-scheduler-direct
run-scheduler-direct: ## 直接运行定时任务（不检查环境）
	@echo "直接启动设备状态自动更新定时任务..."
	export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && python3 device_status_scheduler.py

.PHONY: run-with-scheduler
run-with-scheduler: ## 同时运行Flask应用和定时任务（后台模式）
	@echo "同时启动Flask应用和定时任务..."
	@echo "启动Flask应用..."
	@export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && python3 app.py &
	@echo "启动定时任务..."
	@export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && python3 device_status_scheduler.py &
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

.PHONY: docker-run
docker-run: ## 运行Docker容器
	@echo "运行Docker容器..."
	docker run -p 5000:5000 --env-file .env $(DOCKER_IMAGE):$(DOCKER_TAG)

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
