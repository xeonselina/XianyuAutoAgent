# 甘特图档期一键重排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在甘特图中增加基于 OR-Tools 的两步档期重排，在同型号、使用中设备内压缩未来未寄出主 rental，并安全保存接力关系、保护全部子 rental，同时修复查找档期遗漏生命周期状态过滤的问题。

**Architecture:** 后端把设备资格、接力关系、纯求解器和数据库编排拆成独立单元。预览使用签名快照令牌且零写入；执行锁定全部相关行，用固定预览映射重新做可行性验证，并在一个事务中修改接力元数据、符合条件的主 rental `device_id` 和审计日志。前端使用独立的两步弹窗组件，通过 Pinia store 调用 analyze、preview、execute 三个接口。

**Tech Stack:** Python 3.10、Flask 2.3、Flask-SQLAlchemy 3、MySQL 8、Alembic、OR-Tools CP-SAT 9.15、pytest、Vue 3、Pinia、Element Plus、Vitest、Docker buildx。

## Global Constraints

- 只移动 `parent_rental_id IS NULL`、`status = not_shipped`、`DATE(ship_out_time) >= Asia/Shanghai 今天` 且 `model_id` 非空的主 rental。
- 只修改符合条件的主 rental `device_id`；日期、物流时间、状态和全部子 rental 字段保持不变。
- 子 rental 永远不参与设备优化，附件设备及父子关系保持不变。
- 只分配到相同 `model_id`、`is_accessory = false`、`status = online`、`lifecycle_status = active` 的设备。
- 普通档期允许前单收回日与后单寄出日相同，不允许后单寄出日更早；人工确认的接力链除外。
- `scheduled_for_shipping`、已寄出、进行中及其他不可移动主 rental 固定在原设备。
- 必须先预览后执行；第二步直接执行，不增加第三步确认页。
- 每个型号最多求解 3 秒，`num_search_workers = 1`，固定随机种子。
- 自动化测试不得加载生产 `.env` 或连接生产业务库；可连接 `192.*` 实例中名称含 `test` 的独立测试库，但账号只能访问该测试库。
- 经单独授权可只读 dump 生产业务库；dump 不强制脱敏，但不得提交 Git 或对外暴露。
- 任何快照、完整性、可行性或数据库失败都必须回滚整次执行，不能产生部分更新。

## 文件结构

- `app/models/device.py`：提供统一的“在线且使用中”设备查询入口。
- `app/models/rental_relay_binding.py`：持久化不可分叉的前序/后序接力关系。
- `app/services/gantt/reorder_types.py`：纯数据类型和 API 枚举，不访问数据库。
- `app/services/gantt/reorder_solver.py`：纯 OR-Tools 模型、分层目标和固定映射可行性校验。
- `app/services/gantt/reorder_service.py`：查询数据、构建接力块、快照签名、预览和原子执行。
- `app/handlers/gantt_handlers.py`、`app/routes/gantt_api.py`：三个 HTTP 接口及错误映射。
- `frontend/src/components/ScheduleReorderDialog.vue`：两步接力确认和预览执行界面。
- `frontend/src/stores/gantt.ts`：重排类型和 API 调用。
- `frontend/src/components/GanttChart.vue`：工具栏入口及成功后刷新。
- `tests/support/test_database.py`、`docker-compose.test.yml`：测试库安全保护和隔离 MySQL。
- `tests/unit/test_gantt_reorder_*.py`：设备资格、接力和纯求解器测试。
- `tests/integration/test_gantt_reorder_api.py`：预览、行锁、事务和回滚测试。
- `frontend/tests/unit/components/ScheduleReorderDialog.spec.ts`、`frontend/tests/unit/stores/gantt.spec.ts`：两步 UI 和 store 测试。

## 规格覆盖索引

- 可移动资格、使用中设备及查找档期 bug：Task 1。
- 永久接力、不可分叉链和人工重叠确认：Task 2、Task 4、Task 5。
- 同型号隔离、同日衔接、固定锚点、压缩目标和超时状态：Task 3。
- 零写入预览、十分钟签名令牌和逐笔客户信息：Task 4、Task 6。
- 行锁、固定映射验证、单事务回滚和审计：Task 5。
- 父子 rental 集合、字段和附件设备不变：Task 5 的成功、过期和注入失败测试。
- 两步 UI、返回修改接力且无第三步：Task 6。
- 生产库隔离、`192.*` 独立测试库和专用账号权限：Task 1、Task 7。
- amd64/arm64 容器化 OR-Tools：Task 3、Task 7。

---

### Task 1: 隔离测试环境并修复查找档期设备资格

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/support/__init__.py`
- Create: `tests/support/test_database.py`
- Create: `tests/unit/test_gantt_device_eligibility.py`
- Create: `docker-compose.test.yml`
- Modify: `app/__init__.py:8-14`
- Modify: `app/models/device.py:78-88`
- Modify: `app/services/gantt/gantt_service.py:270-287`

**Interfaces:**
- Produces: `Device.in_service_query(is_accessory: bool | None = None) -> BaseQuery`
- Produces: `build_mysql_test_config() -> type[TestingConfig]`
- Produces: `assert_test_database_url(url: str) -> sqlalchemy.engine.URL`
- Produces: `assert_current_user_has_test_only_grants(connection, database_name: str) -> None`

- [ ] **Step 1: 写测试库保护的失败测试**

```python
# tests/unit/test_gantt_device_eligibility.py
import pytest

from tests.support.test_database import assert_test_database_url


