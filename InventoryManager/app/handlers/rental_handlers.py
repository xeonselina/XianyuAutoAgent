"""
租赁API处理器
包含所有租赁相关的请求处理逻辑
"""

from datetime import datetime
from typing import Dict, Any, Tuple
from flask import request, jsonify, current_app
from app.services.rental.rental_service import RentalService
from app.utils.date_utils import (
    parse_date_strings,
    validate_date_range,
    convert_dates_to_datetime,
    create_error_response,
    create_success_response
)


class RentalHandlers:
    """租赁请求处理器类"""

    @staticmethod
    def handle_get_rentals() -> Tuple[Dict[str, Any], int]:
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

            return {
                'success': True,
                'data': result
            }, 200

        except Exception as e:
            current_app.logger.error(f"获取租赁记录失败: {e}")
            return create_error_response('获取租赁记录失败'), 500

    @staticmethod
    def handle_get_rental(rental_id: str) -> Tuple[Dict[str, Any], int]:
        """处理获取单个租赁记录请求"""
        try:
            rental = RentalService.get_rental_by_id(rental_id)
            if not rental:
                return create_error_response('租赁记录不存在'), 404

            return {
                'success': True,
                'data': rental.to_dict()
            }, 200

        except Exception as e:
            current_app.logger.error(f"获取租赁记录失败: {e}")
            return create_error_response('获取租赁记录失败'), 500

    @staticmethod
    def handle_create_rental() -> Tuple[Dict[str, Any], int]:
        """处理创建租赁记录请求"""
        try:
            data = request.get_json()
            if not data:
                return create_error_response('缺少请求数据'), 400

            # 验证必填字段
            required_fields = ['device_id', 'customer_name', 'customer_phone', 'start_date', 'end_date']
            for field in required_fields:
                if not data.get(field):
                    return create_error_response(f'缺少必填字段: {field}'), 400

            # 创建租赁记录
            main_rental, accessory_rentals = RentalService.create_rental_with_accessories(data)

            # 构建响应数据
            response_data = {
                'main_rental': main_rental.to_dict(),
                'accessory_rentals': [r.to_dict() for r in accessory_rentals]
            }

            return create_success_response(response_data, '租赁记录创建成功'), 201

        except ValueError as e:
            return create_error_response(str(e)), 400
        except Exception as e:
            current_app.logger.error(f"创建租赁记录失败: {e}")
            return create_error_response('创建租赁记录失败'), 500

    @staticmethod
    def handle_update_rental_status(rental_id: str) -> Tuple[Dict[str, Any], int]:
        """处理更新租赁状态请求"""
        try:
            data = request.get_json()
            if not data or 'status' not in data:
                return create_error_response('缺少状态数据'), 400

            new_status = data['status']

            # 验证状态值
            valid_statuses = ['not_shipped', 'shipped', 'returned', 'completed', 'cancelled']
            if new_status not in valid_statuses:
                return create_error_response(f'无效的状态值: {new_status}'), 400

            # 更新状态
            rental = RentalService.update_rental_status(rental_id, new_status)

            return {
                'success': True,
                'message': '状态更新成功',
                'data': {
                    'id': rental.id,
                    'status': rental.status,
                    'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                    'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
                }
            }, 200

        except ValueError as e:
            return create_error_response(str(e)), 404
        except Exception as e:
            current_app.logger.error(f"更新租赁状态失败: {e}")
            return create_error_response('更新状态失败'), 500

    @staticmethod
    def handle_delete_rental(rental_id: str) -> Tuple[Dict[str, Any], int]:
        """处理删除租赁记录请求"""
        try:
            success = RentalService.delete_rental(rental_id)
            if not success:
                return create_error_response('租赁记录不存在'), 404

            return create_success_response(None, message='租赁记录删除成功'), 200

        except Exception as e:
            current_app.logger.error(f"删除租赁记录失败: {e}")
            return create_error_response('删除租赁记录失败'), 500

    @staticmethod
    def handle_check_rental_conflict() -> Tuple[Dict[str, Any], int]:
        """处理检查租赁冲突请求"""
        try:
            data = request.get_json()
            if not data:
                return create_error_response('缺少请求数据'), 400

            # 验证必填字段
            required_fields = ['device_id', 'ship_out_time', 'ship_in_time']
            for field in required_fields:
                if field not in data:
                    return create_error_response(f'缺少必填字段: {field}'), 400

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

            return {
                'success': True,
                'data': {
                    'has_conflicts': len(conflicts) > 0,
                    'conflicts': conflicts
                }
            }, 200

        except Exception as e:
            current_app.logger.error(f"检查租赁冲突失败: {e}")
            return create_error_response('检查冲突失败'), 500

    @staticmethod
    def handle_web_update_rental(rental_id: str) -> Tuple[Dict[str, Any], int]:
        """处理Web界面更新租赁记录请求"""
        try:
            rental = RentalService.get_rental_by_id(rental_id)
            if not rental:
                return create_error_response('租赁记录不存在'), 404

            data = request.get_json()
            if not data:
                return create_error_response('缺少更新数据'), 400

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
                    return create_error_response('结束日期不能早于开始日期'), 400
                rental.end_date = end_date

            if 'ship_out_tracking_no' in data:
                rental.ship_out_tracking_no = data['ship_out_tracking_no']

            if 'ship_in_tracking_no' in data:
                rental.ship_in_tracking_no = data['ship_in_tracking_no']

            # 处理时间字段
            if 'ship_out_time' in data:
                if data['ship_out_time']:
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
            result_data = {
                'success': True,
                'message': '租赁记录更新成功',
                'data': {
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
            }

            return result_data, 200

        except Exception as e:
            from app import db
            db.session.rollback()
            current_app.logger.error(f"更新租赁记录失败: {e}")
            return create_error_response('更新租赁记录失败'), 500

    @staticmethod
    def handle_check_duplicate_rental() -> Tuple[Dict[str, Any], int]:
        """处理检查重复租赁请求"""
        try:
            from app.models.rental import Rental

            data = request.get_json()
            if not data:
                return create_error_response('请求数据不能为空'), 400

            customer_name = data.get('customer_name', '').strip()
            destination = data.get('destination', '').strip()
            exclude_rental_id = data.get('exclude_rental_id')

            if not customer_name and not destination:
                return {
                    'success': True,
                    'has_duplicate': False,
                    'duplicates': []
                }, 200

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

            # 构建返回数据
            duplicate_data = []
            for rental in duplicates:
                duplicate_data.append({
                    'id': rental.id,
                    'customer_name': rental.customer_name,
                    'customer_phone': rental.customer_phone,
                    'destination': rental.destination,
                    'device_name': rental.device.name if rental.device else 'Unknown',
                    'start_date': rental.start_date.isoformat(),
                    'end_date': rental.end_date.isoformat(),
                    'status': rental.status,
                    'created_at': rental.created_at.isoformat()
                })

            return {
                'success': True,
                'has_duplicate': len(duplicates) > 0,
                'duplicates': duplicate_data
            }, 200

        except Exception as e:
            current_app.logger.error(f"检查重复租赁失败: {e}")
            return create_error_response('检查重复租赁失败'), 500