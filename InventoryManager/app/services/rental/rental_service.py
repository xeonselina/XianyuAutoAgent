"""
租赁业务逻辑服务层
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from flask import current_app
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.utils.date_utils import parse_date_strings, validate_date_range


class RentalService:
    """租赁服务类"""

    @staticmethod
    def get_rentals_with_filters(
        page: int = 1,
        per_page: int = 20,
        device_id: Optional[int] = None,
        customer_name: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取带过滤条件的租赁记录"""
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
            # 验证设备存在性
            device = Device.query.get(data['device_id'])
            if not device:
                raise ValueError('设备不存在')

            # 解析日期
            start_date, end_date = parse_date_strings(data['start_date'], data['end_date'])

            # 验证日期范围
            validation_error = validate_date_range(start_date, end_date)
            if validation_error:
                raise ValueError(validation_error)

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

            # 创建主租赁记录（包含配套附件标记）
            main_rental = Rental(
                device_id=data['device_id'],
                customer_name=data['customer_name'],
                customer_phone=data['customer_phone'],
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
                # 新：配套附件标记
                includes_handle=data.get('includes_handle', False),
                includes_lens_mount=data.get('includes_lens_mount', False)
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
                            customer_phone=data['customer_phone'],
                            destination=data.get('destination', ''),
                            start_date=start_date,
                            end_date=end_date,
                            ship_out_time=ship_out_time,
                            ship_in_time=ship_in_time,
                            ship_out_tracking_no=data.get('ship_out_tracking_no', ''),
                            ship_in_tracking_no=data.get('ship_in_tracking_no', ''),
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
    def update_rental_with_accessories(rental_id: int, data: Dict[str, Any]) -> Rental:
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
            rental = Rental.query.get(rental_id)
            if not rental:
                raise ValueError('租赁记录不存在')
            
            # 更新基本信息
            if 'customer_name' in data:
                rental.customer_name = data['customer_name']
            if 'customer_phone' in data:
                rental.customer_phone = data['customer_phone']
            if 'destination' in data:
                rental.destination = data['destination']
            
            # 更新日期
            if 'start_date' in data:
                start_date, _ = parse_date_strings(data['start_date'], data.get('end_date', rental.end_date))
                rental.start_date = start_date
            if 'end_date' in data:
                _, end_date = parse_date_strings(data.get('start_date', rental.start_date), data['end_date'])
                rental.end_date = end_date
            
            # 更新配套附件标记
            if 'includes_handle' in data:
                rental.includes_handle = data['includes_handle']
            if 'includes_lens_mount' in data:
                rental.includes_lens_mount = data['includes_lens_mount']
            
            # 更新库存附件（如果提供）
            if 'accessories' in data:
                RentalService.update_rental_accessories(rental, data['accessories'])
            
            db.session.commit()
            current_app.logger.info(f"成功更新租赁记录: {rental_id}")
            return rental
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"更新租赁记录失败: {e}")
            raise