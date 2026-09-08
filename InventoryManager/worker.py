"""Single-process worker for scheduled shipping and Xianyu reconciliation."""

import argparse
import logging
import os
import time
from datetime import datetime

import schedule
from sqlalchemy import select, text

from app import create_app, db
from app.control.models import Tenant
from app.tenant_context import bind_tenant, clear_tenant_binding, reset_tenant
from app.utils.scheduler_tasks import (
    process_scheduled_shipments_for_current_tenant,
    reconcile_active_shops_for_current_tenant,
)


LOCK_NAME = "inventory-manager-worker-v1"
logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, app, scheduler=None, clock=None, sleeper=None):
        self.app = app
        self.control_store = app.extensions["control_store"]
        self.tenant_registry = app.extensions["tenant_engine_registry"]
        self.scheduler = scheduler or schedule.Scheduler()
        self.clock = clock or datetime.utcnow
        self.sleeper = sleeper or time.sleep
        self._lock_connection = None

    def acquire_lock(self):
        connection = self.control_store.engine.connect()
        try:
            connection.execute(text("SET SESSION wait_timeout = 86400"))
            acquired = connection.execute(
                text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}
            ).scalar_one()
            self._connection_id = connection.execute(text("SELECT CONNECTION_ID()")).scalar_one()
        except Exception:
            connection.close()
            raise
        if acquired != 1:
            connection.close()
            return False
        self._lock_connection = connection
        return True

    def _eligible_tenants(self):
        with self.control_store.session() as session:
            return list(session.scalars(
                select(Tenant).where(
                    Tenant.provisioning_status == "active",
                    Tenant.status == "active",
                    Tenant.expires_at > self.clock(),
                ).order_by(Tenant.id)
            ))

    def _assert_lock_owned(self):
        if self._lock_connection is None:
            return
        owner = self._lock_connection.execute(
            text("SELECT IS_USED_LOCK(:name)"),
            {"name": LOCK_NAME},
        ).scalar_one()
        if owner != self._connection_id:
            raise RuntimeError("lock ownership lost")

    def _run_cycle(self, task):
        self._assert_lock_owned()
        for tenant in self._eligible_tenants():
            self._assert_lock_owned()
            context = self.app.app_context()
            try: context.push()
            except Exception as exc: logger.error("Worker租户上下文异常，租户ID: %s，类型: %s", tenant.id, type(exc).__name__); continue
            else:
                token = None
                try:
                    token = bind_tenant(
                        tenant.id, self.tenant_registry.get(tenant)
                    )
                    task()
                except Exception as exc:
                    logger.error(
                        "Worker租户任务异常，租户ID: %s，类型: %s",
                        tenant.id, type(exc).__name__,
                    )
                finally:
                    if token is not None:
                        try: db.session.remove()
                        except Exception as exc: logger.error("Worker租户会话清理异常，租户ID: %s，类型: %s", tenant.id, type(exc).__name__)
                        try: reset_tenant(token)
                        except Exception as exc: clear_tenant_binding(); logger.error("Worker租户绑定清理异常，租户ID: %s，类型: %s", tenant.id, type(exc).__name__)
            try: context.pop()
            except Exception as exc: logger.error("Worker租户上下文清理异常，租户ID: %s，类型: %s", tenant.id, type(exc).__name__)

    def run_scheduled_shipping_cycle(self):
        self._run_cycle(process_scheduled_shipments_for_current_tenant)

    def run_xianyu_sync_cycle(self):
        self._run_cycle(reconcile_active_shops_for_current_tenant)

    def register_jobs(self):
        self.scheduler.every(60).seconds.do(
            self.run_scheduled_shipping_cycle
        )
        self.scheduler.every(180).seconds.do(self.run_xianyu_sync_cycle)

    def shutdown(self):
        connection, self._lock_connection = self._lock_connection, None
        if connection is not None:
            try:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME}
                )
            except Exception as exc:
                logger.error("Worker锁释放异常，类型: %s", type(exc).__name__)
            finally:
                connection.close()
        try:
            self.tenant_registry.dispose_all()
        finally:
            self.control_store.dispose()

    def run_forever(self):
        try:
            if not self.acquire_lock():
                return False
            self.run_scheduled_shipping_cycle()
            self.run_xianyu_sync_cycle()
            self.register_jobs()
            while True:
                self.scheduler.run_pending()
                self.sleeper(0.5)
        except KeyboardInterrupt:
            return True
        finally:
            self.shutdown()

    def run_once(self):
        try:
            if not self.acquire_lock():
                return False
            self.run_scheduled_shipping_cycle()
            self.run_xianyu_sync_cycle()
            return True
        finally:
            self.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inventory Manager worker")
    parser.add_argument(
        "--once", action="store_true",
        help="run shipping and Xianyu cycles once, then exit",
    )
    arguments = parser.parse_args(argv)
    config_name = os.environ.get("FLASK_ENV", "production")
    worker = Worker(create_app(config_name, worker_mode=True))
    return worker.run_once() if arguments.once else worker.run_forever()


if __name__ == "__main__":
    main()
