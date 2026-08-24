"""Optional Flask wiring for the independent control database."""

from typing import Optional

from flask import Flask, current_app

from .database import ControlDatabase


EXTENSION_KEY = "inventory_control"


def init_control_database(app: Flask) -> Optional[ControlDatabase]:
    """Register a lazy control engine when an explicit URL is configured.

    ``create_engine`` does not open a connection here.  Schema creation and
    migrations remain explicit operator/test actions.
    """

    database_url = app.config.get("CONTROL_DATABASE_URL")
    if not database_url:
        return None
    if EXTENSION_KEY in app.extensions:
        raise RuntimeError("inventory control database is already initialized")

    database = ControlDatabase.from_url(
        database_url,
        engine_options=app.config.get("CONTROL_DATABASE_ENGINE_OPTIONS") or {},
    )
    app.extensions[EXTENSION_KEY] = database
    return database


def get_control_database() -> ControlDatabase:
    database = current_app.extensions.get(EXTENSION_KEY)
    if database is None:
        raise RuntimeError("inventory control database is not configured")
    return database
