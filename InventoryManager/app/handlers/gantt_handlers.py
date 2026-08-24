"""
甘特图API处理器
包含甘特图相关的请求处理逻辑
"""

from datetime import datetime, date, timedelta
from flask import request, current_app
from app.utils.response import (
    ApiResponse,
    success,
    error,
    bad_request,
    server_error,
    not_found
)
from app.utils.date_utils import (
    parse_date_strings,
    validate_date_range,
    convert_dates_to_datetime,
)
from app.services.gantt.gantt_service import GanttService
from app.services.gantt.reorder_service import (
    StalePreviewError,
)
from app.services.gantt.http_runtime import (
    GanttSaasHttpRuntimeUnavailable,
    GanttViewQueryInvalid,
    require_gantt_saas_http_runtime,
)
from app.services.scheduling import ScheduleValidationError
from inventory_control.tenant_http import TenantHttpError


class GanttHandlers:
    """甘特图处理器类"""

    @staticmethod
    def _legacy_single_tenant_reads_unavailable() -> ApiResponse | None:
        """Fail closed until these reads are routed to a tenant database."""

        if (
            current_app.testing is not True
            or current_app.config.get(
                "ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS"
            )
            is not True
        ):
            return error("租户档期读服务尚未就绪", status_code=503)
        return None

    @staticmethod
    def handle_get_gantt_data() -> ApiResponse:
        """处理获取甘特图数据请求"""
        unavailable = GanttHandlers._legacy_single_tenant_reads_unavailable()
        if unavailable is not None:
            return unavailable
        try:
            # 获取查询参数
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # 调用服务层获取甘特图数据
            gantt_data = GanttService.get_gantt_data(start_date_str, end_date_str)
            return success(data=gantt_data)

        except ValueError as e:
            current_app.logger.error(f"参数验证失败: {e}")
            return bad_request(str(e))
        except Exception as e:
            current_app.logger.error(f"获取甘特图数据失败: {e}")
            return server_error('获取甘特图数据失败')

    @staticmethod
    def handle_get_gantt_view() -> ApiResponse:
        """处理标准化、单请求的甘特范围快照。"""
        try:
            runtime = require_gantt_saas_http_runtime()
            return success(
                data=runtime.view(
                    flask_request=request,
                    query=request.args,
                )
            )
        except GanttViewQueryInvalid as exc:
            return bad_request(str(exc))
        except GanttSaasHttpRuntimeUnavailable:
            return error("租户档期服务尚未就绪", status_code=503)
        except TenantHttpError as exc:
            return error(
                exc.public_message,
                status_code=exc.status_code,
                data={"code": exc.code},
            )
        except ScheduleValidationError as exc:
            return error(
                "档期计划事实不完整或已漂移",
                status_code=409,
                data={"code": exc.code},
            )

    @staticmethod
    def handle_get_daily_stats() -> ApiResponse:
        """处理获取每日统计信息请求"""
        unavailable = GanttHandlers._legacy_single_tenant_reads_unavailable()
        if unavailable is not None:
            return unavailable
        try:
            # 获取查询参数
            date_str = request.args.get('date')
            device_model = request.args.get('device_model')

            # 调用服务层获取每日统计
            daily_stats = GanttService.get_daily_statistics(date_str, device_model)
            return success(data=daily_stats)

        except ValueError as e:
            current_app.logger.error(f"参数验证失败: {e}")
            return bad_request(str(e))
        except Exception as e:
            current_app.logger.error(f"获取每日统计失败: {e}")
            return server_error('获取每日统计失败')

    @staticmethod
    def handle_find_rental_slot() -> ApiResponse:
        """处理查找可用租赁时间段请求"""
        unavailable = GanttHandlers._legacy_single_tenant_reads_unavailable()
        if unavailable is not None:
            return unavailable
        try:
            data = request.get_json() or {}

            # 验证必填字段
            required_fields = ['start_date', 'end_date', 'logistics_days', 'model', 'is_accessory']
            for field in required_fields:
                if field not in data:
                    return bad_request(f'缺少必填字段: {field}')

            # 解析日期
            try:
                start_date, end_date = parse_date_strings(data['start_date'], data['end_date'])
            except ValueError as e:
                return bad_request(str(e))

            # 获取其他参数
            try:
                logistics_days = int(data['logistics_days'])
            except (ValueError, TypeError):
                return bad_request('logistics_days 必须是整数')

            model = data['model']
            is_accessory = data.get('is_accessory', False)

            # 验证日期范围
            validation_error = validate_date_range(start_date, end_date, allow_same_date=True)
            if validation_error:
                return bad_request(validation_error)

            # 调用服务层查找可用档期
            available_slot = GanttService.find_available_slot(
                start_date, end_date, logistics_days, model, is_accessory
            )

            if available_slot:
                return success(
                    data=available_slot,
                    message=available_slot.get('message', '找到可用档期')
                )
            else:
                return not_found(f'在指定时间段内没有可用的 {model} 型号设备档期')

        except Exception as e:
            current_app.logger.error(f"查找租赁档期失败: {e}")
            return server_error('查找档期失败')

    @staticmethod
    def handle_analyze_reorder() -> ApiResponse:
        """扫描需要人工确认的接力关系。"""
        try:
            runtime = require_gantt_saas_http_runtime()
            return success(data=runtime.analyze(flask_request=request))
        except GanttSaasHttpRuntimeUnavailable:
            return error("租户档期服务尚未就绪", status_code=503)
        except TenantHttpError as exc:
            return error(
                exc.public_message,
                status_code=exc.status_code,
                data={"code": exc.code},
            )
        except ScheduleValidationError as exc:
            return error(
                "档期计划事实不完整或已漂移",
                status_code=409,
                data={"code": exc.code},
            )

    @staticmethod
    def handle_preview_reorder() -> ApiResponse:
        """生成零写入的档期重排预览。"""
        data = request.get_json(silent=True) or {}
        try:
            runtime = require_gantt_saas_http_runtime()
            return success(
                data=runtime.preview(
                    flask_request=request,
                    decisions=data.get("decisions", []),
                )
            )
        except GanttSaasHttpRuntimeUnavailable:
            return error("租户档期服务尚未就绪", status_code=503)
        except TenantHttpError as exc:
            return error(
                exc.public_message,
                status_code=exc.status_code,
                data={"code": exc.code},
            )
        except ScheduleValidationError as exc:
            return error(
                "档期计划事实不完整或已漂移",
                status_code=409,
                data={"code": exc.code},
            )
        except ValueError as exc:
            return bad_request(str(exc))

    @staticmethod
    def handle_execute_reorder() -> ApiResponse:
        """原子执行已签名的档期重排预览。"""
        data = request.get_json(silent=True) or {}
        try:
            runtime = require_gantt_saas_http_runtime()
            return success(
                data=runtime.execute(
                    flask_request=request,
                    token=data.get("token"),
                ),
                message="档期重排完成",
            )
        except GanttSaasHttpRuntimeUnavailable:
            return error("租户档期服务尚未就绪", status_code=503)
        except TenantHttpError as exc:
            return error(
                exc.public_message,
                status_code=exc.status_code,
                data={"code": exc.code},
            )
        except StalePreviewError as exc:
            return error(str(exc), status_code=409)
        except ScheduleValidationError as exc:
            return error(
                "档期计划事实不完整或已漂移",
                status_code=409,
                data={"code": exc.code},
            )
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception:
            current_app.logger.exception("档期重排执行失败")
            return server_error("档期重排失败，所有修改已回滚")