def test_rejects_production_database_name(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    with pytest.raises(RuntimeError, match="数据库名必须包含 test"):
        assert_test_database_url(
            "mysql+pymysql://inventory_test:secret@192.168.50.132/inventory_db"
        )


def test_accepts_test_database_on_192_instance(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    url = assert_test_database_url(
        "mysql+pymysql://inventory_test:secret@192.168.50.132/inventory_reorder_test"
    )
    assert url.database == "inventory_reorder_test"
```

- [ ] **Step 2: 运行测试并确认因保护模块不存在而失败**

Run: `TESTING=true pytest tests/unit/test_gantt_device_eligibility.py -v`

Expected: FAIL，包含 `ModuleNotFoundError: No module named 'tests.support'`。

- [ ] **Step 3: 实现测试库保护并阻止测试加载生产 `.env`**

```python
# tests/conftest.py
import os

os.environ["TESTING"] = "true"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_HOST", None)

import pytest

from app import create_app, db
from config import TestingConfig
from tests.support.test_database import (
    assert_current_user_has_test_only_grants,
    build_mysql_test_config,
)


@pytest.fixture
def app():
    config_class = build_mysql_test_config() if os.environ.get("TEST_DATABASE_URL") else TestingConfig
    app = create_app(config_class)
    with app.app_context():
        db.create_all()
        if os.environ.get("TEST_DATABASE_URL"):
            database_name = db.engine.url.database
            with db.engine.connect() as connection:
                assert_current_user_has_test_only_grants(connection, database_name)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()
```

```python
# tests/support/test_database.py
import os

from sqlalchemy.engine import make_url
from config import TestingConfig


def assert_test_database_url(url: str):
    if os.environ.get("TESTING", "").lower() != "true":
        raise RuntimeError("必须设置 TESTING=true")
    parsed = make_url(url)
    if "test" not in (parsed.database or "").lower():
        raise RuntimeError("测试数据库名必须包含 test")
    return parsed


def build_mysql_test_config():
    raw_url = os.environ["TEST_DATABASE_URL"]
    parsed = assert_test_database_url(raw_url)

    class MySQLTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = parsed.render_as_string(hide_password=False)
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    return MySQLTestingConfig


def assert_current_user_has_test_only_grants(connection, database_name):
    grants = [row[0] for row in connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER").all()]
    allowed_global = "GRANT USAGE ON *.*"
    for grant in grants:
        if grant.startswith(allowed_global):
            continue
        if f"ON `{database_name}`.*" not in grant and f"ON {database_name}.*" not in grant:
            raise RuntimeError("测试数据库账号拥有测试库以外的权限")
```

```python
# app/__init__.py（替换无条件 load_dotenv）
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.environ.get('TESTING', '').lower() != 'true':
    load_dotenv(os.path.join(_BASE_DIR, '.env'))
```

- [ ] **Step 4: 为设备资格和查找档期写失败测试**

```python
# 追加到 tests/unit/test_gantt_device_eligibility.py
from datetime import date, timedelta

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.services.gantt.gantt_service import GanttService


@pytest.mark.parametrize("lifecycle", ["sold", "damaged", "decommissioned", "retired"])
def test_find_slot_excludes_online_non_active_device(app, lifecycle):
    with app.app_context():
        model = DeviceModel(name="eligibility", display_name="资格测试", is_active=True)
        db.session.add(model)
        db.session.flush()
        db.session.add(Device(
            name=f"设备-{lifecycle}", model="eligibility", model_id=model.id,
            is_accessory=False, status="online", lifecycle_status=lifecycle,
        ))
        db.session.commit()

        result = GanttService.find_available_slot(
            date.today() + timedelta(days=5),
            date.today() + timedelta(days=8),
            1,
            model.id,
            False,
        )

        assert result is None
```

- [ ] **Step 5: 运行资格测试并确认它返回非 active 设备**

Run: `TESTING=true pytest tests/unit/test_gantt_device_eligibility.py -v`

Expected: 参数化用例 FAIL，`result` 包含生命周期非 active 设备。

- [ ] **Step 6: 实现统一设备资格查询并在查找档期中复用**

```python
# app/models/device.py
@classmethod
def in_service_query(cls, is_accessory=None):
    query = cls.query.filter(
        cls.status == 'online',
        cls.lifecycle_status == 'active',
    )
    if is_accessory is not None:
        query = query.filter(cls.is_accessory.is_(is_accessory))
    return query
```

```python
# app/services/gantt/gantt_service.py（替换两条 Device.query.filter 分支）
devices_query = Device.in_service_query(is_accessory=is_accessory)
if model_filter and str(model_filter).strip():
    try:
        model_id = int(model_filter)
    except (TypeError, ValueError):
        current_app.logger.error("无效的 model_id: %s", model_filter)
        return None
    devices_query = devices_query.filter(Device.model_id == model_id)
devices = devices_query.all()
```

- [ ] **Step 7: 增加隔离 MySQL Compose 配置**

```yaml
# docker-compose.test.yml
services:
  mysql-test:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: test_root_password
      MYSQL_DATABASE: inventory_reorder_test
      MYSQL_USER: inventory_test
      MYSQL_PASSWORD: inventory_test_password
    ports:
      - "3307:3306"
    tmpfs:
      - /var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-ptest_root_password"]
      interval: 2s
      timeout: 2s
      retries: 30
```

- [ ] **Step 8: 运行测试并提交**

Run: `TESTING=true pytest tests/unit/test_gantt_device_eligibility.py -v`

Expected: PASS。

```bash
git add app/__init__.py app/models/device.py app/services/gantt/gantt_service.py tests/conftest.py tests/support tests/unit/test_gantt_device_eligibility.py docker-compose.test.yml
git commit -m "fix: restrict rental slots to active devices"
```

---

### Task 2: 建立永久接力关系和重叠分析

**Files:**
- Create: `app/models/rental_relay_binding.py`
- Create: `migrations/versions/20260711_add_rental_relay_bindings.py`
- Create: `app/services/gantt/reorder_types.py`
- Create: `tests/unit/test_gantt_relay_analysis.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/rental.py:70-75`
- Create: `app/services/gantt/reorder_service.py`

**Interfaces:**
- Produces: `RelayDecision(predecessor_rental_id: int, successor_rental_id: int, action: Literal['keep', 'separate'])`
- Produces: `GanttReorderService.analyze(today: date | None = None) -> dict`
- Produces: `RentalRelayBinding.validate_pair(predecessor: Rental, successor: Rental) -> None`

- [ ] **Step 1: 写接力模型和分析的失败测试**

```python
# tests/unit/test_gantt_relay_analysis.py
from datetime import date, datetime, time, timedelta

import pytest

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.services.gantt.reorder_service import GanttReorderService


def make_rental(device_id, rental_id_offset, ship_out_day, ship_in_day):
    return Rental(
        device_id=device_id,
        start_date=ship_out_day + timedelta(days=1),
        end_date=ship_in_day - timedelta(days=1),
        ship_out_time=datetime.combine(ship_out_day, time(19)),
        ship_in_time=datetime.combine(ship_in_day, time(12)),
        customer_name=f"客户{rental_id_offset}",
        customer_phone=f"1380000{rental_id_offset:04d}",
        destination="测试地址",
        status="not_shipped",
    )


def test_analyze_requires_confirmation_for_multi_day_overlap(app):
    with app.app_context():
        model = DeviceModel(name="relay", display_name="接力测试", is_active=True)
        db.session.add(model)
        db.session.flush()
        device = Device(name="R-01", model="relay", model_id=model.id,
                        is_accessory=False, status="online", lifecycle_status="active")
        db.session.add(device)
        db.session.flush()
        first = make_rental(device.id, 1, date(2026, 7, 12), date(2026, 7, 18))
        second = make_rental(device.id, 2, date(2026, 7, 17), date(2026, 7, 23))
        db.session.add_all([first, second])
        db.session.commit()

        result = GanttReorderService.analyze(today=date(2026, 7, 11))

        assert result["overlaps"][0]["status"] == "needs_confirmation"
        assert result["overlaps"][0]["overlap_days"] == 1
        assert result["overlaps"][0]["predecessor"]["customer_phone"] == first.customer_phone
        assert result["overlaps"][0]["successor"]["destination"] == second.destination


def test_binding_rejects_child_rental(app):
    with app.app_context():
        parent = Rental(id=1, device_id=1, start_date=date.today(), end_date=date.today(), customer_name="父")
        child = Rental(id=2, device_id=2, start_date=date.today(), end_date=date.today(), customer_name="子", parent_rental_id=1)
        with pytest.raises(ValueError, match="只允许主 rental"):
            RentalRelayBinding.validate_pair(parent, child)
```

- [ ] **Step 2: 运行并确认模块不存在**

Run: `TESTING=true pytest tests/unit/test_gantt_relay_analysis.py -v`

Expected: FAIL，缺少 `rental_relay_binding` 或 `reorder_service`。

- [ ] **Step 3: 实现接力模型和迁移**

```python
# app/models/rental_relay_binding.py
from datetime import datetime

from app import db


class RentalRelayBinding(db.Model):
    __tablename__ = "rental_relay_bindings"
    __table_args__ = (
        db.UniqueConstraint("predecessor_rental_id", name="uq_relay_predecessor"),
        db.UniqueConstraint("successor_rental_id", name="uq_relay_successor"),
        db.CheckConstraint("predecessor_rental_id <> successor_rental_id", name="ck_relay_distinct"),
    )

    id = db.Column(db.Integer, primary_key=True)
    predecessor_rental_id = db.Column(
        db.Integer, db.ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False
    )
    successor_rental_id = db.Column(
        db.Integer, db.ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False
    )
    confirmed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    predecessor = db.relationship("Rental", foreign_keys=[predecessor_rental_id])
    successor = db.relationship("Rental", foreign_keys=[successor_rental_id])

    @staticmethod
    def validate_pair(predecessor, successor):
        if predecessor.parent_rental_id is not None or successor.parent_rental_id is not None:
            raise ValueError("接力绑定只允许主 rental")
        if predecessor.device_id != successor.device_id:
            raise ValueError("接力 rental 必须位于同一设备")
        if not predecessor.device or not successor.device:
            raise ValueError("接力 rental 缺少设备")
        if predecessor.device.model_id != successor.device.model_id:
            raise ValueError("接力 rental 必须属于同一型号")
        if not predecessor.ship_out_time or not successor.ship_out_time:
            raise ValueError("接力 rental 缺少寄出时间")
        if predecessor.ship_out_time >= successor.ship_out_time:
            raise ValueError("接力顺序不正确")
```

```python
# migrations/versions/20260711_add_rental_relay_bindings.py
from alembic import op
import sqlalchemy as sa

revision = "20260711_relay_bindings"
down_revision = "20260622_lens_combo"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rental_relay_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("predecessor_rental_id", sa.Integer(), nullable=False),
        sa.Column("successor_rental_id", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["predecessor_rental_id"], ["rentals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["successor_rental_id"], ["rentals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("predecessor_rental_id", name="uq_relay_predecessor"),
        sa.UniqueConstraint("successor_rental_id", name="uq_relay_successor"),
        sa.CheckConstraint("predecessor_rental_id <> successor_rental_id", name="ck_relay_distinct"),
    )


def downgrade():
    op.drop_table("rental_relay_bindings")
```

- [ ] **Step 4: 定义重排数据类型和只读重叠分析**

```python
# app/services/gantt/reorder_types.py
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RelayDecision:
    predecessor_rental_id: int
    successor_rental_id: int
    action: Literal["keep", "separate"]


@dataclass(frozen=True)
class ScheduleBlock:
    key: str
    rental_ids: tuple[int, ...]
    model_id: int
    start_day: int
    end_day: int
    current_device_id: int
    allowed_device_ids: tuple[int, ...]
    fixed: bool
```

```python
# app/services/gantt/reorder_service.py（第一阶段）
from datetime import date

from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding


class GanttReorderService:
    @staticmethod
    def _customer(rental):
        return {
            "id": rental.id,
            "customer_name": rental.customer_name,
            "customer_phone": rental.customer_phone,
            "destination": rental.destination,
            "ship_out_time": rental.ship_out_time.isoformat(),
            "ship_in_time": rental.ship_in_time.isoformat(),
        }

    @classmethod
    def analyze(cls, today=None):
        today = today or date.today()
        bindings = {
            (item.predecessor_rental_id, item.successor_rental_id): item
            for item in RentalRelayBinding.query.all()
        }
        rentals = Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != "cancelled",
            Rental.ship_out_time.isnot(None),
            Rental.ship_in_time.isnot(None),
        ).order_by(Rental.device_id, Rental.ship_out_time, Rental.id).all()
        by_device = {}
        for rental in rentals:
            by_device.setdefault(rental.device_id, []).append(rental)
        overlaps = []
        for device_rentals in by_device.values():
            for predecessor, successor in zip(device_rentals, device_rentals[1:]):
                overlap_days = (predecessor.ship_in_time.date() - successor.ship_out_time.date()).days
                if overlap_days <= 0:
                    continue
                binding = bindings.get((predecessor.id, successor.id))
                overlaps.append({
                    "pair_key": f"{predecessor.id}:{successor.id}",
                    "status": "bound" if binding else "needs_confirmation",
                    "binding_id": binding.id if binding else None,
                    "overlap_days": overlap_days,
                    "predecessor": cls._customer(predecessor),
                    "successor": cls._customer(successor),
                })
        return {"today": today.isoformat(), "overlaps": overlaps}
```

- [ ] **Step 5: 导出模型、运行测试和迁移校验**

```python
# app/models/__init__.py
from .rental_relay_binding import RentalRelayBinding

__all__ = [
    'Device', 'Rental', 'AuditLog', 'DeviceModel', 'RentalStatistics',
    'InspectionRecord', 'InspectionCheckItem', 'RentalRelayBinding',
]
```

Run: `TESTING=true pytest tests/unit/test_gantt_relay_analysis.py -v`

Expected: PASS。

Run: `python3 -m flask db heads`

Expected: 包含 `20260711_relay_bindings (head)`。

- [ ] **Step 6: 提交**

```bash
git add app/models app/services/gantt/reorder_types.py app/services/gantt/reorder_service.py migrations/versions/20260711_add_rental_relay_bindings.py tests/unit/test_gantt_relay_analysis.py
git commit -m "feat: persist rental relay bindings"
```

---

### Task 3: 实现纯 OR-Tools 分型号求解器

**Files:**
- Create: `app/services/gantt/reorder_solver.py`
- Create: `tests/unit/test_gantt_reorder_solver.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ScheduleBlock`
- Produces: `SolverResult(status: str, assignments: dict[int, int], used_devices: int, total_gap_days: int, changed_rentals: int)`
- Produces: `GanttReorderSolver.solve(blocks, candidate_device_ids, time_limit_seconds=3.0) -> SolverResult`
- Produces: `GanttReorderSolver.validate_assignment(blocks, assignments) -> None`

- [ ] **Step 1: 写同型号、同日衔接、固定锚点和压缩目标的失败测试**

```python
# tests/unit/test_gantt_reorder_solver.py
from app.services.gantt.reorder_solver import GanttReorderSolver
from app.services.gantt.reorder_types import ScheduleBlock


def block(key, rental_id, start, end, current, allowed, fixed=False):
    return ScheduleBlock(
        key=key, rental_ids=(rental_id,), model_id=1,
        start_day=start, end_day=end, current_device_id=current,
        allowed_device_ids=tuple(allowed), fixed=fixed,
    )


def test_solver_compacts_touching_blocks_on_one_device():
    blocks = [
        block("1", 1, 10, 15, 1, [1, 2]),
        block("2", 2, 15, 20, 2, [1, 2]),
        block("3", 3, 20, 25, 2, [1, 2]),
    ]
    result = GanttReorderSolver.solve(blocks, [1, 2])
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert len(set(result.assignments.values())) == 1
    assert result.total_gap_days == 0


def test_solver_keeps_fixed_block_and_avoids_overlap():
    blocks = [
        block("fixed", 1, 10, 20, 1, [1], fixed=True),
        block("move", 2, 15, 25, 2, [1, 2]),
    ]
    result = GanttReorderSolver.solve(blocks, [1, 2])
    assert result.assignments == {1: 1, 2: 2}


def test_validator_rejects_missing_rental():
    blocks = [block("1", 1, 10, 15, 1, [1, 2])]
    try:
        GanttReorderSolver.validate_assignment(blocks, {})
    except ValueError as exc:
        assert "恰好映射一次" in str(exc)
    else:
        raise AssertionError("缺失 rental 必须被拒绝")
```

- [ ] **Step 2: 运行并确认求解器模块不存在**

Run: `TESTING=true pytest tests/unit/test_gantt_reorder_solver.py -v`

Expected: FAIL，缺少 `reorder_solver`。

- [ ] **Step 3: 固定 OR-Tools 依赖并实现求解结果类型**

```text
# requirements.txt
ortools==9.15.6755
```

```python
# app/services/gantt/reorder_solver.py
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class SolverResult:
    status: str
    assignments: dict[int, int]
    used_devices: int
    total_gap_days: int
    changed_rentals: int
```

- [ ] **Step 4: 实现可选区间、NoOverlap 和分层目标**

```python
# app/services/gantt/reorder_solver.py
class GanttReorderSolver:
    STATUS_NAMES = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
    }

    @classmethod
    def solve(cls, blocks, device_ids, time_limit_seconds=3.0):
        model = cp_model.CpModel()
        horizon_end = max(block.end_day for block in blocks) + 1
        x, intervals = {}, {device_id: [] for device_id in device_ids}

        for block in blocks:
            choices = []
            for device_id in block.allowed_device_ids:
                chosen = model.new_bool_var(f"block_{block.key}_device_{device_id}")
                x[(block.key, device_id)] = chosen
                interval = model.new_optional_interval_var(
                    block.start_day,
                    block.end_day - block.start_day,
                    block.end_day,
                    chosen,
                    f"interval_{block.key}_{device_id}",
                )
                intervals[device_id].append(interval)
                choices.append(chosen)
                if block.fixed:
                    model.add(chosen == (device_id == block.current_device_id))
            model.add_exactly_one(choices)

        for device_id in device_ids:
            model.add_no_overlap(intervals[device_id])

        movable_x = {
            device_id: [x[(block.key, device_id)] for block in blocks
                        if not block.fixed and (block.key, device_id) in x]
            for device_id in device_ids
        }
        used = {}
        for device_id, choices in movable_x.items():
            used[device_id] = model.new_bool_var(f"used_{device_id}")
            if choices:
                model.add_max_equality(used[device_id], choices)
            else:
                model.add(used[device_id] == 0)

        min_start, max_end, assigned_duration, gap = {}, {}, {}, {}
        for device_id in device_ids:
            choices = [(block, x[(block.key, device_id)]) for block in blocks
                       if (block.key, device_id) in x]
            any_block = model.new_bool_var(f"any_{device_id}")
            model.add_max_equality(any_block, [chosen for _, chosen in choices])
            min_start[device_id] = model.new_int_var(0, horizon_end, f"min_{device_id}")
            max_end[device_id] = model.new_int_var(0, horizon_end, f"max_{device_id}")
            model.add_min_equality(
                min_start[device_id],
                [block.start_day * chosen + horizon_end * (1 - chosen) for block, chosen in choices],
            )
            model.add_max_equality(
                max_end[device_id],
                [block.end_day * chosen for block, chosen in choices],
            )
            assigned_duration[device_id] = sum(
                (block.end_day - block.start_day) * chosen for block, chosen in choices
            )
            gap[device_id] = model.new_int_var(0, horizon_end, f"gap_{device_id}")
            model.add(
                gap[device_id] == max_end[device_id] - min_start[device_id]
                - assigned_duration[device_id]
            ).only_enforce_if(any_block)
            model.add(gap[device_id] == 0).only_enforce_if(any_block.Not())

        moves = []
        for block in blocks:
            if block.fixed:
                continue
            for device_id in block.allowed_device_ids:
                if device_id != block.current_device_id:
                    moves.append(len(block.rental_ids) * x[(block.key, device_id)])

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 20260711
        deadline = monotonic() + time_limit_seconds

        objectives = [sum(used.values()), sum(gap.values()), sum(moves)]
        status = cp_model.UNKNOWN
        for objective in objectives:
            solver.parameters.max_time_in_seconds = max(0.05, deadline - monotonic())
            model.minimize(objective)
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return SolverResult(cls.STATUS_NAMES[status], {}, 0, 0, 0)
            model.add(objective == int(solver.objective_value))

        assignments = {}
        for block in blocks:
            target = next(
                device_id for device_id in block.allowed_device_ids
                if solver.boolean_value(x[(block.key, device_id)])
            )
            for rental_id in block.rental_ids:
                assignments[rental_id] = target
        cls.validate_assignment(blocks, assignments)
        return SolverResult(
            cls.STATUS_NAMES[status], assignments,
            sum(solver.value(value) for value in used.values()),
            sum(solver.value(value) for value in gap.values()),
            sum(solver.value(value) for value in moves),
        )

    @staticmethod
    def validate_assignment(blocks, assignments):
        expected = {rental_id for block in blocks for rental_id in block.rental_ids}
        if set(assignments) != expected:
            raise ValueError("每个 rental 必须恰好映射一次")
        for block in blocks:
            targets = {assignments[rental_id] for rental_id in block.rental_ids}
            if len(targets) != 1 or not targets.issubset(block.allowed_device_ids):
                raise ValueError(f"档期块 {block.key} 的设备映射非法")
            if block.fixed and targets != {block.current_device_id}:
                raise ValueError(f"固定档期块 {block.key} 被移动")
```

- [ ] **Step 5: 运行求解器测试并补充接力链块测试**

```python
# 追加到 tests/unit/test_gantt_reorder_solver.py
def test_relay_block_members_stay_on_same_device():
    relay = ScheduleBlock(
        key="relay:1:2", rental_ids=(1, 2), model_id=1,
        start_day=10, end_day=25, current_device_id=1,
        allowed_device_ids=(1, 2), fixed=False,
    )
    result = GanttReorderSolver.solve([relay], [1, 2])
    assert result.assignments[1] == result.assignments[2]
```

Run: `TESTING=true pytest tests/unit/test_gantt_reorder_solver.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt app/services/gantt/reorder_solver.py tests/unit/test_gantt_reorder_solver.py
git commit -m "feat: optimize gantt schedules with OR-Tools"
```

---

### Task 4: 实现零写入预览、签名快照和 API

**Files:**
- Create: `tests/support/reorder_fixtures.py`
- Create: `tests/integration/test_gantt_reorder_api.py`
- Modify: `app/services/gantt/reorder_service.py`
- Modify: `app/handlers/gantt_handlers.py`
- Modify: `app/routes/gantt_api.py`

**Interfaces:**
- Consumes: `list[RelayDecision]`
- Produces: `POST /api/gantt/reorder/analyze`
- Produces: `POST /api/gantt/reorder/preview` with `{decisions: [...]}`
- Produces: preview `{token, models, changes, skipped, overlaps}`
- Produces: `_validate_decisions(decisions: list[dict]) -> list[dict]`，拒绝重复 pair、非法 action 和缺失 ID，并按前序/后序 ID 排序。
- Produces: `_load_reorder_graph(today: date, lock: bool) -> tuple[list[Rental], list[Device], list[RentalRelayBinding]]`，一次加载相关主 rental、全部子 rental、设备和绑定；`lock=True` 时所有查询使用 `with_for_update()`。
- Produces: `_snapshot(rentals, devices, bindings, decisions, today) -> dict`，返回确定排序的 JSON 基础类型快照。
- Produces: `_build_blocks(rentals, devices, bindings, decisions, today) -> tuple[dict[int, dict], list[dict]]`，返回每型号的 `blocks`、全部 `device_ids`（合法目标设备与固定锚点设备的并集）和跳过记录；可移动块的 `allowed_device_ids` 只含合法目标设备。
- Produces: `_model_summary(model_id, model_data, solver_result) -> dict` 和 `_changes(rentals, devices, assignments) -> list[dict]`。
- Produces: `ReorderCase` 测试 fixture，提供稳定的主/子 rental ID 和字段快照。

- [ ] **Step 1: 写 analyze 和零写入 preview API 的失败测试**

```python
# tests/support/reorder_fixtures.py
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytest

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental


@dataclass
class ReorderCase:
    first: Rental
    second: Rental
    child: Rental
    devices: tuple[Device, Device]

    def snapshot(self):
        return [
            (
                rental.id, rental.device_id, rental.parent_rental_id,
                rental.start_date.isoformat(), rental.end_date.isoformat(),
                rental.ship_out_time.isoformat(), rental.ship_in_time.isoformat(),
                rental.status, rental.destination,
            )
            for rental in Rental.query.order_by(Rental.id).all()
        ]

    def child_snapshot(self):
        child = db.session.get(Rental, self.child.id)
        return (
            child.id, child.device_id, child.parent_rental_id,
            child.start_date, child.end_date, child.ship_out_time,
            child.ship_in_time, child.status, child.destination,
        )

    def main_ids(self):
        return {row.id for row in Rental.query.filter(Rental.parent_rental_id.is_(None)).all()}

    def child_ids(self):
        return {row.id for row in Rental.query.filter(Rental.parent_rental_id.isnot(None)).all()}

    @property
    def main_ids_before(self):
        return {self.first.id, self.second.id}

    @property
    def child_ids_before(self):
        return {self.child.id}

    def add_overlap_pair(self):
        base = date.today() + timedelta(days=20)
        third = Rental(
            device_id=self.devices[0].id,
            start_date=base + timedelta(days=1), end_date=base + timedelta(days=5),
            ship_out_time=datetime.combine(base, time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=7), time(12)),
            customer_name="王先生", customer_phone="13800138000",
            destination="北京市朝阳区", status="not_shipped",
        )
        fourth = Rental(
            device_id=self.devices[0].id,
            start_date=base + timedelta(days=5), end_date=base + timedelta(days=9),
            ship_out_time=datetime.combine(base + timedelta(days=6), time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=11), time(12)),
            customer_name="李女士", customer_phone="13900139000",
            destination="上海市浦东新区", status="not_shipped",
        )
        db.session.add_all([third, fourth])
        db.session.commit()
        return third, fourth


