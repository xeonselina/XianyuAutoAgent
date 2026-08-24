"""
验货服务
处理验货记录的业务逻辑
"""
from datetime import datetime, date
from typing import Any, Optional, List, Dict
from app import db
from app.models.audit_log import AuditLog
from app.models.rental import Rental
from app.models.device import Device
from app.models.inspection_record import InspectionRecord
from app.models.inspection_check_item import InspectionCheckItem
from app.models.warehouse import Warehouse
from app.services.checklist_generator import ChecklistGenerator
from app.services.warehouse_movement_service import WarehouseMovementService


class ConcurrentInspectionChangeError(RuntimeError):
    """The inspected rental or inventory changed while it was being locked."""


class InspectionService:
    """验货服务类"""

    @staticmethod
    def find_latest_rental_by_device_id(device_id: int) -> Optional[Rental]:
        """
        根据设备ID查询最近的租赁记录（在今天之前）

        Args:
            device_id: 设备ID

        Returns:
            Rental: 最近的租赁记录，如果没有则返回 None
        """
        today = date.today()

        # 查询该设备在今天之前的最近租赁记录
        # 按开始日期倒序排列，取第一条
        rental = Rental.query.filter(
            Rental.device_id == device_id,
            Rental.start_date < today
        ).order_by(Rental.start_date.desc()).first()

        return rental

    @staticmethod
    def create_inspection_record(
        rental_id: int,
        device_id: int,
        check_items: List[Dict[str, Any]],
        receiving_warehouse_id: Optional[int] = None,
        received_device_ids: Optional[List[int]] = None,
    ):
        """
        创建验货记录

        Args:
            rental_id: 租赁记录ID
            device_id: 设备ID
            check_items: 检查项列表，每项包含 name, is_checked, order
            receiving_warehouse_id: 实际收货仓；省略时使用履约仓
            received_device_ids: 本次实际收到的库存附件 Device ID

        Returns:
            tuple: 创建的验货记录和写入前计算的跨仓影响摘要

        Raises:
            ValueError: 如果租赁记录或设备不存在
        """
        try:
            rental_id = InspectionService._positive_id(
                rental_id, "租赁ID"
            )
            device_id = InspectionService._positive_id(
                device_id, "设备ID"
            )
            normalized_items = InspectionService._validate_check_items(
                check_items
            )
            received_ids = InspectionService._validate_received_ids(
                received_device_ids
            )
            if receiving_warehouse_id is not None:
                receiving_warehouse_id = InspectionService._positive_id(
                    receiving_warehouse_id, "收货仓库ID"
                )

            # Read a bounded snapshot first so locks can always be acquired in
            # Warehouse -> Device -> Rental order.
            rental = db.session.get(Rental, rental_id)
            if rental is None:
                raise ValueError("租赁记录不存在")
            if rental.parent_rental_id is not None:
                raise ValueError("只能对主租赁进行验货")
            if rental.device_id != device_id:
                raise ValueError("设备不属于该主租赁")
            children = Rental.query.filter_by(
                parent_rental_id=rental.id
            ).order_by(Rental.id).all()
            rental_snapshot = InspectionService._rental_snapshot(
                rental, children
            )
            allowed_received_ids = {
                rental.device_id,
                *(child.device_id for child in children),
            }
            if not set(received_ids).issubset(allowed_received_ids):
                raise ValueError("收到的设备不属于该主租赁")

            group_device_ids = sorted(allowed_received_ids)
            devices = Device.query.filter(
                Device.id.in_(group_device_ids)
            ).order_by(Device.id).all()
            if {row.id for row in devices} != set(group_device_ids):
                raise ValueError("租赁关联设备不存在")
            device_snapshot = {
                row.id: row.warehouse_id for row in devices
            }
            target_warehouse_id = (
                receiving_warehouse_id
                if receiving_warehouse_id is not None
                else rental.warehouse_id
            )
            selected_ids = sorted({device_id, *received_ids})
            warehouse_ids = sorted({
                rental.warehouse_id,
                target_warehouse_id,
                *(device_snapshot[item] for item in selected_ids),
            })

            warehouse_query = Warehouse.query.filter(
                Warehouse.id.in_(warehouse_ids)
            ).order_by(Warehouse.id).populate_existing().with_for_update()
            locked_warehouses = warehouse_query.all()
            if {row.id for row in locked_warehouses} != set(warehouse_ids):
                raise ValueError("收货仓库不存在")

            locked_devices = Device.query.filter(
                Device.id.in_(group_device_ids)
            ).order_by(Device.id).populate_existing().with_for_update().all()
            if {row.id for row in locked_devices} != set(group_device_ids):
                raise ConcurrentInspectionChangeError(
                    "租赁关联设备已变化，请重试"
                )
            devices_by_id = {row.id: row for row in locked_devices}

            locked_rentals = Rental.query.filter(
                db.or_(
                    Rental.id == rental_id,
                    Rental.parent_rental_id == rental_id,
                )
            ).order_by(Rental.id).populate_existing().with_for_update().all()
            locked_main = next(
                (
                    row for row in locked_rentals
                    if row.id == rental_id and row.parent_rental_id is None
                ),
                None,
            )
            locked_children = [
                row for row in locked_rentals
                if row.parent_rental_id == rental_id
            ]
            locked_snapshot = (
                InspectionService._rental_snapshot(
                    locked_main, locked_children
                )
                if locked_main is not None
                else None
            )
            unexpected_warehouse = any(
                devices_by_id[item].warehouse_id not in warehouse_ids
                for item in selected_ids
            )
            if locked_snapshot != rental_snapshot or unexpected_warehouse:
                raise ConcurrentInspectionChangeError(
                    "租赁或设备仓位已变化，请重试"
                )
            if receiving_warehouse_id is None and (
                locked_main.warehouse_id != target_warehouse_id
            ):
                raise ConcurrentInspectionChangeError(
                    "租赁履约仓库已变化，请重试"
                )

            moving_devices = [
                devices_by_id[item]
                for item in selected_ids
                if devices_by_id[item].warehouse_id != target_warehouse_id
            ]
            warehouse_impacts = None

            status = (
                "normal"
                if all(item["is_checked"] for item in normalized_items)
                else "abnormal"
            )
            now = datetime.now()
            inspection_record = InspectionRecord(
                rental_id=locked_main.id,
                device_id=device_id,
                status=status,
                created_at=now,
                updated_at=now,
            )
            db.session.add(inspection_record)
            db.session.flush()

            for item_data in normalized_items:
                db.session.add(InspectionCheckItem(
                    inspection_record_id=inspection_record.id,
                    item_name=item_data["name"],
                    is_checked=item_data["is_checked"],
                    item_order=item_data["order"],
                ))

            moves = []
            for moving_device in moving_devices:
                old_warehouse_id = moving_device.warehouse_id
                moving_device.warehouse_id = target_warehouse_id
                moves.append({
                    "device_id": moving_device.id,
                    "old_warehouse_id": old_warehouse_id,
                    "new_warehouse_id": target_warehouse_id,
                })

            # Build one repair plan from the complete post-receipt state. The
            # surrounding transaction makes a preview failure roll back the
            # inspection, its items, and every physical warehouse change.
            db.session.flush()
            if moving_devices:
                warehouse_impacts = (
                    WarehouseMovementService.preview_receipt_repair(
                        device_id,
                        [device.id for device in moving_devices],
                        target_warehouse_id,
                        excluded_main_rental_id=locked_main.id,
                    )
                )

            AuditLog.log_action(
                action="inspection_warehouse_received",
                resource_type="inspection",
                resource_id=str(inspection_record.id),
                description="验货设备入仓",
                details={
                    "rental_id": locked_main.id,
                    "receiving_warehouse_id": target_warehouse_id,
                    "moves": moves,
                },
                commit=False,
            )
            db.session.commit()
            return inspection_record, warehouse_impacts
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _positive_id(value, field_name):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name}无效")
        return value

    @staticmethod
    def _validate_received_ids(received_device_ids):
        if received_device_ids is None:
            return []
        if not isinstance(received_device_ids, list):
            raise ValueError("received_device_ids 必须是数组")
        normalized = []
        for value in received_device_ids:
            normalized.append(InspectionService._positive_id(
                value, "收到的设备ID"
            ))
        return sorted(set(normalized))

    @staticmethod
    def _validate_check_items(check_items):
        if not isinstance(check_items, list) or not check_items:
            raise ValueError("check_items 必须是非空数组")
        normalized = []
        for item in check_items:
            if not isinstance(item, dict):
                raise ValueError("检查项格式无效")
            if not {"name", "is_checked", "order"}.issubset(item):
                raise ValueError("检查项字段不完整")
            name = item["name"]
            checked = item["is_checked"]
            order = item["order"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError("检查项名称无效")
            if len(name) > 1020:
                raise ValueError("检查项名称无效")
            if not isinstance(checked, bool):
                raise ValueError("检查项状态无效")
            if (
                isinstance(order, bool)
                or not isinstance(order, int)
                or order < 0
                or order > 2147483647
            ):
                raise ValueError("检查项顺序无效")
            normalized.append({
                "name": name,
                "is_checked": checked,
                "order": order,
            })
        return normalized

    @staticmethod
    def _rental_snapshot(main, children):
        return (
            main.id,
            main.parent_rental_id,
            main.device_id,
            main.warehouse_id,
            tuple(
                (child.id, child.parent_rental_id, child.device_id)
                for child in sorted(children, key=lambda row: row.id)
            ),
        )

    @staticmethod
    def get_inspection_record(inspection_id: int) -> Optional[InspectionRecord]:
        """
        获取验货记录详情

        Args:
            inspection_id: 验货记录ID

        Returns:
            InspectionRecord: 验货记录，如果不存在则返回 None
        """
        return InspectionRecord.query.get(inspection_id)

    @staticmethod
    def update_inspection_record(
        inspection_id: int,
        check_items: List[Dict[str, any]]
    ) -> InspectionRecord:
        """
        更新验货记录

        Args:
            inspection_id: 验货记录ID
            check_items: 更新后的检查项列表，每项包含 id, is_checked

        Returns:
            InspectionRecord: 更新后的验货记录

        Raises:
            ValueError: 如果验货记录不存在
        """
        inspection_record = InspectionRecord.query.get(inspection_id)
        if not inspection_record:
            raise ValueError(f"Inspection record {inspection_id} not found")

        # 更新检查项
        for item_data in check_items:
            check_item = InspectionCheckItem.query.get(item_data['id'])
            if check_item and check_item.inspection_record_id == inspection_id:
                check_item.is_checked = item_data.get('is_checked', False)

        # 重新计算状态
        all_items = inspection_record.check_items.all()
        status = 'normal' if all(item.is_checked for item in all_items) else 'abnormal'
        inspection_record.status = status
        inspection_record.updated_at = datetime.now()

        db.session.commit()

        return inspection_record

    @staticmethod
    def get_inspection_records(
        device_name: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Dict:
        """
        获取验货记录列表（分页、筛选）

        Args:
            device_name: 设备名称筛选（模糊匹配）
            status: 状态筛选 (normal/abnormal)
            page: 页码
            per_page: 每页数量

        Returns:
            Dict: 包含 records 和 pagination 信息
        """
        query = InspectionRecord.query

        # 设备名称筛选
        if device_name:
            query = query.join(Device).filter(Device.name.like(f'%{device_name}%'))

        # 状态筛选
        if status:
            query = query.filter(InspectionRecord.status == status)

        # 按创建时间倒序排列
        query = query.order_by(InspectionRecord.created_at.desc())

        # 分页
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            'records': [record.to_dict() for record in pagination.items],
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_prev': pagination.has_prev,
                'has_next': pagination.has_next
            }
        }

    @staticmethod
    def generate_checklist_for_rental(rental_id: int) -> List[Dict[str, any]]:
        """
        为指定租赁记录生成检查清单

        Args:
            rental_id: 租赁记录ID

        Returns:
            List[Dict]: 检查清单

        Raises:
            ValueError: 如果租赁记录不存在
        """
        rental = Rental.query.get(rental_id)
        if not rental:
            raise ValueError(f"Rental {rental_id} not found")

        return ChecklistGenerator.generate_checklist(rental)
