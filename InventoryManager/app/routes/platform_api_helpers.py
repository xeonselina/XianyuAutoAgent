"""Shared response and strict-input helpers for platform blueprints."""

from __future__ import annotations

from collections.abc import Collection

from flask import jsonify, request

from inventory_control.platform_http import PlatformHttpError


def strict_json_object(*, allowed_keys: Collection[str]) -> dict[str, object] | None:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) or key not in allowed_keys for key in payload
    ):
        return None
    return payload


def platform_failure(error: PlatformHttpError):
    return jsonify(
        {
            "success": False,
            "message": error.public_message,
            "data": {"code": error.code},
        }
    ), error.status_code


def platform_runtime_unavailable(message: str):
    return jsonify({"success": False, "message": message}), 503


__all__ = [
    "platform_failure",
    "platform_runtime_unavailable",
    "strict_json_object",
]
