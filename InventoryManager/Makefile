IMAGE ?= inventory-manager:saas-main-lite
PLATFORM ?= linux/amd64
IMAGE_REPOSITORY ?= docker.cnb.cool/tdcc-demo/jimmy/inventory-manager
GIT_SHA ?= $(shell git rev-parse --short=12 HEAD)
RELEASE_TIME ?= $(shell date +%Y%m%d-%H%M%S)
RELEASE_TAG ?= $(RELEASE_TIME)-$(GIT_SHA)
BACKUP_VERIFIED ?=
IMAGE_TAG ?=
APP_CONTAINER ?= inventory-manager-app
WORKER_CONTAINER ?= inventory-manager-worker
APP_PORT ?= 5002
ENV_FILE ?= .env

.DEFAULT_GOAL := help
.PHONY: help build push run-app run-worker worker-once build-push check-nas deploy-nas release-nas nas-status nas-logs

help:
	@echo "make build IMAGE=<image> PLATFORM=<platform>"
	@echo "make push IMAGE=<registry/image:tag>"
	@echo "make run-app IMAGE=<image> ENV_FILE=<path> APP_PORT=<port>"
	@echo "make run-worker IMAGE=<image> ENV_FILE=<path>"
	@echo "make worker-once IMAGE=<image> ENV_FILE=<path>"
	@echo "First NAS release setup: see ../docs/deployment/saas-main-lite.md"
	@echo "make deploy-nas IMAGE_TAG=<pushed-tag> BACKUP_VERIFIED=backup-verified"
	@echo "make release-nas BACKUP_VERIFIED=backup-verified"

build:
	docker build --platform "$(PLATFORM)" --tag "$(IMAGE)" .

push:
	docker push "$(IMAGE)"

run-app:
	docker run --rm --name "$(APP_CONTAINER)" --env-file "$(ENV_FILE)" \
		--publish "$(APP_PORT):5002" "$(IMAGE)"

run-worker:
	docker run --rm --name "$(WORKER_CONTAINER)" --env-file "$(ENV_FILE)" \
		--env "PROVISIONER_DATABASE_URL=" --env "TENCENTCLOUD_SECRET_ID=" --env "TENCENTCLOUD_SECRET_KEY=" \
		--env "TENCENT_SMS_SDK_APP_ID=" --env "TENCENT_SMS_SIGN_NAME=" --env "TENCENT_SMS_TEMPLATE_ID=" \
		"$(IMAGE)" python worker.py

worker-once:
	docker run --rm --name "$(WORKER_CONTAINER)" --env-file "$(ENV_FILE)" \
		--env "PROVISIONER_DATABASE_URL=" --env "TENCENTCLOUD_SECRET_ID=" --env "TENCENTCLOUD_SECRET_KEY=" \
		--env "TENCENT_SMS_SDK_APP_ID=" --env "TENCENT_SMS_SIGN_NAME=" --env "TENCENT_SMS_TEMPLATE_ID=" \
		"$(IMAGE)" python worker.py --once

build-push:
	docker buildx build --platform "$(PLATFORM)" \
		--tag "$(IMAGE_REPOSITORY):$(RELEASE_TAG)" --push .

check-nas:
	@IMAGE_REPOSITORY="$(IMAGE_REPOSITORY)" BACKUP_VERIFIED="$(BACKUP_VERIFIED)" \
		bash scripts/deploy_nas.sh check

deploy-nas:
	@test -n "$(IMAGE_TAG)" || { echo "IMAGE_TAG is required" >&2; exit 2; }
	@IMAGE_REPOSITORY="$(IMAGE_REPOSITORY)" IMAGE_TAG="$(IMAGE_TAG)" \
		BACKUP_VERIFIED="$(BACKUP_VERIFIED)" bash scripts/deploy_nas.sh deploy

release-nas:
	@test "$(BACKUP_VERIFIED)" = "backup-verified" || { echo "BACKUP_VERIFIED=backup-verified is required" >&2; exit 2; }
	@test -z "$$(git status --porcelain -- .)" || { echo "InventoryManager working tree must be clean" >&2; exit 2; }
	@$(MAKE) --no-print-directory build-push RELEASE_TAG="$(RELEASE_TAG)"
	@$(MAKE) --no-print-directory deploy-nas IMAGE_TAG="$(RELEASE_TAG)" BACKUP_VERIFIED="$(BACKUP_VERIFIED)"

nas-status:
	@IMAGE_REPOSITORY="$(IMAGE_REPOSITORY)" bash scripts/deploy_nas.sh status

nas-logs:
	@IMAGE_REPOSITORY="$(IMAGE_REPOSITORY)" bash scripts/deploy_nas.sh logs