@pytest.fixture
def seeded_reorder_case(db_session):
    base = date.today() + timedelta(days=5)
    model = DeviceModel(name="reorder", display_name="重排测试", is_active=True)
    db_session.add(model)
    db_session.flush()
    first_device = Device(
        name="R-01", model="reorder", model_id=model.id,
        is_accessory=False, status="online", lifecycle_status="active",
    )
    second_device = Device(
        name="R-02", model="reorder", model_id=model.id,
        is_accessory=False, status="online", lifecycle_status="active",
    )
    accessory = Device(
        name="手机支架-01", model="stand", is_accessory=True,
        status="online", lifecycle_status="active",
    )
    db_session.add_all([first_device, second_device, accessory])
    db_session.flush()
    first = Rental(
        device_id=first_device.id,
        start_date=base + timedelta(days=1), end_date=base + timedelta(days=2),
        ship_out_time=datetime.combine(base, time(19)),
        ship_in_time=datetime.combine(base + timedelta(days=3), time(12)),
        customer_name="客户甲", customer_phone="13800000001", destination="广州", status="not_shipped",
    )
    second = Rental(
        device_id=second_device.id,
        start_date=base + timedelta(days=4), end_date=base + timedelta(days=7),
        ship_out_time=datetime.combine(base + timedelta(days=3), time(19)),
        ship_in_time=datetime.combine(base + timedelta(days=8), time(12)),
        customer_name="客户乙", customer_phone="13800000002", destination="深圳", status="not_shipped",
    )
    db_session.add_all([first, second])
    db_session.flush()
    child = Rental(
        device_id=accessory.id, parent_rental_id=second.id,
        start_date=second.start_date, end_date=second.end_date,
        ship_out_time=second.ship_out_time, ship_in_time=second.ship_in_time,
        customer_name=second.customer_name, customer_phone=second.customer_phone,
        destination=second.destination, status="not_shipped",
    )
    db_session.add(child)
    db_session.commit()
    return ReorderCase(first, second, child, (first_device, second_device))
