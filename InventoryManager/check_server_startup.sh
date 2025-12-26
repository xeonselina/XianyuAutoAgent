#!/bin/bash
# 服务器启动方式诊断脚本

echo "=== 容器启动方式诊断 ==="
echo ""

echo "1. 检查容器启动命令:"
docker inspect $(docker ps -q --filter "publish=5002") --format='{{.Config.Cmd}}'
echo ""

echo "2. 检查容器入口点:"
docker inspect $(docker ps -q --filter "publish=5002") --format='{{.Config.Entrypoint}}'
echo ""

echo "3. 检查容器日志驱动:"
docker inspect $(docker ps -q --filter "publish=5002") --format='{{.HostConfig.LogConfig.Type}}'
echo ""

echo "4. 检查是否使用 gunicorn:"
docker exec $(docker ps -q --filter "publish=5002") ps aux | grep -E "gunicorn|python"
echo ""

echo "5. 查看最近的容器日志:"
docker logs --tail 50 $(docker ps -q --filter "publish=5002")
echo ""

echo "6. 检查 gunicorn_config.py 是否存在:"
docker exec $(docker ps -q --filter "publish=5002") ls -la /app/gunicorn_config.py
echo ""

echo "7. 检查容器中的 Python 进程:"
docker exec $(docker ps -q --filter "publish=5002") ps -ef
