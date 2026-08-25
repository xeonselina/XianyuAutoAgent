"""Development-only, sanitized SF resolver smoke endpoints."""

from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request

from app.models.rental import Rental
from app.services.integration_resolver import (
    ConfigurationIncomplete,
    IntegrationResolver,
)
from app.services.rental.rental_service import WarehouseMismatchError
from app.services.shipping.waybill_print_service import (
    sf_client_order_id_for,
    validate_shipping_preflight,
)


bp = Blueprint('sf_test', __name__, url_prefix='/api/sf-test')


@bp.before_request
def hide_in_production():
    if current_app.config.get('IS_PRODUCTION') or not (
        current_app.testing or current_app.debug
    ):
        abort(404)


def _configuration_error(message, code='CONFIG_INCOMPLETE'):
    return jsonify({
        'success': False, 'code': code, 'message': message,
    }), 400


@bp.route('/order/<int:rental_id>', methods=['POST'])
def test_sf_order(rental_id):
    """Exercise the real resolver and preflight without exposing PII."""
    rental = Rental.query.get(rental_id)
    if rental is None:
        abort(404)
    try:
        validate_shipping_preflight(rental)
        service = IntegrationResolver().sf_for_rental(rental)
        raw_time = (request.get_json(silent=True) or {}).get('scheduled_time')
        scheduled_time = (
            datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
            if raw_time else datetime.utcnow()
        )
        result = service.place_shipping_order(
            rental,
            scheduled_time,
            client_order_id=sf_client_order_id_for(rental),
        )
        if not result.get('success'):
            return jsonify({
                'success': False, 'code': 'EXTERNAL_SERVICE_ERROR',
                'message': '顺丰服务调用失败',
            }), 502
        return jsonify({
            'success': True,
            'data': {'rental_id': rental.id, 'test_mode': service.test_mode},
        }), 200
    except ConfigurationIncomplete:
        return _configuration_error('租赁或仓库顺丰配置不完整')
    except WarehouseMismatchError as exc:
        return _configuration_error(str(exc), 'WAREHOUSE_MISMATCH')
    except ValueError as exc:
        return _configuration_error(str(exc))


@bp.route('/status', methods=['GET'])
def test_sf_status():
    """Return only non-sensitive configuration state for one warehouse."""
    try:
        warehouse_id = int(request.args.get('warehouse_id'))
        service = IntegrationResolver().sf_for_warehouse(warehouse_id)
    except (TypeError, ValueError):
        return _configuration_error('请指定仓库')
    except ConfigurationIncomplete:
        return _configuration_error('仓库顺丰配置不完整')
    return jsonify({
        'success': True,
        'data': {
            'warehouse_id': warehouse_id,
            'configured': True,
            'test_mode': service.test_mode,
        },
    }), 200