```

```python
# tests/integration/test_gantt_reorder_api.py
import pytest

from app.services.gantt.reorder_service import GanttReorderService
from tests.support.reorder_fixtures import seeded_reorder_case


def test_analyze_returns_contact_fields(client, seeded_reorder_case):
    seeded_reorder_case.add_overlap_pair()
    response = client.post("/api/gantt/reorder/analyze")
    assert response.status_code == 200
    overlap = response.get_json()["data"]["overlaps"][0]
    assert overlap["predecessor"]["customer_name"]
    assert overlap["predecessor"]["customer_phone"]
    assert overlap["predecessor"]["destination"]


def test_preview_is_read_only(client, db_session, seeded_reorder_case):
    before = seeded_reorder_case.snapshot()
    response = client.post("/api/gantt/reorder/preview", json={"decisions": []})
    assert response.status_code == 200
    assert response.get_json()["data"]["token"]
    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before
```

- [ ] **Step 2: 运行并确认路由不存在**

Run: `TESTING=true pytest tests/integration/test_gantt_reorder_api.py -v`

Expected: FAIL，接口返回 404。

- [ ] **Step 3: 实现规范化快照和签名令牌**

```python
# app/services/gantt/reorder_service.py
import hashlib
import json

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class StalePreviewError(ValueError):
    pass


