"""接力管理 REST API。"""

from flask import Blueprint

from app.handlers.relay_case_handlers import RelayCaseHandlers
from app.utils.response import handle_response


bp = Blueprint("relay_case_api", __name__)


@bp.route("/api/relay-cases", methods=["GET"])
@handle_response
def list_relay_cases():
    return RelayCaseHandlers.handle_list()


@bp.route(
    "/api/relay-cases/<int:predecessor_id>/<int:successor_id>",
    methods=["PUT"],
)
@handle_response
def update_relay_case(predecessor_id, successor_id):
    return RelayCaseHandlers.handle_update(predecessor_id, successor_id)


@bp.route(
    "/api/relay-cases/<int:case_id>/tracking/refresh",
    methods=["POST"],
)
@handle_response
def refresh_relay_tracking(case_id):
    return RelayCaseHandlers.handle_refresh_tracking(case_id)


@bp.route(
    "/api/relay-cases/tracking/refresh-batch",
    methods=["POST"],
)
@handle_response
def refresh_relay_tracking_batch():
    return RelayCaseHandlers.handle_refresh_tracking_batch()
