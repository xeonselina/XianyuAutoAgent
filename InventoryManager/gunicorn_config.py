"""
Gunicorn 配置文件
在导入任何其他模块之前进行 gevent monkey patching,避免 SSL 递归错误
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
preload_app = True

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