class GanttReorderService:
    TOKEN_SALT = "gantt-schedule-reorder-v1"
    TOKEN_MAX_AGE_SECONDS = 600

    @classmethod
    def _serializer(cls):
        return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=cls.TOKEN_SALT)

    @staticmethod
    def _hash_snapshot(snapshot):
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _sign_preview(cls, snapshot_hash, decisions, assignments, solver_version):
        return cls._serializer().dumps({
            "snapshot_hash": snapshot_hash,
            "decisions": decisions,
            "assignments": {str(key): value for key, value in assignments.items()},
            "solver_version": solver_version,
        })

    @classmethod
    def _load_preview(cls, token):
        try:
            return cls._serializer().loads(token, max_age=cls.TOKEN_MAX_AGE_SECONDS)
        except SignatureExpired as exc:
            raise StalePreviewError("预览已过期，请重新预览") from exc
        except BadSignature as exc:
            raise StalePreviewError("预览令牌无效") from exc
```

- [ ] **Step 4: 实现快照、接力块构建和 preview 编排**

```python
# app/services/gantt/reorder_service.py
@classmethod
def preview(cls, decisions, today=None):
    today = today or date.today()
    normalized = cls._validate_decisions(decisions)
    rentals, devices, bindings = cls._load_reorder_graph(today=today, lock=False)
    snapshot = cls._snapshot(rentals, devices, bindings, normalized, today)
    blocks_by_model, skipped = cls._build_blocks(
        rentals=rentals,
        devices=devices,
        bindings=bindings,
        decisions=normalized,
        today=today,
    )
    all_assignments, model_results = {}, []
    for model_id, model_data in sorted(blocks_by_model.items()):
        result = GanttReorderSolver.solve(
            model_data["blocks"], model_data["device_ids"], 3.0
        )
        if result.status in {"OPTIMAL", "FEASIBLE"}:
            all_assignments.update(result.assignments)
        model_results.append(cls._model_summary(model_id, model_data, result))
    changes = cls._changes(rentals, devices, all_assignments)
    token = cls._sign_preview(
        cls._hash_snapshot(snapshot), normalized, all_assignments, "cp-sat-v1"
    )
    return {
        "token": token,
        "models": model_results,
        "changes": changes,
        "skipped": skipped,
    }
```

`_snapshot()` 的主 rental 条目包含 ID、设备、型号、日期、物流时间、状态、`updated_at` 和按 ID 排序的完整子 rental 快照；设备条目包含型号、online/active 状态和 `updated_at`；绑定条目包含前后 ID。`_build_blocks()` 把已保存或本次选择 keep 的链合并为 `ScheduleBlock`，并让含固定 rental 的链只有当前设备可选。

- [ ] **Step 5: 注册 analyze 和 preview 路由**

```python
# app/handlers/gantt_handlers.py
@staticmethod
def handle_analyze_reorder():
    return success(data=GanttReorderService.analyze())

@staticmethod
def handle_preview_reorder():
    data = request.get_json(silent=True) or {}
    try:
        return success(data=GanttReorderService.preview(data.get("decisions", [])))
    except ValueError as exc:
        return bad_request(str(exc))
```

```python
# app/routes/gantt_api.py
@bp.route('/api/gantt/reorder/analyze', methods=['POST'])
@handle_response
def analyze_reorder():
    return GanttHandlers.handle_analyze_reorder()

@bp.route('/api/gantt/reorder/preview', methods=['POST'])
@handle_response
def preview_reorder():
    return GanttHandlers.handle_preview_reorder()
