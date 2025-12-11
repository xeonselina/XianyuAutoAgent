"""
Gunicorn 配置文件
在导入任何其他模块之前进行 gevent monkey patching,避免 SSL 递归错误

注意：虽然 run.py 中也有 monkey patch，但 gunicorn 在不同时机会导入模块，
因此在配置文件中也需要尽早 patch。gevent 的 monkey patch 是幂等的，
多次调用不会有问题。
"""

# 在所有导入之前进行 monkey patch
import gevent.monkey
gevent.monkey.patch_all()

# Gunicorn 配置
bind = "0.0.0.0:5002"
workers = 4
worker_class = "gevent"
worker_connections = 1000
timeout = 120
keepalive = 2
max_requests = 1000
max_requests_jitter = 100

# 日志配置
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 预加载应用
# 注意：设置为 False 以避免在主进程中预加载应用导致的 SSL monkey patch 问题
# 每个 worker 会独立加载应用，确保 monkey patch 在导入模块之前完成
preload_app = False

# Worker 进程配置
def post_fork(server, worker):
    """Worker 进程启动后的钩子"""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def pre_fork(server, worker):
    """Worker 进程启动前的钩子"""
    pass

def when_ready(server):
    """服务器准备就绪时的钩子"""
    server.log.info("Gunicorn server is ready. Spawning workers")

def worker_int(worker):
    """Worker 收到 INT 或 QUIT 信号时的钩子"""
    worker.log.info(f"Worker received INT or QUIT signal (pid: {worker.pid})")

def worker_abort(worker):
    """Worker 被 SIGABRT 信号终止时的钩子"""
    worker.log.info(f"Worker received SIGABRT signal (pid: {worker.pid})")
