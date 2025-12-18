"""
租赁API处理器
包含所有租赁相关的请求处理逻辑
"""

from datetime import datetime
from flask import request, current_app
from app.services.rental.rental_service import RentalService
from app.utils.response import (
    ApiResponse,
    success,
    error,
    created,
    not_found,
    bad_request,
    server_error
)


class RentalHandlers:
    """租赁请求处理器类"""

    @staticmethod
    def handle_get_rentals() -> ApiResponse:
        """处理获取租赁记录列表请求"""
        try:
            # 获取查询参数
            page = int(request.args.get('page', 1))
            per_page = min(int(request.args.get('per_page', 20)), 100)
            device_id = request.args.get('device_id', type=int)
            customer_name = request.args.get('customer_name')
            status = request.args.get('status')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            phone = request.args.get('phone')

            # 调用服务层
            result = RentalService.get_rentals_with_filters(
                page=page,
                per_page=per_page,
                device_id=device_id,
                customer_name=customer_name,
                status=status,
                start_date=start_date,
                end_date=end_date,
                phone=phone
            )

            return success(data=result)

        except Exception as e:
            current_app.logger.error(f"获取租赁记录失败: {e}")
            return server_error('获取租赁记录失败')

    @staticmethod
    def handle_get_rental(rental_id: str) -> ApiResponse:
        """处理获取单个租赁记录请求"""
        try:
            rental = RentalService.get_rental_by_id(rental_id)
            if not rental:
                return not_found('租赁记录不存在')

            return success(data=rental.to_dict())

        except Exception as e:
            current_app.logger.error(f"获取租赁记录失败: {e}")
            return server_error('获取租赁记录失败')

    @staticmethod
    def handle_create_rental() -> ApiResponse:
        """处理创建租赁记录请求"""
        try:
            data = request.get_json()
            if not data:
                return bad_request('缺少请求数据')

            # 验证必填字段
            required_fields = ['device_id', 'customer_name', 'start_date', 'end_date']
            for field in required_fields:
                if not data.get(field):
                    return bad_request(f'缺少必填字段: {field}')

            # 创建租赁记录
            main_rental, accessory_rentals = RentalService.create_rental_with_accessories(data)

            # 构建响应数据
            response_data = {
                'main_rental': main_rental.to_dict(),
                'accessory_rentals': [r.to_dict() for r in accessory_rentals]
            }

            return created(data=response_data, message='租赁记录创建成功')

        except ValueError as e:
            return bad_request(str(e))
        except Exception as e:
            current_app.logger.error(f"创建租赁记录失败: {e}")
            return server_error('创建租赁记录失败')

    @staticmethod
    def handle_update_rental_status(rental_id: str) -> ApiResponse:
        """处理更新租赁状态请求"""
        try:
            data = request.get_json()
            if not data or 'status' not in data:
                return bad_request('缺少状态数据')

            new_status = data['status']

            # 验证状态值
            valid_statuses = ['not_shipped', 'shipped', 'returned', 'completed', 'cancelled']
            if new_status not in valid_statuses:
                return bad_request(f'无效的状态值: {new_status}')

            # 更新状态
            rental = RentalService.update_rental_status(rental_id, new_status)

            return success(
                message='状态更新成功',
                data={
                    'id': rental.id,
                    'status': rental.status,
                    'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                    'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
                }
            )

        except ValueError as e:
            return not_found(str(e))
        except Exception as e:
            current_app.logger.error(f"更新租赁状态失败: {e}")
            return server_error('更新状态失败')

    @staticmethod
    def handle_delete_rental(rental_id: str) -> ApiResponse:
        """处理删除租赁记录请求"""
        try:
            delete_success = RentalService.delete_rental(rental_id)
            if not delete_success:
                return not_found('租赁记录不存在')

            return success(message='租赁记录删除成功')

        except Exception as e:
            current_app.logger.error(f"删除租赁记录失败: {e}")
            return server_error('删除租赁记录失败')

    @staticmethod
    def handle_check_rental_conflict() -> ApiResponse:
        """处理检查租赁冲突请求"""
        try:
            data = request.get_json()
            if not data:
                return bad_request('缺少请求数据')

            # 验证必填字段
            required_fields = ['device_id', 'ship_out_time', 'ship_in_time']
            for field in required_fields:
                if field not in data:
                    return bad_request(f'缺少必填字段: {field}')

            # 解析时间
            ship_out_time = datetime.fromisoformat(data['ship_out_time'])
            ship_in_time = datetime.fromisoformat(data['ship_in_time'])

            # 从时间中提取日期用于冲突检查
            start_date = ship_out_time.date()
            end_date = ship_in_time.date()

            # 检查冲突
            conflicts = RentalService.check_rental_conflicts(
                device_id=data['device_id'],
                start_date=start_date,
                end_date=end_date,
                ship_out_time=ship_out_time,
                ship_in_time=ship_in_time,
                exclude_rental_id=data.get('exclude_rental_id')
            )

            return success(data={
                'has_conflicts': len(conflicts) > 0,
                'conflicts': conflicts
            })

        except Exception as e:
            current_app.logger.error(f"检查租赁冲突失败: {e}")
            return server_error('检查冲突失败')

    @staticmethod
    def handle_web_update_rental(rental_id: str) -> ApiResponse:
        """处理Web界面更新租赁记录请求"""
        try:
            rental = RentalService.get_rental_by_id(rental_id)
            if not rental:
                return not_found('租赁记录不存在')

            data = request.get_json()
            if not data:
                return bad_request('缺少更新数据')

            current_app.logger.info(f"更新租赁记录: {data}")

            # 更新基本字段
            if 'device_id' in data:
                rental.device_id = data['device_id']

            if 'customer_name' in data:
                rental.customer_name = data['customer_name']

            if 'customer_phone' in data:
                rental.customer_phone = data['customer_phone']

            if 'destination' in data:
                rental.destination = data['destination']

            if 'end_date' in data:
                end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                if end_date < rental.start_date:
                    return bad_request('结束日期不能早于开始日期')
                rental.end_date = end_date

            if 'ship_out_tracking_no' in data:
                rental.ship_out_tracking_no = data['ship_out_tracking_no']

            if 'ship_in_tracking_no' in data:
                rental.ship_in_tracking_no = data['ship_in_tracking_no']

            # 处理订单字段
            if 'xianyu_order_no' in data:
                rental.xianyu_order_no = data['xianyu_order_no']

            if 'order_amount' in data:
                rental.order_amount = data['order_amount']

            if 'buyer_id' in data:
                rental.buyer_id = data['buyer_id']

            # 处理时间字段
            if 'ship_out_time' in data:
                if data['ship_out_time']:
                    try:
                        # 先尝试 ISO 格式
                        rental.ship_out_time = datetime.fromisoformat(data['ship_out_time'].replace('T', ' '))
                        current_app.logger.info(f"寄出时间解析成功(ISO格式): {data['ship_out_time']} -> {rental.ship_out_time}")
                    except ValueError:
                        try:
                            rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
                            current_app.logger.info(f"寄出时间解析成功: {data['ship_out_time']} -> {rental.ship_out_time}")
                        except ValueError:
                            try:
                                rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                                current_app.logger.info(f"寄出时间解析成功(日期格式): {data['ship_out_time']} -> {rental.ship_out_time}")
                            except ValueError:
                                current_app.logger.warning(f"无法解析寄出时间: {data['ship_out_time']}")
                else:
                    rental.ship_out_time = None

            if 'ship_in_time' in data:
                if data['ship_in_time']:
                    try:
                        # 先尝试 ISO 格式
                        rental.ship_in_time = datetime.fromisoformat(data['ship_in_time'].replace('T', ' '))
                        current_app.logger.info(f"收回时间解析成功(ISO格式): {data['ship_in_time']} -> {rental.ship_in_time}")
                    except ValueError:
                        try:
                            rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
                            current_app.logger.info(f"收回时间解析成功: {data['ship_in_time']} -> {rental.ship_in_time}")
                        except ValueError:
                            try:
                                rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                                current_app.logger.info(f"收回时间解析成功(日期格式): {data['ship_in_time']} -> {rental.ship_in_time}")
                            except ValueError:
                                current_app.logger.warning(f"无法解析收回时间: {data['ship_in_time']}")
                else:
                    rental.ship_in_time = None

            # 处理状态更新
            if 'status' in data:
                rental = RentalService.update_rental_status(rental_id, data['status'])

            # 处理附件更新
            if 'accessories' in data:
                current_app.logger.info(f"更新附件: {data['accessories']}")
                RentalService.update_rental_accessories(rental, data['accessories'])

            # 如果状态没有被单独更新，则提交其他更改
            if 'status' not in data:
                from app import db
                current_app.logger.info(f"准备提交数据库事务")
                db.session.commit()
                current_app.logger.info(f"数据库事务已提交")

            # 构建响应数据
            return success(
                message='租赁记录更新成功',
                data={
                    'id': rental.id,
                    'device_id': rental.device_id,
                    'device_name': rental.device.name if rental.device else 'Unknown',
                    'customer_name': rental.customer_name,
                    'customer_phone': rental.customer_phone,
                    'destination': rental.destination,
                    'end_date': rental.end_date.isoformat(),
                    'ship_out_tracking_no': rental.ship_out_tracking_no,
                    'ship_in_tracking_no': rental.ship_in_tracking_no,
                    'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                    'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
                    'status': rental.status
                }
            )

        except Exception as e:
            from app import db
            db.session.rollback()
            current_app.logger.error(f"更新租赁记录失败: {e}")
            return server_error('更新租赁记录失败')

    @staticmethod
    def handle_check_duplicate_rental() -> ApiResponse:
        """处理检查重复租赁请求"""
        try:
            from app.models.rental import Rental

            data = request.get_json()
            if not data:
                return bad_request('请求数据不能为空')

            customer_name = data.get('customer_name', '').strip()
            destination = data.get('destination', '').strip()
            exclude_rental_id = data.get('exclude_rental_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')

            if not customer_name and not destination:
                return success(data={
                    'has_duplicate': False,
                    'duplicates': []
                })

            # 查找重复的租赁记录
            query = Rental.query.filter(Rental.status.in_(['not_shipped', 'shipped', 'returned']))

            # 排除当前编辑的租赁记录
            if exclude_rental_id:
                query = query.filter(Rental.id != exclude_rental_id)

            # 构建查询条件：客户名称完全相同或地址完全相同
            from sqlalchemy import or_
            conditions = []
            if customer_name:
                conditions.append(Rental.customer_name == customer_name)
            if destination:
                conditions.append(Rental.destination == destination)

            if conditions:
                query = query.filter(or_(*conditions))

            duplicates = query.order_by(Rental.created_at.desc()).limit(10).all()

            # 解析日期用于冲突检查
            current_start_date = None
            current_end_date = None
            if start_date_str and end_date_str:
                try:
                    current_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    current_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            # 构建返回数据，并检查档期冲突
            duplicate_data = []
            for rental in duplicates:
                has_date_conflict = False

                # 如果提供了日期，检查档期是否冲突
                if current_start_date and current_end_date:
                    # 档期冲突判断：两个时间段有重叠
                    # 重叠条件：start1 <= end2 AND end1 >= start2
                    has_date_conflict = (
                        current_start_date <= rental.end_date and
                        current_end_date >= rental.start_date
                    )

                duplicate_data.append({
                    'id': rental.id,
                    'customer_name': rental.customer_name,
                    'customer_phone': rental.customer_phone,
                    'destination': rental.destination,
                    'device_name': rental.device.name if rental.device else 'Unknown',
                    'start_date': rental.start_date.isoformat(),
                    'end_date': rental.end_date.isoformat(),
                    'status': rental.status,
                    'created_at': rental.created_at.isoformat(),
                    'has_date_conflict': has_date_conflict
                })

            return success(data={
                'has_duplicate': len(duplicates) > 0,
                'duplicates': duplicate_data
            })

        except Exception as e:
            current_app.logger.error(f"检查重复租赁失败: {e}")
            return server_error('检查重复租赁失败')

    @staticmethod
    def handle_fetch_xianyu_order() -> ApiResponse:
        """处理获取闲鱼订单详情请求"""
        try:
            from app.services.xianyu_order_service import xianyu_service

            data = request.get_json()
            if not data:
                return bad_request('请求数据不能为空')

            order_no = data.get('order_no', '').strip()
            if not order_no:
                return bad_request('订单号不能为空')

            # 调用闲鱼API服务
            order_data = xianyu_service.get_order_detail(order_no)

            if not order_data:
                return server_error('获取订单详情失败，请检查订单号是否正确')

            # 转换数据为前端需要的格式
            response_data = {
                'order_no': order_data.get('order_no'),
                'receiver_name': order_data.get('receiver_name'),
                'receiver_mobile': order_data.get('receiver_mobile'),
                'prov_name': order_data.get('prov_name', ''),
                'city_name': order_data.get('city_name', ''),
                'area_name': order_data.get('area_name', ''),
                'town_name': order_data.get('town_name', ''),
                'address': order_data.get('address', ''),
                'buyer_eid': order_data.get('buyer_eid'),
                'buyer_nick': order_data.get('buyer_nick'),
                'pay_amount': order_data.get('pay_amount'),  # 单位:分
            }

            return success(data=response_data, message='订单信息获取成功')

        except Exception as e:
            current_app.logger.error(f"获取闲鱼订单详情失败: {e}")
            return server_error('获取订单详情失败')

    @staticmethod
    def handle_get_rentals_by_ship_date() -> ApiResponse:
        """处理根据发货日期范围查询租赁记录请求（用于批量打印）"""
        try:
            from datetime import timedelta
            from app.models.rental import Rental

            # 获取查询参数
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            if not start_date_str or not end_date_str:
                return bad_request('缺少必要参数: start_date 和 end_date')

            # 解析日期
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                return bad_request('日期格式错误，应为 YYYY-MM-DD')

            # 验证日期范围
            if end_date < start_date:
                return bad_request('结束日期不能早于开始日期')

            # 防止恶意查询过大范围
            date_diff = (end_date - start_date).days
            if date_diff > 365:
                return bad_request('日期范围不能超过365天')

            # 查询租赁记录
            # 将 end_date 加一天以包含结束日期当天的记录
            query_end_date = datetime.combine(end_date, datetime.max.time())
            query_start_date = datetime.combine(start_date, datetime.min.time())

            # 查询已发货的订单（使用 ship_out_time）和预约发货的订单（使用 scheduled_ship_time）

            rentals = Rental.query.filter(
                Rental.ship_out_time >= query_start_date,
                Rental.ship_out_time <= query_end_date,
                Rental.parent_rental_id.is_(None),
                Rental.status != 'cancelled'
            ).order_by(
                # 按实际发货时间或预约时间排序
                Rental.ship_out_time.asc()
            ).all()

            # 构建响应数据
            rentals_data = [rental.to_dict() for rental in rentals]

            return success(data={
                'rentals': rentals_data,
                'count': len(rentals),
                'date_range': {
                    'start': start_date_str,
                    'end': end_date_str
                }
            })

        except Exception as e:
            current_app.logger.error(f"根据发货日期查询租赁记录失败: {e}")
            return server_error('查询租赁记录失败')