```

- [ ] **Step 6: 运行 API 测试并提交**

Run: `TESTING=true pytest tests/integration/test_gantt_reorder_api.py -v -k 'analyze or preview'`

Expected: PASS，且 preview 前后数据库快照一致。

```bash
git add app/services/gantt/reorder_service.py app/handlers/gantt_handlers.py app/routes/gantt_api.py tests/support/reorder_fixtures.py tests/integration/test_gantt_reorder_api.py
git commit -m "feat: preview gantt schedule reordering"
```

---

### Task 5: 实现带锁原子执行和父子完整性保护

**Files:**
- Modify: `app/services/gantt/reorder_service.py`
- Modify: `app/handlers/gantt_handlers.py`
- Modify: `app/routes/gantt_api.py`
- Modify: `tests/integration/test_gantt_reorder_api.py`

**Interfaces:**
- Produces: `GanttReorderService.execute(token: str) -> dict`
- Produces: `POST /api/gantt/reorder/execute` with `{token: string}`
- Produces: `_integrity_snapshot(rentals) -> dict`，包含主/子 ID 集合、可移动主 ID 集合和全部禁止变化字段。
- Produces: `_validate_pinned_assignments(blocks_by_model, assignments) -> None`，固定令牌映射后运行每型号可行性模型。
- Produces: `_apply_relay_decisions(decisions) -> list[dict]`，只在当前 session 增删绑定，不提交。
- Produces: `_apply_device_assignments(rentals, assignments) -> list[dict]`，重新检查资格、型号和状态后只赋值主 rental `device_id`。
- Produces: `_write_audit_rows(device_changes, relay_changes) -> None`，只调用 `db.session.add()`。
- Produces: `_assert_integrity(before, rentals, assignments) -> None`。

- [ ] **Step 1: 写成功执行、子 rental 不变和回滚的失败测试**

```python
# 追加到 tests/integration/test_gantt_reorder_api.py
def test_execute_changes_only_main_device_and_preserves_child(client, seeded_reorder_case):
    preview = client.post("/api/gantt/reorder/preview", json={"decisions": []}).get_json()["data"]
    child_before = seeded_reorder_case.child_snapshot()
    response = client.post("/api/gantt/reorder/execute", json={"token": preview["token"]})
    assert response.status_code == 200
    assert seeded_reorder_case.child_snapshot() == child_before
    assert seeded_reorder_case.main_ids() == seeded_reorder_case.main_ids_before
    assert seeded_reorder_case.child_ids() == seeded_reorder_case.child_ids_before


def test_execute_rejects_child_change_after_preview(client, db_session, seeded_reorder_case):
    preview = client.post("/api/gantt/reorder/preview", json={"decisions": []}).get_json()["data"]
    seeded_reorder_case.child.destination = "预览后修改"
    db_session.commit()
    response = client.post("/api/gantt/reorder/execute", json={"token": preview["token"]})
    assert response.status_code == 409
    assert "重新预览" in response.get_json()["message"]


def test_execute_rolls_back_every_change_on_injected_failure(
    client, db_session, seeded_reorder_case, monkeypatch
):
    preview = client.post("/api/gantt/reorder/preview", json={"decisions": []}).get_json()["data"]
    before = seeded_reorder_case.snapshot()
    monkeypatch.setattr(
        GanttReorderService,
        "_write_audit_rows",
        classmethod(lambda cls, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("注入失败"))),
    )
    response = client.post("/api/gantt/reorder/execute", json={"token": preview["token"]})
    assert response.status_code == 500
    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before


def test_reusing_preview_token_has_no_duplicate_side_effect(client, seeded_reorder_case):
    preview = client.post("/api/gantt/reorder/preview", json={"decisions": []}).get_json()["data"]
    first = client.post("/api/gantt/reorder/execute", json={"token": preview["token"]})
    second = client.post("/api/gantt/reorder/execute", json={"token": preview["token"]})
    assert first.status_code == 200
    assert second.status_code == 409
```

- [ ] **Step 2: 运行并确认 execute 返回 404**

Run: `TESTING=true pytest tests/integration/test_gantt_reorder_api.py -v -k execute`

Expected: FAIL，execute 路由不存在。

- [ ] **Step 3: 实现行锁、固定映射校验和单次提交**

```python
# app/services/gantt/reorder_service.py
@classmethod
def execute(cls, token):
    payload = cls._load_preview(token)
    try:
        rentals, devices, bindings = cls._load_reorder_graph(lock=True)
        snapshot = cls._snapshot(
            rentals, devices, bindings, payload["decisions"], date.today()
        )
        if cls._hash_snapshot(snapshot) != payload["snapshot_hash"]:
            raise StalePreviewError("档期或设备状态已变化，请重新预览")

        assignments = {int(key): value for key, value in payload["assignments"].items()}
        blocks_by_model, _ = cls._build_blocks(
            rentals, devices, bindings, payload["decisions"], date.today()
        )
        cls._validate_pinned_assignments(blocks_by_model, assignments)
        before = cls._integrity_snapshot(rentals)
        relay_changes = cls._apply_relay_decisions(payload["decisions"])
        device_changes = cls._apply_device_assignments(rentals, assignments)
        cls._write_audit_rows(device_changes, relay_changes)
        db.session.flush()
        cls._assert_integrity(before, rentals, assignments)
        db.session.commit()
        return {"changes": device_changes, "relay_changes": relay_changes}
    except Exception:
        db.session.rollback()
        raise
```

`_validate_pinned_assignments()` 为每个型号重建相同块结构，把每个 rental 的目标设备固定后调用 `GanttReorderSolver.validate_assignment()` 并运行 CP-SAT 可行性检查。

- [ ] **Step 4: 实现不变量和事务内审计日志**

```python
# app/services/gantt/reorder_service.py
@staticmethod
def _assert_integrity(before, rentals, assignments):
    after = GanttReorderService._integrity_snapshot(rentals)
    if before["main_ids"] != after["main_ids"]:
        raise RuntimeError("主 rental 集合发生变化")
    if before["child_ids"] != after["child_ids"]:
        raise RuntimeError("子 rental 集合发生变化")
    if before["child_values"] != after["child_values"]:
        raise RuntimeError("子 rental 字段发生变化")
    if set(assignments) - before["movable_main_ids"]:
        raise RuntimeError("存在未授权的主 rental 更新")

@staticmethod
def _write_audit_rows(device_changes, relay_changes):
    operation_id = str(uuid.uuid4())
    for change in device_changes:
        db.session.add(AuditLog(
            rental_id=change["rental_id"],
            device_id=change["to_device_id"],
            action="gantt_schedule_reordered",
            resource_type="rental",
            resource_id=str(change["rental_id"]),
            description="甘特图一键重排设备",
            details={"operation_id": operation_id, **change},
        ))
    if relay_changes:
        db.session.add(AuditLog(
            action="gantt_relay_bindings_changed",
            resource_type="rental_relay_binding",
            resource_id=operation_id,
            description="甘特图接力关系变更",
            details={"operation_id": operation_id, "changes": relay_changes},
        ))
```

不得调用 `AuditLog.log_action()`，因为该方法内部会独立 `commit()`。

- [ ] **Step 5: 注册 execute 路由并映射 409**

```python
# app/handlers/gantt_handlers.py
@staticmethod
def handle_execute_reorder():
    data = request.get_json(silent=True) or {}
    if not data.get("token"):
        return bad_request("缺少预览令牌")
    try:
        return success(data=GanttReorderService.execute(data["token"]), message="档期重排完成")
    except StalePreviewError as exc:
        return error(str(exc), status_code=409)
    except ValueError as exc:
        return bad_request(str(exc))
    except Exception:
        current_app.logger.exception("档期重排执行失败")
        return server_error("档期重排失败，所有修改已回滚")
```

```python
# app/routes/gantt_api.py
@bp.route('/api/gantt/reorder/execute', methods=['POST'])
@handle_response
def execute_reorder():
    return GanttHandlers.handle_execute_reorder()
