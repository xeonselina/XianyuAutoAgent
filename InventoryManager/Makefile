IMAGE ?= inventory-manager:saas-main-lite
PLATFORM ?= linux/amd64
APP_CONTAINER ?= inventory-manager-app
WORKER_CONTAINER ?= inventory-manager-worker
APP_PORT ?= 5002
ENV_FILE ?= .env

.DEFAULT_GOAL := help
.PHONY: help build push run-app run-worker worker-once

help:
	@echo "make build IMAGE=<image> PLATFORM=<platform>"
	@echo "make push IMAGE=<registry/image:tag>"
	@echo "make run-app IMAGE=<image> ENV_FILE=<path> APP_PORT=<port>"
	@echo "make run-worker IMAGE=<image> ENV_FILE=<path>"
	@echo "make worker-once IMAGE=<image> ENV_FILE=<path>"

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
