"""
租赁业务逻辑服务层
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.services.scheduling import (
    ACTIVE_RENTAL_STATUSES,
    USAGE_PERIOD_CONFLICT,
    VALID_RENTAL_STATUSES,
    RentalSchedule,
    ScheduleOverlapPolicy,
)
from app.utils.date_utils import parse_date_strings, validate_date_range


class RentalUsagePeriodConflictError(ValueError):
    """Stable final-write rejection for an inclusive customer-use conflict."""

    code = USAGE_PERIOD_CONFLICT

    def __init__(self, conflicting_rental_ids: Tuple[int, ...]) -> None:
        self.conflicting_rental_ids = tuple(
            sorted(set(conflicting_rental_ids))
        )
        super().__init__(self.code)


class RentalService:
    """租赁服务类"""

    _schedule_overlap_policy = ScheduleOverlapPolicy()

    @staticmethod
    def _lock_schedule_device(device_id: int) -> Optional[Device]:
        """Serialize final schedule writes for one device.

        The device row is the stable mutex even when the device currently has
        no rentals.  The following range lock therefore cannot be bypassed by
        two concurrent creates both observing an empty schedule.
        """

        return RentalService._lock_schedule_devices((device_id,)).get(
            device_id
        )

    @staticmethod
    def _lock_schedule_devices(
        device_ids: Tuple[int, ...],
    ) -> Dict[int, Device]:
        """Lock every affected device in deterministic primary-key order."""

        ordered_ids = tuple(sorted(set(device_ids)))
        if not ordered_ids:
            return {}
        rows = db.session.execute(
            select(Device)
            .where(Device.id.in_(ordered_ids))
            .order_by(Device.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars()
        return {row.id: row for row in rows}

    @staticmethod
    def _optional_datetime(value: object, field_name: str) -> Optional[datetime]:
        if value is None or value == '':
            return None
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError(f'{field_name} 格式错误')
        normalized = value.replace('T', ' ')
        for pattern in (None, '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return (
                    datetime.fromisoformat(normalized)
                    if pattern is None
                    else datetime.strptime(normalized, pattern)
                )
            except ValueError:
                continue
        raise ValueError(f'{field_name} 格式错误')

    @staticmethod
    def _require_logistics_days(value: object) -> int:
        """Accept the confirmed D33 integer range without truthy defaults."""

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 7
        ):
            raise ValueError('logistics_days 必须是 0 到 7 的整数')
        return value

    @classmethod
    def _planned_logistics_window(
        cls,
        *,
        start_date: date,
        end_date: date,
        logistics_days: int,
    ):
        return cls._schedule_overlap_policy.calculate_planned_window(
            start_date=start_date,
            end_date=end_date,
            logistics_days=logistics_days,
            tenant_timezone=current_app.config.get(
                'TIMEZONE', 'Asia/Shanghai'
            ),
        )

    @classmethod
    def _require_usage_period_available(
        cls,
        *,
        device_id: int,
        start_date: date,
        end_date: date,
        candidate_status: str,
        candidate_rental_id: Optional[int] = None,
        candidate_logistics_days: Optional[int] = None,
    ) -> None:
        """Lock and re-evaluate the authoritative same-device schedule.

        Customer-use conflicts are independent from logistics duration.  A
        nullable legacy ``logistics_days`` is represented as zero only in this
        in-memory policy projection; no persisted logistics fact is invented or
        changed.  The shared policy still owns the inclusive period semantics.
        """

        locked = tuple(
            db.session.execute(
                select(Rental)
                .where(
                    Rental.device_id == device_id,
                    Rental.parent_rental_id.is_(None),
                    Rental.status.in_(tuple(sorted(ACTIVE_RENTAL_STATUSES))),
                )
                .order_by(Rental.start_date.asc(), Rental.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalars()
        )
        schedules = tuple(
            RentalSchedule(
                rental_id=rental.id,
                device_id=rental.device_id,
                start_date=rental.start_date,
                end_date=rental.end_date,
                logistics_days=(
                    rental.logistics_days
                    if rental.logistics_days is not None
                    else 0
                ),
                status=rental.status,
            )
            for rental in locked
        )
        candidate = RentalSchedule(
            rental_id=candidate_rental_id,
            device_id=device_id,
            start_date=start_date,
            end_date=end_date,
            logistics_days=(
                candidate_logistics_days
                if candidate_logistics_days is not None
                else 0
            ),
            status=candidate_status,
        )
        evaluation = cls._schedule_overlap_policy.evaluate(
            schedules,
            candidate=candidate,
            exclude_rental_id=candidate_rental_id,
            tenant_timezone=current_app.config.get(
                "TIMEZONE", "Asia/Shanghai"
            ),
        )

        if candidate_rental_id is None:
            candidate_conflicts = tuple(
                conflict
                for conflict in evaluation.hard_conflicts
                if conflict.predecessor_rental_id is None
                or conflict.successor_rental_id is None
            )
        else:
            candidate_conflicts = tuple(
                conflict
                for conflict in evaluation.hard_conflicts
                if candidate_rental_id
                in (
                    conflict.predecessor_rental_id,
                    conflict.successor_rental_id,
                )
            )
        if not candidate_conflicts:
            return

        conflicting_ids = tuple(
            rental_id
            for conflict in candidate_conflicts
            for rental_id in (
                conflict.predecessor_rental_id,
                conflict.successor_rental_id,
            )
            if rental_id is not None and rental_id != candidate_rental_id
        )
        raise RentalUsagePeriodConflictError(conflicting_ids)

    @staticmethod
    def get_pending_returns(today: Optional[date] = None) -> List[Dict[str, Any]]:
        """获取今天及以前应归还、仍未寄回的主租赁记录。"""
        current_date = today or date.today()
        latest_end_date = current_date - timedelta(days=1)
        rentals = (
            Rental.query
            .options(joinedload(Rental.device))
            .filter(
                Rental.end_date <= latest_end_date,
                Rental.status == 'shipped',
                Rental.parent_rental_id.is_(None),
            )
            .all()
        )

        rows = []
        for rental in rentals:
            due_date = rental.end_date + timedelta(days=1)
            overdue_days = (current_date - due_date).days
            device = rental.device
            device_model = None
            if device:
                if device.device_model:
                    device_model = device.device_model.display_name
                device_model = device_model or device.model or device.name

            rows.append({
                'id': rental.id,
                'device_model': device_model or '-',
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'due_date': due_date.isoformat(),
                'overdue_days': overdue_days,
                'destination': rental.destination,
                'customer_phone': rental.customer_phone,
                'status': rental.status,
            })

        return sorted(
            rows,
            key=lambda row: (-row['overdue_days'], row['id']),
        )

    @staticmethod
    def get_rentals_with_filters(
        page: int = 1,
        per_page: int = 20,
        device_id: Optional[int] = None,
        customer_name: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phone: Optional[str] = None,
        destination: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取带过滤条件的租赁记录
        
        Args:
            page: 页码（从1开始）
            per_page: 每页数量（最多100）
            device_id: 设备ID
            customer_name: 客户名称（模糊查询）
            status: 租赁状态
            start_date: 起始日期（YYYY-MM-DD格式）
            end_date: 结束日期（YYYY-MM-DD格式）
            phone: 客户电话（模糊查询）
            destination: 收货地址（模糊查询）
        
        Returns:
            Dict: 包含rentals列表、分页信息
        """
        try:
            query = Rental.query

            # 应用过滤条件
            if device_id:
                query = query.filter(Rental.device_id == device_id)

            if customer_name:
                query = query.filter(Rental.customer_name.like(f'%{customer_name}%'))

            if status:
                query = query.filter(Rental.status == status)

            if phone:
                query = query.filter(Rental.customer_phone.like(f'%{phone}%'))
            
            if destination:
                query = query.filter(Rental.destination.like(f'%{destination}%'))

            if start_date and end_date:
                start_date_obj, end_date_obj = parse_date_strings(start_date, end_date)
                query = query.filter(
                    Rental.start_date >= start_date_obj,
                    Rental.end_date <= end_date_obj
                )

            # 按ID降序排列（最新的在前面）
            query = query.order_by(Rental.id.desc())

            # 分页
            pagination = query.paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )

            return {
                'rentals': [rental.to_dict() for rental in pagination.items],
                'total': pagination.total,
                'pages': pagination.pages,
                'current_page': page,
                'per_page': per_page,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }

        except Exception as e:
            current_app.logger.error(f"获取租赁记录失败: {e}")
            raise

    @staticmethod
    def get_rental_by_id(rental_id: int) -> Optional[Rental]:
        """根据ID获取租赁记录"""
        return Rental.query.get(rental_id)

    @staticmethod
    def create_rental_with_accessories(data: Dict[str, Any]) -> Tuple[Rental, List[Rental]]:
        """创建租赁记录及其附件
        
        Args:
            data: 租赁数据，包含:
                - device_id: 设备ID
                - customer_name: 客户姓名
                - start_date/end_date: 租赁日期
                - includes_handle: 是否包含手柄（配套附件）
                - includes_lens_mount: 是否包含镜头支架（配套附件）
                - accessories: 库存附件ID列表（手机支架、三脚架）
        
        Returns:
            Tuple[Rental, List[Rental]]: (主租赁, 附件租赁列表)
        """
        try:
            # 解析日期
            start_date, end_date = parse_date_strings(data['start_date'], data['end_date'])

            # 验证日期范围
            validation_error = validate_date_range(start_date, end_date)
            if validation_error:
                raise ValueError(validation_error)

            logistics_days = None
            planned_ship_out_date = None
            planned_return_date = None
            if 'logistics_days' in data:
                logistics_days = RentalService._require_logistics_days(
                    data['logistics_days']
                )
                planned_window = RentalService._planned_logistics_window(
                    start_date=start_date,
                    end_date=end_date,
                    logistics_days=logistics_days,
                )
                planned_ship_out_date = (
                    planned_window.planned_ship_out_date
                )
                planned_return_date = planned_window.planned_return_date

            # 解析时间
            ship_out_time = None
            ship_in_time = None

            if data.get('ship_out_time'):
                try:
                    # 尝试 ISO 格式
                    ship_out_time = datetime.fromisoformat(data['ship_out_time'].replace('T', ' '))
                except ValueError:
                    # 回退到原格式
                    ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')

            if data.get('ship_in_time'):
                try:
                    # 尝试 ISO 格式
                    ship_in_time = datetime.fromisoformat(data['ship_in_time'].replace('T', ' '))
                except ValueError:
                    # 回退到原格式
                    ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')

            # The final write never trusts the separate conflict-preview API.
            # Lock the stable device row first, then lock and re-read every
            # effective main rental before the candidate is added.
            device = RentalService._lock_schedule_device(data['device_id'])
            if not device:
                raise ValueError('设备不存在')
            RentalService._require_usage_period_available(
                device_id=device.id,
                start_date=start_date,
                end_date=end_date,
                candidate_status='not_shipped',
                candidate_logistics_days=logistics_days,
            )

            # 创建主租赁记录（包含配套附件标记）
            main_rental = Rental(
                device_id=data['device_id'],
                customer_name=data['customer_name'],
                customer_phone=data.get('customer_phone'),
                destination=data.get('destination', ''),
                start_date=start_date,
                end_date=end_date,
                ship_out_time=ship_out_time,
                ship_in_time=ship_in_time,
                ship_out_tracking_no=data.get('ship_out_tracking_no', ''),
                ship_in_tracking_no=data.get('ship_in_tracking_no', ''),
                xianyu_order_no=data.get('xianyu_order_no'),
                order_amount=data.get('order_amount'),
                buyer_id=data.get('buyer_id'),
                status='not_shipped',
                logistics_days=logistics_days,
                planned_ship_out_date=planned_ship_out_date,
                planned_return_date=planned_return_date,
                # 新：配套附件标记
                includes_handle=data.get('includes_handle', False),
                includes_lens_mount=data.get('includes_lens_mount', False),
                photo_transfer=data.get('photo_transfer', False),
                # 镜头组合（由 handler 层校验/补全后传入，handler 不传则使用 server_default）
                lens_combo=data.get('lens_combo', 'lens_400mm')
            )

            db.session.add(main_rental)
            db.session.flush()  # 获取主租赁记录的ID

            # 创建附件租赁记录（仅针对库存附件，不包括手柄和镜头支架）
            accessory_rentals = []
            if data.get('accessories'):
                for accessory_id in data['accessories']:
                    accessory_device = Device.query.get(accessory_id)
                    if accessory_device and accessory_device.is_accessory:
                        # 跳过配套附件（手柄和镜头支架）
                        if '手柄' in accessory_device.name or '镜头支架' in accessory_device.name:
                            current_app.logger.info(f"跳过配套附件: {accessory_device.name}")
                            continue
                        
                        # 仅为库存附件（手机支架、三脚架）创建子租赁
                        accessory_rental = Rental(
                            device_id=accessory_id,
                            customer_name=data['customer_name'],
                            customer_phone=data.get('customer_phone'),
                            destination=data.get('destination', ''),
                            start_date=start_date,
                            end_date=end_date,
                            ship_out_time=ship_out_time,
                            ship_in_time=ship_in_time,
                            ship_out_tracking_no=data.get('ship_out_tracking_no', ''),
                            ship_in_tracking_no=data.get('ship_in_tracking_no', ''),
                            status='not_shipped',
                            logistics_days=logistics_days,
                            planned_ship_out_date=planned_ship_out_date,
                            planned_return_date=planned_return_date,
                            parent_rental_id=main_rental.id
                        )
                        db.session.add(accessory_rental)
                        accessory_rentals.append(accessory_rental)

            db.session.commit()
            return main_rental, accessory_rentals

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"创建租赁记录失败: {e}")
            raise

    @staticmethod
    def update_rental_status(rental_id: int, new_status: str) -> Rental:
        """Update status through the same locked final-write transaction."""

        return RentalService.update_rental_with_accessories(
            rental_id,
            {'status': new_status},
        )

    @staticmethod
    def delete_rental(rental_id: int) -> bool:
        """删除租赁记录"""
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                return False

            # 如果是主租赁记录，删除所有子租赁记录（附件）
            if rental.is_main_rental():
                current_app.logger.info(f"删除主租赁记录 {rental_id} 及其所有子租赁记录")
                # 先删除子租赁记录（附件）
                child_rentals = list(rental.child_rentals)  # 转换为列表避免修改时的迭代问题
                for child_rental in child_rentals:
                    current_app.logger.info(f"删除子租赁记录: {child_rental.id}")
                    db.session.delete(child_rental)

                # 删除主租赁记录
                db.session.delete(rental)
            else:
                # 如果是子租赁记录（附件），只删除该记录
                current_app.logger.info(f"删除子租赁记录（附件）: {rental_id}")
                db.session.delete(rental)

            db.session.commit()
            current_app.logger.info(f"成功删除租赁记录: {rental_id}")
            return True

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"删除租赁记录失败: {e}")
            raise

    @staticmethod
    def check_rental_conflicts(
        device_id: int,
        start_date: date,
        end_date: date,
        ship_out_time: datetime,
        ship_in_time: datetime,
        exclude_rental_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """检查租赁冲突"""
        try:
            query = Rental.query.filter(
                Rental.device_id == device_id,
                Rental.status != 'cancelled'
            )

            if exclude_rental_id:
                query = query.filter(Rental.id != exclude_rental_id)

            existing_rentals = query.all()
            conflicts = []

            for existing in existing_rentals:
                if existing.ship_out_time and existing.ship_in_time:
                    # 检查物流时间是否重叠
                    if not (ship_in_time <= existing.ship_out_time or ship_out_time >= existing.ship_in_time):
                        conflicts.append({
                            'rental_id': existing.id,
                            'customer_name': existing.customer_name,
                            'start_date': existing.start_date.isoformat(),
                            'end_date': existing.end_date.isoformat(),
                            'ship_out_time': existing.ship_out_time.isoformat(),
                            'ship_in_time': existing.ship_in_time.isoformat(),
                            'status': existing.status
                        })

            return conflicts

        except Exception as e:
            current_app.logger.error(f"检查租赁冲突失败: {e}")
            raise

    @staticmethod
    def update_rental_accessories(rental: Rental, new_accessory_ids: List[int]):
        """更新租赁附件（仅库存附件，不包括配套附件）
        
        Args:
            rental: 租赁记录对象
            new_accessory_ids: 新的库存附件ID列表（手机支架、三脚架）
        
        Note:
            手柄和镜头支架通过 includes_handle/includes_lens_mount 字段管理
        """
        try:
            current_app.logger.info(f"开始更新附件 - rental_id: {rental.id}, new_accessory_ids: {new_accessory_ids}, 类型: {type(new_accessory_ids)}")

            # 获取当前附件租赁记录
            current_accessory_rentals = list(rental.child_rentals)
            current_accessories = {r.device_id for r in current_accessory_rentals}
            new_accessories = set(new_accessory_ids if new_accessory_ids else [])

            current_app.logger.info(f"当前附件: {current_accessories}")
            current_app.logger.info(f"新附件: {new_accessories}")

            # 找出需要删除和添加的附件
            to_remove = current_accessories - new_accessories
            to_add = new_accessories - current_accessories

            current_app.logger.info(f"需要删除的附件: {to_remove}")
            current_app.logger.info(f"需要添加的附件: {to_add}")

            # 删除不再需要的附件租赁记录
            for accessory_id in to_remove:
                accessory_rental_to_remove = next(
                    (r for r in current_accessory_rentals if r.device_id == accessory_id),
                    None
                )
                if accessory_rental_to_remove:
                    db.session.delete(accessory_rental_to_remove)
                    current_app.logger.info(f"删除附件租赁记录: {accessory_rental_to_remove.id}")

            # 添加新的附件租赁记录（跳过配套附件）
            for accessory_id in to_add:
                accessory_device = Device.query.get(accessory_id)
                if accessory_device and accessory_device.is_accessory:
                    # 跳过配套附件
                    if '手柄' in accessory_device.name or '镜头支架' in accessory_device.name:
                        current_app.logger.info(f"跳过配套附件: {accessory_device.name}")
                        continue
                    
                    new_accessory_rental = Rental(
                        device_id=accessory_id,
                        customer_name=rental.customer_name,
                        customer_phone=rental.customer_phone,
                        destination=rental.destination,
                        start_date=rental.start_date,
                        end_date=rental.end_date,
                        ship_out_time=rental.ship_out_time,
                        ship_in_time=rental.ship_in_time,
                        ship_out_tracking_no=rental.ship_out_tracking_no,
                        ship_in_tracking_no=rental.ship_in_tracking_no,
                        status=rental.status,
                        logistics_days=rental.logistics_days,
                        planned_ship_out_date=rental.planned_ship_out_date,
                        planned_return_date=rental.planned_return_date,
                        actual_shipped_at=rental.actual_shipped_at,
                        actual_returned_at=rental.actual_returned_at,
                        parent_rental_id=rental.id
                    )
                    db.session.add(new_accessory_rental)
                    current_app.logger.info(f"为附件创建新租赁记录: {accessory_device.name}")
                else:
                    current_app.logger.warning(f"附件设备 {accessory_id} 不存在或不是附件类型")

        except Exception as e:
            current_app.logger.error(f"更新租赁附件失败: {e}")
            raise
    
    @staticmethod
    def update_rental_with_accessories(
        rental_id: int,
        data: Dict[str, Any],
        *,
        commit: bool = True,
    ) -> Rental:
        """更新租赁记录及其附件（包括配套附件标记）
        
        Args:
            rental_id: 租赁记录ID
            data: 更新数据，可包含：
                - customer_name, customer_phone, destination: 客户信息
                - start_date, end_date: 日期
                - includes_handle, includes_lens_mount: 配套附件标记
                - accessories: 库存附件ID列表
        
        Returns:
            Rental: 更新后的租赁记录
        """
        try:
            # Read only the lock identity first, then follow the same stable
            # device(s) -> rental -> target schedule lock order as creation.
            source_identity = db.session.execute(
                select(Rental.device_id, Rental.parent_rental_id).where(
                    Rental.id == rental_id
                )
            ).one_or_none()
            if source_identity is None:
                raise ValueError('租赁记录不存在')
            source_device_id, source_parent_rental_id = source_identity
            if source_parent_rental_id is not None:
                raise ValueError('附件租赁必须通过主租赁更新')
            proposed_device_id = data.get('device_id', source_device_id)
            if (
                isinstance(proposed_device_id, bool)
                or not isinstance(proposed_device_id, int)
            ):
                raise ValueError('设备ID无效')
            locked_devices = RentalService._lock_schedule_devices(
                (source_device_id, proposed_device_id)
            )
            if source_device_id not in locked_devices:
                raise ValueError('原设备不存在')
            if proposed_device_id not in locked_devices:
                raise ValueError('设备不存在')
            rental = db.session.execute(
                select(Rental)
                .where(
                    Rental.id == rental_id,
                    Rental.device_id == source_device_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if not rental:
                raise ValueError('租赁记录不存在')
            locked_child_rentals = tuple(
                db.session.execute(
                    select(Rental)
                    .where(Rental.parent_rental_id == rental.id)
                    .order_by(Rental.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).scalars()
            )

            proposed_start_date, proposed_end_date = parse_date_strings(
                data.get('start_date', rental.start_date),
                data.get('end_date', rental.end_date),
            )
            validation_error = validate_date_range(
                proposed_start_date,
                proposed_end_date,
            )
            if validation_error:
                raise ValueError(validation_error)
            proposed_logistics_days = rental.logistics_days
            if 'logistics_days' in data:
                proposed_logistics_days = (
                    RentalService._require_logistics_days(
                        data['logistics_days']
                    )
                )
            planned_facts_changed = any(
                field_name in data
                for field_name in (
                    'start_date',
                    'end_date',
                    'logistics_days',
                )
            )
            proposed_planned_window = None
            if (
                planned_facts_changed
                and proposed_logistics_days is not None
            ):
                proposed_planned_window = (
                    RentalService._planned_logistics_window(
                        start_date=proposed_start_date,
                        end_date=proposed_end_date,
                        logistics_days=proposed_logistics_days,
                    )
                )
            proposed_status = data.get('status', rental.status)
            if proposed_status not in VALID_RENTAL_STATUSES:
                raise ValueError('无效的状态值')
            if rental.parent_rental_id is None:
                RentalService._require_usage_period_available(
                    device_id=proposed_device_id,
                    start_date=proposed_start_date,
                    end_date=proposed_end_date,
                    candidate_status=proposed_status,
                    candidate_rental_id=rental.id,
                    candidate_logistics_days=proposed_logistics_days,
                )

            rental.device_id = proposed_device_id
            for field_name in (
                'customer_name',
                'customer_phone',
                'destination',
                'damage_note',
                'ship_out_tracking_no',
                'ship_in_tracking_no',
                'xianyu_order_no',
                'order_amount',
                'buyer_id',
                'includes_handle',
                'includes_lens_mount',
                'photo_transfer',
                'lens_combo',
            ):
                if field_name in data:
                    setattr(rental, field_name, data[field_name])

            # 更新日期
            if 'start_date' in data:
                rental.start_date = proposed_start_date
            if 'end_date' in data:
                rental.end_date = proposed_end_date
            if 'logistics_days' in data:
                rental.logistics_days = proposed_logistics_days
            if planned_facts_changed:
                rental.planned_ship_out_date = (
                    proposed_planned_window.planned_ship_out_date
                    if proposed_planned_window is not None
                    else None
                )
                rental.planned_return_date = (
                    proposed_planned_window.planned_return_date
                    if proposed_planned_window is not None
                    else None
                )
                for child_rental in locked_child_rentals:
                    child_rental.start_date = rental.start_date
                    child_rental.end_date = rental.end_date
                    child_rental.logistics_days = rental.logistics_days
                    child_rental.planned_ship_out_date = (
                        rental.planned_ship_out_date
                    )
                    child_rental.planned_return_date = (
                        rental.planned_return_date
                    )

            if 'ship_out_time' in data:
                rental.ship_out_time = RentalService._optional_datetime(
                    data['ship_out_time'],
                    'ship_out_time',
                )
            if 'ship_in_time' in data:
                rental.ship_in_time = RentalService._optional_datetime(
                    data['ship_in_time'],
                    'ship_in_time',
                )
            if 'scheduled_ship_time' in data:
                rental.scheduled_ship_time = RentalService._optional_datetime(
                    data['scheduled_ship_time'],
                    'scheduled_ship_time',
                )

            if 'status' in data:
                rental.status = proposed_status
                status_changed_at = datetime.utcnow()
                if proposed_status == 'shipped':
                    if not rental.ship_out_time:
                        rental.ship_out_time = status_changed_at
                    if not rental.actual_shipped_at:
                        rental.actual_shipped_at = rental.ship_out_time
                if proposed_status == 'returned':
                    if not rental.ship_in_time:
                        rental.ship_in_time = status_changed_at
                    if not rental.actual_returned_at:
                        rental.actual_returned_at = rental.ship_in_time
                if proposed_status == 'completed' and not rental.ship_in_time:
                    rental.ship_in_time = status_changed_at
                for child_rental in locked_child_rentals:
                    child_rental.status = proposed_status
                    if proposed_status == 'shipped':
                        if not child_rental.ship_out_time:
                            child_rental.ship_out_time = status_changed_at
                        if not child_rental.actual_shipped_at:
                            child_rental.actual_shipped_at = (
                                child_rental.ship_out_time
                            )
                    if proposed_status == 'returned':
                        if not child_rental.ship_in_time:
                            child_rental.ship_in_time = status_changed_at
                        if not child_rental.actual_returned_at:
                            child_rental.actual_returned_at = (
                                child_rental.ship_in_time
                            )

            # 更新库存附件（如果提供）
            if 'accessories' in data:
                RentalService.update_rental_accessories(rental, data['accessories'])
            
            if commit:
                db.session.commit()
            current_app.logger.info(f"成功更新租赁记录: {rental_id}")
            return rental
            
        except Exception as e:
            if commit:
                db.session.rollback()
            current_app.logger.error(f"更新租赁记录失败: {e}")
            raise
