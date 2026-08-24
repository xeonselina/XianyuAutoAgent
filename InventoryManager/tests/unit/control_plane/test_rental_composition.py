from __future__ import annotations

from flask import Flask

from app.services.rental.composition import install_rental_saas_http_runtime
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRentalSaasHttpRuntime,
)
from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
)


class _TenantBusinessRuntime:
    def tenant_session(
        self,
        *,
        flask_request,
        capability,
        additional_capabilities=(),
        request_id_prefix,
        after_authorize=None,
        passthrough_exceptions=(),
    ):
        raise AssertionError("composition must not open a tenant session")


def test_rental_composition_requires_shared_runtime() -> None:
    app = Flask(__name__)

    try:
        install_rental_saas_http_runtime(app)
    except RuntimeError as exc:
        assert str(exc) == "tenant business HTTP runtime is not installed"
    else:
        raise AssertionError("missing shared runtime must fail closed")

    assert RENTAL_SAAS_HTTP_RUNTIME_EXTENSION not in app.extensions


def test_rental_composition_publishes_once_without_opening_database() -> None:
    app = Flask(__name__)
    app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] = (
        _TenantBusinessRuntime()
    )

    runtime = install_rental_saas_http_runtime(app)

    assert isinstance(runtime, SqlAlchemyRentalSaasHttpRuntime)
    assert app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] is runtime
    try:
        install_rental_saas_http_runtime(app)
    except RuntimeError as exc:
        assert "already installed" in str(exc)
    else:
        raise AssertionError("replacement must be rejected")