```

- [ ] **Step 6: 使用隔离 MySQL 运行事务测试**

Run: `docker compose -f docker-compose.test.yml up -d --wait mysql-test`

Run: `TESTING=true TEST_DATABASE_URL='mysql+pymysql://inventory_test:inventory_test_password@127.0.0.1:3307/inventory_reorder_test' pytest tests/integration/test_gantt_reorder_api.py -v`

Expected: PASS；注入失败用例前后快照完全一致。

- [ ] **Step 7: 提交**

```bash
git add app/services/gantt/reorder_service.py app/handlers/gantt_handlers.py app/routes/gantt_api.py tests/integration/test_gantt_reorder_api.py
git commit -m "feat: execute gantt reordering atomically"
```

---

### Task 6: 实现前端两步接力确认和预览执行

**Files:**
- Create: `frontend/src/components/ScheduleReorderDialog.vue`
- Create: `frontend/tests/unit/components/ScheduleReorderDialog.spec.ts`
- Modify: `frontend/src/stores/gantt.ts`
- Modify: `frontend/tests/unit/stores/gantt.spec.ts`
- Modify: `frontend/src/components/GanttChart.vue`

**Interfaces:**
- Produces: `analyzeScheduleReorder() -> Promise<ReorderAnalysis>`
- Produces: `previewScheduleReorder(decisions: RelayDecision[]) -> Promise<ReorderPreview>`
- Produces: `executeScheduleReorder(token: string) -> Promise<ExecuteResult>`
- Component props: `modelValue: boolean`
- Component events: `update:modelValue`, `completed`

- [ ] **Step 1: 写 store API 失败测试**

```typescript
// 追加到 frontend/tests/unit/stores/gantt.spec.ts
it('调用档期重排 analyze、preview 和 execute 接口', async () => {
  const store = useGanttStore()
  vi.mocked(axios.post)
    .mockResolvedValueOnce({ data: { success: true, data: { overlaps: [] } } })
    .mockResolvedValueOnce({ data: { success: true, data: { token: 'signed', models: [], changes: [] } } })
    .mockResolvedValueOnce({ data: { success: true, data: { changes: [] } } })

  await store.analyzeScheduleReorder()
  await store.previewScheduleReorder([])
  await store.executeScheduleReorder('signed')

  expect(axios.post).toHaveBeenNthCalledWith(1, '/api/gantt/reorder/analyze')
  expect(axios.post).toHaveBeenNthCalledWith(2, '/api/gantt/reorder/preview', { decisions: [] })
  expect(axios.post).toHaveBeenNthCalledWith(3, '/api/gantt/reorder/execute', { token: 'signed' })
})
```

- [ ] **Step 2: 运行并确认 store 方法不存在**

Run: `cd frontend && npm run test:run -- tests/unit/stores/gantt.spec.ts`

Expected: FAIL，三个方法未定义。

- [ ] **Step 3: 增加前端类型和 store 方法**

```typescript
// frontend/src/stores/gantt.ts
export interface ReorderCustomer {
  id: number
  customer_name: string
  customer_phone: string
  destination: string
  ship_out_time: string
  ship_in_time: string
}

export interface ReorderOverlap {
  pair_key: string
  status: 'bound' | 'needs_confirmation'
  overlap_days: number
  predecessor: ReorderCustomer
  successor: ReorderCustomer
}

export interface RelayDecision {
  predecessor_rental_id: number
  successor_rental_id: number
  action: 'keep' | 'separate'
}

export interface ReorderPreview {
  token: string
  models: Array<{ model_id: number; status: string; before_devices: number; after_devices: number }>
  changes: Array<{
    rental_id: number; customer_name: string; customer_phone: string; destination: string
    ship_out_time: string; ship_in_time: string; from_device_name: string; to_device_name: string
  }>
  skipped: Array<{ rental_id: number; reason: string }>
}

const analyzeScheduleReorder = async () => {
  try {
    const response = await axios.post('/api/gantt/reorder/analyze')
    if (!response.data.success) throw new Error(response.data.message || '分析接力关系失败')
    return response.data.data
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '分析接力关系失败')
  }
}

const previewScheduleReorder = async (decisions: RelayDecision[]): Promise<ReorderPreview> => {
  try {
    const response = await axios.post('/api/gantt/reorder/preview', { decisions })
    if (!response.data.success) throw new Error(response.data.message || '生成重排预览失败')
    return response.data.data
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '生成重排预览失败')
  }
}

const executeScheduleReorder = async (token: string) => {
  try {
    const response = await axios.post('/api/gantt/reorder/execute', { token })
    if (!response.data.success) throw new Error(response.data.message || '执行重排失败')
    await loadData()
    return response.data.data
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '执行重排失败')
  }
}
```

把三个方法加入 store 的 return 对象。

- [ ] **Step 4: 写两步弹窗失败测试**

```typescript
// frontend/tests/unit/components/ScheduleReorderDialog.spec.ts
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import ScheduleReorderDialog from '@/components/ScheduleReorderDialog.vue'
import { useGanttStore } from '@/stores/gantt'

