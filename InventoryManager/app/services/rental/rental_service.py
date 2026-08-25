"""
租赁业务逻辑服务层
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Optional, Tuple
from flask import current_app
from sqlalchemy.orm import joinedload
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.models.warehouse import resolve_write_warehouse_id
from app.models.xianyu_order_alert import XianyuOrderAlert
from app.models.xianyu_shop import XianyuShop
from app.utils.date_utils import parse_date_strings, validate_date_range


class WarehouseMismatchError(ValueError):
    """A requested inventory accessory belongs to another warehouse."""


class DeviceUnavailableError(ValueError):
    """A selected device overlaps another active rental."""


class RentalService:
    """租赁服务类"""

    ACTIVE_OCCUPANCY_STATUSES = (
        'not_shipped', 'scheduled_for_shipping', 'shipped', 'returned',
    )

    @staticmethod
    def get_pending_returns(
        today: Optional[date] = None, warehouse_id=None
    ) -> List[Dict[str, Any]]:
        """获取今天及以前应归还、仍未寄回的主租赁记录。"""
        current_date = today or date.today()
        latest_end_date = current_date - timedelta(days=1)
        query = (
            Rental.query
            .options(joinedload(Rental.device))
            .filter(
                Rental.end_date <= latest_end_date,
                Rental.status == 'shipped',
                Rental.parent_rental_id.is_(None),
            )
        )
        if isinstance(warehouse_id, int):
            query = query.filter(Rental.warehouse_id == warehouse_id)
        rentals = query.all()

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
                'warehouse_id': rental.warehouse_id,
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
        destination: Optional[str] = None,
        warehouse_id=None,
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

            if isinstance(warehouse_id, int):
                query = query.filter(Rental.warehouse_id == warehouse_id)

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
    def _parse_datetime(value):
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        normalized = str(value).replace('T', ' ')
        for parser in (
            datetime.fromisoformat,
            lambda raw: datetime.strptime(raw, '%Y-%m-%d'),
        ):
            try:
                return parser(normalized)
            except ValueError:
                continue
        raise ValueError('时间格式错误')

    @staticmethod
    def _effective_occupancy(
        start_date, end_date, ship_out_time=None, ship_in_time=None
    ):
        occupancy_start = ship_out_time or datetime.combine(
            start_date, time.min
        )
        occupancy_end = ship_in_time or datetime.combine(
            end_date, time.max
        )
        if occupancy_start >= occupancy_end:
            raise ValueError('寄出时间必须早于收回时间')
        return occupancy_start, occupancy_end

    @staticmethod
    def _resolve_shop(order_no, requested_shop_id, exclude_rental_id=None):
        order_no = str(order_no or '').strip() or None
        if order_no is None:
            return None, None

        if requested_shop_id not in (None, ''):
            if isinstance(requested_shop_id, bool):
                raise ValueError('闲鱼店铺不存在或已停用')
            try:
                requested_shop_id = int(requested_shop_id)
            except (TypeError, ValueError):
                raise ValueError('闲鱼店铺不存在或已停用') from None
            shop = db.session.get(XianyuShop, requested_shop_id)
            if shop is None or not shop.is_active:
                raise ValueError('闲鱼店铺不存在或已停用')
        else:
            alert_shop_ids = [
                shop_id
                for (shop_id,) in db.session.query(
                    XianyuOrderAlert.xianyu_shop_id
                ).filter(
                    XianyuOrderAlert.order_no == order_no,
                    XianyuOrderAlert.state == 'pending',
                ).distinct().limit(2).all()
            ]
            if len(alert_shop_ids) == 1:
                shop = db.session.get(XianyuShop, alert_shop_ids[0])
                if shop is None:
                    raise ValueError('闲鱼告警所属店铺不存在')
            else:
                active_shops = XianyuShop.query.filter_by(
                    is_active=True
                ).order_by(XianyuShop.id).limit(2).all()
                if len(active_shops) != 1:
                    raise ValueError('请指定闲鱼店铺')
                shop = active_shops[0]

        duplicate_query = Rental.query.filter(
            Rental.xianyu_shop_id == shop.id,
            Rental.xianyu_order_no == order_no,
        )
        if exclude_rental_id is not None:
            duplicate_query = duplicate_query.filter(
                Rental.id != exclude_rental_id
            )
        if duplicate_query.first() is not None:
            raise ValueError('该闲鱼店铺已存在相同订单号')
        return order_no, shop.id

    @staticmethod
    def _validate_selection(
        warehouse_id,
        device_id,
        accessory_ids,
        occupancy_start,
        occupancy_end,
        exclude_rental_ids=(),
        preserve_existing=False,
    ):
        try:
            normalized_device_id = int(device_id)
        except (TypeError, ValueError):
            raise ValueError('设备不存在') from None
        normalized_ids = []
        for raw_id in accessory_ids or []:
            try:
                accessory_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValueError('附件设备不存在') from None
            if accessory_id in normalized_ids:
                raise ValueError('附件设备不能重复选择')
            normalized_ids.append(accessory_id)

        selected_ids = sorted({normalized_device_id, *normalized_ids})
        locked_devices = (
            Device.query.filter(Device.id.in_(selected_ids))
            .order_by(Device.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        device_by_id = {item.id: item for item in locked_devices}
        device = device_by_id.get(normalized_device_id)
        if device is None:
            raise ValueError('设备不存在')
        if device.is_accessory:
            raise ValueError('主设备不能是库存附件')
        if not preserve_existing and device.warehouse_id != warehouse_id:
            raise WarehouseMismatchError('主设备不属于所选仓库')
        if not preserve_existing and not device.is_in_service():
            raise DeviceUnavailableError('主设备当前不可用于新租赁')

        accessories = []
        for accessory_id in normalized_ids:
            accessory = device_by_id.get(accessory_id)
            if accessory is None:
                raise ValueError('附件设备不存在')
            if not accessory.is_accessory:
                raise ValueError('设备不是库存附件')
            if (
                not preserve_existing
                and accessory.warehouse_id != warehouse_id
            ):
                raise WarehouseMismatchError('附件设备不属于所选仓库')
            if not preserve_existing and not accessory.is_in_service():
                raise DeviceUnavailableError('附件设备当前不可用于新租赁')
            accessories.append(accessory)

        if preserve_existing:
            return device, accessories

        conflict_query = Rental.query.filter(
            Rental.device_id.in_(selected_ids),
            Rental.status.in_(RentalService.ACTIVE_OCCUPANCY_STATUSES),
        )
        excluded = tuple(exclude_rental_ids)
        if excluded:
            conflict_query = conflict_query.filter(~Rental.id.in_(excluded))
        conflicts = (
            conflict_query.order_by(Rental.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        for conflict in conflicts:
            existing_start, existing_end = (
                RentalService._effective_occupancy(
                    conflict.start_date,
                    conflict.end_date,
                    conflict.ship_out_time,
                    conflict.ship_in_time,
                )
            )
            if (
                occupancy_start < existing_end
                and occupancy_end > existing_start
            ):
                raise DeviceUnavailableError(
                    f'设备 {conflict.device_id} 在所选租期内不可用'
                )
        return device, accessories

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
            warehouse_id = resolve_write_warehouse_id(
                data.get('warehouse_id')
            )

            # 解析日期
            start_date, end_date = parse_date_strings(data['start_date'], data['end_date'])

            # 验证日期范围
            validation_error = validate_date_range(start_date, end_date)
            if validation_error:
                raise ValueError(validation_error)

            ship_out_time = RentalService._parse_datetime(
                data.get('ship_out_time')
            )
            ship_in_time = RentalService._parse_datetime(
                data.get('ship_in_time')
            )
            occupancy_start, occupancy_end = (
                RentalService._effective_occupancy(
                    start_date,
                    end_date,
                    ship_out_time,
                    ship_in_time,
                )
            )

            _device, validated_accessories = (
                RentalService._validate_selection(
                    warehouse_id,
                    data['device_id'],
                    data.get('accessories') or [],
                    occupancy_start,
                    occupancy_end,
                )
            )
            order_no, shop_id = RentalService._resolve_shop(
                data.get('xianyu_order_no'),
                data.get('xianyu_shop_id'),
            )

            # 创建主租赁记录（包含配套附件标记）
            main_rental = Rental(
                device_id=data['device_id'],
                warehouse_id=warehouse_id,
                customer_name=data['customer_name'],
                customer_phone=data.get('customer_phone'),
                destination=data.get('destination', ''),
                start_date=start_date,
                end_date=end_date,
                ship_out_time=ship_out_time,
                ship_in_time=ship_in_time,
                ship_out_tracking_no=data.get('ship_out_tracking_no', ''),
                ship_in_tracking_no=data.get('ship_in_tracking_no', ''),
                xianyu_order_no=order_no,
                xianyu_shop_id=shop_id,
                order_amount=data.get('order_amount'),
                buyer_id=data.get('buyer_id'),
                status='not_shipped',
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
            for accessory_device in validated_accessories:
                # 跳过配套附件（手柄和镜头支架）
                if (
                    '手柄' in accessory_device.name
                    or '镜头支架' in accessory_device.name
                ):
                    current_app.logger.info(
                        f"跳过配套附件: {accessory_device.name}"
                    )
                    continue

                # 仅为库存附件（手机支架、三脚架）创建子租赁
                accessory_rental = Rental(
                    device_id=accessory_device.id,
                    warehouse_id=warehouse_id,
                    customer_name=data['customer_name'],
                    customer_phone=data.get('customer_phone'),
                    destination=data.get('destination', ''),
                    start_date=start_date,
                    end_date=end_date,
                    ship_out_time=ship_out_time,
                    ship_in_time=ship_in_time,
                    ship_out_tracking_no=data.get(
                        'ship_out_tracking_no', ''
                    ),
                    ship_in_tracking_no=data.get(
                        'ship_in_tracking_no', ''
                    ),
                    status='not_shipped',
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
        """更新租赁状态"""
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                raise ValueError('租赁记录不存在')

            old_status = rental.status
            rental.status = new_status

            current_app.logger.info(f"状态更新: 接收到状态 {new_status}, 当前状态 {old_status}")
            current_app.logger.info(f"状态更新: 已设置 rental.status = {rental.status}")

            # 处理状态变化时的逻辑
            if old_status != new_status:
                current_app.logger.info(f"租赁状态从 {old_status} 变更为 {new_status}")

                # 如果状态变为已发货，设置发货时间
                if new_status == 'shipped' and not rental.ship_out_time:
                    rental.ship_out_time = datetime.utcnow()

                # 如果状态变为已完成，设置收回时间
                if new_status == 'completed' and not rental.ship_in_time:
                    rental.ship_in_time = datetime.utcnow()

                # 同步更新子租赁（附件）的状态
                for child_rental in rental.child_rentals:
                    child_rental.status = new_status

            current_app.logger.info(f"准备提交数据库事务，当前状态: {rental.status}")
            db.session.commit()
            current_app.logger.info(f"数据库事务已提交，当前状态: {rental.status}")

            return rental

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"更新租赁状态失败: {e}")
            raise

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
    def update_rental_accessories(
        rental: Rental,
        requested_devices: List[Device],
        current_children: List[Rental],
    ):
        """Replace serialized accessories from one freshly locked group."""
        current_children = {
            child.device_id: child for child in current_children
        }

        effective_ids = {
            device.id
            for device in requested_devices
            if '手柄' not in device.name and '镜头支架' not in device.name
        }
        for device_id, child in current_children.items():
            if device_id not in effective_ids:
                db.session.delete(child)

        for accessory in requested_devices:
            if '手柄' in accessory.name or '镜头支架' in accessory.name:
                continue
            child = current_children.get(accessory.id)
            if child is None:
                child = Rental(
                    device_id=accessory.id,
                    parent_rental_id=rental.id,
                )
                db.session.add(child)
            child.warehouse_id = rental.warehouse_id
            child.customer_name = rental.customer_name
            child.customer_phone = rental.customer_phone
            child.destination = rental.destination
            child.start_date = rental.start_date
            child.end_date = rental.end_date
            child.ship_out_time = rental.ship_out_time
            child.ship_in_time = rental.ship_in_time
            child.ship_out_tracking_no = rental.ship_out_tracking_no
            child.ship_in_tracking_no = rental.ship_in_tracking_no
            child.status = rental.status
    
    @staticmethod
    def update_rental_with_accessories(rental_id: int, data: Dict[str, Any]) -> Rental:
        """Validate and atomically update a main rental and its children."""
        try:
            rental = db.session.get(Rental, rental_id)
            if not rental:
                raise ValueError('租赁记录不存在')
            target_rental_id = rental.id

            warehouse_id = resolve_write_warehouse_id(
                data.get('warehouse_id')
            )
            start_date, end_date = parse_date_strings(
                data.get('start_date', rental.start_date),
                data.get('end_date', rental.end_date),
            )
            validation_error = validate_date_range(start_date, end_date)
            if validation_error:
                raise ValueError(validation_error)

            status = data.get('status', rental.status)
            valid_statuses = {
                'not_shipped', 'scheduled_for_shipping', 'shipped',
                'returned', 'completed', 'cancelled',
            }
            if status not in valid_statuses:
                raise ValueError(f'无效的状态值: {status}')
            ship_out_time = (
                RentalService._parse_datetime(data['ship_out_time'])
                if 'ship_out_time' in data
                else rental.ship_out_time
            )
            ship_in_time = (
                RentalService._parse_datetime(data['ship_in_time'])
                if 'ship_in_time' in data
                else rental.ship_in_time
            )
            if status != rental.status:
                if status == 'shipped' and not ship_out_time:
                    ship_out_time = datetime.utcnow()
                if status == 'completed' and not ship_in_time:
                    ship_in_time = datetime.utcnow()
            occupancy_start, occupancy_end = (
                RentalService._effective_occupancy(
                    start_date,
                    end_date,
                    ship_out_time,
                    ship_in_time,
                )
            )

            children = list(rental.child_rentals)
            accessory_ids = data.get(
                'accessories', [child.device_id for child in children]
            )
            device_id = data.get('device_id', rental.device_id)
            try:
                selection_is_unchanged = (
                    warehouse_id == rental.warehouse_id
                    and int(device_id) == rental.device_id
                    and {int(row_id) for row_id in accessory_ids}
                    == {child.device_id for child in children}
                )
            except (TypeError, ValueError):
                selection_is_unchanged = False
            occupancy_is_unchanged = (
                start_date == rental.start_date
                and end_date == rental.end_date
                and ship_out_time == rental.ship_out_time
                and ship_in_time == rental.ship_in_time
            )
            preserve_existing = (
                selection_is_unchanged and occupancy_is_unchanged
            )
            _device, validated_accessories = (
                RentalService._validate_selection(
                    warehouse_id,
                    device_id,
                    accessory_ids,
                    occupancy_start,
                    occupancy_end,
                    exclude_rental_ids=[rental.id] + [
                        child.id for child in children
                    ],
                    preserve_existing=preserve_existing,
                )
            )

            # Device rows are always locked before Rental rows. The explicit
            # current read below serializes edits to this main/child group and
            # refreshes objects that may already be present in the identity map.
            main_rental_id = rental.parent_rental_id or rental.id
            locked_group = (
                Rental.query.filter(
                    (Rental.id == main_rental_id)
                    | (Rental.parent_rental_id == main_rental_id)
                )
                .order_by(Rental.id)
                .populate_existing()
                .with_for_update()
                .all()
            )
            rental = next(
                (
                    row
                    for row in locked_group
                    if row.id == target_rental_id
                ),
                None,
            )
            if rental is None:
                raise ValueError('租赁记录不存在')
            fresh_children = [
                row
                for row in locked_group
                if row.parent_rental_id == rental.id
            ]

            # Values omitted by this request came from the initial snapshot.
            # If another serialized edit changed one, retry instead of applying
            # validation results to a different identity or occupancy window.
            stale_defaults = (
                ('device_id' not in data and device_id != rental.device_id)
                or (
                    'accessories' not in data
                    and {int(row_id) for row_id in accessory_ids}
                    != {child.device_id for child in fresh_children}
                )
                or (
                    'start_date' not in data
                    and start_date != rental.start_date
                )
                or ('end_date' not in data and end_date != rental.end_date)
                or (
                    'ship_out_time' not in data
                    and ship_out_time != rental.ship_out_time
                )
                or (
                    'ship_in_time' not in data
                    and ship_in_time != rental.ship_in_time
                )
            )
            if stale_defaults:
                raise ValueError('租赁记录已被其他操作修改，请重试')
            if 'status' not in data:
                status = rental.status

            requested_effective_ids = {
                device.id
                for device in validated_accessories
                if '手柄' not in device.name and '镜头支架' not in device.name
            }
            current_accessory_ids = {
                child.device_id for child in fresh_children
            }
            identity_changed = (
                warehouse_id != rental.warehouse_id
                or int(device_id) != rental.device_id
                or requested_effective_ids != current_accessory_ids
            )
            if preserve_existing and identity_changed:
                raise ValueError('租赁记录已被其他操作修改，请重试')
            has_fulfillment_history = any(
                row.status in {'shipped', 'returned', 'completed'}
                or bool(str(row.ship_out_tracking_no or '').strip())
                for row in locked_group
            )
            if has_fulfillment_history and identity_changed:
                raise ValueError('已履约租赁不能更换仓库或设备')

            if 'xianyu_order_no' in data or 'xianyu_shop_id' in data:
                order_no, shop_id = RentalService._resolve_shop(
                    data.get('xianyu_order_no', rental.xianyu_order_no),
                    data.get('xianyu_shop_id', rental.xianyu_shop_id),
                    exclude_rental_id=rental.id,
                )
            else:
                order_no = rental.xianyu_order_no
                shop_id = rental.xianyu_shop_id

            rental.warehouse_id = warehouse_id
            rental.device_id = device_id
            rental.start_date = start_date
            rental.end_date = end_date
            rental.xianyu_order_no = order_no
            rental.xianyu_shop_id = shop_id
            for field in (
                'customer_name', 'customer_phone', 'destination',
                'damage_note', 'ship_out_tracking_no',
                'ship_in_tracking_no', 'order_amount', 'buyer_id',
                'includes_handle', 'includes_lens_mount',
                'photo_transfer', 'lens_combo', 'express_type_id',
            ):
                if field in data:
                    setattr(rental, field, data[field])
            rental.ship_out_time = ship_out_time
            rental.ship_in_time = ship_in_time
            rental.status = status

            RentalService.update_rental_accessories(
                rental,
                validated_accessories,
                fresh_children,
            )
            db.session.commit()
            current_app.logger.info(f"成功更新租赁记录: {rental_id}")
            return rental
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"更新租赁记录失败: {e}")
            raise
