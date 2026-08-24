"""Tenant member invitations and public single-use handoff endpoints."""

from flask import Blueprint, jsonify, request

from app.services.tenant_invitations import (
    TenantInvitationRuntimeUnavailable,
    TenantInvitationSmsRateLimited,
    require_tenant_invitation_http_runtime,
)
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint("tenant_invitation_api", __name__, url_prefix="/api/v1")


@bp.after_request
def protect_invitation_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@bp.get("/members")
def list_members():
    return _call(
        lambda runtime, _payload: runtime.list_members(flask_request=request)
    )


@bp.post("/members/<membership_id>/mutations")
def mutate_member(membership_id: str):
    return _call(
        lambda runtime, payload: runtime.mutate_member(
            flask_request=request,
            membership_id=membership_id,
            expected_row_version=payload.get("expected_row_version"),
            action=payload.get("action"),
            action_id=payload.get("action_id"),
            target_role=payload.get("target_role"),
        )
    )


@bp.post("/members/<membership_id>/mutations/challenge")
def request_member_mutation_challenge(membership_id: str):
    return _call(
        lambda runtime, payload: runtime.request_member_mutation_challenge(
            flask_request=request,
            membership_id=membership_id,
            expected_row_version=payload.get("expected_row_version"),
            action=payload.get("action"),
            action_id=payload.get("action_id"),
            target_role=payload.get("target_role"),
        ),
        accepted=True,
    )


@bp.post("/members/<membership_id>/mutations/confirm")
def confirm_member_mutation(membership_id: str):
    return _call(
        lambda runtime, payload: runtime.confirm_member_mutation(
            flask_request=request,
            membership_id=membership_id,
            expected_row_version=payload.get("expected_row_version"),
            action=payload.get("action"),
            action_id=payload.get("action_id"),
            target_role=payload.get("target_role"),
            challenge_id=payload.get("challenge_id"),
            plaintext_code=payload.get("code"),
        )
    )


@bp.post("/members/invitations/admin-challenge")
def request_admin_challenge():
    return _call(
        lambda runtime, payload: runtime.request_admin_challenge(
            flask_request=request,
            raw_phone=payload.get("phone"),
            role=payload.get("role"),
            action_id=payload.get("action_id"),
        ),
        accepted=True,
    )


@bp.post("/members/invitations")
def create_or_resend():
    return _call(
        lambda runtime, payload: runtime.create_or_resend(
            flask_request=request,
            raw_phone=payload.get("phone"),
            role=payload.get("role"),
            expected_row_version=payload.get("expected_row_version"),
            action_id=payload.get("action_id"),
            challenge_id=payload.get("challenge_id"),
            plaintext_code=payload.get("code"),
        )
    )


@bp.post("/members/invitations/<invitation_id>/revoke")
def revoke(invitation_id: str):
    return _call(
        lambda runtime, payload: runtime.revoke(
            flask_request=request,
            invitation_id=invitation_id,
            expected_row_version=payload.get("expected_row_version"),
        )
    )


@bp.post("/invitations/inspect")
def inspect():
    return _call(
        lambda runtime, payload: runtime.inspect(
            invitation_id=payload.get("invitation_id"),
            token=payload.get("token"),
            generation=payload.get("generation"),
        )
    )


@bp.post("/invitations/challenges")
def request_acceptance_challenge():
    return _call(
        lambda runtime, payload: runtime.request_acceptance_challenge(
            flask_request=request,
            invitation_id=payload.get("invitation_id"),
            token=payload.get("token"),
            generation=payload.get("generation"),
        ),
        accepted=True,
    )


@bp.post("/invitations/accept")
def accept():
    return _call(
        lambda runtime, payload: runtime.accept(
            invitation_id=payload.get("invitation_id"),
            token=payload.get("token"),
            generation=payload.get("generation"),
            challenge_id=payload.get("challenge_id"),
            plaintext_code=payload.get("code"),
        )
    )


def _call(operation, *, accepted: bool = False):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = operation(require_tenant_invitation_http_runtime(), payload)
        return jsonify({"success": True, "data": result}), 202 if accepted else 200
    except TenantInvitationSmsRateLimited as exc:
        response, status = _failure(exc)
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response, status
    except TenantHttpError as exc:
        return _failure(exc)
    except TenantInvitationRuntimeUnavailable:
        return jsonify({
            "success": False,
            "message": "邀请服务暂不可用。",
            "data": {"code": "INVITATION_RUNTIME_UNAVAILABLE"},
        }), 503


def _failure(exc: TenantHttpError):
    return jsonify({
        "success": False,
        "message": exc.public_message,
        "data": {"code": exc.code},
    }), exc.status_code


__all__ = ["bp"]