describe('ScheduleReorderDialog', () => {
  it('第一步展示双方姓名、电话和地址，第二步直接执行', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useGanttStore()
    vi.spyOn(store, 'analyzeScheduleReorder').mockResolvedValue({ overlaps: [{
      pair_key: '1:2', status: 'needs_confirmation', overlap_days: 1,
      predecessor: { id: 1, customer_name: '王先生', customer_phone: '13800138000', destination: '北京', ship_out_time: '2026-07-12', ship_in_time: '2026-07-18' },
      successor: { id: 2, customer_name: '李女士', customer_phone: '13900139000', destination: '上海', ship_out_time: '2026-07-17', ship_in_time: '2026-07-23' },
    }] })
    vi.spyOn(store, 'previewScheduleReorder').mockResolvedValue({
      token: 'signed', models: [], skipped: [], changes: [{
        rental_id: 2, customer_name: '李女士', customer_phone: '13900139000', destination: '上海',
        ship_out_time: '2026-07-17', ship_in_time: '2026-07-23', from_device_name: 'A', to_device_name: 'B',
      }],
    })
    vi.spyOn(store, 'executeScheduleReorder').mockResolvedValue({ changes: [] })

    const wrapper = mount(ScheduleReorderDialog, {
      props: { modelValue: true },
      global: { plugins: [pinia, ElementPlus] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('王先生')
    expect(wrapper.text()).toContain('13800138000')
    expect(wrapper.text()).toContain('北京')
    await wrapper.get('[data-test="relay-keep-1-2"]').trigger('click')
    await wrapper.get('[data-test="calculate-preview"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('李女士')
    expect(wrapper.find('[data-test="third-step"]').exists()).toBe(false)
    await wrapper.get('[data-test="execute-reorder"]').trigger('click')
    expect(store.executeScheduleReorder).toHaveBeenCalledWith('signed')
  })
})
```

- [ ] **Step 5: 运行并确认组件不存在**

Run: `cd frontend && npm run test:run -- tests/unit/components/ScheduleReorderDialog.spec.ts`

Expected: FAIL，缺少组件。

- [ ] **Step 6: 实现两步弹窗组件**

```vue
<!-- frontend/src/components/ScheduleReorderDialog.vue -->
<template>
  <el-dialog :model-value="modelValue" width="980px" title="一键重排档期" @close="close">
    <el-steps :active="step - 1" finish-status="success">
      <el-step title="确认接力关系" />
      <el-step title="预览并执行" />
    </el-steps>

    <section v-if="step === 1" v-loading="loading" class="relay-step">
      <el-card v-for="overlap in analysis?.overlaps || []" :key="overlap.pair_key">
        <div class="relay-pair">
          <div v-for="customer in [overlap.predecessor, overlap.successor]" :key="customer.id">
            <strong>{{ customer.customer_name }}</strong>　{{ customer.customer_phone }}
            <div>{{ customer.destination }}</div>
            <small>{{ customer.ship_out_time }} — {{ customer.ship_in_time }}</small>
          </div>
        </div>
        <el-radio-group v-model="decisionByPair[overlap.pair_key]">
          <el-radio-button
            :data-test="`relay-keep-${overlap.pair_key.replace(':', '-')}`"
            value="keep"
          >保持接力并永久绑定</el-radio-button>
          <el-radio-button value="separate">解除接力，分开重排</el-radio-button>
        </el-radio-group>
      </el-card>
      <el-button data-test="calculate-preview" type="primary" :disabled="!allDecided" @click="calculatePreview">
        确认接力选择并计算预览
      </el-button>
    </section>

    <section v-else v-loading="loading" class="preview-step">
      <el-table :data="preview?.models || []" class="model-summary">
        <el-table-column prop="model_id" label="型号 ID" />
        <el-table-column prop="status" label="求解状态" />
        <el-table-column label="占用设备">
          <template #default="{ row }">{{ row.before_devices }} → {{ row.after_devices }}</template>
        </el-table-column>
      </el-table>
      <el-table :data="preview?.changes || []">
        <el-table-column prop="customer_name" label="客户" />
        <el-table-column label="电话 / 地址">
          <template #default="{ row }">{{ row.customer_phone }}<br>{{ row.destination }}</template>
        </el-table-column>
        <el-table-column label="档期">
          <template #default="{ row }">{{ row.ship_out_time }} — {{ row.ship_in_time }}</template>
        </el-table-column>
        <el-table-column label="设备调整">
          <template #default="{ row }">{{ row.from_device_name }} → {{ row.to_device_name }}</template>
        </el-table-column>
      </el-table>
      <el-alert
        v-for="item in preview?.skipped || []"
        :key="item.rental_id"
        type="warning"
        :closable="false"
        :title="`Rental ${item.rental_id}：${item.reason}`"
      />
      <div class="dialog-actions">
        <el-button @click="step = 1">返回修改接力</el-button>
        <el-button data-test="execute-reorder" type="success" @click="execute">执行重排</el-button>
      </div>
    </section>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useGanttStore, type RelayDecision, type ReorderPreview } from '@/stores/gantt'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; completed: [] }>()
const store = useGanttStore()
const step = ref(1)
const loading = ref(false)
const analysis = ref<any>(null)
const preview = ref<ReorderPreview | null>(null)
const decisionByPair = ref<Record<string, 'keep' | 'separate'>>({})
const allDecided = computed(() => (analysis.value?.overlaps || []).every((item: any) => decisionByPair.value[item.pair_key]))

watch(() => props.modelValue, async (open) => {
  if (!open) return
  step.value = 1
  preview.value = null
  loading.value = true
  try {
    analysis.value = await store.analyzeScheduleReorder()
    decisionByPair.value = Object.fromEntries(
      analysis.value.overlaps.filter((item: any) => item.status === 'bound').map((item: any) => [item.pair_key, 'keep'])
    )
  } finally { loading.value = false }
}, { immediate: true })

const decisions = computed<RelayDecision[]>(() => Object.entries(decisionByPair.value).map(([key, action]) => {
  const [predecessor_rental_id, successor_rental_id] = key.split(':').map(Number)
  return { predecessor_rental_id, successor_rental_id, action }
}))

async function calculatePreview() {
  loading.value = true
  try { preview.value = await store.previewScheduleReorder(decisions.value); step.value = 2 }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}

async function execute() {
  if (!preview.value) return
  loading.value = true
  try {
    await store.executeScheduleReorder(preview.value.token)
    ElMessage.success('档期重排完成')
    emit('completed')
    close()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}

function close() { emit('update:modelValue', false) }
</script>
```

- [ ] **Step 7: 在甘特图工具栏接入入口**

```vue
<!-- frontend/src/components/GanttChart.vue 工具栏 -->
<el-button type="primary" :icon="Sort" @click="showScheduleReorderDialog = true">
  一键重排档期
</el-button>

<ScheduleReorderDialog
  v-model="showScheduleReorderDialog"
  @completed="ganttStore.loadData()"
/>
```

```typescript
// GanttChart.vue script
import { Sort } from '@element-plus/icons-vue'
import ScheduleReorderDialog from './ScheduleReorderDialog.vue'
const showScheduleReorderDialog = ref(false)
```

- [ ] **Step 8: 运行前端测试、类型检查并提交**

Run: `cd frontend && npm run test:run -- tests/unit/stores/gantt.spec.ts tests/unit/components/ScheduleReorderDialog.spec.ts`

Expected: PASS。

Run: `cd frontend && npm run type-check`

Expected: PASS。

```bash
git add frontend/src/stores/gantt.ts frontend/src/components/GanttChart.vue frontend/src/components/ScheduleReorderDialog.vue frontend/tests/unit/stores/gantt.spec.ts frontend/tests/unit/components/ScheduleReorderDialog.spec.ts
git commit -m "feat: add gantt reorder preview workflow"
```

---

### Task 7: 全量验证、多架构验证和 OpenSpec 收尾

**Files:**
- Modify: `openspec/changes/add-gantt-schedule-reordering/tasks.md`
- Modify only if verification exposes a real issue: files changed in Tasks 1–6

**Interfaces:**
- Consumes: all backend APIs and frontend workflow
- Produces: verified implementation with completed OpenSpec checklist

- [ ] **Step 1: 运行后端单元测试**

Run: `TESTING=true pytest tests/unit/test_gantt_device_eligibility.py tests/unit/test_gantt_relay_analysis.py tests/unit/test_gantt_reorder_solver.py -v`

Expected: 全部 PASS，无 warning 或意外日志。

- [ ] **Step 2: 运行隔离 MySQL 集成测试**

Run: `docker compose -f docker-compose.test.yml up -d --wait mysql-test`

Run: `TESTING=true TEST_DATABASE_URL='mysql+pymysql://inventory_test:inventory_test_password@127.0.0.1:3307/inventory_reorder_test' pytest tests/integration/test_gantt_reorder_api.py -v`

Expected: analyze、preview、execute、过期快照、父子保护和回滚全部 PASS。

- [ ] **Step 3: 运行前端全量测试和构建**

Run: `cd frontend && npm run test:run`

Expected: 全部 PASS。

Run: `cd frontend && npm run build`

Expected: `vue-tsc` 和 Vite build 成功。

- [ ] **Step 4: 验证迁移和 OpenSpec**

Run: `python3 -m flask db heads`

Expected: `20260711_relay_bindings` 是唯一 head；如出现多 head，先创建 merge migration，再继续。

Run: `openspec validate add-gantt-schedule-reordering --strict`

Expected: `Change 'add-gantt-schedule-reordering' is valid`。

- [ ] **Step 5: 验证两种 Docker 架构可导入 CP-SAT**

Run: `docker buildx build --platform linux/amd64 -t inventory-manager:reorder-amd64 --load .`

Run: `docker run --rm --entrypoint python inventory-manager:reorder-amd64 -c 'from ortools.sat.python import cp_model; print(cp_model.CpModel())'`

Expected: 成功输出空 CP-SAT model。

Run: `docker buildx build --platform linux/arm64 -t inventory-manager:reorder-arm64 --load .`

Run: `docker run --rm --entrypoint python inventory-manager:reorder-arm64 -c 'from ortools.sat.python import cp_model; print(cp_model.CpModel())'`

Expected: 成功输出空 CP-SAT model。

- [ ] **Step 6: 执行变更范围审计**

Run: `git diff HEAD~6 -- app frontend/src tests migrations requirements.txt docker-compose.test.yml`

Expected: 生产代码只包含设备资格、接力、重排 API/服务和两步 UI；没有 `.env`、dump、生产数据库地址或无关改动。

- [ ] **Step 7: 更新 OpenSpec 清单并提交验证结果**

把 `openspec/changes/add-gantt-schedule-reordering/tasks.md` 中已经由测试和构建证明完成的项目逐项改为 `- [x]`，不得提前勾选未完成项。

```bash
git add openspec/changes/add-gantt-schedule-reordering/tasks.md
git commit -m "docs: complete gantt reorder implementation checklist"
```

- [ ] **Step 8: 最终工作区检查**

Run: `git status --short`

Expected: 仅显示用户原有的无关修改；本功能文件无未提交变化。
